#!/bin/bash
# Assembles the Elastic Beanstalk application bundle: exactly what the Docker
# platform needs at the zip root -- docker-compose.yml, the same Dockerfile
# used everywhere else, and the source files that Dockerfile COPYs. Beanstalk
# doesn't clone git or read the repo layout; it extracts this zip verbatim and
# runs Docker against whatever's inside it.
set -euo pipefail
cd "$(dirname "$0")/../.."

BUNDLE_DIR=$(mktemp -d)
OUT="${1:-/tmp/invoiceflow-beanstalk.zip}"

cp deploy/beanstalk/docker-compose.yml "$BUNDLE_DIR/docker-compose.yml"
cp Dockerfile "$BUNDLE_DIR/Dockerfile"
cp requirements.txt alembic.ini "$BUNDLE_DIR/"
cp -r migrations "$BUNDLE_DIR/migrations"
cp -r app "$BUNDLE_DIR/app"
find "$BUNDLE_DIR" -name "__pycache__" -type d -exec rm -rf {} +

rm -f "$OUT"
( cd "$BUNDLE_DIR" && zip -qr "$OUT" . )
rm -rf "$BUNDLE_DIR"

echo "Bundle written to: $OUT"
