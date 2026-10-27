# The team's agents as their own ADK service (`adk web`: dev UI + REST API).
# Stages follow the repo convention (deploy/components.yaml):
#   docker build --target test .      imports the app on real ADK; CI builds only this
#   docker build --target runtime .   the Cloud Run image
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONPATH=/app
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY carebridge ./carebridge
COPY adk_runtime ./adk_runtime
COPY apps ./apps

FROM base AS test
RUN cd apps && python -c "from carebridge_coordinator.agent import root_agent; print(root_agent.name)"

FROM base AS runtime
RUN useradd --uid 10001 --no-create-home app
USER app
# Cloud Run sets $PORT; credentials come from the service account (ADC), never the image.
ENV PORT=8080
CMD ["sh", "-c", "exec adk web --host 0.0.0.0 --port ${PORT} --no-reload /app/apps"]
