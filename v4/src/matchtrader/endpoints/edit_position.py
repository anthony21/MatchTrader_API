from matchtrader.models.edit_position_request import EditPositionRequest
from matchtrader.models.operation import Operation

from .base import BaseEndpoint


class EditPosition(BaseEndpoint):
    """POST /mtr-api/SYSTEM_UUID/position/edit."""

    method = "POST"
    path = "mtr-api/SYSTEM_UUID/position/edit"
    scope = "trading"
    write = True
    safe_read = False
    action = ""
    collection = None
    request_model = EditPositionRequest
    response_model = Operation
