# Backend image: Django + gunicorn.
#
# python:3.13-slim matches the 3.13 interpreter the project is developed against. Not alpine:
# psycopg2-binary, numpy and pandas all ship manylinux wheels that alpine's musl libc cannot
# use, so an alpine base would compile them from source on every build.
FROM python:3.13-slim AS base

# PYTHONDONTWRITEBYTECODE: .pyc files in a read-only, single-run container are pure noise.
# PYTHONUNBUFFERED: without it Python buffers stdout when it isn't a TTY, so container logs
# arrive in delayed chunks - or not at all if the process is killed.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# libpq5 is psycopg2-binary's runtime dependency. No build-essential or libpq-dev: every pinned
# requirement resolves to a wheel, so no compiler is needed and leaving one out of the final
# image removes a large amount of attack surface.
RUN apt-get update \
    && apt-get install --no-install-recommends -y libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Requirements copied and installed before the source, so editing application code reuses the
# cached dependency layer instead of reinstalling everything.
COPY requirements.txt .
RUN pip install --require-hashes=false -r requirements.txt

COPY . .

# Run as a non-root user. If the application is ever exploited, the attacker lands as a user
# that cannot write to the code it is running.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/staticfiles \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Liveness only - the readiness endpoint checks the database, and a database outage should not
# make the orchestrator restart an otherwise-healthy container. See api/views/health.py.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT:-8000}/api/health/" || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["gunicorn", "--config", "gunicorn.conf.py", "config.wsgi:application"]
