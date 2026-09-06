#!/bin/bash
# Lightsail launch script (cloud-init user-data). Installs Docker, clones this
# repo's Phase 24 branch, and starts the same three-service stack Phase 23
# built and tested locally -- with docker-compose.lightsail.yml layered on
# top for the differences a long-lived public VM needs (restart policy, the
# database bound to localhost only).
set -euo pipefail

apt-get update
apt-get install -y docker.io docker-compose-v2 git
systemctl enable --now docker

git clone --branch feature/phase-24-lightsail --depth 1 \
  https://github.com/kaavehnemati/InvoiceFlow.git /opt/invoiceflow

cd /opt/invoiceflow
docker compose -f docker-compose.yml -f docker-compose.lightsail.yml up -d
