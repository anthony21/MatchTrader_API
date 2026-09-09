from matchtrader.models.authentication import Authentication
from matchtrader.models.login_with_token_request import LoginWithTokenRequest

from .base import BaseEndpoint


class LoginWithToken(BaseEndpoint):
    """POST /manager/login/co/with-token."""

    method = "POST"
    path = "manager/login/co/with-token"
    scope = "manager"
    write = False
    safe_read = False
    action = "one_time_login"
    collection = None
    request_model = LoginWithTokenRequest
    response_model = Authentication
