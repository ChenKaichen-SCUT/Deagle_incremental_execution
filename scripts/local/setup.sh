#!/usr/bin/env bash
# Run as the ordinary Linux experiment user.
set -euo pipefail
project=$(cd "$(dirname "$0")/../.." && pwd)
runtime=${DEAGLE_RUNTIME:-$HOME/runtime}
linux_project=${DEAGLE_LINUX_PROJECT:-$HOME/project}
cache=${DEAGLE_LOCAL_CACHE:-$project/runs/local-runtime/packages}
export LC_ALL=C PYTHONDONTWRITEBYTECODE=1
upstream=https://github.com/ChenKaichen-SCUT/Deagle_incremental_execution.git
python3 -B "$project/scripts/local/restore.py" "$runtime"
bash "$project/scripts/local/run.sh" build
editable=${DEAGLE_EDITABLE_SOURCE:-$HOME/native-source-11c}
if [[ ! -e $editable ]]; then
  python3 -B "$project/scripts/local/source_snapshot.py" "$runtime" "${DEAGLE_BUILD:-$HOME/build-11c}" "$editable"
  test "$(git -C "$editable" rev-parse HEAD)" = 74e652ea7b76ec4e5d3fd5db40cf95784dbf600d
fi
if [[ -d $editable/.git ]] && ! git -C "$editable" remote get-url origin >/dev/null 2>&1; then
  git -C "$editable" remote add origin "$upstream"
fi
if [[ -d $editable/.git ]] && ! grep -Fxq '/local-build/' "$editable/.git/info/exclude"; then
  printf '\n/local-build/\n' >> "$editable/.git/info/exclude"
fi
args=()
if [[ -f $cache/mini-wheels.tar ]]; then args=(--wheel-tar "$cache/mini-wheels.tar"); fi
python3 -B "$project/scripts/local/mini.py" "$runtime" "${args[@]}"
if [[ ! -d $linux_project/.git ]]; then
  GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0="$project" \
    git clone --no-local --single-branch --branch local-runtime-11c "$project" "$linux_project"
  git -C "$linux_project" remote rename origin windows
  git -C "$linux_project" remote add origin "$upstream"
fi
args=()
if [[ -f $cache/tool-sources.tar.gz ]]; then args=(--reference-archive "$cache/tool-sources.tar.gz"); fi
python3 -B "$project/scripts/local/link_history.py" "$linux_project" "$runtime" "${args[@]}"
