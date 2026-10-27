# API gateway. Stages follow the repo convention (deploy/components.yaml):
#   docker build --target test .      runs pytest; CI builds only this
#   docker build --target runtime .   the Cloud Run image
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY pyproject.toml ./
COPY carebridge ./carebridge

FROM base AS test
RUN pip install --no-cache-dir '.[dev]'
COPY tests ./tests
RUN pytest -q

FROM base AS runtime
RUN pip install --no-cache-dir . && useradd --uid 10001 --no-create-home app
USER app
# Cloud Run sets $PORT; credentials come from the service account (ADC), never the image.
ENV PORT=8080 CAREBRIDGE_ENV=prod
CMD ["sh", "-c", "exec uvicorn carebridge.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers"]
