// No solver is linked. Match the premises once, then invalidate over reverse edges.
#include "structure42.h"
#include "transport_graph.h"
#include <iostream>
#include <sstream>
using namespace d42;
using Clock=std::chrono::steady_clock;
using Counts=std::map<std::string,uint64_t>;
static uint64_t elapsed(Clock::time_point t){
    return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-t).count();
}
static std::ofstream output(const std::string &dir,const char *name){
    std::ofstream f(dir+"/"+name);f.exceptions(std::ios::badbit|std::ios::failbit);return f;
}
static std::map<Fact,char> bindings(const Graph &g,const std::string &path){
    std::ifstream in(path);need(bool(in),"missing declaration certificate");
    std::string line,receipt;std::map<Fact,char> out;
    while(std::getline(in,line)){
        if(line.compare(0,2,"G\t")==0){receipt+=line.substr(2);receipt+='\n';}
        if(line.compare(0,2,"D ")!=0)continue;
        std::istringstream row(line.substr(2));Fact fact;char s;
        need(bool(row>>fact[0]>>fact[1]>>fact[2]>>fact[3]>>s) &&
             (s=='C'||s=='U'||s=='M') && out.emplace(fact,s).second,"bad declaration certificate");
        row>>std::ws;need(row.eof(),"extra declaration fields");
    }
    need(in.eof() && receipt.size()==g.receipt.size() && std::equal(receipt.begin(),receipt.end(),g.receipt.begin()),"wrong installed graph");
    return out;
}
static void membership(const Graph &g,Models &m,const std::vector<Id> &input_node,std::vector<uint8_t> &dead,Counts &counts,const std::string &out){
    std::unordered_map<Literals,std::vector<Id>,d42::Hash> wanted;
    std::vector<uint32_t> witness(g.nodes.size());
    std::vector<uint8_t> translated(g.nodes.size());Literals c;
    for(size_t i=0;i<m.old.ordinals.size();++i){
        Id node=input_node[m.old.ordinals[i]];m.old.get(i,c);
        for(int &l:c)l=m.a.translate(l);
        if(std::find(c.begin(),c.end(),INT_MIN)!=c.end())continue;
        normalize(c);wanted[c].push_back(node);translated[node]=1;
    }
    for(size_t i=0;i<m.now.ordinals.size()&&!wanted.empty();++i){
        m.now.get(i,c);auto it=wanted.find(c);if(it==wanted.end())continue;
        for(Id n:it->second)witness[n]=m.now.ordinals[i];
        wanted.erase(it);
    }
    auto report=output(out,"inputs42.tsv");report<<"occurrence\tuse\tstatus\tp1_permanent_occurrence\n";
    for(size_t i=1;i<input_node.size();++i){
        Id n=input_node[i];if(!n)continue;
        const char *why=g.nodes[n].flags?"scope":witness[n]?"matched":translated[n]?"mapped_absent":"unmapped";
        dead[n]=!witness[n];
        ++counts[std::string("used_input_")+why];
        if(m.use[i]&2)++counts[std::string("permanent_input_")+why];
        report<<i<<'\t'<<int(m.use[i])<<'\t'<<why<<'\t'<<witness[n]<<'\n';
    }
}
static void invalidate(const Graph &g,std::vector<uint8_t> &dead,Counts &counts){
    std::vector<Id> offsets(g.nodes.size()+1);
    for(Id p:g.parents)++offsets[p+1];
    for(size_t i=1;i<offsets.size();++i)offsets[i]+=offsets[i-1];
    auto cursor=offsets;std::vector<Id> children(g.parents.size()),queue;
    for(Id i=1;i<g.nodes.size();++i)for(Id j=g.begin(i);j<g.nodes[i].end;++j)children[cursor[g.parents[j]]++]=i;
    for(Id i=0;i<dead.size();++i)if(dead[i])queue.push_back(i);
    counts["seeds"]=queue.size();
    for(size_t k=0;k<queue.size();++k){
        Id n=queue[k];
        for(Id j=offsets[n];j<offsets[n+1];++j){Id x=children[j];if(!dead[x]){dead[x]=1;queue.push_back(x);}}
    }
    counts["invalidated"]=queue.size();
}
int main(int argc,char **argv){
    if(argc!=10){std::cerr<<"usage: select42 proof old new variables declarations out n0 n1 semantic|structure\n";return 2;}
    try{
        std::string out=argv[6],mode=argv[9];need(mode=="semantic" || mode=="structure","unknown mapping");
        Counts c;auto start=Clock::now();Graph g(argv[1]);Models m(std::stoi(argv[7]),std::stoi(argv[8]),g.occurrence_count);
        auto reached=g.reach();std::vector<Id> input_node(size_t(g.occurrence_count)+1);
        for(Id i=1;i<g.nodes.size();++i)if(g.nodes[i].type==InputLeaf && reached[i]){
            const Id occurrence=g.nodes[i].payload;input_node.at(occurrence)=i;m.use.at(occurrence)=reached[i];
            m.scope.at(occurrence)=g.nodes[i].flags==0?'B':g.nodes[i].flags==Query?'Q':'U';
        }
        m.map(argv[4]);m.read(argv[2],false);m.read(argv[3],true);auto decl=bindings(g,argv[5]);
        c["read_ns"]=elapsed(start);c["p0_inputs"]=m.p0_rows;c["p1_inputs"]=m.p1_rows;
        auto witness=output(out,"structure.tsv");witness<<"round\told_var\tnew_signed_positive\told_occurrence\tnew_occurrence\n";
        Refinement r;auto t=Clock::now();if(mode=="structure")r.run(m,witness);witness.close();
        c["structural_ns"]=elapsed(t);c["rounds"]=r.rounds;c["checks"]=r.checks;c["added"]=r.added;c["ambiguous_signatures"]=r.ambiguous;c["collisions"]=r.collisions;
        auto map=output(out,"effective-map.tsv");map<<"side\tvariable\tpeer\tordinary\n";
        for(int side=0;side<2;++side){const auto &a=side?m.b:m.a;
            for(size_t v=1;v<a.peer.size();++v){
                if(!side && a.peer[v]>=0)++c[a.ordinary[v]?"mapped_ordinary":"mapped_interface_or_other"];
                map<<side<<'\t'<<v<<'\t'<<a.peer[v]<<'\t'<<int(a.ordinary[v])<<'\n';
            }
        }
        map.close();std::vector<uint8_t> dead(g.nodes.size());dead[0]=1;t=Clock::now();
        membership(g,m,input_node,dead,c,out);
        auto facts=output(out,"facts42.tsv");facts<<"op\ta\tb\tc\tuse\tstatus\n";
        for(Id i=1;i<g.nodes.size();++i){auto &n=g.nodes[i];
            if(n.type==FactLeaf){
                const auto &f=g.facts[n.payload];auto it=decl.find(f);need(it!=decl.end(),"missing P0 declaration");
                char state=it->second;
                if(state=='M' && (f[0]==RFDecl||f[0]==GuardDecl) && f[3]>=2)need(m.a.translate(f[3])!=INT_MIN,"unmapped theory port");
                dead[i]=state!='M';if(reached[i])++c[std::string("used_theory_")+state];
                if(reached[i])facts<<f[0]<<'\t'<<f[1]<<'\t'<<f[2]<<'\t'<<f[3]<<'\t'<<int(reached[i])<<'\t'<<state<<'\n';
            }else if(n.type==OpaqueLeaf || (n.type==InputLeaf && n.flags))dead[i]=1;
        }
        facts.close();c["membership_ns"]=elapsed(t);t=Clock::now();invalidate(g,dead,c);c["reverse_ns"]=elapsed(t);
        auto cat=output(out,"catalog42.tsv"),rows=output(out,"batch-rows.tsv");
        cat<<"ordinal\tnative_id\tflags\thas_b\tsupport_alive\tconclusion_mapped\teligible\n";
        for(size_t i=0;i<g.births.size();++i){
            const auto &x=g.births[i];const auto &n=g.nodes[x.node];bool mapped=true;
            for(Id j=g.litBegin(i);j<x.end;++j)if(m.a.translate(g.lits[j])<2)mapped=false;
            bool alive=!dead[x.node] && !(n.flags&7),ok=mapped&&alive;const char family=n.flags&CertifiedTheory?(n.has_b?'M':'T'):'B';
            ++c["births"];c["permanent"]+=!(n.flags&7);c["alive"]+=alive;c["mapped"]+=mapped;c["eligible"]+=ok;
            c["query"]+=bool(n.flags&Query);c["unknown"]+=bool(n.flags&(Theory|Incomplete));
            if(!(n.flags&7))++c[std::string("permanent_")+family];
            if(ok){++c[std::string("eligible_")+family];rows<<i+1<<'\t'<<family<<'\t'<<(x.end-g.litBegin(i));
                for(Id j=g.litBegin(i);j<x.end;++j)rows<<'\t'<<m.a.translate(g.lits[j]);
                rows<<'\n';
            }
            cat<<i+1<<'\t'<<x.original<<'\t'<<int(n.flags)<<'\t'<<int(n.has_b)<<'\t'<<alive<<'\t'<<mapped<<'\t'<<ok<<'\n';
        }
        rows.close();cat.close();c["nodes"]=g.nodes.size();c["edges"]=g.parents.size();c["total_ns"]=elapsed(start);
        auto metrics=output(out,"transport.tsv");for(auto &kv:c)metrics<<kv.first<<'\t'<<kv.second<<'\n';
        metrics<<"stop\t"<<r.stop<<'\n';
    }catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
