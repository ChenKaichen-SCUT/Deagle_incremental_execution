"""Apply guarded observer and importer hooks to a private copy of the 11B build sources."""
from pathlib import Path
import difflib,shutil,sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'stage11b'))
from instrument import build_sources,replace

def create(tree,dest):
    build_sources(tree,dest)
    shutil.copyfile(HERE/'trace.hpp',dest/'trace.hpp')
    core=tree/'minisat-2.2.1/minisat/core'
    shutil.copyfile(core/'Solver.cc',dest/'Solver.cc')
    native_base={n:(dest/n).read_text() for n in ('Closure.cc','ClosureSolver.cc','Solver.cc','driver.cpp','epoch.hpp')}
    s=native_base['Closure.cc']
    s=replace(s,'#include "native_root.hpp"','#include "native_root.hpp"\n#include "trace.hpp"')
    for decl,key in [('closure_edget co(w2, w1, OC_NA, co_reason);',1),('closure_edget fr(r, w2, OC_NA, fr_reason);',2)]:
        # Only instrument executable definitions, never the disabled source near final_check.
        first,rest=s.split('bool closure::activate_apo',1)
        middle,last=rest.split('void closure::push_scope',1)
        assert first.count(decl)+middle.count(decl)==4
        obs=f'c11::state().infer({key},w1,r,w2); '+decl
        s=first.replace(decl,obs)+'bool closure::activate_apo'+middle.replace(decl,obs)+'void closure::push_scope'+last
    for why in ('self_cycle','atomic_order_cycle','race'):
        k=f'conflict_origin = "{why}";'
        s=replace(s,k,'c11::state().attempted(edge.from,edge.to); '+k)
    k='solver->assign_literal(~rf_lit_cand, unit_lv);'
    s=replace(s,k,'c11::state().posted=false; '+k+' if(c11::state().posted)c11::state().prevent(*this,from,to,unit_lv);')
    (dest/'Closure.cc').write_text(s)
    s=native_base['ClosureSolver.cc']
    s=replace(s,'#include "native_root.hpp"','#include "native_root.hpp"\n#include "trace.hpp"')
    for original,new in [
      ('    graph.refine_atomic_atoms();','    graph.refine_atomic_atoms();\n    c11::state().nodes(graph);'),
      ('++oc11::session().rf; cycle =','++oc11::session().rf; if(c11::state().collecting){c11::state().cause=edge.kind==OC_RF?"RF":"CO";c11::state().trigger=edge.from;c11::state().trigger_target=edge.to;} cycle ='),
      ('++oc11::session().guard; cycle =','++oc11::session().guard; if(c11::state().collecting){c11::state().cause="Guard";c11::state().trigger=n;c11::state().trigger_target=-1;} cycle ='),
      ('graph.push_scope();','graph.push_scope(); c11::state().push();'),
      ('literals_to_assign.push_back(std::make_pair(l, lv));','literals_to_assign.push_back(std::make_pair(l, lv)); if(c11::state().chains)c11::state().posted=true;'),
      ('CRef ClosureSolver::propagate()\n{','CRef ClosureSolver::propagate()\n{\n    if(c11::state().chains)c11::state().pending.clear();'),
      ('graph.pop_scope(level);','graph.pop_scope(level); c11::state().pop(level);'),
      ('confl = ca.alloc(minisat_lv, true);','confl = ca.alloc(minisat_lv, true);\n            c11::state().conflict(graph,*this,confl,minisat_lv,decisionLevel());'),
      ('learnt_clause.clear();\n            analyze','learnt_clause.clear();\n            c11::state().start();\n            auto analysis_tick=c11::state().chains?c11::now():0;\n            analyze'),
      ('analyze(confl, learnt_clause, backtrack_level);','analyze(confl, learnt_clause, backtrack_level);\n            if(analysis_tick)c11::state().analysis_ns+=c11::now()-analysis_tick;'),
      ('CRef cr = ca.alloc(learnt_clause, true);\n                learnts.push','CRef cr = ca.alloc(learnt_clause, true);\n                c11::state().learned_ref(cr,learnt_clause);\n                learnts.push'),
      ('CRef cr = ca.alloc(learnt_clause, true);\n            learnts.push','CRef cr = ca.alloc(learnt_clause, true);\n            c11::state().propagated(*this,cr,learnt_clause,decisionLevel());\n            learnts.push'),
      ('Clause& c = ca[confl];','Clause& c = ca[confl];\n        c11::state().parent(confl,c,p.x); c11::state().hit(confl,c,"analyze");'),
      ('    int index   = trail.size() - 1;','    int index   = trail.size() - 1;\n    std::set<int> proof_roots;'),
      ('            Lit q = c[j];','            Lit q = c[j];\n            if(c11::state().recording() && level(var(q))==0)proof_roots.insert(var(q));'),
      ('    int i, j;\n    out_learnt.copyTo','    c11::Key premin; if(c11::state().recording()){premin=c11::lits(out_learnt); c11::state().raw(out_learnt);}\n    int i, j;\n    out_learnt.copyTo'),
      ('    for (int j = 0; j < analyze_toclear.size(); j++)', '''    if(c11::state().recording()){
        auto &ob=c11::state();std::set<int> stop,seen_proof;
        for(int i=0;i<out_learnt.size();++i)stop.insert(var(out_learnt[i]));
        for(int x:premin)if(!stop.count(x/2))proof_roots.insert(x/2);
        std::vector<int> agenda(proof_roots.begin(),proof_roots.end());
        while(!agenda.empty() && seen_proof.size()<192){
            int v=agenda.back();agenda.pop_back();
            if(stop.count(v) || !seen_proof.insert(v).second)continue;
            int assigned=2*v+(value(v)==l_False);
            auto ref=reason(v);
            if(ref==CRef_Undef){ob.log<<"D\\t"<<ob.learn_id<<'\\t'<<assigned<<"\\tunit_or_decision\\t\\n";continue;}
            auto &why=ca[ref];ob.log<<"D\\t"<<ob.learn_id<<'\\t'<<assigned<<'\\t'<<ob.tag(ref,why)<<'\\t'<<c11::field(c11::lits(why))<<"\\n";
            for(int k=0;k<why.size();++k)if(var(why[k])!=v)agenda.push_back(var(why[k]));
        }
    }
    c11::state().finish(out_learnt);
    for (int j = 0; j < analyze_toclear.size(); j++)'''),
      ('                confl = cr;','                c11::state().hit(cr,c,"conflict"); confl = cr;'),
      ('            }else\n                uncheckedEnqueue(first, cr);','            }else {c11::state().hit(cr,c,"unit"); uncheckedEnqueue(first, cr);}'),
      ('    if(graph.use_available_info())','    if(c11::state().collecting)c11::state().cause="root_available";\n    if(graph.use_available_info())'),
    ]:s=replace(s,original,new)
    (dest/'ClosureSolver.cc').write_text(s)
    s=native_base['Solver.cc']
    s=replace(s,'using namespace Minisat;','#include "trace.hpp"\nusing namespace Minisat;')
    for fun,call in [('void Solver::removeClause(CRef cr) {','c11::state().drop(cr);'),('void Solver::garbageCollect()\n{','c11::state().gc();')]:
        s=replace(s,fun,fun+'\n    '+call)
    (dest/'Solver.cc').write_text(s)
    s=native_base['epoch.hpp']
    s=replace(s,'#include "rup.hpp"','#include "rup.hpp"\n#include "trace.hpp"')
    s=replace(s,'  int cycles() const', (HERE/'install.inc').read_text()+'\n  int cycles() const')
    (dest/'epoch.hpp').write_text(s)
    s=native_base['driver.cpp']
    s=replace(s,'#include "epoch.hpp"','#include "sealed.hpp"\n#include "epoch.hpp"')
    shutil.copyfile(HERE/'sealed.hpp',dest/'sealed.hpp')
    s=replace(s,'std::string test=argv[1];','std::string mode=argv[1]; std::string test=(mode=="B"||mode=="T"||mode=="C"||mode=="TC")?"GS":mode;')
    s=replace(s,'Plan plan(dir);','''bool dynamic=mode=="T"||mode=="C"||mode=="TC";
      c11::state().open(dir+"/worker",!phase&&dynamic,!phase&&(mode=="C"||mode=="TC"),phase&&dynamic);
      Plan plan(dir);''')
    s=replace(s,'auto loaded=s10::now();','''if(phase && dynamic){auto approved=c11::approved_stream(dir);epoch->install_dynamic(dir,mode,input->variables,approved);}
      c11::state().assumptions=c11::lits(goals);c11::state().running=true;
      auto loaded=s10::now();''')
    s=replace(s,'auto solved=s10::now();','auto solved=s10::now(); c11::state().running=false;c11::state().end();')
    s=replace(s,'metric(f,"sat_code",rc);','''metric(f,"dynamic_snapshot_ns",c11::state().collection_ns);metric(f,"instrumented_analyze_ns",c11::state().analysis_ns);
      metric(f,"proof_flush_ns",c11::state().persist_ns);metric(f,"install_ns",c11::state().install_ns);metric(f,"sat_code",rc);''')
    (dest/'driver.cpp').write_text(s)
    with (dest/'native.patch').open('w') as f:
        for name,before in native_base.items():
            f.writelines(difflib.unified_diff(before.splitlines(True),(dest/name).read_text().splitlines(True),'a/'+name,'b/'+name))
if __name__=='__main__':create(*map(Path,sys.argv[1:]))
