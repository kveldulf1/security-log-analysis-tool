"""Secret and PII redaction for logs, diagnostics, and every export path.

``redact`` is the single choke point every outward-facing string passes through:
the logging RedactionFilter, finding descriptions, evidence excerpts, and the
JSON/CSV/SARIF exporters. It is deliberately conservative — it errs toward
scrubbing — and every pattern is anchored with no nested quantifiers so it cannot
be turned into a ReDoS vector by attacker-controlled log content.
"""

from __future__ import annotations

import re

REDACTED = "[REDACTED]"
REDACTED_EMAIL = "[REDACTED_EMAIL]"

# Keys whose value is a credential regardless of the surrounding text.
_SENSITIVE_KEYS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api[_-]?key",
    "access[_-]?key",
    "client[_-]?secret",
    "credential",
    "private[_-]?key",
)

# Ordered list of (pattern, replacement). Order matters: broad structural
# patterns (key blocks, URL userinfo) run before token-shape heuristics.
_RULES: list[tuple[re.Pattern[str], str]] = [
    # PEM private key blocks — collapse the whole block.
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        REDACTED,
    ),
    # Inline credentials in a URL userinfo position: scheme://user[:pass]@host.
    # The userinfo run is greedy up to the LAST '@' before the host, so passwords
    # that themselves contain ':' or '@' are fully scrubbed, and token-only
    # (colon-less) userinfo is caught too.
    #
    # The scheme run is length-bounded ({0,32}, not '*'): a long run of
    # scheme-valid characters with no following '://' would otherwise make the
    # engine rescan from every start position — O(n^2) on attacker-controlled log
    # content (a real ReDoS). Real URL schemes are a handful of characters, so the
    # bound is invisible to legitimate input and makes this rule strictly linear.
    (
        re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]{0,32}://)[^\s/]+@"),
        r"\g<scheme>" + REDACTED + "@",
    ),
    # Authorization: Bearer <token>  /  Authorization=<token>
    (
        re.compile(r"(?P<pre>authorization\s*[=:]\s*)(?:bearer\s+)?\S+", re.IGNORECASE),
        r"\g<pre>" + REDACTED,
    ),
    # sensitive_key = value  (value may be quoted)
    (
        re.compile(
            r"(?P<pre>\b(?:" + "|".join(_SENSITIVE_KEYS) + r")\s*[=:]\s*)"
            r"(?P<val>\"[^\"]*\"|'[^']*'|\S+)",
            re.IGNORECASE,
        ),
        r"\g<pre>" + REDACTED,
    ),
    # Provider token shapes (prefix-anchored; no nested quantifiers).
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]+"), REDACTED),
    (re.compile(r"\bgh[posur]_[A-Za-z0-9]+"), REDACTED),
    (re.compile(r"\bsk-ant-[A-Za-z0-9-]+"), REDACTED),
    # Allow hyphens after sk- so OpenAI project/service/admin keys
    # (sk-proj-…, sk-svcacct-…, sk-admin-…) are covered, not just legacy sk-<hex>.
    (re.compile(r"\bsk-[A-Za-z0-9-]{16,}"), REDACTED),
    (re.compile(r"\bglpat-[A-Za-z0-9_-]+"), REDACTED),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]+"), REDACTED),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), REDACTED),
    # Email addresses (PII).
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), REDACTED_EMAIL),
]


def redact(text: object) -> str:
    """Return ``text`` with secrets and PII replaced by fixed placeholders.

    Idempotent: redacting already-redacted text is a no-op. Accepts any object
    and coerces to ``str`` so it is safe to drop into a logging filter.
    """

    result = text if isinstance(text, str) else str(text)
    for pattern, replacement in _RULES:
        result = pattern.sub(replacement, result)
    return result
