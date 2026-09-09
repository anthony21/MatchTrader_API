from matchtrader.core.rate_limiter import RateLimiter

# Capture the real implementation before the autouse offline fixture patches it.
wait = RateLimiter.wait


def test_request_pacing_does_not_burst():
    clock = [100.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    limiter = RateLimiter(60, clock=lambda: clock[0], sleep=sleep)
    wait(limiter)
    wait(limiter)
    wait(limiter)
    assert sleeps == [1.0, 1.0]


def test_accounts_share_conservative_origin_budget():
    first = RateLimiter.for_origin("https://budget.example", 450)
    second = RateLimiter.for_origin("https://budget.example", 300)
    assert first is second
    assert first.interval == 60 / 300
    assert RateLimiter.for_origin("https://other-budget.example", 450) is not first
