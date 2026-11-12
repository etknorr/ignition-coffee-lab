#!/bin/bash
# Seeds the ignition-data volume on first start.
# Adapted from etknorr/project-template (scripts/docker-bootstrap.sh).
#
# One deliberate change from the template: this script does NOT write
# an empty commissioning.json. The template relies on a committed
# user source for its admin user; here the admin is commissioned by
# the gateway image from GATEWAY_ADMIN_USERNAME / GATEWAY_ADMIN_PASSWORD
# on first boot, and a pre-written commissioning.json would pre-empt
# that. If env commissioning ever misbehaves on a beta image, the
# fallback is to restore the template line (echo "{}" into
# commissioning.json) and set the admin through the gateway web UI.
set -e

DATA_DIR="/data"

if [ ! -f "${DATA_DIR}/.ignition-seed-complete" ]; then
  echo "Seeding data for gateway..."

  # Copy base ignition data
  cp -dpR /usr/local/bin/ignition/data/* "${DATA_DIR}/"

  # Generate deterministic UUID and save to gateway network location
  UUID=$(echo -n "${GATEWAY_NAME}" | md5sum | awk '{print $1}' | sed 's/\(........\)\(....\)\(....\)\(....\)\(............\)/\1-\2-\3-\4-\5/' | tr -d '[:space:]')
  mkdir -p "${DATA_DIR}/config/local/ignition/gateway-network"
  echo -n "${UUID}" > "${DATA_DIR}/config/local/ignition/gateway-network/uuid.txt"
  echo "Generated UUID for gateway: ${UUID}"

  touch "${DATA_DIR}/.ignition-seed-complete"

  echo "Seeding complete for gateway."
else
  echo "Gateway already seeded, skipping..."
fi

echo "Bootstrap completed successfully."
