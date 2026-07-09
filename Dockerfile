# Single-stage build: the tool is pure Python with no compiled extensions, so a
# multi-stage build buys nothing here (nothing to discard between stages).
FROM python:3.12-slim

WORKDIR /app

# setuptools needs the src/ tree present to build the wheel (src layout,
# packages discovered from pyproject.toml), so dependency install and source
# copy share one RUN — a source change invalidates this layer either way.
COPY pyproject.toml ./
COPY src/ ./src/
COPY config/ ./config/
COPY sample_logs/ ./sample_logs/

RUN pip install --no-cache-dir .

# Run as a non-root user (least privilege — this container only ever reads
# mounted log files and writes export output, never needs root).
RUN useradd --create-home --shell /usr/sbin/nologin appuser
USER appuser

# No HEALTHCHECK: this is a short-lived CLI invocation (analyze/watch/users),
# not a long-running service — there is no "is it healthy" state to poll.
ENTRYPOINT ["security-log-analysis-tool"]
CMD ["--help"]
