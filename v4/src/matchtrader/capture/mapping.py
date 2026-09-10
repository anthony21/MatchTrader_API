"""Account-scoped identity relationships and execution evidence in the capture transaction.

The owning CaptureStore supplies locking and transactions. A position snapshot is
not an execution, and its volume is not an allocation to a contributing trade.
"""

import json
from decimal import Decimal

from ..version import MAPPING_SCHEMA_VERSION


class MappingLedger:
    def __init__(self, db, broker):
        self.db = db
        self.broker = broker
        db.executescript("""
            CREATE TABLE IF NOT EXISTS mapping_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS identity_links (
                trade_id TEXT, side TEXT, scope TEXT, kind TEXT, native_id TEXT,
                evidence TEXT, updated_at TEXT,
                PRIMARY KEY(trade_id,side,scope,kind,native_id));
            CREATE INDEX IF NOT EXISTS identity_lookup ON identity_links(side,scope,kind,native_id);
            CREATE TABLE IF NOT EXISTS execution_fills (
                side TEXT, scope TEXT, execution_id TEXT, trade_id TEXT, order_id TEXT,
                position_id TEXT, quantity TEXT, price TEXT, effect TEXT, emitted_at TEXT,
                PRIMARY KEY(side,scope,execution_id));
            CREATE TABLE IF NOT EXISTS quantity_observations (
                trade_id TEXT, side TEXT, scope TEXT, requested TEXT, cumulative TEXT,
                remaining TEXT, unit TEXT, updated_at TEXT,
                PRIMARY KEY(trade_id,side,scope));
            CREATE TABLE IF NOT EXISTS position_observations (
                side TEXT, scope TEXT, position_id TEXT, volume TEXT, updated_at TEXT,
                PRIMARY KEY(side,scope,position_id));
            CREATE TABLE IF NOT EXISTS action_history (
                trade_id TEXT, action_key TEXT, broker TEXT, account_id TEXT,
                request_id TEXT, action TEXT, request TEXT, outcome TEXT,
                broker_order_id TEXT, broker_position_id TEXT, updated_at TEXT,
                PRIMARY KEY(trade_id,action_key));
        """)
        with db:
            version = db.execute("SELECT value FROM mapping_meta WHERE key='schema_version'").fetchone()
            if version and version[0] != MAPPING_SCHEMA_VERSION:
                raise ValueError("Unsupported mapping journal schema version")
            old = db.execute("SELECT value FROM mapping_meta WHERE key='broker'").fetchone()
            if old and old[0] != broker:
                raise ValueError("Capture journal belongs to another broker; use its own data directory")
            db.execute("INSERT OR IGNORE INTO mapping_meta VALUES('broker',?)", (broker,))
            db.execute("INSERT OR IGNORE INTO mapping_meta VALUES('schema_version',?)", (MAPPING_SCHEMA_VERSION,))
            if not db.execute("SELECT 1 FROM mapping_meta WHERE key='legacy_migrated'").fetchone():
                for row in db.execute("SELECT * FROM trades").fetchall():
                    t = dict(row)
                    self.link(t['trade_id'], 'source', t['scope'], 'order', t['source_order_id'],
                              'legacy journal', t['updated_at'])
                    self.link(t['trade_id'], 'source', t['scope'], 'position', t['source_position_id'],
                              'legacy journal', t['updated_at'])
                    if t['destination']:
                        scope = self.destination_scope(t['destination'])
                        # Older code substituted positionId for absent orderId. Do not perpetuate that guess.
                        if t['broker_order_id'] != t['broker_position_id']:
                            self.link(t['trade_id'], 'destination', scope, 'order', t['broker_order_id'],
                                      'legacy journal', t['updated_at'])
                        elif t['broker_order_id']:
                            db.execute("UPDATE trades SET broker_order_id='',state='uncertain' WHERE trade_id=?",
                                       (t['trade_id'],))
                        self.link(t['trade_id'], 'destination', scope, 'position', t['broker_position_id'],
                                  'legacy journal', t['updated_at'])
                db.execute("INSERT INTO mapping_meta VALUES('legacy_migrated','1')")
            db.execute("UPDATE action_history SET outcome='uncertain' WHERE outcome='dispatching'")

    def destination_scope(self, account):
        return json.dumps([self.broker, account])

    def link(self, trade, side, scope, kind, native_id, evidence, at):
        if native_id:
            self.db.execute(
                "INSERT OR IGNORE INTO identity_links VALUES(?,?,?,?,?,?,?)",
                (trade, side, scope, kind, native_id, evidence, at),
            )

    def ids(self, trade, side, kind):
        return [r[0] for r in self.db.execute(
            "SELECT DISTINCT native_id FROM identity_links WHERE trade_id=? AND side=? AND kind=?",
            (trade, side, kind),
        )]

    def owners(self, side, scope, position):
        return [r[0] for r in self.db.execute(
            "SELECT DISTINCT trade_id FROM identity_links WHERE side=? AND scope=? "
            "AND kind='position' AND native_id=?", (side, scope, position),
        )]

    def source_event(self, trade, event):
        scope, at = json.dumps(event.scope), event.emitted_at.isoformat()
        self.link(trade, 'source', scope, 'order', event.order_id, 'native order', at)
        if event.position_id and event.kind in {'FILL', 'POSITION'}:
            self.link(trade, 'source', scope, 'position', event.position_id, 'native relationship', at)
        if event.kind == 'FILL' and event.execution_id:
            self.fill(trade, 'source', scope, event.execution_id, event.order_id, event.position_id,
                      event.quantity, event.price, event.fill_effect, at)
        if event.position_id and event.position_quantity is not None:
            self.position('source', scope, event.position_id, event.position_quantity, at)
        requested = event.order_quantity
        if requested is None and event.kind == 'ACCEPTED' and event.action in {'CREATE', 'EDIT'}:
            requested = event.quantity
        self.quantities(trade, 'source', scope, requested, event.cumulative_filled_quantity,
                        event.remaining_quantity, event.quantity_unit, at)

    def fill(self, trade, side, scope, execution, order, position, quantity, price, effect, at):
        values = (side, scope, execution, trade, order, position, str(quantity), str(price), effect, at)
        old = self.db.execute(
            "SELECT * FROM execution_fills WHERE side=? AND scope=? AND execution_id=?",
            (side, scope, execution),
        ).fetchone()
        if old:
            # Equal quantities may have different decimal spellings; receipt/event IDs may change.
            stable = tuple(old)[:6] == values[:6] and old['effect'] == effect
            if not stable or Decimal(old['quantity']) != quantity or Decimal(old['price']) != price:
                raise ValueError("Execution ID reused with conflicting fill data")
            return
        self.db.execute("INSERT INTO execution_fills VALUES(?,?,?,?,?,?,?,?,?,?)", values)
        self.link(trade, side, scope, 'order', order, 'execution', at)
        self.link(trade, side, scope, 'position', position, 'execution', at)

    def quantities(self, trade, side, scope, requested, cumulative, remaining, unit, at):
        old = self.db.execute("SELECT updated_at FROM quantity_observations WHERE trade_id=? AND side=? AND scope=?",
                              (trade, side, scope)).fetchone()
        if old and old[0] > at:
            return
        self.db.execute(
            "INSERT INTO quantity_observations VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(trade_id,side,scope) DO UPDATE SET "
            "requested=COALESCE(excluded.requested,requested),cumulative=COALESCE(excluded.cumulative,cumulative),"
            "remaining=COALESCE(excluded.remaining,remaining),unit=excluded.unit,updated_at=excluded.updated_at",
            (trade, side, scope, *[str(x) if x is not None else None for x in (requested, cumulative, remaining)],
             unit, at),
        )

    def position(self, side, scope, position, volume, at):
        self.db.execute(
            "INSERT INTO position_observations VALUES(?,?,?,?,?) ON CONFLICT(side,scope,position_id) "
            "DO UPDATE SET volume=excluded.volume,updated_at=excluded.updated_at "
            "WHERE excluded.updated_at>=position_observations.updated_at",
            (side, scope, position, str(volume), at),
        )

    def guard_position(self, trade):
        for side in ('source', 'destination'):
            links = self.db.execute(
                "SELECT scope,native_id FROM identity_links WHERE trade_id=? AND side=? AND kind='position'",
                (trade, side),
            ).fetchall()
            if len(links) > 1:
                raise ValueError(f"Split {side} positions require an explicit action allocation")
            for row in links:
                if len(self.owners(side, row['scope'], row['native_id'])) > 1:
                    raise ValueError(f"Merged {side} position requires an explicit action allocation")

    def snapshot(self, trade):
        identity = trade['trade_id']
        links = [dict(r) for r in self.db.execute("SELECT * FROM identity_links WHERE trade_id=?", (identity,))]
        fills = [dict(r) for r in self.db.execute(
            "SELECT * FROM execution_fills WHERE trade_id=? ORDER BY emitted_at,execution_id", (identity,))]
        quantities = [dict(r) for r in self.db.execute(
            "SELECT * FROM quantity_observations WHERE trade_id=?", (identity,))]
        for q in quantities:
            known = [f for f in fills if f['side'] == q['side'] and f['scope'] == q['scope']]
            for effect in ('OPEN', 'CLOSE'):
                matching = [f for f in known if f['effect'] == effect]
                q[effect.lower() + '_filled'] = str(sum((Decimal(f['quantity']) for f in matching), Decimal(0)))
            q['unknown_effect_fills'] = sum(f['effect'] == 'UNKNOWN' for f in known)
            q['partial'] = (q['cumulative'] is not None and q['remaining'] is not None
                            and Decimal(q['cumulative']) > 0 and Decimal(q['remaining']) > 0)
        for link in links:
            link['scope'] = json.loads(link['scope'])
            if link['kind'] == 'position':
                scope = json.dumps(link['scope'])
                link['contributors'] = self.owners(link['side'], scope, link['native_id'])
                observations = self.db.execute(
                    "SELECT volume,updated_at FROM position_observations WHERE side=? AND scope=? AND position_id=?",
                    (link['side'], scope, link['native_id']),
                ).fetchone()
                link['position_snapshot'] = dict(observations) if observations else None
                evidence = [f for f in fills if f['side'] == link['side'] and f['scope'] == scope
                            and f['position_id'] == link['native_id']]
                link['observed_open_contribution'] = str(sum(
                    (Decimal(f['quantity']) for f in evidence if f['effect'] == 'OPEN'), Decimal(0)))
                link['observed_close_contribution'] = str(sum(
                    (Decimal(f['quantity']) for f in evidence if f['effect'] == 'CLOSE'), Decimal(0)))
                link['allocation_confirmed'] = False  # Observed fills alone do not prove complete allocation.
        reasons = []
        try:
            self.guard_position(identity)
        except ValueError as exc:
            reasons.append(str(exc))
        has_destination = any(x['side'] == 'destination' for x in links)
        if not has_destination:
            reasons.append('Destination identity not confirmed')
        if trade['state'] == 'open' and not self.ids(identity, 'destination', 'position'):
            reasons.append('Destination position identity not confirmed')
        if trade['state'] == 'open' and not self.ids(identity, 'source', 'position'):
            reasons.append('Source position identity not confirmed')
        status = ('uncertain' if trade['state'] in {'uncertain', 'dispatching'}
                  else 'incomplete' if reasons else 'confirmed')
        actions = [dict(r) for r in self.db.execute(
            "SELECT * FROM action_history WHERE trade_id=? ORDER BY updated_at DESC", (identity,))]
        for action in actions:
            action['request'] = json.loads(action['request'])
        return {'schema_version': MAPPING_SCHEMA_VERSION, 'trade_id': identity, 'broker': self.broker,
                'source_scope': json.loads(trade['scope']),
                'symbol': trade.get('symbol', ''), 'side': trade.get('side', ''), 'source': trade.get('source', 'UNKNOWN'),
                'account_id': trade['destination'], 'state': trade['state'], 'mapping_status': status,
                'reasons': reasons, 'links': links, 'fills': fills, 'quantities': quantities,
                'actions': actions, 'updated_at': trade['updated_at']}
