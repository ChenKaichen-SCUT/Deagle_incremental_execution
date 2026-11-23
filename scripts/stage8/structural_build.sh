#!/usr/bin/env bash
set -euo pipefail
base=$(realpath "$1")
enhanced=$(realpath "$2")
new=$(realpath -m "$3")
out=$(realpath -m "$4")
project="$(cd "$(dirname "$0")/../.." && pwd)"
expected=a159f9923722646185ba8028610b2eef2618fa72
mkdir -p "$out"
if ! test -e "$new"; then
  git -C "$base" worktree add -b stage8-f0-equation "$new" "$expected"
fi
test "$(git -C "$new" branch --show-current)" = stage8-f0-equation
if test "$(git -C "$new" rev-parse HEAD)" = "$expected"; then
  python3 -B "$project/scripts/stage8/model_observer.py" "$new" "$enhanced"
  git -C "$new" add src/goto-checker/stage8_full_model.h src/goto-checker/multi_path_symex_only_checker.cpp
  GIT_AUTHOR_DATE=2026-11-23T00:00:00Z GIT_COMMITTER_DATE=2026-11-23T00:00:00Z \
    git -C "$new" -c user.name=Stage8 -c user.email=stage8@localhost commit -qm "Read-only baseline model observer"
fi
test "$(git -C "$new" rev-parse HEAD^)" = "$expected"
git -C "$new" diff --binary HEAD^ HEAD > "$out/structural.patch"
export CCACHE_BASEDIR="$new" PATH="/usr/lib/ccache:$PATH"
make -C "$new/src" -j4 cbmc.dir > "$out/structural-build.log" 2>&1 || { tail -30 "$out/structural-build.log";exit 1; }
sha256sum "$new/src/cbmc/deagle_exe"
