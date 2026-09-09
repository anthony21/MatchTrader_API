from matchtrader.models.create_pending_order_request import CreatePendingOrderRequest
from matchtrader.models.operation import Operation

from .base import BaseEndpoint


class CreatePendingOrder(BaseEndpoint):
    """POST /mtr-api/SYSTEM_UUID/pending-order/create."""

    method = "POST"
    path = "mtr-api/SYSTEM_UUID/pending-order/create"
    scope = "trading"
    write = True
    safe_read = False
    action = ""
    collection = None
    request_model = CreatePendingOrderRequest
    response_model = Operation
