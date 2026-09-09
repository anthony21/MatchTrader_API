from matchtrader.models.session_update import SessionUpdate

from .base import BaseEndpoint


class RefreshToken(BaseEndpoint):
    """POST /manager/refresh-token."""

    method = "POST"
    path = "manager/refresh-token"
    scope = "manager"
    write = False
    safe_read = False
    action = "refresh"
    collection = None
    response_model = SessionUpdate
    allow_empty_response = True
