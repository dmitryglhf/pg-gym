FROM postgres-gym-task:17.11

USER root
RUN apt-get update && apt-get install -y --no-install-recommends pkg-config libicu-dev \
    && rm -rf /var/lib/apt/lists/*
USER bench

COPY src /opt/postgres-gym/src
COPY suites /opt/postgres-gym/suites

USER root
