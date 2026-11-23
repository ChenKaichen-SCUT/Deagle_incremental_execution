#!/usr/bin/env bash
# Restore the exact compatibility commit and its two independent build directories.
set -euo pipefail
cd "$(dirname "$0")/../.."
base=third_party/deagle-baseline
work=third_party/deagle-work
bundle="$PWD/patches/deagle-stage01.bundle"
commit=$(python3 -c 'import json; print(json.load(open("configs/toolchain.lock.json"))["repositories"]["deagle"]["compatibility_commit"])')
git -C "$base" bundle verify "$bundle"
git -C "$base" fetch --no-tags "$bundle" refs/heads/stage1-baseline
test "$(git -C "$base" rev-parse FETCH_HEAD)" = "$commit"
if git -C "$base" show-ref --verify --quiet refs/heads/stage1-baseline; then
  git -C "$base" switch stage1-baseline
  git -C "$base" merge --ff-only "$commit"
else
  git -C "$base" switch -c stage1-baseline "$commit"
fi
if test -e "$work/.git"; then
  test "$(git -C "$work" branch --show-current)" = incdeagle-work
  git -C "$work" merge --ff-only "$commit"
else
  git -C "$base" worktree add -b incdeagle-work ../deagle-work "$commit"
fi
for tree in "$base" "$work"; do
  test "$(git -C "$tree" rev-parse HEAD)" = "$commit"
  git -C "$tree" diff --quiet HEAD --
done
