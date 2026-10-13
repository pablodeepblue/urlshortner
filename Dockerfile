FROM python:3.14-slim

# Copy the uv binary from the official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Install dependencies first (cached unless the lockfile changes)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Then copy the app
COPY app.py .

# Non-root user + writable folder for the SQLite file
RUN useradd -m appuser && mkdir /data && chown appuser /data
USER appuser

ENV PATH="/app/.venv/bin:$PATH" \
    DATABASE=/data/urls.db
VOLUME /data
EXPOSE 8000

CMD ["gunicorn", "-b", "0.0.0.0:8000", "-w", "2", "app:create_app()"]
