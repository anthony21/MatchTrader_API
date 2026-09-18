from matchtrader.models.operation import Operation
from matchtrader.models.partial_close_request import PartialCloseRequest

from .base import BaseEndpoint


class PartialClose(BaseEndpoint):
    """POST /mtr-api/SYSTEM_UUID/position/close-partially."""

    method = "POST"
    path = "mtr-api/SYSTEM_UUID/position/close-partially"
    scope = "trading"
    write = True
    safe_read = False
    action = ""
    collection = None
    request_model = PartialCloseRequest
    response_model = Operation
