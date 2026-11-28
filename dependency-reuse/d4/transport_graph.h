// The on-disk Light format only encodes support. Full Audit input is accepted by
// the offline equivalence check and the reference ablation, never replayed by P1.
#ifndef DEAGLE_TRANSPORT_GRAPH_H
#define DEAGLE_TRANSPORT_GRAPH_H
#include "minisat/core/SupportStore.h"
#include "transport_check.h"
#include <algorithm>
#include <array>
#include <cstring>
#include <fstream>
#include <stdexcept>
#include <set>
#include <vector>
namespace d42 {
using namespace Minisat;
using Id=uint32_t;
using Fact=std::array<int,4>;
enum Type : uint8_t { MissingLeaf,InputLeaf,FactLeaf,OpaqueLeaf,Group,Learn };
struct Node { Id end,payload; uint8_t type,flags,has_b; };
struct Birth {Id node,end,original;};
struct Graph {
    std::vector<Node> nodes{{0,0,MissingLeaf,Incomplete,0}};
    std::vector<Id> parents;std::vector<int> lits;std::vector<Birth> births;
    std::vector<Fact> facts;std::vector<char> receipt;
    std::array<uint64_t,10> stats{};Id occurrence_count=0;int status=0;
    Id begin(Id i)const{return i?nodes.at(i-1).end:0;}
    Id litBegin(size_t i)const{return i?births.at(i-1).end:0;}
    Id add(Type type,Id payload,uint32_t flag,const std::vector<Id> &ps){
        const Id id=SupportFormat::number(nodes.size());
        bool b=type==InputLeaf && flag!=Incomplete;
        for(Id p:ps){need(p<id,"non-topological support");flag|=nodes[p].flags;b|=nodes[p].has_b;}
        parents.insert(parents.end(),ps.begin(),ps.end());
        need(parents.size()<UINT32_MAX,"edge limit");
        nodes.push_back({uint32_t(parents.size()),payload,type,uint8_t(flag),uint8_t(b)});
        return id;
    }
    void birth(Id original,Id node,const int *c,size_t n){
        if(n)lits.insert(lits.end(),c,c+n);
        births.push_back({node,uint32_t(lits.size()),original});
    }
    std::vector<uint8_t> reach()const{
        std::vector<uint8_t> v(nodes.size());
        for(auto &b:births)v[b.node]=1|((nodes[b.node].flags&7)?0:2);
        for(size_t i=v.size();i-->1;)if(v[i])for(Id j=begin(i);j<nodes[i].end;++j)v[parents[j]]|=v[i];
        return v;
    }
    static uint32_t word(std::istream &f){uint32_t x;f.read(reinterpret_cast<char*>(&x),4);return x;}
    void light(std::ifstream &f){
        using F=SupportFormat;
        std::vector<Id> decoded{0},inputs,ps;std::vector<int> clause;
        for(;;){
            uint32_t header=word(f);if(header==F::End)break;
            uint32_t k=header&15,flags=(header>>4)&15,n=header>>8;ps.clear();
            for(uint32_t i=0;i<n;++i){
                uint32_t raw=word(f),j=F::index(raw);Id p=0;
                need(!(raw&F::Temp),"transient handle in archive");
                if(raw&F::Input){
                    need(j && (F::flags(raw)==0 || F::flags(raw)==Query || F::flags(raw)==Incomplete),"input flags");
                    if(j>=inputs.size())inputs.resize(size_t(j)+1);
                    if(!inputs[j])inputs[j]=add(InputLeaf,j,F::flags(raw),{});
                    p=inputs[j];
                }else p=decoded.at(j);
                need(nodes.at(p).flags==F::flags(raw),"support reference flags");ps.push_back(p);
            }
            Id id=0;
            if(k==F::Declaration){
                need(!n,"declaration parents");Fact fact;for(int &v:fact)v=int32_t(word(f));
                need(fact[0]>=0 && fact[0]<=BlockDecl,"unknown declared rule");
                id=add(FactLeaf,uint32_t(facts.size()),CertifiedTheory,{});facts.push_back(fact);
            }else if(k==F::Opaque){
                uint32_t kind=word(f);need(!n && (kind==TheoryReason||kind==TheoryConflict||kind==DynamicCO||kind==TheoryEmpty),"opaque kind");
                id=add(OpaqueLeaf,kind,Theory,{});
            }else{
                need((k==F::Join||k==F::Birth) && n,"bad join");
                id=add(k==F::Birth?Learn:Group,0,0,ps);
                if(k==F::Birth){
                    uint32_t arity=word(f);need(arity<=F::IndexMask,"birth length");clause.resize(arity);
                    if(arity)f.read(reinterpret_cast<char*>(clause.data()),4*arity);
                    birth(uint32_t(decoded.size())|(flags<<F::FlagShift),id,clause.data(),arity);
                }
            }
            need(nodes[id].flags==flags,"inherited flags");decoded.push_back(id);
        }
        occurrence_count=word(f);need(word(f)+1==decoded.size() && inputs.size()<=size_t(occurrence_count)+1,"support directory");
        f.read(reinterpret_cast<char*>(stats.data()),sizeof(stats));uint32_t bytes=word(f);receipt.resize(bytes);
        if(bytes)f.read(receipt.data(),bytes);
        status=int(word(f));char end[4];f.read(end,4);need(!std::memcmp(end,"ENDL",4) && f.peek()==EOF,"light footer");
    }
    void audit(const std::string &path){
        ProofStore g;status=g.read(path);need(g.d3&&g.triplets&&!g.compact,"need full D4.1 archive");
        receipt.swap(g.graph_receipt);occurrence_count=uint32_t(g.inputs.size());
        std::vector<uint8_t> live(g.nodes.size());std::vector<Id> remap(g.nodes.size()),ps;
        for(const auto &b:g.learned)live.at(b.id)=1;
        for(size_t i=live.size();i-->1;)if(live[i])for(auto j=g.edgeBegin(i);j<g.nodes[i].edge_end;++j)live[g.edges[j].parent]=1;
        size_t input=0,decl=0;
        for(Id i=1;i<g.nodes.size();++i){
            const auto &v=g.nodes[i];bool leaf=v.kind==BooleanInput||v.kind==UnknownInput||v.kind==QueryInput;
            if(leaf){need(g.inputs.at(input).leaf==i,"audit occurrence");++input;}
            const TheoryRecord *r=nullptr;
            if(v.kind==TheoryDeclaration||v.kind==TheoryInference){r=&g.theory_records.at(decl++);need(r->id==i,"audit theory directory");}
            if(!live[i])continue;
            ps.clear();for(auto j=g.edgeBegin(i);j<v.edge_end;++j)ps.push_back(remap.at(g.edges[j].parent));
            if(leaf)remap[i]=add(InputLeaf,uint32_t(input),v.flags,{});
            else if(v.kind==TheoryDeclaration){
                remap[i]=add(FactLeaf,uint32_t(facts.size()),CertifiedTheory,{});
                facts.push_back({{int(r->op),r->a,r->b,r->c}});
            }else if(v.kind==TheoryReason||v.kind==TheoryConflict||v.kind==TheoryEmpty||v.kind==DynamicCO)
                remap[i]=add(OpaqueLeaf,v.kind,Theory,{});
            else{
                remap[i]=add(v.kind==Learned?Learn:Group,0,0,ps);
                if(v.kind==Learned)birth(i,remap[i],g.lits.data()+g.litBegin(i),v.lit_end-g.litBegin(i));
            }
            need(nodes[remap[i]].flags==v.flags,"audit flag discrepancy");
        }
        need(input==g.inputs.size() && decl==g.theory_records.size() && births.size()==g.learned.size(),"incomplete audit");
        for(int i=0;i<3;++i)stats[7+i]=g.discharge_stats[i];
    }
    explicit Graph(const std::string &path){
        std::ifstream f(path,std::ios::binary);f.exceptions(std::ios::failbit|std::ios::badbit);
        char magic[8];f.read(magic,8);
        if(!std::memcmp(magic,"DEAGSL1",8))light(f);else{f.close();audit(path);}
        need(status==0||status==10,"incomplete native solve");
    }
};
}
#endif
