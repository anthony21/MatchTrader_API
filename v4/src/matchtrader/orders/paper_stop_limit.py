"""Paper execution of R01 ledger intents as LIMIT and emulated STOP_LIMIT orders on live quotes.

New R01_TRADES.csv rows (never history) become paper plans. Each plan is driven by the
destination's live bid/ask and records what a real order would have done: the trigger, the
fill, the bracket exit, and the quote at each moment. The API owner is created with
enable_writes=False and only login, instruments and quotes are ever called, so no broker
order can be produced by this module.

Cancellation is owned here, not delegated: a plan expires when it is not reached within the
arm window, when a triggered stop-limit rests unfilled past the touch TTL, or when R01
regrades the level below the accepted grades. R01's own cancelled rows are honoured too,
so a level R01 has withdrawn is never left armed.
"""

import argparse
import json
import signal
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

from .stop_limit import Route, StopLimitPlan, decide

ORDER_TYPES = {
    "resting limit at range edge": "LIMIT",
    "resting stop at beyond edge": "STOP_LIMIT",
    "resting stop-limit at beyond edge, limit at trigger": "STOP_LIMIT",
}
GRADES = ("PRIME", "STRONG", "FAIR", "POOR", "WEAK", "AVOID")
TERMINAL = {"cancelled", "expired", "held", "closed"}


def size_lots(risk, entry, sl, *, contract_size=Decimal(1), step=Decimal("0.01"),
              minimum=Decimal("0.01"), maximum=Decimal(50)):
    """Lots such that a stop-out loses `risk`; floored to the volume step and clamped."""
    distance = abs(Decimal(entry) - Decimal(sl))
    if distance <= 0:
        raise ValueError("Stop distance must be positive")
    lots = (Decimal(risk) / (distance * contract_size)).quantize(step, rounding=ROUND_DOWN)
    return min(max(lots, minimum), maximum)


@dataclass
class PaperPlan:
    id: str
    label: str
    side: str                 # BUY / SELL
    kind: str                 # LIMIT / STOP_LIMIT
    entry: Decimal
    sl: Decimal
    tp: Decimal
    limit: Decimal            # worst acceptable fill (== entry for LIMIT)
    grade: str
    stamp: str
    lots: Decimal
    detail: str
    source_line: int
    armed_at: str
    state: str = "armed"      # armed -> working -> filled -> closed | cancelled | expired | held
    reason: str = ""
    duplicates: int = 0
    triggered_at: str | None = None
    fill_at: str | None = None
    fill_price: Decimal | None = None
    fill_bid: Decimal | None = None
    fill_ask: Decimal | None = None
    r01_touched_at: str | None = None
    exit_at: str | None = None
    exit_price: Decimal | None = None
    exit_bid: Decimal | None = None
    exit_ask: Decimal | None = None
    exit_reason: str | None = None
    pnl: Decimal | None = None
    history: list = field(default_factory=list)

    def sign(self):
        return 1 if self.side == "BUY" else -1


