# Manual test procedures

Everything in this document needs a human — a real inbox, a visible desktop,
a browser, or a Jenkins UI click. Each procedure is copy-paste setup + run
steps, what to look for, the expected result, and cleanup. Agentic
(pytest/behave) coverage for the same features lives in `tests/` and
`features/`; this file only covers what those can't reach.

## 1. Real SMTP alert email

**Setup**

1. Create a Gmail (or other SMTP provider) [app password](https://support.google.com/accounts/answer/185833)
   — never your primary account password.
2. Copy `.env.example` to `.env` and fill in the SMTP block:
   ```
   SLAT_SMTP_HOST=smtp.gmail.com
   SLAT_SMTP_PORT=587
   SLAT_SMTP_STARTTLS=true
   SLAT_SMTP_USERNAME=<your-address>@gmail.com
   SLAT_SMTP_PASSWORD=<the-app-password>
   SLAT_SMTP_FROM=<your-address>@gmail.com
   SLAT_SMTP_TO=<an-address-you-can-check>
   ```
3. `.env` is gitignored — confirm `git status` shows it untracked before continuing.

**Run**

```bash
security-log-analysis-tool analyze sample_logs/access.log sample_logs/auth.log
```

(omit `--no-alerts` so the alert dispatcher fires; findings are above the
default `min_severity: high` in `config/rules.yaml`.)

**Expected result**

- An email arrives at `SLAT_SMTP_TO` within a minute, subject referencing the
  analysis run, body listing HIGH/CRITICAL findings with severity, rule id,
  IP, and evidence line numbers.
- No secret or full password ever appears in the email body (findings only
  reference redacted excerpts).

**Cleanup**: delete the app password from your Google Account once done;
do not leave `.env` populated with a live credential longer than needed.

## 2. Desktop toast notification (Windows)

**Setup**: same `.env`/rules as above; run from an interactive Windows
desktop session (toast is a no-op on CI/headless/off-Windows by design).

**Run**

```powershell
security-log-analysis-tool analyze sample_logs/access.log sample_logs/auth.log
```

**Expected result**: a Windows toast notification appears summarizing the
run's highest-severity finding within a few seconds of the console report
printing. Dismiss it manually (no cleanup needed).

## 3. TUI walkthrough

**Setup**: `security-log-analysis-tool users seed-demo` once, to create the
two demo accounts (`amelia.reyes` / `Password123!` admin,
`oscar.lindqvist` / `P@ssword123?` analyst).

**Run**: `security-log-analysis-tool tui`

(if that console script isn't on `PATH`, use the PATH-independent equivalent
`python -c "from security_log_analysis_tool.cli import main; main()" tui`)

A captured run of the steps below lives in
[e2e-report.md §6 — TUI walkthrough](e2e-report.md#6-tui-walkthrough-visual-evidence).

**Steps and expected results**

| Step | Expected result |
|---|---|
| Log in as `oscar.lindqvist` | Main menu shown; no admin-only options (e.g. manage users) visible |
| Start an analysis on `sample_logs/access.log` + `sample_logs/auth.log` | Job appears queued, transitions to running, then done |
| Open findings | Severity-colored table; correlated findings called out separately |
| Open tool logs, pick a level (e.g. WARNING) | Log view filters live to that level and above |
| Try invalid input on any screen (empty field, out-of-range choice) | A validation message appears; you stay on the screen or return to the main menu — the app never exits |
| Log out, log back in as `amelia.reyes` | Admin-only options now visible |
| Quit | App exits cleanly; no orphaned Python threads/processes remain (check Task Manager) |

**Cleanup**: none required; `users seed-demo` accounts are safe to leave for
future manual runs.

## 4. Jenkins: job run, Allure tab, RED-build demo

**One-time setup**

1. Install Jenkins (native Windows, or Docker per
   [jenkins.io](https://www.jenkins.io/doc/book/installing/docker/)) plus a
   JDK if not already present.
2. Install the **Allure Jenkins plugin** (Manage Jenkins → Plugins) and
   configure an **Allure Commandline** tool (Manage Jenkins → Tools).
3. New Item → Pipeline. Under "Pipeline", set **Definition** = "Pipeline
   script from SCM", **SCM** = this repository, **Script Path** = `Jenkinsfile`.
4. Save, then **Build Now** for the first manual run.

**Expected result (green run)**

- Console output shows the `Setup` and `Regression` stages completing.
- Build goes **green**.
- An "Allure Report" link/tab appears on the job page; open it — the merged
  pytest + behave results render with a pass/fail breakdown.
- **Screenshot this** (job page with Allure tab, and the Allure report
  itself) for `docs/e2e-report.md`.

**RED-build demo**

1. On a scratch branch, introduce a deliberately failing test (e.g. `assert
   False` in a new throwaway test function).
2. Push the branch and point a temporary Jenkins job (or reconfigure the
   branch on the existing one) at it, or trigger a build against that branch.
3. **Expected result**: the `Regression` stage fails, the build goes **red**,
   and the Allure report (published via `post { always { ... } }`) still
   renders showing the failing test — proving the pipeline both blocks on a
   red suite and still reports why.
4. **Screenshot this** for `docs/e2e-report.md`.
5. **Cleanup**: delete the scratch branch and the failing test/job.

## 5. GitHub Pages Allure report (browser check)

**Setup**: push to `master` so `.github/workflows/ci.yml`'s `allure-pages`
job runs (needs `test` to succeed first); confirm GitHub Pages is enabled
for the repo (Settings → Pages → Source = the `gh-pages` branch this
workflow publishes to).

**Run**: open `https://kveldulf1.github.io/security-log-analysis-tool/` in a
browser once the workflow run completes.

**Expected result**: the Allure report loads, shows the latest smoke-suite
run (pytest + behave merged), and the trend/history graph reflects prior
runs (not just a single data point) once a few pushes have landed.

**Cleanup**: none — this is a durable published artifact, expected to stay live.
