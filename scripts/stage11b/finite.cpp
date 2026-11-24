#include "closure_delta.hpp"
#include <iostream>
using namespace oc11;
static Atom atom(){
    Atom a;if(!(std::cin>>a[0]>>a[1]>>a[2]))throw std::runtime_error("truncated atom");return a;
}
int main(){
    Closure engine;std::string op;std::set<Atom> base;std::set<Rule> rules;
    while(std::cin>>op){
        if(op=="B")base.insert(atom());
        else if(op=="R"){
            int label,n;std::cin>>label;Atom h=atom();std::cin>>n;
            if(n<0 || n>25)throw std::runtime_error("rule arity");
            std::vector<Atom> p;while(n--)p.push_back(atom());rules.insert({label,h,p});
        }else if(op=="CLEAR"){engine=Closure();}
        else if(op=="RUN"){
            engine.update(base,rules);std::cout<<"C "<<engine.facts.size()<<" "<<engine.instances()<<" "
                <<engine.stats.dirty<<" "<<engine.stats.clean_derived<<" "<<engine.stats.affected<<" "
                <<engine.stats.rederived<<" "<<engine.stats.checked<<"\n";
            for(auto a:engine.facts)std::cout<<a[0]<<" "<<a[1]<<" "<<a[2]<<"\n";
            base.clear();rules.clear();
        }else throw std::runtime_error("unknown command");
    }
}
