#!/usr/bin/env bash
# Run from any directory in WSL/Linux, with two unused destination paths.
set -euo pipefail
[[ $# == 2 ]] || { echo "usage: $0 NEW_STOCK_TREE NEW_BUILD_EVIDENCE" >&2; exit 2; }
root=$(cd "$(dirname "$0")/../.." && pwd)
stock=$(realpath -m "$1")
evidence=$(realpath -m "$2")
commit=d8c79eaba5df03b1a013dc6ffbb3a1e249485c1e
[[ ! -e "$stock" && ! -e "$evidence" && "$stock" != "$evidence" ]]
[[ $(git -C "$root" cat-file -t "$commit") == commit ]]
git -C "$root" worktree add --detach "$stock" "$commit"
mkdir -p "$evidence"
cd "$stock"
test ! -e src/cbmc/deagle_exe
git diff --exit-code HEAD --
date -u '+%FT%TZ' > "$evidence/start.utc"
export LC_ALL=C PATH=/usr/bin:/bin
/usr/bin/time -v -o "$evidence/time.txt" make -C src -j12 cbmc.dir >"$evidence/build.log" 2>&1
date -u '+%FT%TZ' > "$evidence/end.utc"
python3 "$root/dependency-reuse/scripts/lock_build.py" "$stock" "$evidence"
