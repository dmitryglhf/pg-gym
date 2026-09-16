#!/bin/sh
set -eu

mkdir -p /home/bench/.config/markov /home/bench/.config/opencode
cp -r /etc/postgres-gym/markov/. /home/bench/.config/markov/
cp -r /etc/postgres-gym/opencode/. /home/bench/.config/opencode/
chown -R bench:bench /home/bench/.config /home/bench/.local 2>/dev/null || true

export GOOSE_DISABLE_KEYRING=1
export OPENCODE_DISABLE_MODELS_FETCH=1
export OPENCODE_DISABLE_AUTOUPDATE=1
export OPENCODE_DISABLE_LSP_DOWNLOAD=1
export OPENCODE_DISABLE_PROJECT_CONFIG=1

if [ -f /work/.env ]; then
    while IFS='=' read -r key value; do
        case "$key" in
            MARKOV_API_KEY|PGPRO_API_KEY|LANGFUSE_PUBLIC_KEY|LANGFUSE_SECRET_KEY)
                value=$(printf '%s' "$value" | sed "s/^['\"]//; s/['\"]$//")
                export "$key=$value"
                ;;
        esac
    done < /work/.env
    rm -f /work/.env
fi

provider_key=${PGPRO_API_KEY:-${MARKOV_API_KEY:-}}
if [ -n "$provider_key" ]; then
    umask 077
    printf 'PGPRO_API_KEY: %s\n' "$provider_key" > /home/bench/.config/markov/secrets.yaml
    chown bench:bench /home/bench/.config/markov/secrets.yaml
fi

case " $* " in
    *cli:opencode*)
        if [ -n "$provider_key" ]; then
            export POSTGRES_GYM_PROVIDER_KEY="$provider_key"
        fi
        ;;
esac

if [ "${1:-}" = "shell" ]; then
    shift
    exec gosu bench /bin/bash "$@"
fi

exec gosu bench python -m postgres_gym.cli "$@"
