import httpx
import pytest

from matchtrader.core.reason import broker_reason, local_reason, transport_reason, unconfirmed_reason

ALL_REASONS = []


def _record(reason):
    ALL_REASONS.append(reason)
    return reason


@pytest.fixture(autouse=True)
def check_every_reason_is_investigable():
    """The user's rule: no reason produced here may ever be a bare unknown."""
    ALL_REASONS.clear()
    yield
    for reason in ALL_REASONS:
        assert reason["origin"], reason
        assert reason["code"], reason
        assert reason["evidence"], reason


def test_allowlist_drops_every_other_key():
    data = {
        "status": "REJECTED",
        "errorMessage": "Not enough free margin",
        "nativeCode": "MARGIN_001",
        "password": "hunter2",
        "requestBody": {"accountId": "12345678"},
    }
    reason = _record(broker_reason(400, data))
    assert reason["origin"] == "broker"
    assert reason["code"] == "MARGIN_001"
    assert reason["summary"] == "Not enough free margin"
    assert reason["body_captured"] is True
    assert "password" not in str(reason)
    assert "hunter2" not in str(reason)
    assert "requestBody" not in str(reason)
    assert "12345678" not in str(reason)


def test_sensitive_key_value_pairs_are_masked():
    data = {"errorMessage": "Rejected; password=hunter2secret token=abc.def.ghi cookie=sid9"}
    reason = _record(broker_reason(400, data))
    assert "hunter2secret" not in reason["summary"]
    assert "abc.def.ghi" not in reason["summary"]
    assert "sid9" not in reason["summary"]


def test_bare_bearer_token_is_masked():
    data = {"errorMessage": "Rejected upstream; saw header Bearer abcdefghijklmnop in the request"}
    reason = _record(broker_reason(400, data))
    assert "abcdefghijklmnop" not in reason["summary"]
    assert "Bearer ***" in reason["summary"]


def test_authorization_header_pair_is_fully_masked():
    data = {"errorMessage": "Rejected; Authorization: Bearer abc123def456xyz was invalid"}
    reason = _record(broker_reason(400, data))
    assert "abc123def456xyz" not in reason["summary"]


def test_long_digit_runs_and_email_addresses_are_masked():
    data = {"errorMessage": "Account 123456789012 rejected; contact trader@example.com for help"}
    reason = _record(broker_reason(400, data))
    assert "123456789012" not in reason["summary"]
    assert "trader@example.com" not in reason["summary"]
    assert "***" in reason["summary"]


def test_summary_is_truncated_and_control_characters_are_stripped():
    data = {"errorMessage": "bad\x00\x01" + "x" * 300}
    reason = _record(broker_reason(400, data))
    assert "\x00" not in reason["summary"]
    assert "\x01" not in reason["summary"]
    assert len(reason["summary"]) <= 200


def test_whitespace_is_collapsed():
    data = {"errorMessage": "too   many\n\nspaces\there"}
    reason = _record(broker_reason(400, data))
    assert reason["summary"] == "too many spaces here"


def test_absent_or_unparseable_body_still_yields_a_usable_code_and_evidence():
    reason = _record(broker_reason(503, None))
    assert reason["body_captured"] is False
    assert reason["summary"] == ""
    assert reason["code"] == "HTTP 503"
    assert "no parseable body" in reason["evidence"]


def test_non_dict_body_is_treated_as_uncaptured():
    reason = _record(broker_reason(500, ["not", "a", "dict"]))
    assert reason["body_captured"] is False
    assert reason["code"] == "HTTP 500"


def test_native_code_must_look_like_a_code_not_arbitrary_text():
    data = {"errorMessage": "oops", "nativeCode": "some free text with spaces, far past sixty four chars!!"}
    reason = _record(broker_reason(400, data))
    assert reason["code"] == "HTTP 400"


def test_native_code_used_when_it_looks_like_a_code():
    data = {"nativeCode": 4021}
    reason = _record(broker_reason(400, data))
    assert reason["code"] == "4021"


