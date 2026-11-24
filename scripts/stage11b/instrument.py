"""Generate the small edits against the frozen stage-10 native core and worker."""
import argparse
from pathlib import Path
import shutil

def replace(src,old,new):
    if src.count(old)!=1:
        raise ValueError("unexpected upstream context: "+old[:85])
    return src.replace(old,new)

def build_sources(tree,dest):
    here=Path(__file__).resolve().parent
    base=here.parent/'stage10'
    core=tree/'minisat-2.2.1/minisat/core'
    dest.mkdir(parents=True,exist_ok=True)
    for n in ('closure_delta.hpp','native_root.hpp','rup.hpp'):
        shutil.copyfile(here/n,dest/n)
    for n in ('input.hpp','repeat_graph.hpp'):
        shutil.copyfile(base/n,dest/n)
    for n in ('Closure.cc','ClosureSolver.cc'):
        s=(core/n).read_text()
        anchor='using namespace Minisat;'
        s=replace(s,anchor,'#include "native_root.hpp"\n'+anchor)
        if n=='Closure.cc':
            anchor='if(need_closure)\n        {'
            s=replace(s,anchor,'''int cached = -1;
        if(need_closure && kind==OC_PO && reason.empty())
            cached=oc11::session().join(*this,from_rep,to_rep,
                [this](int a,int b){return has_edge(a,b);},
                [this](int a,int b){
                    closure_edget inferred(a,b,OC_NA,empty_lv);
                    return activate_directed_edge(inferred,false);
                });
        if(cached==1)return true;
        if(need_closure && cached<0)
        {''')
        else:
            anchor='    for(auto pair: po_table)'
            s=replace(s,anchor,'''    auto &stage11 = oc11::session();
    stage11.prepare(graph,po_table,apo_table,!race_table.empty());
    stage11.static_po=stage11.enabled;
'''+anchor)
            s=replace(s,'    // for(auto pair: ws_table)','    stage11.static_po=false;\n    // for(auto pair: ws_table)')
            for a,b in [('graph.push_scope();','++oc11::session().push;'),('graph.pop_scope(level);','++oc11::session().pop;'),
                        ('cycle = graph.light_guard(n);','++oc11::session().guard;'),
                        ('cycle = graph.activate_edge(edge.from, edge.to, edge.kind, edge.reason);','if(edge.kind==OC_RF)++oc11::session().rf;'),
                        ('Var var12 = newVar(), var21 = newVar();','++oc11::session().co;')]:
                # Wrap one-line if bodies together, preserving scoping (var12 is used in the same block).
                s=replace(s,a, (b+'\n        '+a) if a.startswith('Var ') else '{'+b+' '+a+'}')
        (dest/n).write_text(s)
    e=(base/'epoch.hpp').read_text()
    e=replace(e,'#include <new>','#include <new>\n#include "rup.hpp"')
    e=replace(e,'std::map<CRef,Key> original;','std::map<CRef,Key> original;\n  std::map<int,int> rebind;')
    e=replace(e,'void switch_version(const std::set<int> &confirmed,const session10::Input &next){',
                'void switch_version(const std::set<int> &confirmed,const session10::Input &next,const std::map<int,int> &mapping){\n    rebind=mapping;')
    e=replace(e,'if(it==original.end() || !candidates.count(it->second))continue;', '''if(it==original.end())continue;
      Key remapped;
      for(int lit:it->second){
        auto target=rebind.find(lit/2);
        if(target==rebind.end()){remapped.clear();break;}
        remapped.push_back(target->second^(lit&1));
      }
      std::sort(remapped.begin(),remapped.end());
      if(remapped.empty() || !candidates.count(remapped))continue;''')
    e=replace(e,'available[it->second].push_back(cr);','available[remapped].push_back(cr);')
    e=replace(e,'session10::key(physical)==k','session10::key(physical)==e.original.at(cr) && physical.size()==ps.size()')
    e=replace(e,'e.used.emplace_back(cr,k);','for(int i=0;i<ps.size();++i)physical[i]=ps[i];\n    e.used.emplace_back(cr,k);')
    e=replace(e,'  int cycles() const', '''  size_t proved=0,unmapped=0,refused=0,unchecked=0,rup_work=0;
  void restore_learning(const session10::Input &next,const std::string &dir){
    std::vector<Key> formula;
    for(const auto &op:next.ops)if(op.tag==session10::ClauseOp)formula.push_back(op.payload);
    std::ofstream cert(dir+"/worker/rup.tsv");
    for(size_t i=0;i<learnt_seal.size();){
      int cr=learnt_seal.at(i++),n=learnt_seal.at(i++);Key key;
      for(int j=0;j<n;++j){
        int lit=learnt_seal.at(i++);auto target=rebind.find(lit/2);
        if(target!=rebind.end())key.push_back(target->second^(lit&1));
      }
      if(int(key.size())!=n){++unmapped;continue;}
      if(key.size()>12 || proved+refused>=32 || rup_work>=300000){++unchecked;continue;}
      std::vector<size_t> proof;
      if(!oc11::rup(next.variables,formula,key,proof,rup_work,300000)){++refused;continue;}
      vec<Lit> clause;for(int x:key)clause.push(session10::literal(x));
      s.addClause_(clause);++proved;cert<<cr;
      for(int x:key)cert<<" "<<x;
      cert<<" |";for(auto p:proof)cert<<" "<<p;cert<<"\\n";
    }
  }
  int cycles() const''')
    (dest/'epoch.hpp').write_text(e)
    s=(base/'driver.cpp').read_text()
    s=replace(s,'#include "epoch.hpp"','#include "epoch.hpp"\n#include "native_root.hpp"')
    s=replace(s,'std::set<int> vars;','std::set<int> vars;\n  std::map<int,int> mapping;')
    s=replace(s,'int v;while(in>>v){require(v>=0 && vars.insert(v).second,"invalid or duplicated bound variable");}',
        '''int v,raw;while(in>>v){require(bool(in>>raw) && v>=0 && raw>=0 && vars.insert(raw/2).second && mapping.emplace(v,raw).second,"invalid signed bijection");}''')
    s=replace(s,'bool keep=phase && verdict=="keep";', '''bool keep=phase && verdict=="keep" && (test=="S" || test=="GS" || test=="damage-learning");
      oc11::session().open(dir,phase && verdict!="refuse_damaged_learning" && (test=="G" || test=="GS"));
      ::write_order.clear();''')
    s=replace(s,'epoch->switch_version(plan.vars,*input)','epoch->switch_version(plan.vars,*input,plan.mapping)')
    s=replace(s,'if(!phase)epoch->register_old(plan.vars);','if(!phase && (test=="S" || test=="GS" || test=="damage-learning"))epoch->register_old(plan.vars);')
    s=replace(s,'if(!phase)epoch->seal();','if(!phase)epoch->seal();\n      oc11::session().report();')
    s=replace(s,'auto loaded=s10::now();','auto original_end=s10::now();\n      if(keep)epoch->restore_learning(*input,dir);\n      auto loaded=s10::now();')
    s=replace(s,'metric(f,"sat_code",rc);', '''metric(f,"rup_ns",loaded-original_end);metric(f,"rup_proved",epoch->proved);
      metric(f,"rup_unmapped",epoch->unmapped);metric(f,"rup_unproved",epoch->refused);
      metric(f,"rup_unchecked",epoch->unchecked);metric(f,"rup_work",epoch->rup_work);
      metric(f,"sat_code",rc);''')
    (dest/'driver.cpp').write_text(s)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('native',type=Path);p.add_argument('out',type=Path)
    a=p.parse_args();build_sources(a.native,a.out)
