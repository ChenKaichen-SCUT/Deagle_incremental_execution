#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
target=${1:?usage: build.sh deagle-baseline|deagle-work|damer-camc}
case "$target" in deagle-baseline|deagle-work|damer-camc) ;; *) exit 2 ;; esac
tree="$PWD/third_party/$target"
jobs=$(python3 -c 'import yaml; print(yaml.safe_load(open("configs/project.yaml"))["resources"]["build"]["jobs"])')
export CCACHE_DIR="$PWD/runs/stage-01/ccache" CCACHE_BASEDIR="$tree"
mkdir -p "$CCACHE_DIR"
export PATH="/usr/lib/ccache:$PATH"
ccache --max-size=4G
printf 'tree=%s commit=%s jobs=%s\n' "$target" "$(git -C "$tree" rev-parse HEAD)" "$jobs"
if [[ "$target" == damer-camc ]]; then
  cmake -S "$tree" -B "$tree/build"
  cmake --build "$tree/build" --parallel "$jobs"
else
  make -C "$tree/src" -j"$jobs" cbmc.dir
fi
