#!/usr/bin/env bash
# Install the frozen Stage 5 commit alongside Stage 4 and the independent baseline.
set -euo pipefail
cd "$(dirname "$0")/../.."
work=third_party/deagle-stage5
prior=third_party/deagle-stage4
bundle="$PWD/patches/deagle-stage05.bundle"
field() { python3 -c 'import json,sys;print(json.load(open("configs/stage05.lock.json"))[sys.argv[1]])' "$1"; }
test "$(git -C "$prior" rev-parse HEAD)" = "$(field parent_commit)"
echo "$(field bundle_sha256)  $bundle" | sha256sum -c -
if ! test -e "$work"; then
  git clone --quiet --no-checkout --depth 1 --branch incdeagle-stage4 "file://$PWD/$prior" "$work"
  git -C "$work" switch -c incdeagle-stage5 "$(field parent_commit)"
fi
test "$(git -C "$work" branch --show-current)" = incdeagle-stage5
git -C "$work" diff --quiet HEAD --
git -C "$work" bundle verify "$bundle"
git -C "$work" fetch --no-tags "$bundle" refs/heads/incdeagle-stage5
test "$(git -C "$work" rev-parse FETCH_HEAD)" = "$(field development_commit)"
git -C "$work" merge --ff-only FETCH_HEAD
test "$(git -C "$work" rev-parse HEAD^{tree})" = "$(field development_tree)"