class PaperBook:
    """Pure state machine over ledger rows and quotes; every transition is returned as an event."""

    def __init__(self, *, symbol, risk, tolerance, grades=GRADES, arm_ttl=900, touch_ttl=45,
                 contract_size=Decimal(1), step=Decimal("0.01"), minimum=Decimal("0.01"),
                 maximum=Decimal(50), stops_level=Decimal(0)):
        self.symbol, self.risk, self.tolerance = symbol, Decimal(risk), Decimal(tolerance)
        self.grades, self.arm_ttl, self.touch_ttl = set(grades), arm_ttl, touch_ttl
        self.sizing = {"contract_size": contract_size, "step": step, "minimum": minimum, "maximum": maximum}
        self.stops_level = stops_level
        self.plans: dict[str, PaperPlan] = {}   # label -> live plan (non-terminal)
        self.done: list[PaperPlan] = []

    # ---- ledger rows -------------------------------------------------------------------------
    def apply_row(self, row, line, now):
        events = []
        if row.get("symbol") != self.symbol or not row.get("label"):
            return events
        kind, label = row.get("kind"), row["label"]
        live = self.plans.get(label)
        if kind == "intent":
            events += self._intent(row, line, now, live)
        elif kind in {"regrade", "modified"} and live:
            events += self._update(row, live, now)
        elif kind == "cancelled" and live:
            if live.state in {"armed", "working"}:
                events.append(self._finish(live, "cancelled", f"R01 cancelled: {row.get('detail', '')}", now))
            else:
                live.history.append((now, "r01-cancelled-ignored", live.state))
        elif kind == "touched" and live:
            live.r01_touched_at = live.r01_touched_at or row.get("utc")
            events.append(("r01-touched", live))
        return events

    def _intent(self, row, line, now, live):
        order_type = ORDER_TYPES.get(row.get("detail", ""))
        if order_type is None:
            return [("ignored", {"label": row["label"], "reason": f"unknown intent detail {row.get('detail')!r}"})]
        entry, sl, tp = (Decimal(row[k]) for k in ("entry", "sl", "tp"))
        side = {"long": "BUY", "short": "SELL"}.get(row.get("side"), "")
        if live:
            same = (live.entry, live.sl, live.tp, live.side) == (entry, sl, tp, side)
            if live.state in {"filled"}:
                live.history.append((now, "intent-while-open", line))
                return [("held-duplicate", live)]
            if same:
                live.duplicates += 1
                return []
            self._finish(live, "cancelled", "replaced by a re-priced intent for the same label", now)
        grade = row.get("grade", "")
        if grade not in self.grades:
            return [("ignored", {"label": row["label"], "reason": f"grade {grade} not accepted"})]
        plan = PaperPlan(id=f"{row['label']}@{line}", label=row["label"], side=side, kind=order_type,
                         entry=entry, sl=sl, tp=tp, limit=entry, grade=grade, stamp=row.get("stamp", ""),
                         lots=Decimal(0), detail=row.get("detail", ""), source_line=line, armed_at=now)
        if not side or (side == "BUY" and not sl < entry < tp) or (side == "SELL" and not tp < entry < sl):
            plan.state, plan.reason = "held", "brackets do not match the side"
            self.done.append(plan)
            return [("held", plan)]
        try:
            plan.lots = size_lots(self.risk, entry, sl, **self.sizing)
        except ValueError as error:
            plan.state, plan.reason = "held", str(error)
            self.done.append(plan)
            return [("held", plan)]
        if order_type == "STOP_LIMIT":
            plan.limit = entry + self.tolerance if side == "BUY" else entry - self.tolerance
            try:
                self._stop_plan(plan)
            except ValueError as error:
                plan.state, plan.reason = "held", f"stop-limit plan rejected: {error}"
                self.done.append(plan)
                return [("held", plan)]
        self.plans[plan.label] = plan
        return [("armed", plan)]

    def _update(self, row, live, now):
        events = []
        grade = row.get("grade", live.grade)
        if row.get("kind") == "modified" and live.state == "armed":
            live.entry, live.sl, live.tp = (Decimal(row[k]) for k in ("entry", "sl", "tp"))
            live.limit = live.entry if live.kind == "LIMIT" else (
                live.entry + self.tolerance if live.side == "BUY" else live.entry - self.tolerance)
            live.lots = size_lots(self.risk, live.entry, live.sl, **self.sizing)
            live.history.append((now, "modified", str(live.entry)))
            events.append(("modified", live))
        if grade != live.grade:
            live.history.append((now, "regrade", f"{live.grade}->{grade}"))
            live.grade, live.stamp = grade, row.get("stamp", live.stamp)
            if grade not in self.grades and live.state in {"armed", "working"}:
                events.append(self._finish(live, "expired", f"retracted on downgrade to {grade}", now))
        return events

    # ---- quotes ------------------------------------------------------------------------------
    def on_quote(self, bid, ask, now, monotonic):
        events = []
        bid, ask = Decimal(str(bid)), Decimal(str(ask))
        for plan in list(self.plans.values()):
            if plan.state == "armed":
                events += self._armed(plan, bid, ask, now, monotonic)
            elif plan.state == "working":
                events += self._working(plan, bid, ask, now, monotonic)
            elif plan.state == "filled":
                events += self._open(plan, bid, ask, now)
        return events

    def _age(self, plan, monotonic):
        return monotonic - plan.history[0][0] if plan.history and plan.history[0][1] == "armed-mono" else 0

    def _armed(self, plan, bid, ask, now, monotonic):
        if not plan.history or plan.history[0][1] != "armed-mono":
            plan.history.insert(0, (monotonic, "armed-mono", ""))
        if self.arm_ttl and self._age(plan, monotonic) > self.arm_ttl:
            return [self._finish(plan, "expired", f"not reached within {self.arm_ttl}s", now)]
        if plan.kind == "LIMIT":
            reached = ask <= plan.entry if plan.side == "BUY" else bid >= plan.entry
            if reached:
                return [self._fill(plan, plan.entry, bid, ask, now, "resting LIMIT reached")]
            return []
        decision = decide(self._stop_plan(plan), _Quote(bid, ask), stops_level=self.stops_level)
        if decision.route is Route.WAIT:
            return []
        plan.triggered_at = now
        plan.history.append((monotonic, "triggered", decision.reason))
        if decision.route is Route.MARKET:
            return [self._fill(plan, decision.price, bid, ask, now, "triggered inside the limit; market fill")]
        if decision.route is Route.HOLD:
            return [self._finish(plan, "held", decision.reason, now)]
        plan.state = "working"
        return [("working", plan)]

    def _working(self, plan, bid, ask, now, monotonic):
        trigger = next((m for m, k, _ in plan.history if k == "triggered"), monotonic)
        reached = ask <= plan.limit if plan.side == "BUY" else bid >= plan.limit
        if reached:
            return [self._fill(plan, plan.limit, bid, ask, now, "resting LIMIT at the limit price reached")]
        if self.touch_ttl and monotonic - trigger > self.touch_ttl:
            return [self._finish(plan, "expired", f"triggered but unfilled after {self.touch_ttl}s", now)]
        return []

    def _open(self, plan, bid, ask, now):
        mark = bid if plan.side == "BUY" else ask     # the price a close would be executed at
        hit_sl = mark <= plan.sl if plan.side == "BUY" else mark >= plan.sl
        hit_tp = mark >= plan.tp if plan.side == "BUY" else mark <= plan.tp
        if not (hit_sl or hit_tp):
            return []
        price = plan.sl if hit_sl else plan.tp
        plan.exit_at, plan.exit_price, plan.exit_bid, plan.exit_ask = now, price, bid, ask
        plan.exit_reason = "SL" if hit_sl else "TP"
        plan.pnl = (price - plan.fill_price) * plan.sign() * plan.lots * self.sizing["contract_size"]
        return [self._finish(plan, "closed", f"{plan.exit_reason} at {price}; quote {bid}/{ask}", now)]

    # ---- helpers -----------------------------------------------------------------------------
    def _stop_plan(self, plan):
        return StopLimitPlan(instrument=self.symbol, orderSide=plan.side, volume=plan.lots or Decimal("0.01"),
                             stopPrice=plan.entry, limitPrice=plan.limit, slPrice=plan.sl, tpPrice=plan.tp)

    def _fill(self, plan, price, bid, ask, now, reason):
        plan.state, plan.fill_at, plan.fill_price = "filled", now, Decimal(price)
        plan.fill_bid, plan.fill_ask, plan.reason = bid, ask, reason
        return ("filled", plan)

    def _finish(self, plan, state, reason, now):
        plan.state, plan.reason = state, reason
        if state != "closed":
            plan.exit_at = now
        self.plans.pop(plan.label, None)
        self.done.append(plan)
        return (state, plan)

    def active(self):
        return bool(self.plans)


