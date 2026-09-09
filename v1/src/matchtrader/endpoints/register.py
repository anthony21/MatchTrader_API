from matchtrader.models.register_request import RegisterRequest
from matchtrader.models.token import Token

from .base import BaseEndpoint


class Register(BaseEndpoint):
    """POST /manager/user."""

    method = "POST"
    path = "manager/user"
    scope = "manager"
    write = True
    safe_read = False
    action = ""
    collection = None
    request_model = RegisterRequest
    response_model = Token
