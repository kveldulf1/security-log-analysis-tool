# Secrets Hygiene

A leaked credential is a production incident. Treat every one of these as radioactive and never let one
reach a terminal command, a file, a commit, a plan, a memory, or the chat transcript.

## Radioactive patterns (prefixes only — never write a full example anywhere)
- GitHub: `ghp_`, `github_pat_`, `gho_`, `ghu_`, `ghs_`, `ghr_`
- Anthropic / OpenAI: `sk-ant-`, `sk-`
- AWS: `AKIA…`
- GitLab: `glpat-`
- Slack: `xoxb-` / `xoxp-` / `xoxa-` / `xoxr-`
- Private keys: any `-----BEGIN … PRIVATE KEY-----` block
- Any URL carrying an inline credential in the userinfo position (anything before the `@` in `https://...@host`)

## Never embed credentials in git remote URLs
- Auth goes through the OS credential helper (on this machine: `credential.helper=wincred`, Windows Credential Manager). The helper prompts once and stores the token outside the repo.
- Fix broken auth with `git remote set-url origin https://github.com/<owner>/<repo>.git` — a **clean** URL. Never paste a token into the URL to "make push work."
- A token in `remote.origin.url` sits in plaintext in `.git/config` and leaks into every `git remote -v` you run.

## Redact before echoing anything that can print a remote URL
Commands like `git remote -v` and `git config --list` can surface an inline-auth URL. Pipe through a redactor:
- PowerShell: `git remote -v | % { $_ -replace '://[^@/]+@','://[REDACTED]@' }`
- Bash tool (sh): `git remote -v | sed -E 's#://[^@/]+@#://[REDACTED]@#'`
When you only need to confirm a leak was cleaned, prefer a **count**, not the content: report `path:line`, never the matched line.

## Never paste a token into chat, plans, memories, commit messages, or code
If you spot a secret in command output or a file, STOP. Report only `found a credential in <path>` (path, not value), treat it as a live leak, and follow the response procedure below. Do not repeat the secret to "confirm" it.

## .gitignore floor — every project carries at least
```
.env
.env.*
!.env.example
*.pem
*.key
*.pfx
*.p12
id_rsa*
secrets/
.claude/settings.local.json
```
Do **not** blanket-ignore `.claude/` — committed skills/rules/memories live there. Only the local settings file is ignored.

## Leak response procedure
1. **Revoke** the exposed credential at its issuer immediately (do not wait to finish other work).
2. **Rotate** — mint a replacement, scoped as narrowly as possible; enter it only at the credential-helper prompt.
3. **Scrub** — remove the secret from every file it reached (config, transcripts, plans, history), replacing with a non-secret placeholder. No backups (a backup retains the secret).
4. **Verify** — re-run a residual scan for the radioactive patterns; expect zero matches.
