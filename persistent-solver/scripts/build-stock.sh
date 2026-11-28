#!/usr/bin/env bash
# Usage: bash build-stock.sh UPSTREAM_REPO NEW_DETACHED_TREE NEW_LOG_DIRECTORY
set -euo pipefail
test "$#" = 3
repo=$(realpath "$1")
stock=$(realpath -m "$2")
e=$(realpath -m "$3")
test ! -e "$stock" && test ! -e "$e" && test "$stock" != "$e"
sha=d8c79eaba5df03b1a013dc6ffbb3a1e249485c1e
git -C "$repo" worktree add --quiet --detach "$stock" "$sha"
mkdir "$e"
cd "$stock"
git status --porcelain=v1 > "$e/pristine.txt"
test ! -s "$e/pristine.txt" && test ! -e src/cbmc/deagle_exe
export LC_ALL=C PATH=/usr/bin:/bin
date -u +%FT%TZ > "$e/start.utc"
/usr/bin/time -v -o "$e/build-time.txt" make -C src -j12 cbmc.dir > "$e/build.log" 2>&1
date -u +%FT%TZ > "$e/end.utc"
sha256sum src/cbmc/deagle_exe
git diff --exit-code HEAD --
