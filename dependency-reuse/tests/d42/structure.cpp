#include "../../d4/structure42.h"
#include "../../d4/transport_graph.h"
#include <iostream>
#include <sstream>
using namespace d42;
int main(int argc,char **argv){
    if(argc!=2)return 2;
    Graph g(argv[1]);
    // Isolate matching from native allocation. The P0 premise is in the permanent slice.
    auto model=[&](){
        Models m(8,8,2);
        m.use={0,2,2};
        m.a.peer[1]=4;m.b.peer[2]=2;
        m.a.ordinary[3]=1;m.b.ordinary[4]=m.b.ordinary[5]=1;
        m.old.add({2,6},1);m.now.add({4,9},1);
        return m;
    };
    std::ostringstream log;
    auto p=model();Refinement first;first.run(p,log);
    need(p.a.translate(6)==9 && p.a.translate(7)==8 && p.b.translate(9)==6,"lost polarity");
    auto q=model();q.now.add({4,10},2);Refinement ambiguous;ambiguous.run(q,log);
    need(q.a.peer[3]<0 && ambiguous.ambiguous,"symmetric proposal accepted");
    auto t=model();t.a.theory(6);Refinement iface;iface.run(t,log);need(t.a.peer[3]<0,"theory alias admitted");
    auto u=model();u.b.ordinary[4]=0;Refinement unknown;unknown.run(u,log);need(u.a.peer[3]<0,"unknown peer admitted");
    auto v=model();v.b.peer[2]=3;bool failed=false;try{v.validate();}catch(const std::exception&){failed=true;}
    need(failed,"wrong reverse polarity accepted");
    std::cout<<"signed inverse checked; differing polarity, symmetric alternatives, theory aliases and unknown role rejected\n";
}
