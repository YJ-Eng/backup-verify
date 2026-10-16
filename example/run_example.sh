#!/usr/bin/env bash
# Builds a fake backup folder, then runs manifest -> verify -> freshness -> stale -> corrupt -> report.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dir="$(mktemp -d)" || { echo "mktemp failed" >&2; exit 1; }
[ -n "$dir" ] && [ -d "$dir" ] || { echo "no temp dir" >&2; exit 1; }
trap 'rm -rf -- "$dir"' EXIT
tool() { python3 "$here/../backup_verify.py" "$@"; }
# run a command that may exit non-zero and show its exit code
show() { local rc=0; "$@" || rc=$?; echo "exit=$rc"; }

mkdir -p "$dir/databases" "$dir/filestore" "$dir/config"
echo "-- fake dump" > "$dir/databases/app.sql"
head -c 4096 /dev/zero > "$dir/filestore/blob.bin"
echo "setting=1" > "$dir/config/app.conf"

echo "== manifest";  tool manifest "$dir"
echo "== verify";    show tool verify "$dir"
echo "== freshness"; show tool freshness "$dir"
echo "== simulate a stale backup (set mtimes 40 h back)"
touch -d "40 hours ago" "$dir/databases/app.sql" "$dir/filestore/blob.bin" "$dir/config/app.conf"
show tool freshness "$dir"
echo "== simulate silent corruption (and keep it old)"
echo "oops" >> "$dir/databases/app.sql"
touch -d "40 hours ago" "$dir/databases/app.sql"
show tool verify "$dir"
echo "== report, last rsync exit 24"
show tool report "$dir" --rsync-exit 24
