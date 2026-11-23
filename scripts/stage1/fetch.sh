#!/usr/bin/env bash
# Fetch the recorded commit, or import a previously verified Git bundle for it.
set -euo pipefail
cd "$(dirname "$0")/../.."
tool=${1:?usage: fetch.sh TOOL [BUNDLE]}
readarray -t fields < <(python3 - "$tool" <<'PY'
import json, sys
row = json.load(open("configs/toolchain.lock.json"))["repositories"][sys.argv[1]]
print(row["url"], row["commit"], row["checkouts"][0], sep="\n")
print(row.get("compatibility_commit", ""))
PY
)
url=${fields[0]} sha=${fields[1]} dir=${fields[2]}
[[ "$sha" =~ ^[0-9a-f]{40}$ ]]
bundle=""
if [[ -n ${2:-} ]]; then bundle=$(realpath "$2"); fi
if ! test -d "$dir/.git"; then
  mkdir -p "$dir"
  git init -q "$dir"
  git -C "$dir" remote add origin "$url.git"
fi
test "$(git -C "$dir" remote get-url origin)" = "$url.git"
if head=$(git -C "$dir" rev-parse --verify HEAD 2>/dev/null); then
  if [[ "$head" == "$sha" || "$head" == "${fields[3]:-}" ]]; then
    git -C "$dir" show -s --format='%H %T %s' HEAD
    exit 0
  fi
  echo "Existing checkout differs from the lock: $dir ($head)" >&2
  exit 1
fi
if ! git -C "$dir" cat-file -e "$sha^{commit}" 2>/dev/null; then
  if [[ -n "$bundle" ]]; then
    git -C "$dir" bundle verify "$bundle"
    git -C "$dir" fetch "$bundle" "$sha"
  else
    GIT_TERMINAL_PROMPT=0 timeout 150 git -C "$dir" -c http.lowSpeedLimit=1024 -c http.lowSpeedTime=18 fetch --depth=1 --no-tags origin "$sha"
  fi
fi
git -C "$dir" checkout --detach "$sha"
test "$(git -C "$dir" rev-parse HEAD)" = "$sha"
git -C "$dir" show -s --format='%H %T %s' HEAD
