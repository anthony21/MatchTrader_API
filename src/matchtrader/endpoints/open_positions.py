from matchtrader.models.position import Position

from .base import BaseEndpoint


class GetOpenPositions(BaseEndpoint):
    """GET /mtr-api/SYSTEM_UUID/open-positions."""

    method = "GET"
    path = "mtr-api/SYSTEM_UUID/open-positions"
    scope = "trading"
    write = False
    safe_read = True
    action = ""
    collection = "positions"
    response_model = Position
