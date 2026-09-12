"""Turn a broker rejection or a transport failure into an investigable reason.

Every reason returned here carries a non-empty origin, code and evidence: nothing
downstream may ever record a bare "unknown". A broker reason only ever reads an
allowlisted subset of the response body, so an upstream body that echoes request
data (credentials, account numbers) cannot leak through it.
"""

import re

_ALLOWED_KEYS = ("status", "errorMessage", "nativeCode")
_CODE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
# Excludes \t\n\r: those are whitespace, normalized below, not stripped to nothing here -
# stripping them outright would fuse "line one\nline two" into "line oneline two".
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")
# A generous cap applied *before* any scrubbing runs (see _summary_from): it bounds every
# regex below to a fixed amount of work regardless of input size, while staying far larger
# than the final 200-char summary so nothing a scrub would have caught is trimmed away first.
_RAW_CAP = 4000
_FINAL_CAP = 200
# The value alternative tries a scheme+credential form ("Bearer <token>"/"Basic <token>")
# first so an "Authorization: Bearer/Basic <value>" pair is consumed whole; a lone scheme
# token with no leading key is still caught by _AUTH_SCHEME below. The quoted-value
# alternative uses a named backreference (?P=q) so it consumes the *entire* quoted run up to
# its matching close quote - not just up to the first space inside it - so a JSON- or
# repr-quoted echo ("password": "hunter2 with a tail") cannot leak everything after the
# first space by falling through to the bare \S+ alternative.
_SENSITIVE_KV = re.compile(
    r"(?i)\b(password|passwd|pwd|token|access[_-]?token|refresh[_-]?token|auth[_-]?token|"
    r"authorization|api[_-]?key|secret|cookie|session|jwt)\b[\"']?\s*[:=]\s*"
    r"((?:bearer|basic)\s+\S+|(?P<q>[\"'])(?:(?!(?P=q)).)*(?P=q)|\S+)"
)
# Catches a bare scheme+credential pair with no leading key at all (e.g. a raw
# "Authorization" header value logged without its header name), for any of the schemes this
# broker or its upstreams might echo - not just Bearer.
_AUTH_SCHEME = re.compile(r"(?i)\b(Bearer|Basic|Digest|Negotiate|NTLM)\s+\S+")
# A run of 12+ digits - contiguous, or split into groups by single spaces/hyphens, e.g. an
# account or card number spelled "1234 5678 9012 3456" or "1234-5678-9012-3456". Runs of 11
# digits or fewer are left alone: that length is common in harmless identifiers. \d matches
# any Unicode decimal digit, not just ASCII ones.
_LONG_DIGITS = re.compile(r"\d(?:[ -]?\d){11,}")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _scrub(text):
    text = _SENSITIVE_KV.sub(lambda m: m.group(1) + "=***", text)
    text = _AUTH_SCHEME.sub(lambda m: m.group(1) + " ***", text)
    text = _LONG_DIGITS.sub("***", text)
    text = _EMAIL.sub("***", text)
    return text


def _summary_from(text):
    # Scrub BEFORE the final truncation, not after: cutting to 200 chars first can chop a
    # long secret (e.g. a 16-digit account number) below the pattern's detection threshold,
    # leaking whatever prefix of it survived the cut. The raw cap keeps this bounded work
    # regardless of input size without reintroducing that ordering bug.
    text = _CONTROL_CHARS.sub("", str(text))[:_RAW_CAP]
    text = _WHITESPACE.sub(" ", text).strip()
    text = _scrub(text)
    return text[:_FINAL_CAP]


def _code_from(status_code, native_code):
    if native_code is not None:
        candidate = str(native_code)
        # A code that is, or contains, a secret or a long digit run (an account/card number
        # the broker echoed back verbatim) must never be stored as the code. Scrubbing it and
        # comparing catches both: any change means something was masked, so the candidate is
        # not safe to keep verbatim.
        if _scrub(candidate) != candidate:
            return f"HTTP {status_code}"
        if _CODE_RE.match(candidate) and not _LONG_DIGITS.search(candidate):
            return candidate
    return f"HTTP {status_code}"


