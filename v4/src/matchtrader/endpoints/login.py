from matchtrader.models.authentication import Authentication
from matchtrader.models.login_request import LoginRequest

from .base import BaseEndpoint


class Login(BaseEndpoint):
    """POST /manager/mtr-login."""

    method = "POST"
    path = "manager/mtr-login"
    scope = "manager"
    write = False
    safe_read = False
    action = "login"
    collection = None
    request_model = LoginRequest
    response_model = Authentication
