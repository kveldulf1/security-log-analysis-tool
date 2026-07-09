---
name: project-conventions
description: Working conventions for security-log-analysis-tool — treat external input as untrusted, redact secrets/PII, keep core logic pure and table-tested. Tailor to this project's spec.
metadata:
  type: project
---

<!-- Starter conventions (generic security/data best-practice). Tailor to this project's actual spec. -->

Conventions for security-log-analysis-tool. Apply when adding parsers, detectors, transforms, or output.

- **Treat every log line as untrusted input.** Logs can carry attacker-controlled content — guard against injection into downstream sinks (shell, SQL, HTML reports), ReDoS in regex parsers, and resource exhaustion from crafted/oversized lines. Fail closed on malformed input; never let one bad line crash the whole run.
- **Redact secrets and PII** in every report, diagnostic, and error message — tokens, passwords, API keys, and personal data. Never echo a raw secret discovered in a log.
- **Parsers are pure and table-tested.** A parser maps raw line → normalized event with no I/O; cover it with table-driven fixtures: well-formed, malformed, truncated, and adversarial.
- **Detectors are isolated and independently testable.** Each detection rule is its own unit with clear inputs/outputs; a new rule ships with its own known-good and known-bad samples.
- **Timestamps carry timezone.** Normalize to UTC internally; never assume local time from a log.

**Why:** a security tool that mishandles its own untrusted input, or leaks secrets in its output, is worse than useless. Purity + table tests keep parsing and detection correct and regression-safe.

**How to apply:** new parser → pure function + fixture table (including adversarial cases). New detector → isolated unit + good/bad samples. Any output path → run it through redaction first.
