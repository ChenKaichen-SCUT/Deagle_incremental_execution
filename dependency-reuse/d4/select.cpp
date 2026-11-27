// Runtime selection. Inspect membership, archive structure and the recorded reverse index.
// This binary links ProofStore only. It has no SAT, resolution-replay or Closure engine.
#include "minisat/core/ProofStore.h"
#include <array>
#include <chrono>
#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <unordered_set>

using namespace Minisat;
namespace {
using Clock=std::chrono::steady_clock;
using Key=std::array<int,4>;
void check(bool good,const char *why) { if(!good) throw std::runtime_error(why); }
long long ns(Clock::time_point a,Clock::time_point b)
{ return std::chrono::duration_cast<std::chrono::nanoseconds>(b-a).count(); }
std::vector<unsigned char> validate(const ProofStore &g)
{
    const size_t n=g.nodes.size();
    check(n && n<UINT32_MAX && g.nodes[0].kind==Missing && g.nodes[0].flags==Incomplete &&
          !g.nodes[0].lit_end && !g.nodes[0].edge_end,"missing sentinel");
    check(g.offsets.size()==n+1 && !g.offsets.front() && g.offsets.back()==g.edges.size() &&
          g.children.size()==g.edges.size() && g.nodes.back().edge_end==g.edges.size() &&
          g.nodes.back().lit_end==g.lits.size(),"archive section bounds");
    auto cursor=g.offsets;
    std::vector<unsigned char> has_b(n);
    size_t births=0, theories=0;
    for(ProofId id=1;id<n;++id)
    {
        const auto &node=g.nodes[id];
        const auto eb=g.edgeBegin(id);
        check(node.kind>Missing && node.kind<=TheoryLemma && eb<=node.edge_end && node.edge_end<=g.edges.size() &&
              g.litBegin(id)<=node.lit_end && node.lit_end<=g.lits.size(),"invalid proof node");
        bool opaque=node.kind==TheoryReason || node.kind==TheoryConflict || node.kind==DynamicCO || node.kind==TheoryEmpty;
        const bool derived=node.kind==Shortened || node.kind==RootUnit || node.kind==Learned ||
                           node.kind==RootConflict || node.kind==TheoryInference || node.kind==TheoryLemma;
        check(derived==(eb<node.edge_end),"incorrect parent arity");
        uint32_t flags=opaque ? Theory : node.kind==QueryInput ? Query : node.kind==UnknownInput ? Incomplete :
                       node.kind==TheoryDeclaration ? CertifiedTheory : 0;
        has_b[id]=node.kind==BooleanInput || node.kind==QueryInput;
        for(auto j=eb;j<node.edge_end;++j)
        {
            const auto p=g.edges[j].parent;
            check(p<id && cursor[p]<g.offsets[p+1] && g.children.at(cursor[p]++)==id,"invalid reverse dependency");
            flags|=g.nodes[p].flags;
            has_b[id]|=has_b[p];
        }
        check(flags==node.flags,"invalid origin flags");
        if(node.kind==Learned)
        {
            check(births<g.learned.size() && g.learned[births].id==id && g.learned[births].uip_edges,
                  "non-native or unordered birth");
            ++births;
        }
        if(node.kind==TheoryInference || node.kind==TheoryDeclaration)
        {
            const auto &r=g.theory_records.at(theories++);
            check(r.id==id && (node.kind==TheoryDeclaration ? r.op<=BlockDecl : r.op>=POEdge && r.op<=PreventRF),
                  "unsupported theory archive rule");
        }
    }
    for(size_t i=0;i<n;++i) check(cursor[i]==g.offsets[i+1],"missing reverse edge");
    check(births==g.learned.size() && theories==g.theory_records.size(),"extra proof directory entries");
    return has_b;
}

std::vector<uint8_t> bindInputs(const ProofStore &g,const std::string &manifest,const std::string &dir)
{
    std::ifstream counts(dir+"/clause-counts.tsv"),occ(dir+"/occurrences.tsv"),raw(manifest);
    check(counts && occ && raw,"missing Boolean delta");
    std::map<unsigned,std::pair<char,bool>> leaves;
    unsigned leaf,a,b;
    char scope;
    while(counts>>leaf>>scope>>a>>b)
        check(leaf && leaves.emplace(leaf,std::make_pair(scope,b!=0)).second,"duplicate canonical input");
    check(counts.eof(),"malformed input counts");
    std::vector<uint8_t> result;
    std::string line,occurrence,why;
    while(std::getline(raw,line))
    {
        if(line.compare(0,2,"C\t")!=0) continue;
        const auto &r=g.inputs.at(result.size());
        const auto &node=g.nodes.at(r.leaf);
        std::istringstream input(line.substr(2));
        input>>scope;
        check((scope=='B' && node.kind==BooleanInput) || (scope=='Q' && node.kind==QueryInput) ||
              (scope=='U' && node.kind==UnknownInput),"P0 scope mismatch");
        for(auto k=g.litBegin(r.leaf);k<node.lit_end;++k)
        {
            int lit;
            check(bool(input>>lit) && lit==g.lits[k],"P0 archive/manifest input mismatch");
        }
        input>>std::ws;check(input.eof(),"extra input literal");
        check(bool(std::getline(occ,occurrence)),"missing delta occurrence");
        std::istringstream entry(occurrence);
        unsigned side,seq;char s;
        check(bool(entry>>side>>seq>>s>>leaf>>why) && !side && seq==result.size()+1 && s==scope,
              "delta occurrence mismatch");
        if(leaf) check(leaves.at(leaf).first==scope,"cross-scope input");
        result.push_back(leaf && leaves.at(leaf).second);
    }
    check(raw.eof() && result.size()==g.inputs.size(),"incomplete P0 input stream");
    return result;
}

std::vector<uint8_t> bindTheory(const ProofStore &g,const std::string &path)
{
    std::ifstream file(path);
    std::map<Key,char> declared;
    std::string line,receipt;
    while(std::getline(file,line))
    {
        if(line.compare(0,2,"G\t")==0) {receipt+=line.substr(2);receipt+='\n';}
        if(line.compare(0,2,"D ")!=0) continue;
        char status;
        Key k;
        std::istringstream s(line.substr(2));
        check(bool(s>>k[0]>>k[1]>>k[2]>>k[3]>>status) && (status=='M'||status=='C'||status=='U') &&
              declared.emplace(k,status).second,"invalid declaration table");
    }
    check(file.eof() && receipt.size()==g.graph_receipt.size() &&
          std::equal(receipt.begin(),receipt.end(),g.graph_receipt.begin()),"different installed P0 graph");
    std::vector<uint8_t> result;
    for(const auto &r:g.theory_records)
        if(g.nodes[r.id].kind==TheoryDeclaration)
            result.push_back(declared.at({int(r.op),r.a,r.b,r.c})=='M');
    return result;
}

std::map<int,int> translation(const std::string &dir,int p0,int p1)
{
    std::ifstream file(dir+"/variables.tsv");
    int side,var,peer;
    std::string role,why,anchor;
    std::map<int,int> forward,reverse;
    while(file>>side>>var>>peer>>role>>why>>anchor)
    {
        check((side==0 || side==1) && var>0,"invalid variable identity");
        if(peer<0) continue;
        check(peer>=2 && var<(side?p1:p0) && peer/2<(side?p0:p1) &&
              (side?reverse:forward).emplace(var,peer).second,"out of range mapping");
    }
    check(file.eof() && forward.size()==reverse.size(),"incomplete mapping");
    for(const auto &v:forward)
        check(reverse.at(v.second/2)==(2*v.first+(v.second&1)),"non-injective signed mapping");
    return forward;
}
}

