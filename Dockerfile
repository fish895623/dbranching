# Multi-stage Dockerfile for dbranching
FROM python:3.11-slim as base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r dbranching && useradd -r -g dbranching dbranching

# Production stage
FROM base as production

# Install dbranching from PyPI
RUN pip install dbranching[all-databases]

# Switch to non-root user
USER dbranching

# Set working directory
WORKDIR /workspace

# Verify installation
RUN python -c "import dbranching; print('DBranching installed successfully')" && \
    dbranching --version && \
    dbbranch --version

# Entry point
ENTRYPOINT ["dbranching"]
CMD ["--help"]

# Development stage
FROM base as development

# Install Poetry
RUN pip install poetry

# Set work directory
WORKDIR /app

# Copy Poetry files
COPY pyproject.toml poetry.lock ./

# Configure Poetry
RUN poetry config virtualenvs.create false

# Install dependencies
RUN poetry install --no-interaction --no-ansi --extras all-databases

# Copy source code
COPY . .

# Install package in development mode
RUN poetry install --no-interaction --no-ansi

# Switch to non-root user
USER dbranching

# Verify installation
RUN python -c "import dbranching; print('DBranching installed successfully')" && \
    dbranching --version && \
    dbbranch --version

# Entry point
ENTRYPOINT ["dbranching"]
CMD ["--help"]