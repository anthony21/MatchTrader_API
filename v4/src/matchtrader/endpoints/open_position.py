from matchtrader.models.open_position_request import OpenPositionRequest
from matchtrader.models.operation import Operation

from .base import BaseEndpoint


class OpenPosition(BaseEndpoint):
    """POST /mtr-api/SYSTEM_UUID/position/open."""

    method = "POST"
    path = "mtr-api/SYSTEM_UUID/position/open"
    scope = "trading"
    write = True
    safe_read = False
    action = ""
    collection = None
    request_model = OpenPositionRequest
    response_model = Operation