def broker_reason(status_code, data):
    """Build a reason from a broker write response, reading only an allowlisted subset.

    `data` is the response body already parsed to Python (or None when it was absent or
    could not be parsed as JSON). Only `status`, `errorMessage` and `nativeCode` are ever
    read from it; every other field, including one an attacker-controlled broker echoes
    back from the request, is dropped before it can reach a summary, log or record.
    """
    body_captured = isinstance(data, dict)
    allowed = {key: data[key] for key in _ALLOWED_KEYS if body_captured and key in data}
    error_message = allowed.get("errorMessage")
    # A structured errorMessage (dict/list/etc) is never str()'d: doing so would flatten an
    # echoed request body straight past every keyword/pattern check below. Treat it as absent.
    if not isinstance(error_message, str):
        error_message = ""
    summary = _summary_from(error_message) if error_message else ""
    evidence = (
        "broker write response"
        if body_captured
        else "broker write response; no parseable body, status only"
    )
    return {
        "origin": "broker",
        "code": _code_from(status_code, allowed.get("nativeCode")),
        "summary": summary,
        "evidence": evidence,
        "body_captured": body_captured,
    }


def transport_reason(error, status_code=None, *, correlation=None):
    """Build a reason for a failure known to be on the wire: a transport-level exception, or
    a response that was never received at all. Reserve this for genuine wire failures - never
    use it as a catch-all for an exception whose phase (wire vs local) was never established;
    see `unconfirmed_reason` for that case.

    The outcome is honestly unconfirmed - never claim the broker accepted or rejected the
    write - but the record still names the exception type, the HTTP status when one exists,
    and the exception's own (scrubbed) message. The evidence names only what is actually
    persisted for reconciliation: this module writes no request archive itself, so it never
    claims one exists.
    """
    kind = type(error).__name__
    detail = _summary_from(str(error)) if str(error) else ""
    summary = f"Outcome unconfirmed after {kind}"
    if detail:
        summary += f": {detail}"
    summary += "; broker state was not verified"
    if correlation:
        evidence = f"no broker response was captured for this write; reconcile using {correlation}"
    else:
        evidence = "no broker response was captured for this write; reconcile against broker state directly"
    return {
        "origin": "transport",
        "code": f"HTTP {status_code}" if status_code is not None else "transport",
        "summary": summary,
        "evidence": evidence,
        "body_captured": False,
    }


def unconfirmed_reason(error, *, correlation=None):
    """Build a reason for a failure whose phase could not be established at all: it carries
    no structured `.reason`, and there is no positive evidence it happened on the wire, at
    the broker, or in our own code afterward. origin='transport' would assert a wire cause
    that was never established; origin='local' would assert the opposite. origin='unconfirmed'
    says plainly that the boundary is unknown while still keeping every fact that is known:
    the exception's own type and (scrubbed) message.
    """
    kind = type(error).__name__
    detail = _summary_from(str(error)) if str(error) else ""
    summary = f"Outcome unconfirmed after {kind}"
    if detail:
        summary += f": {detail}"
    summary += "; the failure phase (broker, wire or local) could not be established"
    if correlation:
        evidence = f"no structured broker or wire evidence was attached; reconcile using {correlation}"
    else:
        evidence = "no structured broker or wire evidence was attached; reconcile against broker state"
    return {
        "origin": "unconfirmed",
        "code": kind,
        "summary": summary,
        "evidence": evidence,
        "body_captured": False,
    }


def local_reason(error, evidence="broker replied to the write; response failed router validation"):
    """Build a reason for a failure raised by our own code after the broker responded.

    origin='local' keeps this distinct from a genuine wire failure: origin='transport' must
    only ever mean the wire. Here the broker replied, but the response failed a check we
    impose, so the summary is the message we chose - the one investigable string we control -
    not a guess about what happened on the wire.
    """
    return {
        "origin": "local",
        "code": type(error).__name__,
        "summary": _summary_from(str(error)) if str(error) else "",
        "evidence": evidence,
        "body_captured": False,
    }
