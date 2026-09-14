"""The broker call, and nothing else. Takes a plan or a cancel request, returns what happened."""

import json
from dataclasses import dataclass

from .engine import OrderPlan


@dataclass(frozen=True)
class Outcome:
    decision: str        # accepted / uncertain
    request: dict
    response: dict
    reason: str


def _json_safe(value):
    return json.loads(json.dumps(value, default=str))


class BrokerDispatcher:
    def __init__(self, raw_log=None):
        self.raw_log = raw_log   # the capture store's evidence log, when the owner has one

    def send(self, plan: OrderPlan, api, *, correlation) -> Outcome:
        """Open the order the plan describes. Accepted only when the broker returned an identity."""
        request = plan.request()
        return self._call(getattr(api, plan.method), request, api_kind="broker-request", correlation=correlation,
                          accepted=lambda r: r.status in {"", None, "OK"} and bool(r.orderId or r.positionId),
                          ok="MatchTrader accepted the configured copy request")

    def cancel(self, request: dict, api, *, correlation) -> Outcome:
        """Cancel the exact pending order in `request`, prepared by the owner from its own record."""
        return self._call(api.cancel_pending_order, request, api_kind="broker-request", correlation=correlation,
                          accepted=lambda r: r.status == "OK", ok="MatchTrader accepted the cancellation")

    def _call(self, method, request, *, api_kind, correlation, accepted, ok):
        safe = _json_safe(request)
        if self.raw_log is not None:
            self.raw_log.append("out", api_kind, {"signal_id": correlation, "body": safe})
        try:
            response = method(**request)
            data = response.model_dump(mode="json")
            if self.raw_log is not None:
                self.raw_log.append("in", "broker-response", {"signal_id": correlation, "body": data})
            if accepted(response):
                return Outcome("accepted", safe, data, ok)
            return Outcome("uncertain", safe, data, "Unrecognized write response; no automatic retry")
        except Exception as error:
            return Outcome("uncertain", safe, {"error_type": type(error).__name__},
                           f"Copy write outcome unconfirmed after {type(error).__name__}; broker state not "
                           f"verified, no automatic retry (signal {correlation})")
