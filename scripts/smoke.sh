#!/bin/sh
set -eu

base="${1:-https://localhost:8443}"
curl --fail --silent --show-error --cacert certs/server.crt "$base/api/health" | grep -q '"ok"'
curl --fail --silent --show-error --cacert certs/server.crt "$base/api/ready" | grep -q '"ready"'
curl --fail --silent --show-error --cacert certs/server.crt "$base/" | grep -q 'cJudge'
test "$(curl --silent --output /dev/null --write-out '%{http_code}' http://localhost:8080/)" = 308
printf 'M0 smoke check passed\n'
