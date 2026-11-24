// Independent RUP proof producer. Each result is a resolution recipe checked by Python.
#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <stdexcept>
#include <vector>
using Row=std::vector<int>;
struct Database{
    std::vector<Row> clauses,occ;
    int base=0;
    explicit Database(std::istream &stream){
        auto word=[&](){uint32_t x;if(!stream.read(reinterpret_cast<char*>(&x),4))throw std::runtime_error("truncated stream");return x;};
        while(stream.peek()!=EOF){
            auto tag=word();
            if(tag==0xfffffff1){word();word();word();occ.resize(occ.size()+2);}
            else if(tag==0xfffffff4){word();word();}
            else if(tag==0xfffffff2){}
            else if(tag==0xfffffff0 || tag==0xfffffff3){
                Row c;int n=word();while(n--)c.push_back(word());
                if(tag==0xfffffff0)add(c);
            }else throw std::runtime_error("invalid stream");
        }
        base=clauses.size();
    }
    void add(Row c){
        std::sort(c.begin(),c.end());c.erase(std::unique(c.begin(),c.end()),c.end());
        for(int x:c)occ.at(x).push_back(clauses.size());
        clauses.push_back(c);
    }
    bool prove(const Row &target,int limit,int &conflict,std::vector<std::pair<int,int>>& proof){
        Row value(occ.size()/2,-1),reason(value.size(),-1),trail;
        auto put=[&](int x,int ref){value[x/2]=x;reason[x/2]=ref;trail.push_back(x);};
        for(int x:target)put(x^1,-1);
        int cost=0;conflict=-1;
        for(int j=0;j<limit && conflict<0;++j){
            auto &c=clauses[j];
            if(c.empty()){conflict=j;break;}
            if(c.size()!=1)continue;
            int x=c[0],v=value[x/2];
            if(v==(x^1))conflict=j;else if(v<0)put(x,j);
        }
        for(size_t i=0;i<trail.size() && conflict<0;++i){
            for(auto j:occ[trail[i]^1]){
                if(j>=limit)break;
                if(++cost>1800000)return false;
                int free=0,last=-1;bool sat=false;
                for(int y:clauses[j]){
                    if(value[y/2]==y){sat=true;break;}
                    if(value[y/2]<0){++free;last=y;}
                }
                if(sat || free>1)continue;
                if(!free){conflict=j;break;}
                put(last,j);
            }
        }
        if(conflict<0)return false;
        std::set<int> current(clauses[conflict].begin(),clauses[conflict].end());
        for(auto p=trail.rbegin();p!=trail.rend();++p){
            int x=*p,ref=reason[x/2];if(ref<0 || !current.erase(x^1))continue;
            for(int y:clauses[ref])if(y!=x)current.insert(y);
            proof.emplace_back(x,ref);
        }
        for(int y:current)if(std::find(target.begin(),target.end(),y)==target.end())throw std::runtime_error("invalid RUP discharge");
        return true;
    }
};
int main(int argc,char** argv){
    if(argc!=2)return 2;
    std::ifstream stream(argv[1],std::ios::binary);Database db(stream);
    char type;int id,n;
    while(std::cin>>type>>id>>n){
        Row cs(n);for(int &x:cs)std::cin>>x;
        if(type=='T'){db.add(cs);continue;}
        for(int mode=0;mode<2;++mode){
            int start;std::vector<std::pair<int,int>> path;
            if(db.prove(cs,mode?db.clauses.size():db.base,start,path)){
                std::cout<<id<<" "<<mode<<" "<<start;
                for(auto &p:path)std::cout<<" "<<p.first<<":"<<p.second;
                std::cout<<"\n";break;
            }
        }
    }
}
