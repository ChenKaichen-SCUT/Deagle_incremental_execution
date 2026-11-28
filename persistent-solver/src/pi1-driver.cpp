#include "pi1-wire.h"
#include <cstdlib>
int main(int argc,char**argv){
    try{
        require(argc==2||argc==3,"usage: pi1 protocol [native-audit]");std::ifstream protocol(argv[1]);
        require(protocol.good(),"missing protocol");std::ofstream audit;
        PersistentClosureSession session;
        if(argc==3){audit.open(argv[2]);require(audit.good(),"audit path");session.set_audit_output(&audit);}
        std::ofstream controls;
        if(const char *path=std::getenv("PI1_ASSUMPTION_FILE")) {controls.open(path,std::ios::binary);require(controls.good(),"control receipt");session.set_assumption_output(&controls);}
        VersionId version{};std::string line;
        while(std::getline(protocol,line)){
            if(line.empty())continue;
            auto f=split(line);auto cmd=f[0];
            if(cmd=="APPEND"){version=session.append_version(readTransaction(f.at(1)));std::cout<<"PUBLISHED "<<version.id<<std::endl;}
            else if(cmd=="REJECT"||cmd=="REJECT_QUERY"){
                bool rejected=false;
                try{auto t=readTransaction(f.at(1));if(cmd=="REJECT")session.append_version(std::move(t));else session.append_query(version,std::move(t.first_query));}
                catch(const std::exception&e){rejected=true;std::cout<<"REJECTED "<<json(e.what())<<'\n';}
                require(rejected,"invalid transaction published");
            }else if(cmd=="QUERY"){auto t=readTransaction(f.at(1));session.append_query(version,std::move(t.first_query));}
            else if(cmd=="GC")session.collect_at_boundary();
            else if(cmd=="RESTART")session.first_restart_for_test(num(f.at(1)));
            else if(cmd=="BUDGET")session.conflict_budget_for_test(num(f.at(1)));
            else if(cmd=="INTERRUPT")session.interrupt_next_query();
            else if(cmd=="RESUME")session.clear_interrupt();
            else if(cmd=="PROBE"||cmd=="SOLVE"){
                QueryId id{nat(f.at(1))};QueryResult result{};
                if(cmd=="PROBE")session.probe_boundary(version,id);else result=session.solve_query(version,id);
                auto s=session.statistics();const char* names[]={"SAT","UNSAT","UNKNOWN","FAILED"};
                std::cout<<std::setprecision(12)<<"ROW {\"version\":"<<version.id<<",\"query\":"<<id.id
                    <<",\"status\":"<<json(cmd=="PROBE"?"DIAGNOSTIC":names[int(result.status)])
                    <<",\"rss_kib\":"<<rss()<<",\"native\":"<<s.receipt;
#define OUT(x) std::cout<<",\"" #x "\":"<<s.x
                OUT(solver_construct_count);OUT(old_learnt_export_count);OUT(old_learnt_import_count);OUT(per_clause_reproof_count);
                OUT(global_vars);OUT(program_vars);OUT(selectors);OUT(co_vars);OUT(reused);OUT(fresh);OUT(rejected_ports);
                OUT(occurrences);OUT(unique_inputs);OUT(skipped);OUT(install_seconds);OUT(assumption_build_seconds);
#undef OUT
                std::cout<<",\"assignment\":\"";for(auto v:result.local_assignment)std::cout<<"01?"[int(v)];
                std::cout<<"\",\"order\":{";bool first=true;for(auto &e:result.event_order){if(!first)std::cout<<',';first=false;std::cout<<json(e.first)<<':'<<e.second;}
                std::cout<<"},\"properties\":{";first=true;for(auto &p:result.property_results){if(!first)std::cout<<',';first=false;std::cout<<json(p.first)<<':'<<json(p.second);}
                std::cout<<"},\"native_failed_assumptions\":"<<result.failed_native_assumptions.size()<<"}"<<std::endl;
            }else throw std::runtime_error("bad protocol command");
        }
        session.close();return 0;
    }catch(const std::exception&e){std::cerr<<"PI1_FAILED "<<e.what()<<'\n';return 1;}
}
