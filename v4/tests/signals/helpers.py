from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from matchtrader.models.operation import Operation
from matchtrader.signals import Context, SymbolMap, SymbolMapping


def raw(**changes):
    return {"clientEventId": "e1", "machineId": "qt", "source": "chain", "kind": "intent",
            "timestampUtc": datetime.now(UTC).isoformat(), "label": "box", "symbol": "US TECH 100",
            "side": "short", "entry": 100, "stopLoss": 105, "takeProfit": 95, **changes}


def lane(**changes):
    fields = {"machine_id": "qt", "source": "chain", "additional_sources": [], "connection_name": "",
              "destination_account": "demo", "x17_only": False}
    return SimpleNamespace(**{**fields, **changes})


def symbols(order_type="LIMIT", lots="0.2", min_box="0"):
    return SymbolMap({"US TECH 100": SymbolMapping(destination="NAS100", lots=Decimal(lots),
                                                   order_type=order_type, min_box=Decimal(min_box))})


class Broker:
    def __init__(self, bid="99", ask="101", equity="1000"):
        self.calls, self.bid, self.ask = [], Decimal(bid), Decimal(ask)
        self.equity = Decimal(equity)
        self.quote_time = int(datetime.now(UTC).timestamp() * 1000)

    def balance(self):
        return SimpleNamespace(equity=self.equity, currency="USD")

    def instruments(self):
        return [SimpleNamespace(symbol="NAS100",
                                model_dump=lambda: {"volumeMin": "0.1", "volumeMax": "10", "volumeStep": "0.1"})]

    def quotes(self, **kwargs):
        return [SimpleNamespace(symbol="NAS100", bid=self.bid, ask=self.ask, timestampMs=self.quote_time)]

    def create_pending_order(self, **kwargs):
        self.calls.append(kwargs)
        return Operation(status="OK", orderId="order-1")

    open_position = create_pending_order


def context(**changes):
    fields = {"mode": "live", "armed": True, "armed_at": datetime.now(UTC) - timedelta(seconds=1),
              "now": datetime.now(UTC), "destination": "demo", "api": Broker(), "verified": True}
    return Context(**{**fields, **changes})
