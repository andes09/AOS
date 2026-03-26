FROM python:3.12-slim

WORKDIR /app

# Force Python stdout/stderr to be unbuffered so logs appear in Railway
ENV PYTHONUNBUFFERED=1

# Install uv
RUN pip install uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies into the project venv (no dev deps)
RUN uv sync --frozen --no-dev

# Copy source (ARG here busts only the COPY layer, not the uv install layer)
ARG BUILD_DATE=unknown
COPY . .

# Ensure the venv binaries are on PATH at runtime
ENV PATH="/app/.venv/bin:$PATH"

# Default command (overridden per Railway service)
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