def test_transport_reason_never_claims_broker_origin():
    reason = _record(transport_reason(TimeoutError("boom")))
    assert reason["origin"] == "transport"
    assert "TimeoutError" in reason["summary"]
    assert "unconfirmed" in reason["summary"]
    # The evidence must never name a destination this module did not write (no request
    # archive is captured here); absent a correlation id it says plainly that nothing was.
    assert "no broker response was captured" in reason["evidence"]
    assert "relay" not in reason["evidence"]
    assert reason["code"] == "transport"


def test_transport_reason_evidence_references_a_supplied_correlation_id():
    reason = _record(transport_reason(TimeoutError("boom"), correlation="trade t1 action CREATE"))
    assert "trade t1 action CREATE" in reason["evidence"]


def test_transport_reason_carries_status_code_when_known():
    reason = _record(transport_reason(ValueError("bad json"), 502))
    assert reason["code"] == "HTTP 502"
    assert reason["origin"] == "transport"


def test_transport_reason_includes_the_scrubbed_error_detail():
    # A genuine httpx transport error - never claim broker origin, but do keep its own
    # (scrubbed) message: host/errno detail is investigable and httpx never puts headers
    # or bodies in it.
    reason = _record(transport_reason(httpx.ConnectError("[Errno 111] Connection refused")))
    assert reason["origin"] == "transport"
    assert "ConnectError" in reason["summary"]
    assert "Connection refused" in reason["summary"]


def test_local_reason_carries_the_error_message_and_local_origin():
    reason = _record(local_reason(RuntimeError("Broker identity missing after submission")))
    assert reason["origin"] == "local"
    assert reason["code"] == "RuntimeError"
    assert "Broker identity missing after submission" in reason["summary"]
    assert reason["evidence"]


def test_unconfirmed_reason_never_claims_a_wire_or_local_cause():
    # No structured evidence exists for this exception: origin='transport' or 'local' would
    # both assert a cause that was never established.
    reason = _record(unconfirmed_reason(RuntimeError("boom, no .reason attribute here")))
    assert reason["origin"] == "unconfirmed"
    assert reason["code"] == "RuntimeError"
    assert "boom, no .reason attribute here" in reason["summary"]
    assert reason["evidence"]


def test_unconfirmed_reason_evidence_references_a_supplied_correlation_id():
    reason = _record(unconfirmed_reason(RuntimeError("boom"), correlation="trade t1 action CREATE"))
    assert "trade t1 action CREATE" in reason["evidence"]


def test_json_shaped_quoted_credentials_are_masked():
    # A broker echoing the request back verbatim is the most likely way this happens; a
    # quote immediately after the key defeated the old separator regex.
    data = {"errorMessage": '{"password": "hunter2", "apiKey":"k-123"}'}
    reason = _record(broker_reason(400, data))
    assert "hunter2" not in reason["summary"]
    assert "k-123" not in reason["summary"]


def test_structured_error_message_is_never_stringified():
    # str()-ing a dict errorMessage is itself the leak: Python's repr of a dict routes
    # around every keyword/pattern check unless the whole value is refused up front.
    data = {"errorMessage": {"password": "hunter2"}}
    reason = _record(broker_reason(400, data))
    assert reason["summary"] == ""
    assert "hunter2" not in str(reason)


def test_widened_keyword_set_masks_every_new_alias():
    data = {"errorMessage": "accessToken=h8 refresh_token=i9 passwd=a1 pwd=b2 jwt=d4 session=e5"}
    reason = _record(broker_reason(400, data))
    for leaked in ("h8", "i9", "a1", "b2", "d4", "e5"):
        assert leaked not in reason["summary"].split(), reason["summary"]


def test_grouped_digit_runs_are_masked_for_space_and_hyphen_separators():
    for text in ("acct 1234 5678 9012 3456 is on file", "card 1234-5678-9012-3456 was used"):
        reason = _record(broker_reason(400, {"errorMessage": text}))
        assert "***" in reason["summary"], reason["summary"]
        assert "1234" not in reason["summary"]
        assert "9012" not in reason["summary"]
        assert "3456" not in reason["summary"]


