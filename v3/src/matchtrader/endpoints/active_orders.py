from matchtrader.models.order import Order

from .base import BaseEndpoint


class GetActiveOrders(BaseEndpoint):
    """GET /mtr-api/SYSTEM_UUID/active-orders."""

    method = "GET"
    path = "mtr-api/SYSTEM_UUID/active-orders"
    scope = "trading"
    write = False
    safe_read = True
    action = ""
    collection = "orders"
    response_model = Order
