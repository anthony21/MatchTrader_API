"""Read-only CLI. Importing this module does not connect or read .env."""

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from .api import MatchTraderAPI
from .core.errors import MatchTraderError
from .core.settings import Settings


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only Match-Trader client")
    parser.add_argument("--env", default=".env", help="Path to local credentials file")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("platform", help="Discover public platform details without a trading login")
    sub.add_parser("balance", help="Log in and retrieve the selected account balance")
    snapshot = sub.add_parser("snapshot", help="Retrieve all six account/market data categories plus candles")
    snapshot.add_argument("--symbols", required=True, help="Comma-separated exact broker symbols")
    snapshot.add_argument("--from", dest="from_", required=True, help="ISO datetime with timezone")
    snapshot.add_argument("--to", required=True, help="ISO datetime with timezone")
    snapshot.add_argument("--interval", default="M15")
    snapshot.add_argument("--output", default="data/snapshot")
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env(args.env)
        with MatchTraderAPI(settings) as api:
            if args.command == "platform":
                print(api.platform_details().model_dump_json(indent=2))
            elif args.command == "balance":
                print(api.balance().model_dump_json(indent=2))
            else:
                # Validate time range before making any network requests.
                from .models.closed_positions_request import ClosedPositionsRequest

                window = ClosedPositionsRequest(from_=args.from_, to=args.to)
                output = Path(args.output)
                output.mkdir(parents=True, exist_ok=True)
                datasets = {
                    "balance": api.balance(),
                    "quotes": api.quotes(symbols=args.symbols),
                    "instruments": api.instruments(),
                    "active_orders": api.active_orders(),
                    "open_positions": api.open_positions(),
                    "closed_positions": api.closed_positions(window),
                }
                for i, symbol in enumerate(args.symbols.split(",")):
                    datasets[f"candles_{i}"] = api.candles(
                        symbol=symbol.strip(), interval=args.interval, from_=window.from_, to=window.to
                    )
                manifest = {
                    "account_id": api.connection.account_id,
                    "platform": settings.platform_url,
                    "from_": args.from_,
                    "to": args.to,
                    "symbols": args.symbols,
                    "interval": args.interval,
                }
                for name, records in datasets.items():
                    rows = records if isinstance(records, list) else [records]
                    raw = [r.model_dump(mode="json") for r in rows]
                    (output / (name + ".json")).write_text(json.dumps(raw, indent=2), encoding="utf-8")
                    api.dataframe(rows).to_csv(output / (name + ".csv"), index=False)
                (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
                print(f"Saved {len(datasets)} datasets to {output}")
        return 0
    except ValidationError:
        print("Invalid configuration or input. Check .env and request fields; values are not echoed.")
        return 2
    except MatchTraderError as exc:
        print(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
