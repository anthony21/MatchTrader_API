from decimal import Decimal

import pytest
from pydantic import ValidationError

from matchtrader.capture.route import RouteConfig


def test_routes_never_guess_account_symbol_or_origin(route, event):
    assert route.match(event).quantity_multiplier * event.quantity == Decimal("0.01")
    for change in [{"account_id": "other"}, {"source": "UNKNOWN"}, {"symbol": "ES"}]:
        with pytest.raises(ValueError):
            route.match(event.model_copy(update=change))
    with pytest.raises(ValidationError):
        RouteConfig.model_validate({**route.model_dump(), "legacy_route_disabled": False})
