#include "theory_check.h"

int main(int argc,char **argv)
{
    if(argc!=7) return 2;
    try {
        ProofStore g;
        const int status=g.read(argv[1]);
        require(g.d3 && (status==0 || status==10),"requires a completed D3 archive");
        Analysis a(g);
        GraphModel m(argv[5]);
        require(m.graph_receipt==g.graph_receipt,"P0 native graph receipt mismatch");
        verifyGraph(g,a.metrics,true);
        TheoryAudit audit(m,a);
        audit.replay();
        checkNative(g,argv[4]);
        a.inputs(argv[2]);
        readMapping(a,argv[3]);
        a.classify(argv[6],true);
        audit.witness(argv[6]);
    }
    catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
