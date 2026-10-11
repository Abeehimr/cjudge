#!/bin/sh
set -eu

hosts="${CJUDGE_ALLOWED_HOSTS:-localhost,127.0.0.1}"
case "$hosts" in
  ''|,*|*,|*,,*|*[!A-Za-z0-9.,-]*) echo 'Invalid CJUDGE_ALLOWED_HOSTS' >&2; exit 1 ;;
esac
printf 'server_name %s;\n' "$(printf '%s' "$hosts" | tr ',' ' ')" > /tmp/cjudge-hosts.conf
