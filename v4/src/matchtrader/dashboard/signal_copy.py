"""Receive signals, decide once through the engine, dispatch once, and remember everything.

    receive()  ->  parse_signal()  ->  SignalEngine.decide()  ->  BrokerDispatcher.send()

This module keeps the durable record (signals and their appearances) and the lane settings.
The symbol map is a separate file the engine looks up. Cancels and closes of exposure this
owner created go through capture.unwind or the dispatcher's cancel, whatever the switches say.
"""
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import RLock
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..capture import unwind
from ..signals import (
    BrokerDispatcher, Context, Refusal, SignalEngine, SymbolMap, SymbolMapping, SymbolMapStore, parse_signal,
)
from ..signals.shapes import BaseSignal as Signal  # noqa: F401  (the base shape, for callers that build one)
from .copy_settings import save_settings

GRADES = ('PRIME', 'STRONG', 'FAIR', 'POOR', 'WEAK', 'AVOID')


class SignalSymbol(BaseModel):
    """The legacy per-symbol row the settings form still posts; it is split into the symbol map."""
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, str_strip_whitespace=True)
    destination: str = Field(min_length=1, max_length=100)
    fixed_lots: Decimal = Field(gt=0)
    order_type: Literal['MARKET', 'LIMIT', 'STOP', 'SOURCE', 'ENTRY']
    same_price_scale: Literal[True]


class SignalSettings(BaseModel):
    """The lane: which machine and source, to which account, and how attribution is proven.

    `symbols` is accepted for compatibility with saved files and the current form, but it is
    stored in the symbol map, not in the lane."""
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    machine_id: str = Field(min_length=1, max_length=100)
    source: str = Field(default='chain', min_length=1, max_length=100)
    connection_name: str = Field(default='', max_length=200)
    destination_account: str = Field(min_length=1, max_length=200)
    symbols: dict[Annotated[str, Field(min_length=1, max_length=100)], SignalSymbol] = Field(default_factory=dict)
    exclusive_destination: Literal[True]
    p01_log_enabled: bool = False
    additional_sources: list[Literal['chain', 'panel']] = Field(default_factory=list)
    x17_only: bool = False
    # Strategy lanes (R01): which ledger grades may open, whether a downgrade below them retracts a
    # resting copy, and an optional dollar risk per trade that replaces the map's fixed lots.
    accepted_grades: list[Literal['PRIME', 'STRONG', 'FAIR', 'POOR', 'WEAK', 'AVOID']] = Field(default_factory=list)
    retract_on_downgrade: bool = True
    risk_usd: Decimal | None = Field(default=None, gt=0)
    # How lots are sized: 'lots' uses the Symbol map's fixed lots; 'dollar' risks a fixed dollar
    # amount per trade; 'percent' risks that percent of the destination account's equity. The value
    # is the dollars or the percent. None falls back to the legacy risk_usd (dollar) if it is set.
    sizing: Literal['lots', 'dollar', 'percent'] | None = None
    sizing_value: Decimal | None = Field(default=None, gt=0)
    # The minimum box (take-profit to stop-loss distance) this lane will copy, with its own switch.
    # It lives on the lane, not the symbol map, so one setting governs every instrument this lane
    # handles. Tight boxes sit inside spread and noise and stop out on entry; 0 or the switch off
    # disables the filter.
    min_box: Decimal = Field(default=Decimal(0), ge=0)
    min_box_enabled: bool = False

    @model_validator(mode='before')
    @classmethod
    def retire_cancel_pending(cls, value):
        # Cancelling a linked pending order is no longer optional: a cancel or closed signal always
        # acts on exposure we created. Saved files from before this rule still load; the key is dropped.
        if isinstance(value, dict) and 'cancel_pending' in value:
            value = {k: v for k, v in value.items() if k != 'cancel_pending'}
        return value

    def symbol_map(self):
        return SymbolMap({k: SymbolMapping(destination=v.destination, lots=v.fixed_lots, order_type=v.order_type)
                          for k, v in self.symbols.items()})


