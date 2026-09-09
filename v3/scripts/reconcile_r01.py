"""Evidence-based R01 ledger versus Match-Trader closed-history comparison."""

import argparse
import csv
import hashlib
import html
import json
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd


def utc(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Source/window UTC timestamps must have offsets")
    return result


def load_ledger(path, end):
    content = path.read_bytes()
    rows, invalid = [], []
    for line, row in enumerate(csv.DictReader(content.decode("utf-8-sig").splitlines()), 2):
        row["extra_fields"] = json.dumps(row.pop(None, []))
        row["source_line"] = line
        try:
            row["time"] = utc(row["utc"])
            for key in ("entry", "sl", "tp"):
                if not Decimal(row[key]).is_finite():
                    raise ValueError("Nonfinite level")
        except (ValueError, KeyError, ArithmeticError):
            invalid.append(line)
            continue
        if row["time"] < end:
            rows.append(row)
    rows.sort(key=lambda r: (r["time"], r["source_line"]))
    return rows, invalid, hashlib.sha256(content).hexdigest()


def states_from_events(events):
    """Keep repeated labels and successive brackets distinct, including old states."""
    episodes, active, states = {}, {}, {}
    for row in events:
        label = (row["symbol"], row["label"], row["side"])
        if row["kind"] == "intent" or label not in active:
            episode = {
                "id": row["source_line"],
                "intent": row if row["kind"] == "intent" else None,
                "events": [],
            }
            episodes[episode["id"]] = episode
            active[label] = episode
        episode = active[label]
        episode["events"].append(row)
        if row["kind"] not in {"intent", "regrade", "touched"}:
            continue
        key = (episode["id"], *(Decimal(row[k]) for k in ("entry", "sl", "tp")))
        if key not in states:
            states[key] = {"first": row, "episode": episode}
    return list(states.values()), episodes


def candidates(trade, states, level_tolerance=Decimal("0.01001"), entry_tolerance=Decimal("2")):
    side = {"BUY": "long", "SELL": "short"}[trade["Side"]]
    return [
        s
        for s in states
        if s["first"]["symbol"] == trade["Symbol"]
        and s["first"]["side"] == side
        and abs(Decimal(s["first"]["entry"]) - Decimal(trade["Open Price"])) <= entry_tolerance
        and all(
            abs(Decimal(s["first"][k]) - Decimal(trade[c])) < level_tolerance
            for k, c in (("sl", "Stop Loss"), ("tp", "Take Profit"))
        )
    ]


def broker_rows(path):
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    trades = raw.loc[raw["ID"].str.startswith("W")].copy()
    footer = raw.loc[~raw["ID"].str.startswith("W")]
    if trades.empty or not trades.ID.is_unique:
        raise ValueError("Expected nonempty, unique closed-trade IDs; inspect partial-close schema")
    if len(trades) + len(footer) != len(raw) or len(footer) > 1:
        raise ValueError("Unexpected non-trade rows")
    total = sum(map(Decimal, trades.Profit))
    if len(footer) and Decimal(footer.iloc[0]["Profit"]) != total:
        raise ValueError("Trade profits do not reconcile with the export total")
    return trades.to_dict("records"), total


def evidence_csv(path, rows):
    if rows:
        pd.DataFrame(rows).drop(columns=["time"], errors="ignore").to_csv(path, index=False)


def reconcile(ledger, broker, output, start, end, account, verdicts=None, slogs=None):
    output.mkdir(parents=True, exist_ok=True)
    originals = {"ledger": str(ledger), "broker": str(broker)}
    snapshots = output / "source-snapshots"
    snapshots.mkdir(exist_ok=True)
    for name, source in (("ledger", ledger), ("broker", broker), ("verdicts", verdicts)):
        if source is not None:
            (snapshots / (name + ".csv")).write_bytes(source.read_bytes())
    ledger, broker = snapshots / "ledger.csv", snapshots / "broker.csv"
    if verdicts:
        verdicts = snapshots / "verdicts.csv"
    trades, total = broker_rows(broker)
    if any(t.get("Account", account) != account for t in trades):
        raise ValueError("Broker export account differs from requested account")
    events, invalid, ledger_hash = load_ledger(ledger, end)
    states, episodes = states_from_events(events)
    window_events = [r for r in events if start <= r["time"] < end]
    rows, alternatives, used_episodes = [], [], set()
    for trade in trades:
        possible = candidates(trade, states)
        row = {
            "account": account,
            "broker_id": trade["ID"],
            "symbol": trade["Symbol"],
            "side": trade["Side"],
            "volume": trade["Volume"],
            "match": "Unique level candidate"
            if len(possible) == 1
            else "Ambiguous level candidates"
            if possible
            else "No level candidate",
            "candidate_count": len(possible),
            "qt_label": "",
            "qt_intent_utc": "",
            "qt_state_utc": "",
            "qt_state_kind": "",
            "qt_requested_entry": "",
            "qt_sl": "",
            "qt_tp": "",
            "qt_source_line": "",
            "qt_send_utc": "",
            "relay_ack_utc": "",
            "broker_received_utc": "",
            "broker_fill_time_as_exported": trade["Open Time"],
            "broker_entry": trade["Open Price"],
            "broker_sl": trade["Stop Loss"],
            "broker_tp": trade["Take Profit"],
            "broker_close_time_as_exported": trade["Close Time"],
            "broker_close_price": trade["Close Price"],
            "profit_usd": trade["Profit"],
            "outcome": "WIN"
            if Decimal(trade["Profit"]) > 0
            else "LOSS"
            if Decimal(trade["Profit"]) < 0
            else "BREAKEVEN",
            "close_reason": trade["Reason"],
            "entry_difference_broker_minus_qt": "",
            "sl_difference_broker_minus_qt": "",
            "tp_difference_broker_minus_qt": "",
            "qt_later_cancellations_utc": "",
            "qt_quote_touches_utc": "",
            "notes": "No shared broker/source ID or send/receipt timestamps. Broker export timezone unspecified.",
        }
        for state in possible:
            first, episode = state["first"], state["episode"]
            alternatives.append(
                {
                    "broker_id": trade["ID"],
                    "episode": episode["id"],
                    "qt_source_line": first["source_line"],
                    "utc": first["utc"],
                    **{k: first[k] for k in ("label", "kind", "entry", "sl", "tp")},
                }
            )
            used_episodes.add(episode["id"])
        if len(possible) == 1:
            state = possible[0]
            first, episode = state["first"], state["episode"]
            row.update(
                qt_label=first["label"],
                qt_intent_utc=(episode["intent"] or {}).get("utc", ""),
                qt_state_utc=first["utc"],
                qt_state_kind=first["kind"],
                qt_requested_entry=first["entry"],
                qt_sl=first["sl"],
                qt_tp=first["tp"],
                qt_source_line=first["source_line"],
            )
            for dest, src, column in (
                ("entry", "entry", "Open Price"),
                ("sl", "sl", "Stop Loss"),
                ("tp", "tp", "Take Profit"),
            ):
                row[f"{dest}_difference_broker_minus_qt"] = str(Decimal(trade[column]) - Decimal(first[src]))
            row["qt_later_cancellations_utc"] = "; ".join(
                e["utc"] for e in episode["events"] if e["kind"] == "cancelled" and e["time"] >= first["time"]
            )
            row["qt_quote_touches_utc"] = "; ".join(
                e["utc"] for e in episode["events"] if e["kind"] == "touched" and e["time"] >= first["time"]
            )
        rows.append(row)
    evidence_csv(output / "side-by-side.csv", rows)
    evidence_csv(output / "all-candidates.csv", alternatives)
    evidence_csv(output / "r01-window-events.csv", window_events)
    evidence_csv(
        output / "r01-candidate-episodes.csv", [r for key in used_episodes for r in episodes[key]["events"]]
    )
    evidence_csv(
        output / "r01-intents-without-closed-counterpart.csv",
        [r for r in window_events if r["kind"] == "intent" and r["source_line"] not in used_episodes],
    )
    verdict_rows = []
    if verdicts:
        with verdicts.open(encoding="utf-8-sig", newline="") as stream:
            verdict_rows = [
                dict(r, source_line=i)
                for i, r in enumerate(csv.DictReader(stream), 2)
                if start <= utc(r["utc"]) < end
            ]
        evidence_csv(output / "relay-verdicts.csv", verdict_rows)
    strategy_events = []
    if slogs:
        for path in sorted(slogs.glob("HCAMM R01*/logs/*.slog")):
            for line, raw in enumerate(
                path.read_text(encoding="utf-8-sig", errors="replace").splitlines(), 1
            ):
                try:
                    value = json.loads(raw)
                    event_time = utc(value["@t"])
                except (ValueError, KeyError):
                    continue
                if start <= event_time < end:
                    strategy_events.append(
                        {
                            "utc": value["@t"],
                            "event": value["ev"],
                            "source_file": str(path),
                            "source_line": line,
                        }
                    )
        evidence_csv(output / "strategy-manager-events.csv", strategy_events)
    profits = np.array([float(Decimal(t["Profit"])) for t in trades])
    summary = {
        "account": account,
        "window_start_utc": start.isoformat(),
        "window_end_utc": end.isoformat(),
        "window_hours": (end - start).total_seconds() / 3600,
        "window_basis": "Existing browser Last 24h export; no later data silently added.",
        "broker_timezone": "Unspecified in export; no UTC latency or Chicago-date conversion claimed.",
        "broker_closed_trades": len(trades),
        "wins": int(np.sum(profits > 0)),
        "losses": int(np.sum(profits < 0)),
        "breakevens": int(np.sum(profits == 0)),
        "win_percentage": round(float(np.mean(profits > 0) * 100), 4),
        "profit_usd_as_exported": str(total),
        "matches": dict(Counter(r["match"] for r in rows)),
        "confirmed_id_matches": 0,
        "r01_window_events": dict(Counter(r["kind"] for r in window_events)),
        "unmatched_intents": sum(
            r["kind"] == "intent" and r["source_line"] not in used_episodes for r in window_events
        ),
        "relay_verdicts": dict(Counter(r["verdict"] for r in verdict_rows)),
        "relay_unique_verdict_ids": len({r["verdictId"] for r in verdict_rows}),
        "strategy_events": len(strategy_events),
        "invalid_ledger_rows": invalid,
        "ledger_sha256": ledger_hash,
        "broker_sha256": hashlib.sha256(broker.read_bytes()).hexdigest(),
        "source_ledger": str(ledger),
        "source_broker": str(broker),
        "original_source_paths": originals,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    notes = (
        "All broker trades are shown. Matches are inferred candidates, not proven send-to-fill identities. "
        "Matching uses XAUUSD/symbol, side, SL and TP within 0.01001 and entry within 2.00 price units; "
        "no nearest-time assignment. Repeated intent episodes and changed brackets stay distinct. "
        "Source events before the rolling window are considered for older resting orders. "
        "Broker times have no timezone marker, so they are preserved and no latency is calculated. "
        "QT state time means an intent/regrade/observation was logged, not a measured send timestamp. "
        "Blank send/acknowledgement/receipt fields mean not established by these inputs. "
        "A later R01 cancellation does not prove a broker cancellation was sent or applied. "
        "R01 intents without a closed counterpart are not classified as failed or losing trades. "
        "The broker CSV total row was excluded; commissions/swaps are not subtracted again. "
        "Win rate counts profitable closing rows divided by all closing rows, including breakevens. "
        "The Last 24h window is the original export snapshot, not the time this report was regenerated."
    )
    (output / "methodology.txt").write_text(notes, encoding="utf-8")
    columns = [
        "broker_id",
        "side",
        "qt_label",
        "qt_intent_utc",
        "qt_state_utc",
        "qt_state_kind",
        "qt_requested_entry",
        "qt_sl",
        "qt_tp",
        "broker_fill_time_as_exported",
        "broker_entry",
        "broker_sl",
        "broker_tp",
        "broker_close_time_as_exported",
        "broker_close_price",
        "profit_usd",
        "outcome",
        "match",
    ]
    titles = [
        "Aqua ID",
        "Side",
        "R01 label",
        "QT intent (UTC)",
        "QT bracket recorded (UTC)",
        "QT event",
        "QT entry",
        "QT SL",
        "QT TP",
        "Aqua fill time (source)",
        "Aqua entry",
        "Aqua SL",
        "Aqua TP",
        "Aqua close time (source)",
        "Aqua close price",
        "Profit USD",
        "Result",
        "Match evidence",
    ]
    table = (
        pd.DataFrame(rows)[columns]
        .rename(columns=dict(zip(columns, titles, strict=True)))
        .to_html(index=False, escape=True, border=0)
    )
    page = f"""<!doctype html><meta charset="utf-8"><title>R01 and AquaFunded comparison</title>
<style>body{{font:15px system-ui;margin:28px;color:#142434}}p{{max-width:1200px;line-height:1.5}}
table{{border-collapse:collapse;font-size:13px}}td,th{{padding:8px;border:1px solid #ccd4dc;white-space:nowrap}}
th{{position:sticky;top:0;background:#eaf1f7}}tr:nth-child(even){{background:#f5f8fa}}input{{padding:10px;width:420px}}
.scroll{{overflow:auto;max-height:75vh}}</style>
<h1>R01 → AquaFunded · account {html.escape(account)}</h1>
<p><b>{len(trades)} closed trades · {summary["wins"]} wins / {summary["losses"]} losses ·
{summary["win_percentage"]:.2f}% win rate · ${total} displayed profit</b></p>
<p>Snapshot: {start.isoformat()} to {end.isoformat()} ({summary["window_hours"]:g} hours). Broker timestamps shown as exported.</p>
<p>{html.escape(notes)}</p><p>{html.escape(str(summary["matches"]))}. Confirmed shared-ID matches: 0.</p>
<input aria-label="Filter trades" placeholder="Filter by ID, price, time, outcome…"
oninput="document.querySelectorAll('tbody tr').forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(this.value.toLowerCase()))">
<div class="scroll">{table}</div>"""
    (output / "side-by-side.html").write_text(page, encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("ledger", "broker", "output"):
        parser.add_argument("--" + option, type=Path, required=True)
    parser.add_argument("--start", type=utc, required=True)
    parser.add_argument("--end", type=utc, required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--verdicts", type=Path)
    parser.add_argument("--slogs", type=Path)
    args = parser.parse_args()
    if args.end <= args.start:
        parser.error("end must be after start")
    print(json.dumps(reconcile(**vars(args)), indent=2))
