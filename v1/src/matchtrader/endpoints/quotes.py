from matchtrader.models.quote import Quote
from matchtrader.models.quotes_request import QuotesRequest

from .base import BaseEndpoint


class GetQuotes(BaseEndpoint):
    """GET /mtr-api/SYSTEM_UUID/quotations."""

    method = "GET"
    path = "mtr-api/SYSTEM_UUID/quotations"
    scope = "trading"
    write = False
    safe_read = True
    action = ""
    collection = "body"
    request_model = QuotesRequest
    response_model = Quote
