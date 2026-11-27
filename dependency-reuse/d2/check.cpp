#include "check_core.h"

int main(int argc,char **argv)
{
    if(argc!=6) return 2;
    try
    {
        ProofStore g; int status=g.read(argv[1]);
        require(!g.d3 && (status==0 || status==10),"requires a completed D2 archive");
        Analysis a(g);
        verifyGraph(g,a.metrics);
        checkNative(g,argv[4]);
        a.inputs(argv[2]);
        readMapping(a,argv[3]);
        a.classify(argv[5]);
    }
    catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
