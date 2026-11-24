"""Apply the stage 10 diagnostic patch only to the pinned native stream source."""
import shutil
import subprocess
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
PIN='a2ba2f01fcc8dc83261f614039141017fb846178'
CORE='minisat-2.2.1/minisat/core/'


def apply(tree):
    if subprocess.check_output(['git','-C',tree,'rev-parse','HEAD'],text=True).strip()!=PIN:
        raise ValueError('unexpected native parent')
    def edit(path,before,after):
        p=tree/path
        text=p.read_text()
        if text.count(before)!=1:raise ValueError(f'{path}: missing or ambiguous source anchor {before!r}')
        p.write_text(text.replace(before,after))
    for n in ('telemetry.h','bridge.inc','hooks.h'):
        shutil.copyfile(HERE/n,tree/'src/util'/('stage10_'+n))
    solver=CORE+'Solver.cc';closure=CORE+'ClosureSolver.cc';header=CORE+'ClosureSolver.h'
    edit(header,'    closure graph;','    friend class Stage10Epoch;\n    closure graph;')
    edit(CORE+'Solver.h','class Solver {\npublic:', 'class Solver {\n    friend class Stage10Epoch;\npublic:')
    edit(solver,'#include "../../../src/util/stage8_meter.h"', '#include "../../../src/util/stage8_meter.h"\n#include "../../../src/util/stage10_hooks.h"')
    edit(solver,'CRef cr = ca.alloc(ps, false);','''CRef cr = s10::take ? s10::take(this,ps) : CRef_Undef;
        if(cr==CRef_Undef) cr=ca.alloc(ps,false);
        else {
          Clause &held=ca[cr];
          if(held.mark() || held.learnt() || held.size()!=ps.size()) throw std::runtime_error("invalid retained Clause");
          for(int j=0;j<ps.size();++j) held[j]=ps[j];
        }
        if(s10::born) s10::born(this,ps,cr);''')
    edit(closure,'#include "ClosureSolver.h"', '#include "ClosureSolver.h"\n#include "../../../src/util/stage10_telemetry.h"\n#include "../../../src/util/stage10_hooks.h"\nextern std::vector<std::string> write_order;\nnamespace s10 { Take take=nullptr; Born born=nullptr; }')
    edit(closure,'  s8::first_search();','''  s8::first_search();
#include "../../../src/util/stage10_bridge.inc"
  s10::start_trace();
  struct TraceEnd { ~TraceEnd(){ s10::close_trace(); } } trace_end;
  s10::mark("solve_start");''')
    edit(closure,'    cancelUntil(0);\n    return status;', '    cancelUntil(0);\n    s10::mark("solve_end");\n    return status;')
    edit(closure,'            conflicts++; conflictC++;','            conflicts++; conflictC++;\n            s10::collision(decisionLevel(),ca[confl]);')
    edit(closure,'            if(s8::state().detail && s8::state().first_decisions<32)', '            s10::choice(decisionLevel(),next.x);\n            if(s8::state().detail && s8::state().first_decisions<32)')
    theory='src/goto-checker/theory_lemma.cpp'
    edit(theory,'if(!root || !helper) return;', 'bool capture=std::getenv("S10_DIR")!=nullptr;\n  if(!capture && (!root || !helper)) return;')
    edit(theory,'bool old=dir==std::string(root)+"/old";','bool old=!capture && dir==std::string(root)+"/old";')
    edit(theory,'if(!old && dir!=std::string(root)+"/candidate") return;', 'if(!capture && !old && dir!=std::string(root)+"/candidate") return;')
    edit(theory,'write_json(dir+"/native-bindings.json",graph);','write_json(dir+"/native-bindings.json",graph);\n  if(capture) return;')
    bmc='src/goto-checker/bmc_util.cpp'
    edit(bmc,'#include <solvers/sat/satcheck_minisat2.h>', '#include <solvers/sat/satcheck_minisat2.h>\n#include <solvers/flattening/boolbv.h>\n#include "../util/stage10_telemetry.h"')
    edit(bmc,'  s8::Scope s8_timer(s8::encode_graph);','  s10::mark("model_ready");\n  s8::Scope s8_timer(s8::encode_graph);')
    edit(bmc,'    prepare_order_lemma_cache(deagle_closure_solver,', '''    if(std::getenv("S10_DIR")) {
      const auto &bv=dynamic_cast<const boolbvt&>(decision_procedure);
      std::ofstream tab(s10::directory()+"/bits.tsv");
      for(const auto &row:bv.get_map().get_mapping()) {
        const auto &t=row.second.type;
        tab<<id2string(row.first)<<"\\t"<<id2string(t.id())<<"\\t"<<id2string(t.get(ID_width));
        for(const auto &l:row.second.literal_map) tab<<"\\t"<<Minisat::mkLit(l.var_no(),l.sign()).x;
        tab<<"\\n";
      }
    }
    prepare_order_lemma_cache(deagle_closure_solver,'''.replace('"\t"','"\\t"').replace('"\n"','"\\n"'))
    edit(bmc,'  decision_proceduret::resultt dec_result = property_decider.solve();',
        '  decision_proceduret::resultt dec_result = property_decider.solve();\n  s10::mark("decider_return");')
    adapter='src/solvers/sat/satcheck_minisat2.cpp'
    edit(adapter,'#include "../../util/stage8_meter.h"', '#include "../../util/stage8_meter.h"\n#include "../../util/stage10_telemetry.h"')
    # Use RAII around allocation without modifying solver construction or ownership.
    factory='src/goto-checker/solver_factory.cpp'
    text=(tree/factory).read_text()
    signature='std::unique_ptr<solver_factoryt::solvert> solver_factoryt::get_solver()'
    edit(factory,signature+'\n{','#include "../util/stage10_telemetry.h"\n'+signature+'\n{\n  s10::mark("factory_begin");\n  struct End { ~End(){s10::mark("factory_end");} } end;')

def finish(tree):
    core=tree/CORE/'ClosureSolver.cc'
    shutil.copyfile(HERE/'native_stats.inc',tree/'src/util/stage10_native_stats.inc')
    t=core.read_text()
    if 'stage10_native_stats.inc' not in t:
        include='#include "../../../src/util/stage10_native_stats.inc"'
        for anchor in ('s10::mark("solve_start");','s10::mark("solve_end");'):
            assert t.count(anchor)==1
            t=t.replace(anchor,anchor+'\n'+include)
        core.write_text(t)

if __name__=='__main__':
    tree=Path(sys.argv[1]).resolve()
    if len(sys.argv)==2:apply(tree)
    finish(tree)
