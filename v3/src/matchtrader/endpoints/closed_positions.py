from matchtrader.models.closed_positions_request import ClosedPositionsRequest
from matchtrader.models.closed_trade import ClosedTrade

from .base import BaseEndpoint


class GetClosedPositions(BaseEndpoint):
    """POST /mtr-api/SYSTEM_UUID/closed-positions."""

    method = "POST"
    path = "mtr-api/SYSTEM_UUID/closed-positions"
    scope = "trading"
    write = False
    safe_read = True
    action = ""
    collection = "operations"
    request_model = ClosedPositionsRequest
    response_model = ClosedTrade