class _Quote:
    def __init__(self, bid, ask):
        self.bid, self.ask = bid, ask


# ---- persistence -------------------------------------------------------------------------------
class PaperStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS plans (id TEXT PRIMARY KEY, label TEXT, state TEXT, updated TEXT, plan TEXT);
            CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, at TEXT, type TEXT, label TEXT, detail TEXT);
            CREATE TABLE IF NOT EXISTS quotes (at TEXT, bid TEXT, ask TEXT);
        """)

    def event(self, at, kind, payload):
        if isinstance(payload, PaperPlan):
            label, detail = payload.label, json.dumps(asdict(payload), default=str)
            with self.db:
                self.db.execute("INSERT OR REPLACE INTO plans(id,label,state,updated,plan) VALUES(?,?,?,?,?)",
                                (payload.id, payload.label, payload.state, at, detail))
        else:
            label, detail = payload.get("label", ""), json.dumps(payload, default=str)
        with self.db:
            self.db.execute("INSERT INTO events(at,type,label,detail) VALUES(?,?,?,?)", (at, kind, label, detail))

    def quote(self, at, bid, ask):
        with self.db:
            self.db.execute("INSERT INTO quotes(at,bid,ask) VALUES(?,?,?)", (at, str(bid), str(ask)))

    def report(self):
        rows = [json.loads(r[0]) for r in self.db.execute("SELECT plan FROM plans ORDER BY updated")]
        quotes = self.db.execute("SELECT count(*), min(at), max(at) FROM quotes").fetchone()
        return rows, quotes


def _now():
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def describe(kind, plan):
    if isinstance(plan, dict):
        return f"{kind:10s} {plan.get('label', '')} {plan.get('reason', '')}"
    core = f"{kind:10s} {plan.label} {plan.side} {plan.kind} entry={plan.entry} sl={plan.sl} tp={plan.tp} " \
           f"lots={plan.lots} grade={plan.grade}"
    if kind == "filled":
        return f"{core} fill={plan.fill_price} quote={plan.fill_bid}/{plan.fill_ask}"
    if kind == "closed":
        return f"{core} exit={plan.exit_reason}@{plan.exit_price} pnl={plan.pnl}"
    return f"{core} {plan.reason}"


def run(args):
    from ..bridge.ledger import LedgerTail
    from ..core.settings import Settings

    settings = Settings.model_validate({**Settings.from_env(args.env).model_dump(),
                                        "account_id": args.account, "enable_writes": False})
    from ..api import MatchTraderAPI

    store = PaperStore(args.db)
    stop = {"requested": False}
    signal.signal(signal.SIGINT, lambda *_: stop.update(requested=True))
    with MatchTraderAPI(settings) as api:
        api.login()
        found = [i for i in api.instruments() if getattr(i, "symbol", None) == args.destination]
        if len(found) != 1:
            raise SystemExit(f"Destination instrument {args.destination} is not uniquely available")
        inst = found[0]
        book = PaperBook(symbol=args.symbol, risk=args.risk, tolerance=args.tolerance,
                         grades=[g.strip() for g in args.grades.split(",") if g.strip()],
                         arm_ttl=args.arm_ttl, touch_ttl=args.touch_ttl,
                         contract_size=Decimal(str(inst.contractSize or 1)),
                         step=Decimal(str(inst.volumeStep or "0.01")),
                         minimum=Decimal(str(inst.volumeMin or "0.01")),
                         maximum=Decimal(str(inst.volumeMax or 50)),
                         stops_level=Decimal(str(inst.stopsLevel or 0)))
        tail = LedgerTail(args.ledger)
        print(f"{_now()} paper stop-limit ON | account {args.account} (writes disabled) | {args.symbol}->"
              f"{args.destination} | risk ${args.risk} | tolerance {args.tolerance} | grades {sorted(book.grades)} "
              f"| arm ttl {args.arm_ttl}s | touch ttl {args.touch_ttl}s | ledger from byte {tail.offset}", flush=True)
        store.event(_now(), "start", {"label": "", "account": args.account, "risk": str(args.risk),
                                      "tolerance": str(args.tolerance), "grades": sorted(book.grades)})
        next_quote, last_quote_log = 0.0, 0.0
        while not stop["requested"] and not (args.stop_file and args.stop_file.exists()):
            now = _now()
            for line_offset, payload in tail.poll():
                row = payload["record"]
                for kind, plan in book.apply_row(row, line_offset, now):
                    store.event(now, kind, plan)
                    print(f"{now} {describe(kind, plan)}", flush=True)
            mono = time.monotonic()
            if book.active() and mono >= next_quote:
                next_quote = mono + args.quote_interval
                try:
                    quotes = [q for q in api.quotes(symbols=args.destination) if q.symbol == args.destination]
                except Exception as error:  # a quote failure must never end the paper session
                    print(f"{now} quote read failed: {type(error).__name__}", flush=True)
                    quotes = []
                if quotes:
                    bid, ask = quotes[0].bid, quotes[0].ask
                    if mono - last_quote_log >= 60:
                        store.quote(now, bid, ask)
                        last_quote_log = mono
                    for kind, plan in book.on_quote(bid, ask, now, mono):
                        store.event(now, kind, plan)
                        print(f"{now} {describe(kind, plan)}", flush=True)
            time.sleep(0.25)
        store.event(_now(), "stop", {"label": "", "open_plans": [p.label for p in book.plans.values()]})
        print(f"{_now()} paper stop-limit OFF | {len(book.done)} plans finished, {len(book.plans)} still armed",
              flush=True)


def report(args):
    rows, quotes = PaperStore(args.db).report()
    by_state = {}
    for r in rows:
        by_state[r["state"]] = by_state.get(r["state"], 0) + 1
    print(f"plans: {len(rows)} by state {by_state}; quote samples {quotes[0]} from {quotes[1]} to {quotes[2]}")
    pnl = sum(Decimal(r["pnl"]) for r in rows if r.get("pnl") is not None)
    closed = [r for r in rows if r["state"] == "closed"]
    print(f"closed: {len(closed)}  wins {sum(1 for r in closed if Decimal(r['pnl']) > 0)}  "
          f"losses {sum(1 for r in closed if Decimal(r['pnl']) < 0)}  P/L {pnl}")
    for r in rows:
        if r["state"] in {"filled", "closed"}:
            slip = (Decimal(r["fill_price"]) - Decimal(r["entry"])) * (1 if r["side"] == "BUY" else -1)
            print(f"  {r['label']} {r['side']} {r['kind']} grade={r['grade']} lots={r['lots']} level={r['entry']} "
                  f"fill={r['fill_price']} (slip {slip:+}) at {r['fill_at']} r01_touch={r['r01_touched_at']} "
                  f"-> {r.get('exit_reason') or 'open'} {r.get('exit_price') or ''} pnl={r.get('pnl')}")
    for r in rows:
        if r["state"] in {"cancelled", "expired", "held"}:
            print(f"  {r['state']:9s} {r['label']} {r['side']} {r['kind']} grade={r['grade']}: {r['reason']}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--account", required=True, help="Destination demo account id (quotes only; no writes)")
    parser.add_argument("--symbol", default="BTCUSD", help="R01 symbol as written in the ledger")
    parser.add_argument("--destination", default="BTCUSD", help="Destination instrument symbol")
    parser.add_argument("--risk", type=Decimal, default=Decimal(5), help="USD lost at the stop, sets lots")
    parser.add_argument("--tolerance", type=Decimal, default=Decimal(5), help="Stop-limit: worst fill past trigger")
    parser.add_argument("--grades", default=",".join(GRADES))
    parser.add_argument("--arm-ttl", type=float, default=900, help="Seconds an armed level may wait; 0 = forever")
    parser.add_argument("--touch-ttl", type=float, default=45, help="Seconds a triggered stop-limit may rest")
    parser.add_argument("--quote-interval", type=float, default=1.0)
    parser.add_argument("--db", type=Path, default=Path("data/paper/stop-limit-paper.sqlite3"))
    parser.add_argument("--stop-file", type=Path)
    parser.add_argument("--report", action="store_true", help="Print the paper record and exit")
    args = parser.parse_args(argv)
    if args.report:
        return report(args)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
