#!/usr/bin/env bash
# After stage 1 preparation, install the observation commit in the development tree.
set -euo pipefail
cd "$(dirname "$0")/../.."
w=third_party/deagle-work
b=third_party/deagle-baseline
lock=configs/stage03.lock.json
field() { python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$lock" "$1"; }
test "$(git -C "$b" rev-parse HEAD)" = "$(field compatibility_commit)"
test "$(git -C "$w" branch --show-current)" = incdeagle-work
git -C "$w" diff --quiet HEAD --
bundle="$PWD/patches/deagle-stage03.bundle"
echo "$(field bundle_sha256)  $bundle" | sha256sum -c -
git -C "$w" bundle verify "$bundle"
git -C "$w" fetch --no-tags "$bundle" refs/heads/incdeagle-work
test "$(git -C "$w" rev-parse FETCH_HEAD)" = "$(field development_commit)"
git -C "$w" merge --ff-only FETCH_HEAD
test "$(git -C "$w" rev-parse HEAD)" = "$(field development_commit)"
