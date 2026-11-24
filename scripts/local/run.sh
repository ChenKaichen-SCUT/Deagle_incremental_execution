#!/usr/bin/env bash
set -euo pipefail
project=$(cd "$(dirname "$0")/../.." && pwd)
runtime=${DEAGLE_RUNTIME:-$HOME/runtime}
build=${DEAGLE_BUILD:-$HOME/build-11c}
jobs=${DEAGLE_RUNS:-$HOME/deagle-runs}
export LC_ALL=C PYTHONDONTWRITEBYTECODE=1
action=${1:-doctor}
if [[ $# -gt 0 ]]; then shift; fi
case "$action" in
  restore)
    exec python3 -B "$project/scripts/local/restore.py" "$runtime" ;;
  build)
    mkdir -p "$build"
    exec bash "$project/scripts/stage11c/build.sh" "$runtime/native" "$build" ;;
  doctor)
    python3 -B "$project/scripts/local/restore.py" "$runtime" --check
    for executable in worker rupcheck native-contract; do test -x "$build/$executable"; done
    gcc -dumpfullversion
    python3 --version
    exec python3 -B "$project/scripts/stage11c/verify_sources.py" "$runtime/native" "$project/reports/evidence/stage-11c" ;;
  check)
    python3 -B "$project/scripts/stage11c/seal.py"
    exec python3 -B "$project/scripts/stage11c/check_evidence.py" "$project/reports/evidence/stage-11c" ;;
  verify)
    flags=()
    for arg in "$@"; do
      if [[ $arg =~ ^[A-Za-z]:[\\/] ]]; then
        arg=$(wslpath -u "$arg")
      elif [[ $arg != -* && $arg == *\\* ]]; then
        converted=${arg//\\//}
        if [[ -e $converted ]]; then arg=$converted; fi
      fi
      flags+=("$arg")
    done
    exec bash "$project/scripts/local/native-root.sh" "$runtime/native/src/cbmc/deagle_exe" "${flags[@]}" ;;
  shell)
    export NATIVE="$runtime/native" SOURCES="$runtime/sources" F0="$runtime/baseline/src/cbmc/deagle_exe"
    export DEAGLE_WORKER="$build/worker"
    exec bash -i ;;
  replay)
    source_project=${DEAGLE_LINUX_PROJECT:-$HOME/project}
    export PATH="$project/scripts/local/user-bin:$PATH"
    cd "$source_project"
    exec .venv/bin/python -B -m incdeagle.cli replay-pair --check-model --case "${1:-cases/batch_total/task.yaml}" ;;
  smoke|full)
    mkdir -p "$jobs"
    out=$(mktemp -d "$jobs/$action-XXXXXXXX")
    echo "Local output: $out"
    if [[ $action == full ]]; then
      export F0="$runtime/baseline/src/cbmc/deagle_exe"
      export PATH="$project/scripts/local/control-bin:$PATH"
      bash "$project/scripts/local/native-root.sh" bash "$project/scripts/stage11c/reproduce.sh" "$runtime/native" "$runtime/sources" "$project" "$out"
      exec python3 -B "$project/scripts/local/verify_full.py" "$out"
    fi
    args=(python3 -B "$project/scripts/stage11c/experiments.py" "$runtime/native/src/cbmc/deagle_exe"
          "$build/worker" "$build/rupcheck" "$runtime/sources" "$project" "$out/formal")
    for case in fib_updates_8 lock12 ticket56-reviewed; do
      for mode in stock F TC; do
        rep=1; if [[ $mode == stock ]]; then rep=0; fi
        "${args[@]}" --one "$case" "$rep" "$mode"
      done
    done
    python3 -B "$project/scripts/local/verify_smoke.py" "$out"
    ;;
  *) echo 'Expected restore, build, doctor, check, verify, replay, smoke, full or shell.' >&2; exit 2 ;;
esac