class SignalCopy:
    """One lane: its settings, its durable record, and the engine and dispatcher it decides through.
    Several lanes (P01 log, R01 ledger) share one symbol map through a `SymbolMapStore`."""

    def __init__(self, directory, ledger=None, symbols=None):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / 'signal-copy-settings.json'
        self.symbol_store = symbols if symbols is not None else SymbolMapStore(directory / 'symbol-map.json')
        self.config = SignalSettings.model_validate_json(self.path.read_text()) if self.path.exists() else None
        if self.config and self.config.symbols and not len(self.symbols):
            self.symbol_store.replace(self.config.symbol_map())   # first load of a file saved before the split
        # The CaptureStore holding the trades the owner sent; cancel/closed signals unwind against it.
        self.ledger = ledger
        self.dispatcher = BrokerDispatcher(raw_log=ledger.raw_log if ledger is not None else None)
        self.lock = RLock()
        self.armed = False
        self.copy_mode = None
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

    @property
    def symbols(self):
        return self.symbol_store.map

    @property
    def engine(self):
        return SignalEngine(self.config, self.symbols)

    # ---- settings ----------------------------------------------------------------------------
    def settings(self):
        with self.lock:
            config = self.config.model_dump(mode='json') if self.config else None
            if config is not None:
                config['symbols'] = {k: {'destination': m.destination, 'fixed_lots': str(m.lots),
                                         'order_type': m.order_type, 'same_price_scale': True}
                                     for k, m in self.symbols.root.items()}
            return {'config': config, 'live': self.armed}

    def configure(self, payload):
        value = SignalSettings.model_validate(payload)
        if value.p01_log_enabled and 'panel' in value.additional_sources:
            raise ValueError('Use either P01 local log or structured panel signals, not both')
        if value.p01_log_enabled and value.source != 'P01_LOG':
            raise ValueError('P01 log routing requires source P01_LOG')
        if value.p01_log_enabled and any(v.order_type != 'SOURCE' for v in value.symbols.values()):
            raise ValueError('P01 log routing must preserve the source Limit/Stop order type')
        if not value.symbols and not len(self.symbols):
            raise ValueError('At least one symbol mapping is required')
        with self.lock:
            if self.armed and self.copy_mode != 'paper':
                raise ValueError('Turn live signal copying off before editing settings')
            if value.symbols:
                self.symbol_store.replace(value.symbol_map())
            lane = value.model_copy(update={'symbols': {}})
            save_settings(self.path, lane)
            self.config = lane
            return self.settings()

    def configure_symbols(self, payload):
        """Replace the symbol map on its own; the lane is untouched."""
        symbols = SymbolMap.model_validate(payload)
        if not len(symbols):
            raise ValueError('At least one symbol mapping is required')
        with self.lock:
            if self.armed and self.copy_mode != 'paper':
                raise ValueError('Turn live signal copying off before editing settings')
            self.symbol_store.replace(symbols)
            return self.symbols.model_dump(mode='json')

    def arm(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('Live mode must be a boolean')
        with self.lock:
            self.armed = enabled
            self.armed_at = datetime.now(UTC) if enabled else None

    # ---- the record --------------------------------------------------------------------------
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

    def _record(self, key, **columns):
        with self.db:
            self.db.execute('UPDATE signals SET ' + ','.join(f'{k}=?' for k in columns) + ' WHERE id=?',
                            (*columns.values(), key))

    @staticmethod
    def scope(raw):
        return tuple(raw.get(k, '') for k in ('machineId', 'source', 'accountId', 'connectionName', 'symbol', 'label'))

    def related(self, raw):
        rows = self.db.execute('SELECT * FROM signals WHERE machine=? AND source=? AND label=?',
                               (raw.get('machineId'), raw.get('source'), raw.get('label'))).fetchall()
        return [r for r in rows if self.scope(json.loads(r['payload'])) == self.scope(raw)]

    def legacy_copy(self, raw, destination):
        """True when this module itself dispatched the intent of this lifecycle while armed."""
        return any(r['kind'] == 'intent' and r['request'] and r['destination'] == destination for r in self.related(raw))

    def live_copy(self, raw, destination):
        """True when the broker accepted a live copy of this lifecycle: exposure exists to unwind,
        whatever the master switch says now. A paper record never counts."""
        return any(r['kind'] == 'intent' and r['request'] and r['destination'] == destination
                   and r['decision'] == 'accepted' for r in self.related(raw))

    # ---- receive -----------------------------------------------------------------------------
    def receive(self, payload, api, destination, verified):
        if not isinstance(payload, list) or not 1 <= len(payload) <= 100 or any(not isinstance(p, dict) for p in payload):
            raise ValueError('Expected an array of 1 to 100 signal objects')
        # A completed lifecycle in the same batch must not open an obsolete intent.
        closed = {self.scope(p) for p in payload if p.get('kind') in {'closed', 'cancelled', 'cancel'} and p.get('label')}
        results = []
        with self.lock:
            for raw in payload:
                try:
                    signal = parse_signal(raw)
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
            self._open(key, signal, raw, closed, api, destination, verified, now)
        elif self.copy_mode is not None and signal.kind == 'closed':
            pass  # This flow only opens orders and cancels pending orders; filled positions are left alone.
        elif (self.copy_mode == 'paper' and signal.kind in unwind.CANCEL_KINDS
              and not self.live_copy(raw, destination)):
            pass  # Paper never created a broker order for this lifecycle, so there is nothing to cancel.
        elif signal.kind in unwind.UNWIND_KINDS:
            self._unwind(key, signal, raw, api, destination, verified)
        return self.result(self.db.execute('SELECT * FROM signals WHERE id=?', (key,)).fetchone())

    # ---- open: engine, then dispatcher ---------------------------------------------------------
    def _context(self, signal, raw, closed, api, destination, verified, now):
        related = self.related(raw)
        bridge = False
        if self.copy_mode is not None and self.ledger is not None:
            from ..capture.manual_send import already_sent
            bridge = any(already_sent(self.ledger, trade['trade_id'])
                         for trade in unwind.linked_trades(self.ledger, signal.machineId, signal.label))
        return Context(
            mode=self.copy_mode, armed=self.armed, armed_at=self.armed_at, now=now, destination=destination,
            api=api, verified=verified,
            ended_in_batch=self.scope(raw) in closed or (signal.machineId, signal.source, signal.label) in closed,
            later_end_recorded=any(r['kind'] in {'closed', 'cancelled', 'cancel'}
                                   and r['emitted'] >= signal.timestampUtc.isoformat() for r in related),
            already_attempted=any(r['kind'] == 'intent' and r['request'] and r['destination'] == destination
                                  for r in related),
            bridge_request_exists=bridge)

    def _open(self, key, signal, raw, closed, api, destination, verified, now):
        try:
            plan = self.engine.decide(signal, self._context(signal, raw, closed, api, destination, verified, now))
        except Refusal as refusal:
            self._record(key, decision='held', reason=str(refusal))
            return
        except Exception as error:
            self._record(key, decision='held', reason=f'Processing interrupted by {type(error).__name__}; no automatic retry')
            return
        request = plan.request()
        if self.copy_mode == 'paper':
            self._record(key, decision='paper', destination=destination, request=json.dumps(request, default=str),
                         reason='Paper: broker request recorded; nothing sent')
            return
        # Commit the attempt before invoking a broker write. Uncertain outcomes are never retried.
        self._record(key, decision='dispatching', destination=destination, request=json.dumps(request, default=str))
        outcome = self.dispatcher.send(plan, api, correlation=key)
        self._record(key, decision=outcome.decision, reason=outcome.reason, response=json.dumps(outcome.response))

    # ---- unwind ------------------------------------------------------------------------------
    def _unwind(self, key, signal, raw, api, destination, verified):
        """A cancel or closed signal acts on exposure we created, now, whatever the toggles say."""
        if signal.kind in unwind.CANCEL_KINDS and self.legacy_copy(raw, destination):
            self._cancel_own_copy(key, signal, raw, api, destination, verified)
            return
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
            self._record(key, decision=outcome['decision'], reason=outcome['reason'], destination=destination,
                         request=json.dumps(outcome['request'], default=str) if outcome['request'] is not None else None,
                         response=json.dumps(outcome['response'], default=str) if outcome['response'] is not None else None)
            return
        reason = (f'Signal carries no lifecycle label; nothing to {verb}' if not signal.label else
                  f'No sent trade is linked to lifecycle {signal.label!r} from {signal.machineId}; nothing to {verb}')
        self._record(key, decision='captured', reason=reason)

    def _cancel_own_copy(self, key, signal, raw, api, destination, verified):
        """Cancel a pending order this module placed. Not gated by arming, freshness or the master
        switch: the order is real. The connection and the exact-match checks remain."""
        try:
            request = self.prepare_cancel(signal, raw, api, destination, verified)
        except ValueError as error:
            self._record(key, decision='held', reason=str(error))
            return
        self._record(key, decision='dispatching', destination=destination, request=json.dumps(request, default=str))
        outcome = self.dispatcher.cancel(request, api, correlation=key)
        self._record(key, decision=outcome.decision, reason=outcome.reason, response=json.dumps(outcome.response))

    def prepare_cancel(self, signal, raw, api, destination, verified):
        if not api or not verified:
            raise ValueError('Connect the authenticated destination before cancelling its pending order')
        if getattr(getattr(api, 'connection', None), 'account_id', destination) != destination:
            raise ValueError('The broker connection belongs to a different account')
        if not signal.label:
            raise ValueError('Cancellation requires the original label')
        related = self.related(raw)
        if any(r['kind'] in unwind.CANCEL_KINDS and r['request'] and r['destination'] == destination for r in related):
            raise ValueError('Cancellation already attempted; no automatic retry')
        opens = [r for r in related if r['kind'] == 'intent' and r['request'] and r['destination'] == destination]
        if len(opens) != 1 or opens[0]['decision'] != 'accepted':
            raise ValueError('No unique accepted copy is linked to this cancellation')
        request = json.loads(opens[0]['request'])
        response = json.loads(opens[0]['response'])
        order_id = response.get('orderId')
        if not order_id or request.get('type') not in {'LIMIT', 'STOP'}:
            raise ValueError('The linked copy is not a pending order')
        return unwind.pending_order_request(api, order_id, request)

    def close(self):
        with self.lock:
            self.armed = False
            self.db.close()
