// Production structural refinement over static CNFs and compact occurrence flags.
#include "structure42.h"
#include <chrono>
#include <iostream>
#include <iterator>
using namespace d42;
using Clock=std::chrono::steady_clock;
static long long elapsed(Clock::time_point start){
    return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-start).count();
}
static std::ofstream file(const std::string &dir,const char *name){
    std::ofstream stream(dir+"/"+name);
    stream.exceptions(std::ios::badbit|std::ios::failbit);
    return stream;
}
int main(int argc,char **argv){
    if(argc!=8)return 2;
    try{
        auto start=Clock::now();
        std::ifstream flags(argv[4],std::ios::binary);
        need(bool(flags),"missing compact occurrence directory");
        std::vector<uint8_t> inputs((std::istreambuf_iterator<char>(flags)),{});
        const int n0=std::stoi(argv[6]),n1=std::stoi(argv[7]);
        need(n0>0 && n1>0,"empty variable domain");
        Models m(n0,n1,inputs.size());const std::string dir=argv[5];
        for(size_t i=0;i<inputs.size();++i){
            const auto f=inputs[i];need(f<=4 || f==8,"invalid compact occurrence flags");
            m.scope[i+1]=f==4?'Q':f==8?'U':'B';
            m.use[i+1]=(f&1)?3:(f&2)?1:0;
        }
        m.map(argv[3]);
        m.read(argv[1],false);m.read(argv[2],true);
        auto read_ns=elapsed(start);start=Clock::now();
        auto proposals=file(dir,"structure.tsv");
        proposals<<"round\told_var\tnew_signed_positive\told_occurrence\tnew_occurrence\n";
        Refinement refinement;refinement.run(m,proposals);proposals.close();
        auto refine_ns=elapsed(start);start=Clock::now();
        auto mapping=file(dir,"effective-map.tsv");
        mapping<<"side\tvariable\tpeer\tordinary\n";
        for(int v=0;v<2;++v){
            const Atoms &side=v?m.b:m.a;
            for(size_t j=1;j<side.peer.size();++j)
                mapping<<v<<'\t'<<j<<'\t'<<side.peer[j]<<'\t'<<int(side.ordinary[j])<<'\n';
        }
        mapping.close();auto map_out_ns=elapsed(start);start=Clock::now();
        std::unordered_map<Literals,std::vector<size_t>,Hash> wanted;
        std::vector<int> matches(m.old.ordinals.size(),-1);
        Literals c;
        for(size_t i=0;i<m.old.ordinals.size();++i){
            m.old.get(i,c);
            for(int &lit:c)lit=m.a.translate(lit);
            if(std::find(c.begin(),c.end(),INT_MIN)!=c.end())continue;
            normalize(c);wanted[c].push_back(i);matches[i]=0;
        }
        for(size_t i=0;i<m.now.ordinals.size()&&!wanted.empty();++i){
            m.now.get(i,c);auto it=wanted.find(c);if(it==wanted.end())continue;
            for(auto old:it->second)matches[old]=int(m.now.ordinals[i]);
            wanted.erase(it);
        }
        auto result=file(dir,"input-matches.tsv");
        result<<"occurrence\tP1_permanent_occurrence\n";
        for(size_t i=0;i<matches.size();++i)result<<m.old.ordinals[i]<<'\t'<<matches[i]<<'\n';
        result.close();
        auto times=file(dir,"structure-stats.tsv");
        times<<"static_CNF_read_ns\t"<<read_ns<<"\nrefinement_ns\t"<<refine_ns
             <<"\nmap_write_ns\t"<<map_out_ns<<"\nmembership_ns\t"<<elapsed(start)
             <<"\nrounds\t"<<refinement.rounds<<"\nchecks\t"<<refinement.checks
             <<"\nadded\t"<<refinement.added<<"\nambiguous\t"<<refinement.ambiguous
             <<"\ncollisions\t"<<refinement.collisions<<"\nstop\t"<<refinement.stop
             <<"\nold_checked\t"<<matches.size()<<"\np1_occurrences\t"<<m.p1_rows<<'\n';
    }catch(const std::exception &error){std::cerr<<error.what()<<'\n';return 1;}
}
