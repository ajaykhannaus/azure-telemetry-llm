#!/bin/sh
# Substitute Azure backend endpoints then start the Collector.
set -e

CONFIG=/etc/otelcol-contrib/config.yaml
OUT=/tmp/otel-config.yaml

for var in TEMPO_ENDPOINT LOKI_ENDPOINT PROM_WRITE_ENDPOINT; do
  eval "val=\$$var"
  if [ -z "$val" ]; then
    echo "ERROR: $var is required" >&2
    exit 1
  fi
done

sed \
  -e "s|__TEMPO_ENDPOINT__|${TEMPO_ENDPOINT}|g" \
  -e "s|__LOKI_ENDPOINT__|${LOKI_ENDPOINT}|g" \
  -e "s|__PROM_WRITE_ENDPOINT__|${PROM_WRITE_ENDPOINT}|g" \
  "$CONFIG" > "$OUT"

exec /otelcol-contrib --config="$OUT"
