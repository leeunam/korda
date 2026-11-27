#!/usr/bin/env bash
set -euo pipefail
while true; do
    bash /ops/backup.sh
    sleep 86400
done
