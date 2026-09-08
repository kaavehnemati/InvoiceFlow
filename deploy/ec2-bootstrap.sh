#!/bin/sh
# EC2 launch script (user-data). Installs Docker, Nginx, and git, clones this
# repo's Phase 25 branch, wires Nginx as a reverse proxy in front of the app,
# and starts the stack through a systemd unit rather than directly -- the
# unit is the actual process manager for this phase, not a decorative wrapper.
#
# POSIX sh, not bash, and set -eu without pipefail: the same discipline
# deploy/lightsail-bootstrap.sh settled on after breaking under dash when
# pasted into a console text box. There is no pipeline here whose exit status
# matters, so nothing bash-specific is needed regardless of which shell
# actually runs this.
set -eu

apt-get update
apt-get install -y docker.io docker-compose-v2 git nginx

systemctl enable --now docker

git clone --branch feature/phase-25-ec2 --depth 1 https://github.com/kaavehnemati/InvoiceFlow.git /opt/invoiceflow

cp /opt/invoiceflow/deploy/nginx-invoiceflow.conf /etc/nginx/sites-available/invoiceflow
ln -sf /etc/nginx/sites-available/invoiceflow /etc/nginx/sites-enabled/invoiceflow
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

cp /opt/invoiceflow/deploy/invoiceflow.service /etc/systemd/system/invoiceflow.service
systemctl daemon-reload
systemctl enable --now invoiceflow.service
