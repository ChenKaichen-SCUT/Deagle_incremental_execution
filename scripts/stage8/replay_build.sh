#!/usr/bin/env bash
set -euo pipefail
source_tree=$(realpath "$1")
new=$(realpath -m "$2")
role=$3
out=$(realpath -m "$4")
project="$(cd "$(dirname "$0")/../.." && pwd)"
case "$role" in baseline|enhanced) ;; *) exit 2 ;; esac
mkdir -p "$out"
if ! test -e "$new"; then git -C "$source_tree" worktree add -b "stage8-$role-stream" "$new" HEAD; fi
test "$(git -C "$new" branch --show-current)" = "stage8-$role-stream"
if test "$(git -C "$new" rev-parse HEAD)" = "$(git -C "$source_tree" rev-parse HEAD)"; then
  python3 -B - "$new" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])/'minisat-2.2.1/minisat/core/ClosureSolver.cc'
x=p.read_text()
assert x.count('  s8::first_search();')==1 and x.count('  s8::Scope s8_timer(s8::graph_load);')==1
x=x.replace('  s8::Scope s8_timer(s8::graph_load);','  s8::raw(0xfffffff2U);\n  s8::Scope s8_timer(s8::graph_load);')
record='''  if(s8::state().detail) {
    s8::raw(0xfffffff3U);s8::raw(assumptions.size());
    for(int i=0;i<assumptions.size();++i)s8::raw(assumptions[i].x);
    std::ofstream config(s8::state().out+"/s8-initial.tsv");
    config.precision(17);
    config<<nVars()<<" "<<nClauses()<<" "<<nAssigns()<<" "<<random_seed<<" "<<random_var_freq<<" "<<var_decay<<" "<<clause_decay<<" "
          <<phase_saving<<" "<<rnd_pol<<" "<<rnd_init_act<<" "<<ccmin_mode<<" "<<luby_restart<<" "<<restart_first<<" "<<restart_inc<<" "
          <<learntsize_factor<<" "<<learntsize_inc<<" "<<assumptions.size()<<std::endl;
  }
'''
x=x.replace('  s8::first_search();',record+'  s8::first_search();')
p.write_text(x)
p=Path(sys.argv[1])/'src/solvers/sat/satcheck_minisat2.cpp'
x=p.read_text()
token='solver->setPolarity(a.var_no(), value ? l_True : l_False);'
assert x.count(token)==1
p.write_text('#include "../../util/stage8_meter.h"\n'+x.replace(token,'s8::raw(0xfffffff4U); s8::raw(a.var_no()); s8::raw(Minisat::toInt(value ? l_True : l_False));\n    '+token))
PY
  git -C "$new" add minisat-2.2.1/minisat/core/ClosureSolver.cc src/solvers/sat/satcheck_minisat2.cpp
  GIT_AUTHOR_DATE=2026-11-23T00:00:00Z GIT_COMMITTER_DATE=2026-11-23T00:00:00Z \
    git -C "$new" -c user.name=Stage8 -c user.email=stage8@localhost commit -qm "Record graph insertion point and solver assumptions"
fi
test "$(git -C "$new" rev-parse HEAD^)" = "$(git -C "$source_tree" rev-parse HEAD)"
git -C "$new" diff HEAD^ HEAD > "$out/stream-$role.patch"
export CCACHE_BASEDIR="$new" PATH="/usr/lib/ccache:$PATH"
make -C "$new/src" -j4 cbmc.dir > "$out/stream-$role-build.log" 2>&1 || { tail -24 "$out/stream-$role-build.log";exit 1; }
mkdir -p "$out/driver-$role"
g++ -std=c++11 -O2 -DSATCHECK_MINISAT2 -DHAVE_MINISAT2 -D__STDC_FORMAT_MACROS -D__STDC_LIMIT_MACROS -I"$new/minisat-2.2.1" -I"$new/src" "$project/scripts/stage8/solver_replay.cpp" \
  -Wl,--start-group "$new/src/solvers/solvers.a" "$new/src/util/util.a" -Wl,--end-group -lz -lpthread -o "$out/driver-$role/solver-replay"
sha256sum "$new/src/cbmc/deagle_exe" "$out/driver-$role/solver-replay"
