#!/bin/sh
set -eu

base="${1:-https://localhost:8443}"
http_base="${2:-http://localhost:8080}"
curl --fail --silent --show-error --max-time 15 --cacert certs/server.crt "$base/api/health" | grep -q '"ok"'
curl --fail --silent --show-error --max-time 15 --cacert certs/server.crt "$base/api/ready" | grep -q '"ready"'
curl --fail --silent --show-error --max-time 15 --cacert certs/server.crt "$base/" | grep -q 'cJudge'
test "$(curl --fail --silent --show-error --max-time 15 --output /dev/null --write-out '%{http_code} %{redirect_url}' "$http_base/")" = "308 $base/"
printf 'Smoke check passed: %s\n' "$base"
