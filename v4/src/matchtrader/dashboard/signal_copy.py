"""Explicit, local-only signal copying; durable identities prevent replayed orders.

Opening copies is gated (armed, configured, fresh). Unwinding is not: a `cancelled`, `cancel`
or `closed` signal is handed to capture.unwind against the ledger of trades the owner sent, and
acts whatever the toggles say, because it only ever removes exposure. The one legacy case - a
pending order this module itself dispatched while armed - is cancelled by prepare_cancel under
the same rule: its checks that the order is still resting and matches the stored copy remain,
its arming and freshness gates do not.
"""
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import RLock
from types import SimpleNamespace
from typing import Annotated, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from ..capture import unwind
from ..capture.router import CaptureRouter
from .copy_settings import save_settings


class SignalSymbol(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, str_strip_whitespace=True)
    destination: str = Field(min_length=1, max_length=100)
    fixed_lots: Decimal = Field(gt=0)
    order_type: Literal['MARKET', 'LIMIT', 'STOP', 'SOURCE', 'ENTRY']
    same_price_scale: Literal[True]


class SignalSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    machine_id: str = Field(min_length=1, max_length=100)
    source: str = Field(default='chain', min_length=1, max_length=100)
    connection_name: str = Field(default='', max_length=200)
    destination_account: str = Field(min_length=1, max_length=200)
    symbols: dict[Annotated[str, Field(min_length=1, max_length=100)], SignalSymbol] = Field(min_length=1)
    exclusive_destination: Literal[True]
    p01_log_enabled: bool = False
    additional_sources: list[Literal['chain', 'panel']] = Field(default_factory=list)
    x17_only: bool = False

    @model_validator(mode='before')
    @classmethod
    def retire_cancel_pending(cls, value):
        # Cancelling a linked pending order is no longer optional: a cancel or closed signal always
        # acts on exposure we created. Saved files from before this rule still load; the key is dropped.
        if isinstance(value, dict) and 'cancel_pending' in value:
            value = {k: v for k, v in value.items() if k != 'cancel_pending'}
        return value


class Signal(BaseModel):
    model_config = ConfigDict(extra='ignore', allow_inf_nan=False)
    clientEventId: str = Field(min_length=1, max_length=200)
    machineId: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=100)
    connectionName: str = Field(default='', max_length=200)
    kind: str = Field(min_length=1, max_length=100)
    label: str = Field(default='', max_length=200)
    timestampUtc: datetime
    symbol: str = Field(default='', max_length=100)
    side: str = Field(default='', max_length=20)
    entry: Decimal = Field(default=Decimal(0), ge=0)
    stopLoss: Decimal = Field(default=Decimal(0), ge=0)
    takeProfit: Decimal = Field(default=Decimal(0), ge=0)
    copyOrderType: Literal['', 'MARKET', 'LIMIT', 'STOP'] = Field(default='', validation_alias=AliasChoices('copyOrderType', 'orderType'))

    @field_validator('copyOrderType', mode='before')
    @classmethod
    def normalize_type(cls, value):
        return value.upper() if isinstance(value, str) else value

    @field_validator('timestampUtc')
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError('Timestamp must include a timezone')
        return value.astimezone(UTC)


