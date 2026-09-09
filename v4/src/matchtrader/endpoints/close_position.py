from matchtrader.models.close_position_request import ClosePositionRequest
from matchtrader.models.operation import Operation

from .base import BaseEndpoint


class ClosePosition(BaseEndpoint):
    """POST /mtr-api/SYSTEM_UUID/position/close."""

    method = "POST"
    path = "mtr-api/SYSTEM_UUID/position/close"
    scope = "trading"
    write = True
    safe_read = False
    action = ""
    collection = None
    request_model = ClosePositionRequest
    response_model = Operation
