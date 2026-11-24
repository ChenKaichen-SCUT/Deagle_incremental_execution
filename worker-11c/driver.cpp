// Long-lived worker for two independently built models. Only native Clause objects can be reused.
#include "sealed.hpp"
#include "epoch.hpp"
#include "native_root.hpp"
#include <memory>
#include <iomanip>

using namespace Minisat;
using namespace session10;

struct Plan {
  std::string disposition;
  std::set<int> vars;
  std::map<int,int> mapping;
  explicit Plan(const std::string &dir){
    std::ifstream in(dir+"/plan.txt");require(bool(in>>disposition),"missing admission decision");
    int v,raw;while(in>>v){require(bool(in>>raw) && v>=0 && raw>=0 && vars.insert(raw/2).second && mapping.emplace(v,raw).second,"invalid signed bijection");}
    require(in.eof(),"malformed plan");
  }
};
static void deliver(ClosureSolver &s,Stage10Epoch &epoch,Input &input,vec<Lit>& goals){
  vec<Lit> ps;
  for(const Op &op:input.ops){
    auto &v=op.payload;
    switch(op.tag){
    case VarOp:require(s.newVar(lbool(uint8_t(v[1])),v[2])==v[0],"native allocation order");break;
    case ClauseOp:
      epoch.submitting(v);ps.clear();for(int x:v)ps.push(literal(x));s.addClause_(ps);break;
    case PolOp:s.setPolarity(v[0],lbool(uint8_t(v[1])));break;
    case GraphOp:s.save_raw_graph(input.edges,input.guards,input.locations,input.order);break;
    case GoalOp:for(int x:v)goals.push(literal(x));break;
    }
  }
  epoch.close();
}
static void metric(std::ofstream &f,const std::string &k,uint64_t v){f<<k<<"\t"<<v<<"\n";}
#include "repeat_graph.hpp"

