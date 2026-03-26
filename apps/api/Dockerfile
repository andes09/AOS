FROM python:3.12-slim

WORKDIR /app

# Force Python stdout/stderr to be unbuffered so logs appear in Railway
ENV PYTHONUNBUFFERED=1

# Cache bust: 2026-03-26
ARG BUILD_DATE=2026-03-26

# Install uv
RUN pip install uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies into the project venv (no dev deps)
RUN uv sync --frozen --no-dev

# Copy source
COPY . .

# Explicitly copy alembic migrations to ensure no layer cache omits them
COPY alembic/ alembic/

# Ensure the venv binaries are on PATH at runtime
ENV PATH="/app/.venv/bin:$PATH"

# Default command (overridden per Railway service)
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
