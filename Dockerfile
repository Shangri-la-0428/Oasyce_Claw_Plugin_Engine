FROM python:3.12-slim AS base

LABEL maintainer="Oasyce Team"
LABEL description="Oasyce Protocol — AI Intelligence & Memory Free Market"

WORKDIR /app

# Install system deps (cryptography needs these)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy and install Python package
COPY pyproject.toml README.md LICENSE ./
COPY oasyce/ oasyce/
COPY scripts/ scripts/

RUN pip install --no-cache-dir . && \
    apt-get purge -y gcc && apt-get autoremove -y

# Create data directory
RUN mkdir -p /root/.oasyce

EXPOSE 8420 9527

# Health check
HEALTHCHECK --interval=30s --timeout=5s \
    CMD oasyce doctor --json || exit 1

ENTRYPOINT ["oasyce"]
CMD ["serve"]
