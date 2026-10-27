# Mobile Care Planner, web build served by nginx. Stages follow the repo
# convention (deploy/components.yaml):
#   docker build --target test .      runs flutter test; CI builds only this
#   docker build --target runtime .   the Cloud Run image
#
# Built once for every env: CAREBRIDGE_API=same-origin makes the app call its
# own origin, and nginx forwards /v1/ to $API_URL (set per env by Cloud Run).
ARG FLUTTER_VERSION=3.32.5

FROM ghcr.io/cirruslabs/flutter:${FLUTTER_VERSION} AS deps
WORKDIR /app
COPY pubspec.yaml pubspec.lock ./
RUN flutter pub get
COPY . .

FROM deps AS test
RUN flutter test

FROM deps AS build
RUN flutter build web --release --dart-define=CAREBRIDGE_API=same-origin

FROM nginx:1.27-alpine AS runtime
# Lets the template use ${NGINX_LOCAL_RESOLVERS} (from /etc/resolv.conf), so the
# API hostname resolves per request and the UI can start before the API exists.
# GOOGLE_MAPS_KEY must be defined (even empty) or envsubst leaves ${GOOGLE_MAPS_KEY} in the config.
ENV NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1 PORT=8080 API_URL=http://host.docker.internal:8000 GOOGLE_MAPS_KEY=""
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/build/web /usr/share/nginx/html
