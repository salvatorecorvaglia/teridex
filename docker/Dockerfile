# syntax=docker/dockerfile:1.7

# ---- Builder ---------------------------------------------------------
FROM python:3.15-rc-alpine AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
 && ln -s /root/.local/bin/uv /usr/local/bin/uv

WORKDIR /src
COPY pyproject.toml uv.lock* README.md ./
COPY src ./src

# Fail loud if uv.lock is stale rather than silently regenerating it — the
# lock file is committed and the image must build from exactly those pins.
RUN uv sync --frozen --no-dev --all-extras

# ---- Runtime --------------------------------------------------------
FROM python:3.15-rc-alpine AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TERIDEX_LOG_LEVEL=INFO

RUN useradd -ms /bin/false -u 10001 teridex

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /src /app

WORKDIR /app
USER teridex

ENTRYPOINT ["teridex"]
CMD ["--help"]