int main(int argc,char **argv)
{
    if(argc!=8) return 2;
    try
    {
        auto start=Clock::now();
        ProofStore g;
        const int code=g.read(argv[1]);
        check(g.d3 && (code==0 || code==10),"incomplete native D3 archive");
        const auto loaded=Clock::now();
        auto has_b=validate(g);
        auto inputs=bindInputs(g,argv[2],argv[3]);
        auto decls=bindTheory(g,argv[4]);
        const int p0=std::stoi(argv[5]),p1=std::stoi(argv[6]);
        auto mapped=translation(argv[3],p0,p1);
        const auto bound=Clock::now();
        auto dead=g.invalidatedInputs(inputs,decls);
        const auto marked=Clock::now();
        size_t dead_nodes=0,dead_edges=0,survive=0;
        for(ProofId id=0;id<dead.size();++id) if(dead[id])
        {
            ++dead_nodes;
            dead_edges+=g.offsets[id+1]-g.offsets[id];
        }
        std::string out=argv[7];
        std::ofstream table(out+"/catalog.tsv"),batch(out+"/selected.tsv"),metrics(out+"/selection.tsv");
        for(auto f:{&table,&batch,&metrics}) f->exceptions(std::ios::badbit|std::ios::failbit);
        std::ostringstream selected;
        size_t n=0;
        table<<"id\tflags\thas_B\talive\tmapped\tselected\n";
        for(const auto &birth:g.learned)
        {
            const ProofId id=birth.id;
            bool can_map=true;
            const auto &node=g.nodes[id];
            for(auto k=g.litBegin(id);k<node.lit_end;++k)
                if(g.lits[k]<2 || !mapped.count(g.lits[k]/2)) {can_map=false;break;}
            if(!dead[id]) check(node.flags==0 || node.flags==CertifiedTheory,"surviving non-permanent proof");
            const bool take=!dead[id] && can_map;
            table<<id<<'\t'<<node.flags<<'\t'<<int(has_b[id])<<'\t'<<!dead[id]<<'\t'<<can_map<<'\t'<<take<<'\n';
            survive+=!dead[id];
            if(!take) continue;
            const char type=node.flags==0 ? 'B' : has_b[id] ? 'M' : 'T';
            selected<<id<<'\t'<<type<<'\t'<<node.lit_end-g.litBegin(id);
            for(auto k=g.litBegin(id);k<node.lit_end;++k)
                selected<<'\t'<<(mapped.at(g.lits[k]/2)^(g.lits[k]&1));
            selected<<'\n';
            ++n;
        }
        batch<<"D4-selected-v1\t"<<p1<<'\t'<<n<<'\n'<<selected.str();
        table.close();batch.close();
        metrics<<"births\t"<<g.learned.size()<<"\nsurviving\t"<<survive<<"\nselected\t"<<n
               <<"\nnodes\t"<<g.nodes.size()-1<<"\nedges\t"<<g.edges.size()
               <<"\ninvalidated_nodes_including_sentinel\t"<<dead_nodes<<"\nvisited_reverse_edges\t"<<dead_edges
               <<"\narchive_read_ns\t"<<ns(start,loaded)<<"\nvalidation_and_binding_ns\t"<<ns(loaded,bound)
               <<"\nreverse_ns\t"<<ns(bound,marked)<<"\nselection_ns\t"<<ns(marked,Clock::now())<<'\n';
        metrics.close();
    }
    catch(const std::exception &e) {std::cerr<<e.what()<<'\n';return 1;}
}
