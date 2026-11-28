#pragma once
#include "session_contract.h"
#include <linux/if_alg.h>
#include <sys/socket.h>
#include <unistd.h>
#include <cstring>
#include <sys/resource.h>
#include <algorithm>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <sstream>
#include <stdexcept>

using namespace deagle_pi;
namespace {
void require(bool ok,const std::string &msg){if(!ok)throw std::runtime_error(msg);}
std::string json(const std::string &s){
    std::ostringstream out;out<<'"';
    for(unsigned char c:s){if(c=='"'||c=='\\')out<<'\\'<<c;else if(c<32)out<<"\\u"<<std::hex<<std::setw(4)<<std::setfill('0')<<int(c)<<std::dec;else out<<c;}
    out<<'"';return out.str();
}
LocalLit literal(int x){
    if(x<0){require(x==-1||x==-2,"invalid constant");return {x==-1?LiteralKind::constant_true:LiteralKind::constant_false,{0},false};}
    return {LiteralKind::variable,{unsigned(x/2)},bool(x&1)};
}
int num(const std::string &s){
    size_t k=0;int i=std::stoi(s,&k);require(k==s.size(),"bad integer");return i;
}
unsigned nat(const std::string &s){int i=num(s);require(i>=0,"negative index");return unsigned(i);}
std::vector<std::string> split(const std::string &s){
    std::vector<std::string> f;size_t pos=0;
    for(;;){size_t next=s.find('\t',pos);f.emplace_back(s.substr(pos,next-pos));if(next==std::string::npos)return f;pos=next+1;}
}
// Linux SHA-256 provider. Hash the same bytes the parser consumes, in bounded chunks.
class StreamSeal {
    int parent=-1, op=-1;
    std::string buffer;
    void sendBlock(int flags) {
        auto n=send(op,buffer.data(),buffer.size(),flags);
        require(n==static_cast<ssize_t>(buffer.size()),"SHA256 write");buffer.clear();
    }
public:
    StreamSeal(){
        sockaddr_alg address{};address.salg_family=AF_ALG;
        std::strcpy(reinterpret_cast<char*>(address.salg_type),"hash");
        std::strcpy(reinterpret_cast<char*>(address.salg_name),"sha256");
        parent=socket(AF_ALG,SOCK_SEQPACKET,0);
        require(parent>=0 && bind(parent,reinterpret_cast<sockaddr*>(&address),sizeof(address))==0,"SHA256 provider");
        op=accept(parent,nullptr,nullptr);require(op>=0,"SHA256 stream");
    }
    ~StreamSeal(){if(op>=0)::close(op);if(parent>=0)::close(parent);}
    void line(const std::string &s){buffer+=s;buffer+='\n';if(buffer.size()>=65536)sendBlock(MSG_MORE);}
    std::string finish(){sendBlock(0);unsigned char digest[32];require(read(op,digest,sizeof(digest))==32,"SHA256 digest");
        std::ostringstream hex;for(auto v:digest)hex<<std::hex<<std::setw(2)<<std::setfill('0')<<unsigned(v);return hex.str();}
};
ModelTransaction readTransaction(const std::string &path){
    std::ifstream file(path,std::ios::binary),seal(path+".sha256");
    std::string expected;seal>>expected;require(file && expected.size()==64,"missing transaction or seal: "+path);
    ModelTransaction m{};auto &q=m.first_query;
    StreamSeal ctx;std::string line;
    uint64_t occurrence=0,expectedInputs=0;bool header=false,end=false;
    while(std::getline(file,line)){
        require(!end && !file.eof(),"unsealed trailing records or truncated line");
        ctx.line(line);
        auto f=split(line);
        auto at=[&](size_t n)->const std::string&{return f.at(n);};
        if(!header){
            require(f.size()==4&&f[0]=="PI1.1","bad header");
            m.native_variable_count=q.native_variable_count_at_boundary=nat(at(1));q.id={nat(at(2))};
            m.graph.rules_version=at(3);header=true;continue;
        }
        if(f[0]=="CONFIG"){require(m.complete_configuration.empty(),"duplicate config");m.complete_configuration=at(1);}
        else if(f[0]=="B"||f[0]=="Q"){
            InputOccurrence c{};c.scope=f[0]=="B"?InputScope::model:InputScope::query;c.occurrence=occurrence++;
            for(size_t i=1;i<f.size();++i)c.literals.push_back(literal(num(at(i))));
            (c.scope==InputScope::model?m.inputs:q.scoped_inputs).push_back(std::move(c));
        }else if(f[0]=="NODE"){
            require(f.size()==7,"bad node");m.graph.events.push_back({at(1),at(2),bool(nat(at(3))),bool(nat(at(4))),bool(nat(at(5))),num(at(6))});
        }else if(f[0]=="EDGE"){
            static const std::map<std::string,Relation> kinds={{"po",Relation::po},{"apo",Relation::apo},{"rf",Relation::rf},{"race",Relation::race}};
            m.graph.edges.push_back({kinds.at(at(1)),{nat(at(2))},{nat(at(3))},literal(num(at(4)))});
        }else if(f[0]=="GUARD")m.graph.guards.push_back({{nat(at(1))},literal(num(at(2)))});
        else if(f[0]=="BLOCK"||f[0]=="DOMAIN"){
            std::vector<EventId> ids;for(size_t i=f[0]=="BLOCK"?1:2;i<f.size();++i)ids.push_back({nat(at(i))});
            if(f[0]=="BLOCK")m.graph.atomic_blocks.push_back(std::move(ids));else m.graph.candidate_writes.emplace_back(EventId{nat(at(1))},std::move(ids));
        }else if(f[0]=="BASE"){require(m.predecessor_receipt.empty() && f.size()==2,"duplicate predecessor");m.predecessor_receipt=at(1);}
        else if(f[0]=="MATCH")m.certified_matches.push_back({{nat(at(1))},literal(num(at(2))),at(3)});
        else if(f[0]=="EVENTMATCH")m.certified_events.push_back({{nat(at(1))},{nat(at(2))}});
        else if(f[0]=="ASSUME")q.native_assumptions.push_back(literal(num(at(1))));
        else if(f[0]=="GOAL")q.goals.push_back(literal(num(at(1))));
        else if(f[0]=="TARGET")q.properties.push_back(at(1));
        else if(f[0]=="UNWIND")q.unwind_obligations.push_back(at(1));
        else if(f[0]=="NEWATOM")q.new_query_atoms.push_back({{nat(at(1))},{AtomRole::ordinary},{}});
        else if(f[0]=="END"){expectedInputs=nat(at(1));end=true;}else throw std::runtime_error("unknown transaction record");
    }
    require(end&&expectedInputs==occurrence&&ctx.finish()==expected,"invalid transaction seal or occurrence count");
    m.model_receipt=expected;
    return m;
}
long rss(){rusage u;getrusage(RUSAGE_SELF,&u);return u.ru_maxrss;}
}
