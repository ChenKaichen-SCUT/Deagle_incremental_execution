// Offline reader for little-endian x86-64 reduceDB predicate segments.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <iomanip>
#include <limits>
#include <stdexcept>
struct Segment {
    uint64_t count;
    double limit;
    std::array<int64_t,6> start,step;
};
static_assert(sizeof(Segment)==112,"trace ABI");

// Count indices in [0,n) for which first + i*step >= target.
static uint64_t countAtLeast(int64_t first,int64_t step,int64_t target,int64_t n) {
    if (!step) return first>=target ? n : 0;
    if (step<0) return countAtLeast(first+(n-1)*step,-step,target,n);
    if (first>=target) return n;
    int64_t start=(target-first+step-1)/step;
    return start<n ? n-start : 0;
}
int main() {
    using std::int64_t;
    std::ios::sync_with_stdio(false);
    Segment s;uint64_t checks=0,runs=0,triggers=0,shadow=0;
    int64_t lo[6],hi[6]={};std::fill(lo,lo+6,INT64_MAX);
    double minLimit=std::numeric_limits<double>::infinity(),maxLimit=0;
    int64_t maxNative=INT64_MIN,maxShadow=INT64_MIN;
    while(std::cin.read(reinterpret_cast<char*>(&s),sizeof(s))) {
        if(!s.count || s.count>INT32_MAX || !std::isfinite(s.limit)) return 2;
        const int64_t n=s.count; ++runs;checks+=n;
        const auto &a=s.start,&d=s.step;
        for(int64_t i:{int64_t(0),n-1}) {
            int64_t x[6];
            for(int j=0;j<6;++j) {
                x[j]=a[j]+d[j]*i;
                if(x[j]<0)return 3;
                lo[j]=std::min(lo[j],x[j]);hi[j]=std::max(hi[j],x[j]);
            }
            if(x[1]+x[2]+x[3]!=x[4])return 4;
            maxNative=std::max(maxNative,x[0]-x[4]);maxShadow=std::max(maxShadow,x[0]-x[4]+x[2]);
        }
        minLimit=std::min(minLimit,s.limit);maxLimit=std::max(maxLimit,s.limit);
        int64_t threshold=std::ceil(s.limit);
        triggers+=countAtLeast(a[0]-a[4],d[0]-d[4],threshold,n);
        shadow+=countAtLeast(a[0]-a[4]+a[2],d[0]-d[4]+d[2],threshold,n);
    }
    if(!std::cin.eof() || std::cin.gcount()!=0 || !checks)return 5;
    std::cout<<std::setprecision(17)<<"{\"checks\":"<<checks<<",\"segments\":"<<runs<<",\"native_true\":"<<triggers
       <<",\"without_selector_subtraction\":"<<shadow<<",\"only_shadow_true\":"<<shadow-triggers
       <<",\"max_native_lhs\":"<<maxNative<<",\"max_shadow_lhs\":"<<maxShadow
       <<",\"min_limit\":"<<minLimit<<",\"max_limit\":"<<maxLimit<<",\"ranges\":[";
    for(int j=0;j<6;++j)std::cout<<(j?",":"")<<'['<<lo[j]<<','<<hi[j]<<']';
    std::cout<<"]}\n";
}
