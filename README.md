# security-log-analysis-tool

TODO: one paragraph describing what security-log-analysis-tool does.

## Install (global Python, no venv)

    python -m pip install -e ".[dev]"

## Run

    security-log-analysis-tool --version
    # or, without the console script:
    python -m security_log_analysis_tool.cli --version

## Develop

    python -m pytest          # run tests
    python -m ruff check .    # lint
    python -m ruff format .   # format
    pre-commit install        # activate the ruff pre-commit hook
