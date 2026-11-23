#!/usr/bin/env bash
# Install the stage 4 commit alongside the independent baseline and Stage 3.
set -euo pipefail
cd "$(dirname "$0")/../.."
work=third_party/deagle-stage4
prior=third_party/deagle-work
bundle="$PWD/patches/deagle-stage04.bundle"
field() { python3 -c 'import json,sys;print(json.load(open("configs/stage04.lock.json"))[sys.argv[1]])' "$1"; }
test "$(git -C "$prior" rev-parse HEAD)" = "$(field parent_commit)"
echo "$(field bundle_sha256)  $bundle" | sha256sum -c -
if ! test -e "$work"; then
  git clone --quiet --no-checkout --depth 1 --branch incdeagle-work "file://$PWD/$prior" "$work"
  git -C "$work" switch -c incdeagle-stage4 "$(field parent_commit)"
fi
test "$(git -C "$work" branch --show-current)" = incdeagle-stage4
git -C "$work" diff --quiet HEAD --
git -C "$work" bundle verify "$bundle"
git -C "$work" fetch --no-tags "$bundle" refs/heads/incdeagle-stage4
test "$(git -C "$work" rev-parse FETCH_HEAD)" = "$(field development_commit)"
git -C "$work" merge --ff-only FETCH_HEAD
test "$(git -C "$work" rev-parse HEAD^{tree})" = "$(field development_tree)"
