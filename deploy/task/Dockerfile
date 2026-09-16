FROM debian:bookworm-slim

ARG PG_REF=refs/postgres-gym/pristine
ARG TARGETARCH

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
        bison build-essential ca-certificates curl flex git gosu libicu-dev \
        libssl3 locales openssl perl pkg-config python3 python3-venv tzdata zlib1g-dev \
    && localedef -i de_DE -f UTF-8 de_DE.UTF-8 \
    && localedef -i en_US -f UTF-8 en_US.UTF-8 \
    && localedef -i sv_SE -f UTF-8 sv_SE.UTF-8 \
    && localedef -i tr_TR -f UTF-8 tr_TR.UTF-8 \
    && localedef --no-archive -i de_DE -f UTF-8 /usr/lib/locale/de_DE \
    && localedef --no-archive -i en_US -f UTF-8 /usr/lib/locale/en_US \
    && localedef --no-archive -i sv_SE -f UTF-8 /usr/lib/locale/sv_SE \
    && localedef --no-archive -i tr_TR -f UTF-8 /usr/lib/locale/tr_TR \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 bench
WORKDIR /bench
RUN chown bench:bench /bench
USER bench

COPY --chown=bench:bench stand/pg.git /bench/pg.git
RUN set -eu; \
    g() { git --git-dir=/bench/pg.git --work-tree=/bench/pg "$@"; }; \
    g config core.ignorecase false; \
    g config core.precomposeunicode false; \
    mkdir -p /bench/pg; \
    sha="$(g rev-parse "$PG_REF")"; \
    g update-ref refs/postgres-gym/pristine "$sha"; \
    g update-ref refs/heads/postgres-gym "$sha"; \
    g symbolic-ref HEAD refs/heads/postgres-gym; \
    g reset --hard

RUN cd /bench/pg \
    && ./configure --prefix=/bench/pg-install --enable-cassert --enable-debug --with-icu --without-readline \
    && make -j"$(nproc)" \
    && make install

USER root
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir "rich>=15"

ARG MARKOV_CHANNEL=canary
ARG MARKOV_SHA256=
ARG MARKOV_BASE=https://git.postgrespro.ru/api/v4/projects/3154/packages/generic/markov
ARG MARKOV_S3_HOST=s3.d.postgrespro.ru
ARG MARKOV_CA_FINGERPRINT=69:AA:81:A2:94:15:B0:3C:C7:B4:22:68:46:FD:E7:68:12:89:B5:1A:CD:3C:E1:35:96:B0:1B:AA:6E:0F:F3:66
RUN set -eu; \
    openssl s_client -connect "${MARKOV_S3_HOST}:443" -showcerts </dev/null 2>/dev/null \
      | awk '/-----BEGIN/{c=""} {c=c $0 ORS} /-----END/{last=c} END{printf "%s", last}' > /tmp/ca.crt; \
    got="$(openssl x509 -in /tmp/ca.crt -noout -fingerprint -sha256 | cut -d= -f2)"; \
    test "$got" = "$MARKOV_CA_FINGERPRINT"; \
    cp /tmp/ca.crt /usr/local/share/ca-certificates/ca-postgrespro.crt; \
    update-ca-certificates >/dev/null; \
    case "$TARGETARCH" in \
      arm64) target=aarch64-unknown-linux-gnu; sha="${MARKOV_SHA256:-a1f5bbc5ef8266efd1721a806eb06a20fcd495a46b02072810fd1b7f5d3ec7b0}" ;; \
      amd64) target=x86_64-unknown-linux-gnu; sha="$MARKOV_SHA256"; test -n "$sha" || { echo 'MARKOV_SHA256 is required on amd64' >&2; exit 2; } ;; \
      *) echo "unsupported TARGETARCH=$TARGETARCH" >&2; exit 2 ;; \
    esac; \
    curl -fsSL -o /tmp/markov.tar.gz "${MARKOV_BASE}/${MARKOV_CHANNEL}/markov-cli-${target}.tar.gz"; \
    echo "$sha  /tmp/markov.tar.gz" | sha256sum -c -; \
    mkdir -p /tmp/markov; \
    tar -xzf /tmp/markov.tar.gz -C /tmp/markov; \
    find /tmp/markov -type f -perm -u+x -exec install -m 0755 {} /usr/local/bin/ \; ; \
    rm -rf /tmp/markov /tmp/markov.tar.gz /tmp/ca.crt; \
    markov --version

ARG OPENCODE_VERSION=v1.18.20
RUN set -eu; \
    case "$TARGETARCH" in arm64) target=linux-arm64 ;; amd64) target=linux-x64 ;; *) exit 2 ;; esac; \
    curl -fsSL -o /tmp/opencode.tar.gz "https://github.com/anomalyco/opencode/releases/download/${OPENCODE_VERSION}/opencode-${target}.tar.gz"; \
    mkdir -p /tmp/opencode; \
    tar -xzf /tmp/opencode.tar.gz -C /tmp/opencode; \
    find /tmp/opencode -type f -perm -u+x -exec install -m 0755 {} /usr/local/bin/ \; ; \
    rm -rf /tmp/opencode /tmp/opencode.tar.gz; \
    opencode --version

COPY src /opt/postgres-gym/src
COPY suites/sql-function-set/src /opt/postgres-gym/suites/sql-function-set/src
COPY suites/commit/src /opt/postgres-gym/suites/commit/src
COPY deploy/task/markov /etc/postgres-gym/markov
COPY deploy/task/opencode /etc/postgres-gym/opencode
COPY deploy/task/entrypoint.sh /usr/local/bin/postgres-gym-entry

ENV POSTGRES_GYM_ROOT=/opt/postgres-gym \
    POSTGRES_GYM_SRC=/bench/pg \
    POSTGRES_GYM_PREFIX=/bench/pg-install \
    POSTGRES_GYM_GIT_DIR=/bench/pg.git \
    PYTHONPATH=/opt/postgres-gym/src \
    PATH=/opt/venv/bin:/home/bench/.local/bin:$PATH

RUN chmod +x /usr/local/bin/postgres-gym-entry \
    && mkdir -p /work /home/bench/.local \
    && chown -R bench:bench /work /home/bench

WORKDIR /work
ENTRYPOINT ["/usr/local/bin/postgres-gym-entry"]
CMD ["tasks"]