static int controls(const std::string &dir){
  s10::where()=dir;
  ClosureSolver s;
  auto act=mkLit(s.newVar()),x=mkLit(s.newVar());
  s.addClause(~act,x);s.addClause(~act,~x);vec<Lit> a;a.push(act);
  int first=toInt(s.solveLimited(a));bool after=s.okay();
  a[0]=~act;int second=toInt(s.solveLimited(a));a[0]=act;int third=toInt(s.solveLimited(a));
  require(first==1 && after && second==0 && third==1,"assumption guarded SAT control");
  ClosureSolver root;auto p=mkLit(root.newVar());root.addClause(p);root.addClause(~p);a.clear();
  int unsat=toInt(root.solveLimited(a));a.push(~p);int retry=toInt(root.solveLimited(a));
  ClosureSolver fresh;auto q=mkLit(fresh.newVar());fresh.addClause(~q);a.clear();int clean=toInt(fresh.solveLimited(a));
  require(unsat==1 && !root.okay() && retry==1 && clean==0,"root UNSAT control");
  std::ofstream(dir+"/controls.tsv")<<"guarded\t"<<first<<" "<<second<<" "<<third<<"\nroot\t"<<unsat<<" "<<retry<<" "<<clean<<"\n";
  return 0;
}
int main(int argc,char **argv){
  try{
    if(argc==4 && std::string(argv[1])=="--same-graph")return repeat_graph(argv[2],argv[3]);
    if(argc==3 && std::string(argv[1])=="--controls")return controls(argv[2]);
    require(argc==2,"expected test option or 'normal'");std::string mode=argv[1]; std::string test=(mode=="B"||mode=="T"||mode=="C"||mode=="TC")?"GS":mode;
    std::unique_ptr<ClosureSolver> solver;
    std::unique_ptr<Stage10Epoch> epoch;
    std::unique_ptr<Input> previous;
    unsigned generation=0;
    for(int phase=0;phase<2;++phase){
      std::string dir;if(!std::getline(std::cin,dir))break;
      auto start=s10::now();s10::where()=dir+"/worker";
      s8::State observation;
      observation.out=s10::where();observation.detail=true;observation.deep=false;
      observation.born=s8::ns(CLOCK_MONOTONIC);observation.cpu_born=s8::ns(CLOCK_PROCESS_CPUTIME_ID);
      s8::state()=observation;
      std::unique_ptr<Input> input(new Input(dir));
      bool dynamic=mode=="T"||mode=="C"||mode=="TC";
      c11::state().open(dir+"/worker",!phase&&dynamic,!phase&&(mode=="C"||mode=="TC"),phase&&dynamic);
      Plan plan(dir);auto parsed=s10::now();
      std::string verdict=plan.disposition;
      if(phase && test=="damage-learning")epoch->corrupt_for_test();
      if(phase && !epoch->intact())verdict="refuse_damaged_learning";
      bool keep=phase && verdict=="keep" && (test=="S" || test=="GS" || test=="damage-learning");
      oc11::session().open(dir,phase && verdict!="refuse_damaged_learning" && (test=="G" || test=="GS"));
      ::write_order.clear();
      int retired=phase?epoch->old_learnts:0,roots=phase?epoch->old_roots:0,prior_nodes=phase?epoch->old_nodes:0;
      auto old_address=reinterpret_cast<uintptr_t>(solver.get());
      if(!keep){
        std::unique_ptr<ClosureSolver> replacement(new ClosureSolver());
        epoch.reset();solver=std::move(replacement);epoch.reset(new Stage10Epoch(*solver));++generation;
        if(!phase && (test=="S" || test=="GS" || test=="damage-learning"))epoch->register_old(plan.vars);
      }else epoch->switch_version(plan.vars,*input,plan.mapping);
      auto initialized=s10::now();
      vec<Lit> goals;
      auto before_submission=solver->propagations;
      auto cleared_roots=solver->nAssigns(),cleared_learnts=solver->nLearnts(),cleared_nodes=epoch->nodes();
      require(!cleared_roots && !cleared_learnts && !cleared_nodes && solver->okay(),"unclean candidate epoch");
      deliver(*solver,*epoch,*input,goals);
      auto original_end=s10::now();
      if(keep)epoch->restore_learning(*input,dir);
      if(phase && dynamic){auto approved=c11::approved_stream(dir);epoch->install_dynamic(dir,mode,input->variables,approved);}
      c11::state().assumptions=c11::lits(goals);c11::state().running=true;
      auto loaded=s10::now();int submitted=solver->nClauses();
      auto starts=solver->starts,dec=solver->decisions,conf=solver->conflicts,prop=solver->propagations;
      int cycles=epoch->cycles(),theory=epoch->theory();
      int rc=toInt(solver->solveLimited(goals));auto solved=s10::now(); c11::state().running=false;c11::state().end();
      if(!phase)epoch->seal();
      oc11::session().report();
      auto sealed=s10::now();
      s8::flush();
      write_answer(dir,*solver,*input,rc);
      std::ofstream f(dir+"/worker/stats.tsv");
      f<<"admission\t"<<verdict<<"\n";
      metric(f,"pid",getpid());metric(f,"object",reinterpret_cast<uintptr_t>(solver.get()));metric(f,"previous_object",old_address);metric(f,"generation",generation);
      metric(f,"parse_ns",parsed-start);metric(f,"init_switch_ns",initialized-parsed);metric(f,"submit_ns",loaded-initialized);
      metric(f,"search_ns",solved-loaded);metric(f,"retain_ns",sealed-solved);metric(f,"reply_ns",s10::now()-sealed);
      metric(f,"input_variables",input->variables);metric(f,"input_clauses",input->clauses);metric(f,"active_before_solve",submitted);
      metric(f,"rup_ns",loaded-original_end);metric(f,"rup_proved",epoch->proved);
      metric(f,"rup_unmapped",epoch->unmapped);metric(f,"rup_unproved",epoch->refused);
      metric(f,"rup_unchecked",epoch->unchecked);metric(f,"rup_work",epoch->rup_work);
      metric(f,"dynamic_snapshot_ns",c11::state().collection_ns);metric(f,"instrumented_analyze_ns",c11::state().analysis_ns);
      metric(f,"proof_flush_ns",c11::state().persist_ns);metric(f,"install_ns",c11::state().install_ns);metric(f,"sat_code",rc);metric(f,"peak_rss_kib",s10::rss_kib());metric(f,"arena_bytes",epoch->arena_bytes());
      std::ifstream smaps("/proc/self/smaps_rollup");
      for(std::string row;std::getline(smaps,row);){
        std::istringstream s(row);std::string k;uint64_t value;
        if(s>>k>>value && (k=="Pss:" || k=="Rss:" || k=="Private_Dirty:"))
          metric(f,"resident_"+k.substr(0,k.size()-1)+"_kib",value);
      }
      metric(f,"retained_index_bytes",epoch->seal_bytes);metric(f,"postsolve_learnts",solver->nLearnts());metric(f,"retired_learnts",retired);
      metric(f,"old_root_assigns",roots);metric(f,"old_graph_nodes",prior_nodes);metric(f,"new_root_assigns_before_input",cleared_roots);
      metric(f,"new_learnts_before_input",cleared_learnts);metric(f,"new_graph_nodes_before_input",cleared_nodes);
      metric(f,"approved_candidates",epoch->surviving);metric(f,"actually_reattached",epoch->used.size());
      metric(f,"submission_propagations",prop-before_submission);
      metric(f,"starts",solver->starts-starts);metric(f,"decisions",solver->decisions-dec);metric(f,"conflicts",solver->conflicts-conf);
      metric(f,"propagations",solver->propagations-prop);metric(f,"theory_propagations",epoch->theory()-theory);metric(f,"theory_conflicts",epoch->cycles()-cycles);
      for(const auto &row:epoch->used){std::ofstream u(dir+"/worker/retained.tsv",std::ios::app);u<<row.first;for(int x:row.second)u<<"\t"<<x;u<<"\n";}
      f.close();previous=std::move(input);
      dprintf(std::stoi(std::getenv("S10_PROTOCOL_FD")),"STAGE10_DONE %d\n",phase);
    }
  }catch(const std::exception &e){std::cerr<<"stage10: "<<e.what()<<"\n";return 2;}
}
