#!/usr/bin/env bash
# Build the independent full baseline and the final native branch in a clean project clone.
# An optional Git bundle supplies the pinned upstream commit for an offline rebuild.
set -euo pipefail
cd "$(dirname "$0")/../.."
python3 -B scripts/init_workspace.py
bash scripts/stage1/fetch.sh deagle "$@"
if ! test -d third_party/deagle-work/.git && ! test -f third_party/deagle-work/.git; then
  bash scripts/stage1/prepare_deagle.sh
fi
bash scripts/stage1/build.sh deagle-baseline
bash scripts/stage3/prepare_deagle.sh
bash scripts/stage4/prepare_deagle.sh
bash scripts/stage5/prepare_deagle.sh
bash scripts/stage5/build.sh
python3 -B -m incdeagle.cli doctor
