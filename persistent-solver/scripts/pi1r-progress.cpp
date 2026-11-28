// Compare the two implementations on the very same native trail and decision limits.
#include <minisat/core/Solver.h>
#include <cmath>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <stdexcept>
using namespace Minisat;
class Probe : public Solver {
public:
    void check(int vars,int depth,int stride) {
        for(int i=0;i<vars;++i)newVar();
        int next=0;
        if(vars && stride==1) uncheckedEnqueue(mkLit(next++));
        for(int i=0;i<depth;++i) {
            newDecisionLevel();
            if(i%stride==0 && next<vars) uncheckedEnqueue(mkLit(next++));
        }
        int visits=0;
        double original=progressEstimate(), optimized=zeroTailProgress(visits);
        if(std::memcmp(&original,&optimized,sizeof(double)) || visits>depth+1 ||
           (vars<2 && visits!=depth+1)) throw std::logic_error("progress bits or loop boundary");
        uint64_t bits;std::memcpy(&bits,&original,sizeof(bits));
        std::cout<<vars<<' '<<depth<<' '<<stride<<' '<<visits<<' '<<std::hex<<bits<<std::dec<<'\n';
    }
};
int main() {
    for(int n:{0,1,2,3,16,257}) for(int depth:{0,1,16,128,1023,1074,1075,1076,1600})
        for(int stride:{1,3,113,1277}) { Probe p;p.check(n,depth,stride); }
}
