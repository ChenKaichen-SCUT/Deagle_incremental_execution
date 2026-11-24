#!/usr/bin/env bash
# The arguments are the prepared stage-10 tree, stage-7 sources/, the SV-COMP pilot project, and a new output directory.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd); project=$(realpath "$here/../..")
native=$(realpath "$1"); sources=$(realpath "$2"); pilot=$(realpath "$3"); out=$(realpath -m "$4")
mkdir -p "$out"; test -z "$(ls -A "$out")"
ln -s "$native" "$out/native"; mkdir -p "$out/build" "$out/audit-build" "$out/controls"
export LC_ALL=C PYTHONDONTWRITEBYTECODE=1
bash "$here/build.sh" "$native" "$out/build" > "$out/build/build.log" 2>&1
p=(python3 -B "$here/experiments.py" "$native/src/cbmc/deagle_exe" "$out/build/worker" "$out/build/rupcheck" "$sources" "$pilot")
"${p[@]}" "$out/formal" --repeats 5 > "$out/formal.log"
for name in fib_updates_8 lock12 ticket56-reviewed; do
  for i in 6 7; do
    if [[ $i == 6 ]]; then modes=(TC C T B F); else modes=(B T C TC F); fi
    for mode in "${modes[@]}"; do "${p[@]}" "$out/formal" --one "$name" "$i" "$mode"; done
  done
done > "$out/extra.log"
mkdir -p "$out/reference-build"
bash "$project/scripts/stage11b/build.sh" "$native" "$out/reference-build" > "$out/reference-build/build.log" 2>&1
flags=(-std=c++11 -O2 -Wno-literal-suffix -DSATCHECK_MINISAT2 -DHAVE_MINISAT2 -D__STDC_FORMAT_MACROS -D__STDC_LIMIT_MACROS -I"$native/minisat-2.2.1" -I"$native/src" -I"$native/minisat-2.2.1/minisat/core" -I"$out/build/src")
g++ "${flags[@]}" "$here/co_control.cpp" "$out/build/"{Closure,ClosureSolver,Solver}.o -Wl,--start-group "$native/src/solvers/solvers.a" "$native/src/util/util.a" -Wl,--end-group -lz -lpthread -o "$out/build/co-control"
python3 -B "$here/negative.py" "$out/formal" "$out/controls/negative" "$out/reference-build/worker" "$out/build/worker" "$out/build/co-control"
python3 -B "$project/scripts/stage11b/multiquery.py" "$out" "$pilot" "$out/arithmetic"
bash "$here/build.sh" "$native" "$out/audit-build" --counters > "$out/audit-build/build.log" 2>&1
python3 -B "$here/lifecycle.py" replay "$out/formal" "$out/audit-build/worker" "$out/lifecycle"
for name in batch_total batch_retained; do
  "${p[@]}" "$out/mechanism" --one "$name" 0 stock
  "${p[@]}" "$out/mechanism" --one "$name" 1 T
done
{ uname -srmo; nproc; awk '/MemTotal/ {print}' /proc/meminfo; g++ --version | head -1; python3 --version; } > "$out/controls/host.txt"
python3 -B "$here/archive.py" "$out" "$out/export"
python3 -B "$here/legacy.py" "$out/export/stage5-regression.json"
python3 -B "$project/scripts/stage11b/weak_controls.py" "$project/reports/evidence/stage-11b/panel" "$out/export/weak-sc.json"
python3 -B "$here/summary.py" "$out/export"
python3 -B "$here/inventory.py" "$out/export"
python3 -B "$here/original.py" "$out/formal" "${F0:-$project/third_party/deagle-baseline/src/cbmc/deagle_exe}" "$out/export"
python3 -B "$here/tables.py" "$out/export"
python3 -B "$here/check_evidence.py" "$out/export" --record
python3 -B "$here/verify_sources.py" "$native" "$out/export"
