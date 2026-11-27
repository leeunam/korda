#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ ${1:-} == --help ]]; then
    printf 'Usage: restore.sh --disposable-target ctx_restore_<id> <backup-id>\nOnly creates a new database and extracts to an empty /restore-media volume.\n'
    exit 0
fi
[[ $# == 3 && $1 == --disposable-target ]] || { echo 'An explicit disposable target is required' >&2; exit 2; }
target=$2
backup_id=$3
[[ $target =~ ^ctx_restore_[a-z0-9_]{1,48}$ && $target != "${PGDATABASE:-}" ]] || { echo 'Unsafe restore database target' >&2; exit 2; }
[[ $backup_id =~ ^[0-9]{8}T[0-9]{6}Z-[a-zA-Z0-9]{8}$ ]] || { echo 'Invalid backup ID' >&2; exit 2; }
backup="/backups/$backup_id"
[[ -d $backup && ! -L $backup && -d /restore-media && ! -L /restore-media ]] || { echo 'Restore mounts missing' >&2; exit 2; }
[[ -z $(ls -A /restore-media) ]] || { echo 'Restore media volume must be empty; no existing files were changed' >&2; exit 2; }
[[ $(sed -n '1p' "$backup/manifest.txt") == format_version=1 ]] || { echo 'Unsupported backup format' >&2; exit 2; }
# Do not trust a manifest to name arbitrary paths for checksum verification.
[[ $(wc -l < "$backup/SHA256SUMS") == 3 ]] || { echo 'Invalid checksum manifest' >&2; exit 2; }
for file in database.dump media.tar.gz manifest.txt; do
    [[ -f "$backup/$file" && ! -L "$backup/$file" ]] || { echo 'Invalid backup file' >&2; exit 2; }
    grep -Eq "^[a-f0-9]{64}  ${file//./\\.}$" "$backup/SHA256SUMS" || { echo 'Invalid checksum entry' >&2; exit 2; }
done
(cd "$backup" && sha256sum --check --strict SHA256SUMS)
while IFS= read -r member; do
    case "$member" in /*|../*|*/../*|*/..) echo 'Unsafe archive path' >&2; exit 2;; esac
done < <(tar --list --gzip --file "$backup/media.tar.gz")
if tar --list --verbose --gzip --file "$backup/media.tar.gz" | grep -Eq '^[lh]'; then
    echo 'Links are not accepted in the media archive' >&2; exit 2
fi
exists=$(psql --no-psqlrc --tuples-only --no-align --set=ON_ERROR_STOP=1 \
    --command "SELECT 1 FROM pg_database WHERE datname='$target'")
[[ -z $exists ]] || { echo 'Restore target already exists; no database was changed' >&2; exit 2; }
createdb --maintenance-db "$PGDATABASE" --owner "$PGUSER" "$target"
pg_restore --no-owner --no-privileges --exit-on-error --dbname "$target" "$backup/database.dump"
tar --extract --gzip --no-same-owner --no-same-permissions --file "$backup/media.tar.gz" --directory /restore-media
media_rows=$(PGDATABASE="$target" psql --no-psqlrc --tuples-only --no-align --field-separator=$'\t' \
    --set=ON_ERROR_STOP=1 --command 'SELECT storage_path,sha256 FROM ctx_media')
while IFS=$'\t' read -r stored_path checksum; do
    [[ -n $stored_path ]] || continue
    case "$stored_path" in /var/lib/korda/media/*) relative=${stored_path#/var/lib/korda/media/};;
        *) echo 'Unexpected stored media path' >&2; exit 2;; esac
    case "$relative" in ../*|*/../*|*/..) echo 'Unsafe stored media path' >&2; exit 2;; esac
    [[ -f "/restore-media/$relative" ]] || { echo 'A referenced media file is missing' >&2; exit 2; }
    [[ $(sha256sum "/restore-media/$relative" | cut -d ' ' -f 1) == "$checksum" ]] || { echo 'Media checksum mismatch' >&2; exit 2; }
done <<< "$media_rows"
chown -R 10001:10001 /restore-media
printf 'Restore drill complete in new database %s; original database and media were untouched.\n' "$target"
