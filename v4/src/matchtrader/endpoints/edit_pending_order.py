from matchtrader.models.edit_pending_order_request import EditPendingOrderRequest

from .base import BaseEndpoint


class EditPendingOrder(BaseEndpoint):
    """POST /mtr-api/SYSTEM_UUID/pending-order/edit."""

    method = "POST"
    path = "mtr-api/SYSTEM_UUID/pending-order/edit"
    scope = "trading"
    write = True
    safe_read = False
    action = ""
    collection = None
    request_model = EditPendingOrderRequest