class SignalCopy:
    def __init__(self, directory, ledger=None):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / 'signal-copy-settings.json'
        self.config = SignalSettings.model_validate_json(self.path.read_text()) if self.path.exists() else None
        # The CaptureStore holding the trades the owner sent; cancel/closed signals unwind against it.
        self.ledger = ledger
        self.lock = RLock()
        self.armed = False
        self.armed_at = None
        self.db = sqlite3.connect(directory / 'signal-copy.sqlite3', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS signals (
                id TEXT PRIMARY KEY, client_id TEXT, machine TEXT, source TEXT, label TEXT,
                kind TEXT, emitted TEXT, received TEXT, digest TEXT, payload TEXT,
                decision TEXT, reason TEXT, destination TEXT, request TEXT, response TEXT);
            CREATE INDEX IF NOT EXISTS signals_scope ON signals(machine,source,label);
            CREATE TABLE IF NOT EXISTS appearances (
                seq INTEGER PRIMARY KEY, signal_id TEXT, received TEXT, payload TEXT, conflict INTEGER);
        ''')
        with self.db:
            self.db.execute("UPDATE signals SET decision='uncertain',reason='Interrupted write; no automatic retry' WHERE decision='dispatching'")

    def settings(self):
        with self.lock:
            return {'config': self.config.model_dump(mode='json') if self.config else None, 'live': self.armed}

    def configure(self, payload):
        value = SignalSettings.model_validate(payload)
        if value.p01_log_enabled and 'panel' in value.additional_sources:
            raise ValueError('Use either P01 local log or structured panel signals, not both')
        if value.p01_log_enabled and value.source != 'P01_LOG':
            raise ValueError('P01 log routing requires source P01_LOG')
        if value.p01_log_enabled and any(v.order_type != 'SOURCE' for v in value.symbols.values()):
            raise ValueError('P01 log routing must preserve the source Limit/Stop order type')
        with self.lock:
            if self.armed:
                raise ValueError('Turn live signal copying off before editing settings')
            save_settings(self.path, value)
            self.config = value
            return self.settings()

    def arm(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('Live mode must be a boolean')
        with self.lock:
            self.armed = enabled
            self.armed_at = datetime.now(UTC) if enabled else None

    def feed(self):
        with self.lock:
            rows = self.db.execute('SELECT * FROM signals ORDER BY rowid DESC LIMIT 100').fetchall()
            return {'events': [self.result(row) for row in rows]}

    @staticmethod
    def result(row, duplicate=False):
        payload = json.loads(row['payload'])
        return {'label': row['label'], 'source': row['source'], 'symbol': payload.get('symbol', ''),
                'connectionName': payload.get('connectionName', ''), 'clientEventId': row['client_id'], 'machineId': row['machine'], 'kind': row['kind'],
                'received_at': row['received'], 'status': row['decision'], 'reason': row['reason'],
                'duplicate': duplicate, 'destination_account': row['destination'],
                'copy_request': json.loads(row['request']) if row['request'] else None,
                'copy_response': json.loads(row['response']) if row['response'] else None}

    def receive(self, payload, api, destination, verified):
        if not isinstance(payload, list) or not 1 <= len(payload) <= 100 or any(not isinstance(p, dict) for p in payload):
            raise ValueError('Expected an array of 1 to 100 signal objects')
        # A completed lifecycle in the same batch must not open an obsolete intent.
        closed = {self.scope(p) for p in payload if p.get('kind') in {'closed', 'cancelled', 'cancel'} and p.get('label')}
        results = []
        with self.lock:
            for raw in payload:
                try:
                    signal = Signal.model_validate(raw)
                    results.append(self._receive(signal, raw, closed, api, destination, verified))
                except ValueError:
                    results.append({'clientEventId': raw.get('clientEventId'), 'status': 'invalid', 'reason': 'Invalid signal identity, timestamp, or numeric fields; no copy attempted'})
        return {'origin': 'x.0.1', 'received': len(payload), 'forwarded_to_tradingbox': False, 'results': results}

    def _receive(self, signal, raw, closed, api, destination, verified):
        key = hashlib.sha256(json.dumps([signal.machineId, signal.clientEventId]).encode()).hexdigest()
        digest = hashlib.sha256(signal.model_dump_json(
            exclude={'copyOrderType'} if not signal.copyOrderType else set()).encode()).hexdigest()
        now = datetime.now(UTC)
        serialized = json.dumps(raw, ensure_ascii=False, allow_nan=False)
        previous = self.db.execute('SELECT * FROM signals WHERE id=?', (key,)).fetchone()
        conflict = bool(previous and previous['digest'] != digest)
        with self.db:
            self.db.execute('INSERT INTO appearances(signal_id,received,payload,conflict) VALUES(?,?,?,?)', (key, now.isoformat(), serialized, int(conflict)))
        if previous:
            result = self.result(previous, duplicate=True)
            if conflict:
                result.update(status='held', reason='Repeated identity has conflicting signal fields; no new order attempted')
            return result
        with self.db:
            self.db.execute('INSERT INTO signals(id,client_id,machine,source,label,kind,emitted,received,digest,payload,decision,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                            (key, signal.clientEventId, signal.machineId, signal.source, signal.label, signal.kind,
                             signal.timestampUtc.isoformat(), now.isoformat(), digest, serialized, 'captured', 'Local logging; no copy attempted'))
        if signal.kind == 'intent':
            self._dispatch(key, signal, destination,
                           lambda: self.prepare(signal, closed, api, destination, verified, now, raw=raw))
        elif signal.kind in unwind.UNWIND_KINDS:
            self._unwind(key, signal, raw, api, destination, verified)
        return self.result(self.db.execute('SELECT * FROM signals WHERE id=?', (key,)).fetchone())

    def _dispatch(self, key, signal, destination, preparer):
        try:
            kwargs, method = preparer()
            # Commit the attempt before invoking a broker write. Uncertain outcomes are never retried.
            with self.db:
                self.db.execute("UPDATE signals SET decision='dispatching',destination=?,request=? WHERE id=?", (destination, json.dumps(kwargs, default=str), key))
            try:
                response = method(**kwargs)
                response_data = response.model_dump(mode='json')
                accepted = response.status in {'', None, 'OK'} and (bool(response.orderId or response.positionId) if signal.kind == 'intent' else response.status == 'OK')
                decision = 'accepted' if accepted else 'uncertain'
                reason = 'MatchTrader accepted the configured copy request' if accepted else 'Unrecognized write response; no automatic retry'
            except Exception as error:
                response_data = {'error_type': type(error).__name__}
                decision = 'uncertain'
                reason = (f'Copy write outcome unconfirmed after {type(error).__name__}; broker state not verified, '
                          f'no automatic retry (signal {signal.machineId}:{signal.clientEventId})')
            with self.db:
                self.db.execute('UPDATE signals SET decision=?,reason=?,response=? WHERE id=?', (decision, reason, json.dumps(response_data), key))
        except (ValueError, TypeError) as error:
            with self.db:
                self.db.execute("UPDATE signals SET decision='held',reason=? WHERE id=?", (str(error), key))
        except Exception as error:
            with self.db:
                self.db.execute("UPDATE signals SET decision=CASE WHEN decision='dispatching' THEN 'uncertain' ELSE 'held' END,reason=? WHERE id=?",
                                (f'Processing interrupted by {type(error).__name__}; no automatic retry', key))

    def _unwind(self, key, signal, raw, api, destination, verified):
        """A cancel or closed signal acts on exposure we created, now, whatever the toggles say."""
        verb = 'cancel' if signal.kind in unwind.CANCEL_KINDS else 'close'
        outcome = None
        if self.ledger is not None and signal.label:
            try:
                outcome = unwind.apply(self.ledger, signal, api, destination, verified)
            except Exception as error:
                outcome = {'decision': 'uncertain', 'request': None, 'response': None,
                           'reason': (f'Unwind processing interrupted by {type(error).__name__}; completion is '
                                      f'unconfirmed. Check the capture journal for lifecycle {signal.label!r} '
                                      'and reconcile broker state before any retry')}
        if outcome is not None:
            with self.db:
                self.db.execute('UPDATE signals SET decision=?,reason=?,destination=?,request=?,response=? WHERE id=?', (
                    outcome['decision'], outcome['reason'], destination,
                    json.dumps(outcome['request'], default=str) if outcome['request'] is not None else None,
                    json.dumps(outcome['response'], default=str) if outcome['response'] is not None else None, key))
            return
        if signal.kind in unwind.CANCEL_KINDS and self.legacy_copy(raw, destination):
            self._dispatch(key, signal, destination, lambda: self.prepare_cancel(signal, raw, api, destination, verified))
            return
        reason = (f'Signal carries no lifecycle label; nothing to {verb}' if not signal.label else
                  f'No sent trade is linked to lifecycle {signal.label!r} from {signal.machineId}; nothing to {verb}')
        with self.db:
            self.db.execute("UPDATE signals SET decision='captured',reason=? WHERE id=?", (reason, key))

    def legacy_copy(self, raw, destination):
        """True when this module itself dispatched the intent of this lifecycle while armed."""
        return any(r['kind'] == 'intent' and r['request'] and r['destination'] == destination for r in self.related(raw))

    def check_route(self, signal, api, destination, verified, now):
        config = self.config
        if not self.armed or not config:
            raise ValueError('Live signal copying is off')
        if not api or not verified or destination != config.destination_account:
            raise ValueError('Connect the configured authenticated destination')
        if signal.machineId != config.machine_id or signal.source not in {config.source, *config.additional_sources}:
            raise ValueError('Signal does not match the configured machine/source')
        if config.connection_name and signal.source != 'panel' and signal.connectionName != config.connection_name:
            raise ValueError('Signal does not match the configured chart connection')
        if not self.armed_at or signal.timestampUtc < self.armed_at or not -5 <= (now - signal.timestampUtc).total_seconds() <= 30:
            raise ValueError('Signal is stale or predates enabling live mode; no replay')
        return config

    @staticmethod
    def scope(raw):
        return tuple(raw.get(k, '') for k in ('machineId', 'source', 'accountId', 'connectionName', 'symbol', 'label'))

    def related(self, raw):
        rows = self.db.execute('SELECT * FROM signals WHERE machine=? AND source=? AND label=?',
                               (raw.get('machineId'), raw.get('source'), raw.get('label'))).fetchall()
        return [r for r in rows if self.scope(json.loads(r['payload'])) == self.scope(raw)]

    def prepare(self, signal, closed, api, destination, verified, now, *, raw=None):
        config = self.check_route(signal, api, destination, verified, now)
        raw = raw or signal.model_dump(mode='json')
        if not signal.label:
            raise ValueError('A labeled lifecycle is required for copying')
        if config.x17_only and signal.source == 'chain' and not str(raw.get('detail', '')).lower().startswith('x17-spine '):
            raise ValueError('Chain intent is not identified as X17')
        if signal.source == 'panel' and not signal.label.startswith('P01RR_'):
            raise ValueError('Panel intent is not identified as manual P01')
        if self.scope(raw) in closed or (signal.machineId, signal.source, signal.label) in closed:
            raise ValueError('This batch already contains an ended lifecycle')
        related = self.related(raw)
        if any(r['kind'] in {'closed', 'cancelled', 'cancel'} and r['emitted'] >= signal.timestampUtc.isoformat() for r in related):
            raise ValueError('A later ended lifecycle was already recorded')
        if any(r['kind'] == 'intent' and r['request'] and r['destination'] == destination for r in related):
            raise ValueError('This scoped lifecycle already has a broker attempt; no duplicate order')
        mapping = config.symbols.get(signal.symbol)
        if not mapping:
            raise ValueError('No configured symbol mapping')
        side = {'long': 'BUY', 'short': 'SELL', 'BUY': 'BUY', 'SELL': 'SELL'}.get(signal.side)
        if not side or min(signal.entry, signal.stopLoss, signal.takeProfit) <= 0:
            raise ValueError('Intent needs a side and positive entry, stop and target')
        if (side == 'BUY' and not signal.stopLoss < signal.entry < signal.takeProfit) or (side == 'SELL' and not signal.takeProfit < signal.entry < signal.stopLoss):
            raise ValueError('Intent bracket prices do not match its side')
        order_type = signal.copyOrderType if mapping.order_type == 'SOURCE' else mapping.order_type
        if order_type == 'ENTRY' and signal.copyOrderType in {'LIMIT', 'STOP'}:
            order_type = signal.copyOrderType
        if order_type == 'ENTRY':
            quotes = [q for q in api.quotes(symbols=mapping.destination) if q.symbol == mapping.destination]
            if len(quotes) != 1:
                raise ValueError('A unique destination quote is required for pending entry')
            quote = quotes[0]
            bid, ask = Decimal(str(quote.bid)), Decimal(str(quote.ask))
            if not bid.is_finite() or not ask.is_finite() or not 0 < bid <= ask:
                raise ValueError('Destination quote is invalid')
            timestamp = getattr(quote, 'timestampMs', None) or (getattr(quote, 'timestampSec', None) or 0) * 1000
            if not timestamp or not -5000 <= now.timestamp() * 1000 - timestamp <= 10000:
                raise ValueError('A fresh timestamped broker quote is required')
            reference = ask if side == 'BUY' else bid
            if signal.entry == reference:
                raise ValueError('Entry equals current quote; pending type is ambiguous')
            order_type = 'LIMIT' if (signal.entry < reference if side == 'BUY' else signal.entry > reference) else 'STOP'
        if order_type not in {'MARKET', 'LIMIT', 'STOP'}:
            raise ValueError('Source intent has no supported order type')
        event = SimpleNamespace(action='CREATE', order_type=order_type, price=signal.entry, sl=signal.stopLoss, tp=signal.takeProfit, side=side)
        CaptureRouter._validate_instrument(api, mapping.destination, mapping.fixed_lots, event)
        kwargs = {'instrument': mapping.destination, 'orderSide': side, 'volume': mapping.fixed_lots, 'slPrice': signal.stopLoss, 'tpPrice': signal.takeProfit}
        if order_type == 'MARKET':
            return kwargs, api.open_position
        return {**kwargs, 'type': order_type, 'price': signal.entry}, api.create_pending_order

    def prepare_cancel(self, signal, raw, api, destination, verified):
        """Cancel a pending order this module dispatched itself. Deliberately not gated by the arming
        switch or signal freshness: the order exists at the broker, so a late or post-disarm cancel
        still removes it. The connection and the exact-match checks remain."""
        if not api or not verified:
            raise ValueError('Connect the authenticated destination before cancelling its pending order')
        if not signal.label:
            raise ValueError('Cancellation requires the original label')
        related = self.related(raw)
        if any(r['kind'] in unwind.CANCEL_KINDS and r['request'] and r['destination'] == destination for r in related):
            raise ValueError('Cancellation already attempted; no automatic retry')
        opens = [r for r in related if r['kind'] == 'intent' and r['request'] and r['destination'] == destination]
        if len(opens) != 1 or opens[0]['decision'] != 'accepted':
            raise ValueError('No unique accepted copy is linked to this cancellation')
        original = opens[0]
        request = json.loads(original['request'])
        response = json.loads(original['response'])
        order_id = response.get('orderId')
        if not order_id or request.get('type') not in {'LIMIT', 'STOP'}:
            raise ValueError('The linked copy is not a pending order')
        return unwind.pending_order_request(api, order_id, request), api.cancel_pending_order

    def close(self):
        with self.lock:
            self.armed = False
            self.db.close()
