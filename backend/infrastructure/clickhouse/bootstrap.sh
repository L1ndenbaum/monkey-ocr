#!/bin/sh
set -eu

host="${CLICKHOUSE_HOST:-clickhouse}"
port="${CLICKHOUSE_NATIVE_PORT:-9000}"
database="${CLICKHOUSE_DATABASE:-monkeyocr_logging_db}"
user="${CLICKHOUSE_USER:-monkeyocr_logging}"
password="${CLICKHOUSE_PASSWORD:-}"

until clickhouse-client --host "$host" --port "$port" --user "$user" --password "$password" --query "SELECT 1" >/dev/null 2>&1; do
  sleep 2
done

clickhouse-client --host "$host" --port "$port" --user "$user" --password "$password" \
  --query "CREATE DATABASE IF NOT EXISTS ${database}"
exec migrate -path /migrations \
  -database "clickhouse://${host}:${port}?username=${user}&password=${password}&database=${database}&x-multi-statement=true" up
