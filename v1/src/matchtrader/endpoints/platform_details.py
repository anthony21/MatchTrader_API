from matchtrader.models.platform import Platform

from .base import BaseEndpoint


class GetPlatformDetails(BaseEndpoint):
    """GET /manager/platform-details."""

    method = "GET"
    path = "manager/platform-details"
    scope = "manager"
    write = False
    safe_read = True
    action = ""
    collection = None
    response_model = Platform
