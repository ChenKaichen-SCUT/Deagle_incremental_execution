#!/usr/bin/env bash
# OUT must be fresh. BASELINE_ROOT contains the frozen upstream, D1 observer and D4.1 reference products.
set -euo pipefail
tree=$(cd "$(dirname "$0")/../.." && pwd)
b=$(realpath "${BASELINE_ROOT:?directory containing stock-build, rebuild-d1 and runs}")
o=$(realpath -m "${1:?new output directory}")
mkdir "$o"
cd "$tree"; export PATH=/usr/bin:/bin LC_ALL=C
s=dependency-reuse/scripts
d41="$b/runs/d41"
make -C src -j8 cbmc.dir > "$o/build.log" 2>&1
bash "$s/build42.sh" "$tree" "$o/tools"
python3 "$s/identity42.py" "$d41/matrix" "$d41/final-audit" "$d41/tools" "$o/controls"
python3 "$s/fixed42.py" "$d41/release" "$d41/tools" "$o/historical"
bash dependency-reuse/tests/d41/build.sh "$tree" "$b/rebuild-d1/final" "$b/runs/d3/observer/ClosureSolver.o" "$o/tests"
bash dependency-reuse/tests/d42/check.sh "$tree" "$o/tools" "$o/tests" "$o/micro"
mkdir "$o/observer"
cp dependency-reuse/bench/fib-snapshot-11/old/program.i "$o/observer/program.i"
(cd "$o/observer"; taskset -c 0 "$b/runs/d3/observer/deagle_exe" --function main --deagle-closure --mm sc --32 --unwind 25 --unwinding-assertions --trace --json-ui program.i > stdout 2> stderr)
python3 "$s/run_d42.py" functional "$tree/src/cbmc/deagle_exe" "$o/tools" "$o/functional"
python3 "$s/audit_d42.py" "$o/functional" "$d41/matrix" "$d41/final-audit" "$o/controls" "$o/historical" "$o/observer" "$o/tools" "$o/tests" "$o/micro" "$o/audit"
python3 "$s/clock42.py" "$b/runs/d4/stock-timer/deagle_exe" "$o/functional" "$o/clocks"
python3 "$s/run_d42.py" performance "$tree/src/cbmc/deagle_exe" "$o/tools" "$o/performance" --gate "$o/audit/gate.json"
python3 "$s/summarize42.py" "$o/functional" "$o/performance" "$o/audit" "$o/clocks" "$b/runs/d4/release-runs" "$o/report"
