from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from matchtrader.capture.event import CaptureEvent
from matchtrader.capture.route import RouteConfig
from matchtrader.models.instrument import Instrument
from matchtrader.models.operation import Operation


@pytest.fixture
def event():
    return CaptureEvent(
        event_id="event1",
        machine="qt",
        connection_id="connection",
        account_id="source",
        order_id="order1",
        request_id="run:1",
        emitted_at=datetime.now(UTC),
        kind="ACCEPTED",
        action="CREATE",
        source="MANUAL",
        symbol="EURUSD",
        side="BUY",
        order_type="LIMIT",
        quantity="1",
        price="1.15000",
        sl="1.14980",
        tp="1.16",
    )


@pytest.fixture
def route():
    return RouteConfig(
        machine="qt",
        connection_id="connection",
        account_id="source",
        destination_account="demo",
        sources=["MANUAL"],
        exclusive_destination=True,
        legacy_route_disabled=True,
        symbols={
            "EURUSD": {
                "destination": "EURUSD",
                "quantity_multiplier": ".01",
                "max_lots": ".1",
                "same_price_scale": True,
            }
        },
    )


@pytest.fixture
def broker():
    class Broker:
        calls = None

        def __init__(self):
            self.calls = []
            self.orders = []
            self.positions = []

        def instruments(self):
            return [Instrument(symbol="EURUSD", volumeMin=".01", volumeMax="50", volumeStep=".01")]

        def active_orders(self):
            return self.orders

        def open_positions(self):
            return self.positions

        def create_pending_order(self, **kwargs):
            self.calls.append(("CREATE", kwargs))
            self.orders = [SimpleNamespace(id="aqua1", type="LIMIT")]
            return Operation(orderId="aqua1")

        def edit_pending_order(self, **kwargs):
            self.calls.append(("EDIT", kwargs))
            return Operation(status="OK")

        def cancel_pending_order(self, **kwargs):
            self.calls.append(("CANCEL", kwargs))
            self.orders = []
            return Operation(status="OK")

        def open_position(self, **kwargs):
            self.calls.append(("MARKET", kwargs))
            return Operation(orderId="market1", positionId="position1")

        def close_position(self, **kwargs):
            self.calls.append(("CLOSE", kwargs))
            return Operation(status="OK")

        def partial_close(self, **kwargs):
            self.calls.append(("PARTIAL", kwargs))
            return Operation(status="OK")

    return Broker()
