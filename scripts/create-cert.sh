#!/bin/sh
set -eu

host="${1:-localhost}"
san="${2:-DNS:localhost,IP:127.0.0.1,DNS:$host}"
mkdir -p certs
chmod 700 certs
openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 365 \
  -keyout certs/server.key -out certs/server.crt \
  -subj "/CN=$host" \
  -addext "subjectAltName=$san"
chmod 600 certs/server.key
printf 'Certificate: certs/server.crt\n'
