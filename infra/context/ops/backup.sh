#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ ${1:-} == --help ]]; then
    printf 'Usage: backup.sh\nWrites a PostgreSQL dump, immutable media and SHA-256 manifest under /backups.\n'
    exit 0
fi
[[ $# == 0 ]] || { echo 'Unexpected backup arguments' >&2; exit 2; }
[[ ${PGDATABASE:-} =~ ^[a-zA-Z0-9_]+$ ]] || { echo 'Invalid database name' >&2; exit 2; }
[[ ${SOURCE_IMAGE_TAG:-} =~ ^[a-zA-Z0-9_.-]+$ ]] || { echo 'Image commit tag is required' >&2; exit 2; }
[[ -d /backups && ! -L /backups && -d /source/media ]] || { echo 'Private backup/media mounts are required' >&2; exit 2; }
mkdir /backups/.backup.lock || { echo 'Another backup is active; inspect a stale lock before removing it' >&2; exit 1; }
trap 'rmdir /backups/.backup.lock' EXIT

partial=$(mktemp -d /backups/.partial-XXXXXXXX)
backup_id="$(date -u +%Y%m%dT%H%M%SZ)-${partial##*.partial-}"
pg_dump --format=custom --no-owner --no-privileges --file "$partial/database.dump"
# Files are content-addressed and immutable. Exclude downloads that are not committed yet.
(cd /source/media && find . -type f ! -name '*.part' -print0 | tar --null --files-from=- --create --gzip --file "$partial/media.tar.gz")
printf 'format_version=1\ncreated_at=%s\ndatabase=%s\nimage_tag=%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$PGDATABASE" "$SOURCE_IMAGE_TAG" > "$partial/manifest.txt"
(cd "$partial" && sha256sum database.dump media.tar.gz manifest.txt > SHA256SUMS)
mv -T -- "$partial" "/backups/$backup_id"
printf 'Backup complete: %s\n' "$backup_id"
