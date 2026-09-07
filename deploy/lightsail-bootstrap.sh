#!/bin/sh
# Lightsail launch script (cloud-init user-data). Installs Docker, clones this
# repo's Phase 24 branch, and starts the same three-service stack Phase 23
# built and tested locally -- with docker-compose.lightsail.yml layered on
# top for the differences a long-lived public VM needs (restart policy, the
# database bound to localhost only).
#
# Deliberately POSIX sh, not bash: pasting this into the Lightsail console's
# launch-script box does not reliably preserve the shebang as the literal
# first line, and cloud-init falls back to /bin/sh (dash) when it can't
# recognize one. Confirmed directly: a first version used
# `set -euo pipefail`, dash rejected `-o pipefail` as an illegal option, and
# the whole script aborted before Docker was even installed. `set -eu` alone
# is supported by both shells and is all this script actually needs -- there
# is no pipeline here whose exit status matters.
set -eu

apt-get update
apt-get install -y docker.io docker-compose-v2 git
systemctl enable --now docker

git clone --branch feature/phase-24-lightsail --depth 1 https://github.com/kaavehnemati/InvoiceFlow.git /opt/invoiceflow

cd /opt/invoiceflow
docker compose -f docker-compose.yml -f docker-compose.lightsail.yml up -d
