from pydantic import ValidationError

from matchtrader.core.base_service import BaseService
from matchtrader.core.errors import ProtocolError


class BaseEndpoint(BaseService):
    method = "GET"
    scope = "trading"
    write = False
    safe_read = True
    action = ""
    request_model = None
    response_model = None
    collection = None
    single_as_list = False
    allow_empty_response = False

    def execute(self, payload=None, **kwargs):
        if payload is not None and kwargs:
            raise TypeError("Supply either a request model/dict or keyword fields")
        data = payload if payload is not None else kwargs
        if self.request_model:
            request = self.request_model.model_validate(data)
            data = request.wire()
        elif data:
            raise TypeError("This endpoint takes no request fields")
        result = self.connection.request(
            self.method,
            self.path,
            body=data if self.method == "POST" and data else None,
            params=data if self.method == "GET" and data else None,
            scope=self.scope,
            write=self.write,
            safe_read=self.safe_read,
            action=self.action,
        )
        if self.response_model is None or (result is None and self.allow_empty_response):
            return result
        try:
            if self.collection is not None:
                if isinstance(result, dict):
                    if self.collection in result:
                        result = result[self.collection]
                    elif self.single_as_list:
                        result = [result]
                    else:
                        raise ProtocolError("Expected response collection is absent")
                if not isinstance(result, list):
                    raise ProtocolError("Expected a list response")
                return [self.response_model.model_validate(row) for row in result]
            return self.response_model.model_validate(result)
        except ValidationError:
            raise ProtocolError("Response does not match the documented model") from None
