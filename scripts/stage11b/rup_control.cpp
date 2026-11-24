#include "rup.hpp"
#include <iostream>
int main(){
    // (a OR b) & (!a OR c) entails (b OR c). A removed second premise invalidates it.
    std::vector<std::vector<int>> formula={{0,2},{1,4}};
    std::vector<size_t> proof;size_t work=0;
    if(!oc11::rup(3,formula,{2,4},proof,work,100))return 1;
    for(auto i:proof)std::cout<<i<<" ";std::cout<<"\n";
    formula.pop_back();work=0;proof.clear();
    if(oc11::rup(3,formula,{2,4},proof,work,100))return 2;
    work=0;proof.clear();
    if(oc11::rup(3,{}, {0},proof,work,100))return 3;
    std::cout<<"removed premise and unproved theory unit both rejected\n";
}
