#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdlib>
#include <set>
#include <vector>
namespace oc11 {
// Reprove a candidate with P1 originals only, under the negation of its conclusion.
// Each positive step indexes an exact submitted clause. The last index is conflicting.
inline bool rup(int n,const std::vector<std::vector<int>> &formula,const std::vector<int> &clause,
                std::vector<size_t> &steps,size_t &work,size_t cap) {
    std::vector<int> values(n,-1);
    for(int x:clause){
        if(x<0 || x/2>=n || values[x/2]!=-1)return false;
        values[x/2]=(x&1)^1;
    }
    bool changed=true;
    while(changed){
        changed=false;
        for(size_t i=0;i<formula.size();++i){
            if(++work>cap)return false;
            int unit=-1;bool satisfied=false,multiple=false;
            for(int x:formula[i]){
                int val=values[x/2];
                if(val==(x&1)){satisfied=true;break;}
                if(val==-1){
                    if(unit!=-1 && unit!=x)multiple=true;
                    unit=x;
                }
            }
            if(satisfied || multiple)continue;
            steps.push_back(i);
            if(unit==-1)return true;
            values[unit/2]=unit&1;changed=true;
        }
    }
    return false;
}
}