def test_eleven_digits_are_not_masked():
    data = {"errorMessage": "reference 12345678901 is not an account number"}
    reason = _record(broker_reason(400, data))
    assert "12345678901" in reason["summary"]


def test_unicode_digits_are_masked():
    data = {"errorMessage": "account ١٢٣٤٥٦٧٨٩٠١٢ held"}
    reason = _record(broker_reason(400, data))
    assert "١٢٣" not in reason["summary"]
    assert "***" in reason["summary"]


def test_native_code_long_digit_run_falls_back_to_http_status():
    # An account number must never be stored as the code, even though it otherwise looks
    # like a legal code (digits are an allowed character in _CODE_RE).
    data = {"errorMessage": "oops", "nativeCode": "1234567890123456"}
    reason = _record(broker_reason(503, data))
    assert reason["code"] == "HTTP 503"
    assert "1234567890123456" not in str(reason)


def test_redaction_regexes_stay_fast_on_pathological_input():
    import time

    adversarial = ("password" * 200) + (":" * 200) + ("1" * 5000) + (" " * 5000)
    started = time.monotonic()
    _record(broker_reason(400, {"errorMessage": adversarial}))
    assert time.monotonic() - started < 1.0


def test_redaction_stays_fast_on_a_very_large_grouped_digit_input():
    # Re-measurement after moving scrubbing ahead of truncation: the auditor saw ~20ms on a
    # 200k-char grouped-digit input once work is bounded by the pre-scrub cap: confirm that
    # bound holds regardless of how large the raw input is.
    import time

    adversarial = "1" * 100000 + " " + "1-" * 50000
    started = time.monotonic()
    _record(broker_reason(400, {"errorMessage": adversarial}))
    assert time.monotonic() - started < 0.5


def test_quoted_value_with_internal_spaces_is_fully_masked():
    # Bypass (a): the quoted value alternative used to be unreachable because the separator
    # already consumed the opening quote, so only the first word of the value was masked.
    data = {"errorMessage": 'Rejected; password="alpha secret tail" - contact support'}
    reason = _record(broker_reason(400, data))
    assert "alpha secret tail" not in reason["summary"]
    assert "secret" not in reason["summary"]
    assert "tail" not in reason["summary"]


def test_basic_auth_credentials_are_fully_masked():
    # Bypass (b): only the Bearer scheme was ever recognized; Basic credentials leaked whole.
    data = {"errorMessage": "Rejected; Authorization: Basic dXNlcjpwYXNz was invalid"}
    reason = _record(broker_reason(400, data))
    assert "dXNlcjpwYXNz" not in reason["summary"]


def test_auth_token_alias_is_masked():
    # Bypass (c): the keyword set had no alias for "authToken".
    data = {"errorMessage": "Rejected; authToken=secret-value-here in the request"}
    reason = _record(broker_reason(400, data))
    assert "secret-value-here" not in reason["summary"]


def test_native_code_carrying_a_secret_falls_back_to_http_status():
    # Bypass (d): nativeCode was only ever checked for long digit runs, so a non-digit
    # secret riding along in it was stored verbatim.
    data = {"errorMessage": "oops", "nativeCode": "password:hunter2"}
    reason = _record(broker_reason(503, data))
    assert reason["code"] == "HTTP 503"
    assert "hunter2" not in str(reason)


def test_secret_past_the_two_hundred_char_cut_is_still_scrubbed():
    # Bypass (e): truncating to 200 chars before scrubbing could cut a long digit run below
    # its 12-digit detection threshold, leaking whatever prefix of it survived the cut.
    account = "1234567890123456"
    data = {"errorMessage": "x" * 190 + account + " trailing text past the cut"}
    reason = _record(broker_reason(400, data))
    assert account not in reason["summary"]
    assert "123456" not in reason["summary"]
