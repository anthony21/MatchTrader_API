"""One renewal timer per broker connection.

Each connected broker session keeps its own SessionRenewer. When it connects, the renewer arms
a single timer that fires when that connection's token is `margin` seconds from expiry; it renews
that one connection, then re-arms from the new expiry. Connections are independent: one broker's
renewal, failure, or backoff never touches another's, and dropping a connection cancels only its
own timer. This is timer-driven, never interval polling.
"""

from threading import Lock, Timer


class SessionRenewer:
    def __init__(self, name, api, on_result, *, margin=120, min_delay=1.0, backoff=60.0,
                 max_delay=86400.0, timer_factory=Timer):
        self.name, self.api, self.on_result = name, api, on_result
        self.margin, self.min_delay, self.backoff, self.max_delay = margin, min_delay, backoff, max_delay
        self._timer_factory = timer_factory
        self._lock = Lock()
        self._timer = None
        self._cancelled = False

    def start(self):
        """Arm the first timer from the connection's current expiry."""
        self._arm()

    def _delay(self):
        try:
            d = self.api.connection.renewal_delay(self.margin)
        except Exception:
            return self.min_delay   # cannot tell: check soon rather than sleep on a stale deadline
        if d is None:
            return None             # no session to keep alive
        # Cap the single sleep so a token valid for days does not overflow the OS timer; the renewer
        # simply re-arms and re-checks at the cap. A real trading token's delay is far under it.
        return min(self.max_delay, max(self.min_delay, d))

    def _arm(self, delay=None):
        with self._lock:
            if self._cancelled:
                return
            if delay is None:
                delay = self._delay()
            if delay is None:
                self._timer = None   # nothing to renew; a reconnect will start a fresh renewer
                return
            self._timer = self._timer_factory(delay, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self):
        if self._cancelled:
            return
        ok, reason, renewed = True, "", False
        try:
            renewed = bool(self.api.connection.renew_if_due(self.margin))
        except Exception as error:
            ok, reason = False, type(error).__name__
        try:
            self.on_result(self.name, renewed, ok, reason)
        except Exception:
            pass  # a reporting failure must not stop this connection renewing next time
        # Re-arm from the new expiry; after a failure wait a backoff so a bad credential cannot spin.
        self._arm(self.backoff if not ok else None)

    def cancel(self):
        with self._lock:
            self._cancelled = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
