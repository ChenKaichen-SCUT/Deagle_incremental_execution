#!/usr/bin/env bash
# Rebuild the generated thin archive in Makefile order on both upgraded and fresh trees.
set -euo pipefail
cd "$(dirname "$0")/../.."
work=third_party/deagle-work
run=runs/stage-03
mkdir -p "$run"
exec 9>"$run/development-build.lock"
flock 9
expected=$(python3 -c 'import json;print(json.load(open("configs/stage03.lock.json"))["development_commit"])')
test "$(git -C "$work" rev-parse HEAD)" = "$expected"
git -C "$work" diff --quiet HEAD --
archive="$work/src/goto-symex/goto-symex.a"
backup=$(mktemp -d "$run/relink.XXXXXX")
if test -f "$archive"; then
  mv -- "$archive" "$backup/previous.a"
fi
if bash scripts/stage1/build.sh deagle-work; then
  if test -f "$backup/previous.a"; then rm -- "$backup/previous.a"; fi
  rmdir -- "$backup"
else
  rc=$?
  if test -f "$backup/previous.a"; then mv -f -- "$backup/previous.a" "$archive"; fi
  rmdir -- "$backup"
  exit "$rc"
fi
sha256sum "$work/src/cbmc/deagle_exe"
