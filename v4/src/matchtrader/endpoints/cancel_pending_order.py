from matchtrader.models.cancel_pending_order_request import CancelPendingOrderRequest
from matchtrader.models.operation import Operation

from .base import BaseEndpoint


class CancelPendingOrder(BaseEndpoint):
    """POST /mtr-api/SYSTEM_UUID/pending-order/cancel."""

    method = "POST"
    path = "mtr-api/SYSTEM_UUID/pending-order/cancel"
    scope = "trading"
    write = True
    safe_read = False
    action = ""
    collection = None
    request_model = CancelPendingOrderRequest
    response_model = Operation
