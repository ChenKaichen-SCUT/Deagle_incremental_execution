#ifndef D43C_FIXTURE_CAPTURE_H
#define D43C_FIXTURE_CAPTURE_H
#include "minisat/core/BoundaryAudit43.h"
#include <cstdlib>
namespace Minisat {
struct FixtureOwners43 : dependency_manifest::group_owner_interfacet {
    unsigned occurrence=0;std::string key;
    const bool shared=std::getenv("D43C_SAME_GROUP")!=nullptr;
    const std::string &boolean(const int *,size_t) override{
        key="[\"B\",\"fixture\","+std::to_string(shared?0:++occurrence)+"]";return key;
    }
    void node(int,const std::string &) override{}
    std::string theory(int op,int a,int b) const override{
        if(shared)return "[\"T\",\"shared\"]";
        return "[\"T\",\"fixture\","+std::to_string(op)+","+std::to_string(a)+","+std::to_string(b)+"]";
    }
};
struct FixtureTrace43 {
    BoundaryAudit43 observer;
    static FILE *&trace(){static FILE *file=nullptr;return file;}
    explicit FixtureTrace43(const std::string &dir):observer(dir+"/boundaries.bin.cert"){
        trace()=std::fopen((dir+"/boundaries.bin").c_str(),"wbx");
        if(!trace())throw std::runtime_error("fixture trace open");
    }
    void attach(ClosureSolver &s){
        s.observe_boundary=[](unsigned kind,const vec<Lit> &v){
            uint32_t n=v.size();
            if(std::fwrite(&kind,4,1,trace())!=1 || std::fwrite(&n,4,1,trace())!=1 ||
               (n && std::fwrite(&v[0],4,n,trace())!=n))throw std::runtime_error("fixture trace write");
        };
    }
    void finish(){if(!observer.finish() || std::fclose(trace()))throw std::runtime_error("fixture trace close");trace()=nullptr;}
};
}
#endif
