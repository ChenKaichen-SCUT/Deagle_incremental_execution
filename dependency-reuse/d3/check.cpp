// Exact local rule replay on the P0 graph declarations. The solver library is not linked.
#include "../d2/check_core.h"
#include <array>

namespace {
struct Site { int rep,address,read,write; };
using Key=std::array<int,4>;
struct GraphModel {
    std::map<int,Site> nodes;
    std::set<std::pair<int,int>> within,reverse;
    std::map<Key,char> declarations;
    std::vector<char> graph_receipt;

    explicit GraphModel(const std::string &path)
    {
        std::ifstream f(path); require(bool(f),"missing P0 declaration table");
        std::string line;
        while(std::getline(f,line))
        {
            if(line.compare(0,2,"G\t")==0)
            {
                graph_receipt.insert(graph_receipt.end(),line.begin()+2,line.end());
                graph_receipt.push_back('\n');
                continue;
            }
            std::istringstream row(line);
            char kind; require(bool(row>>kind),"empty declaration row");
            int a,b;
            if(kind=='N')
            {
                Site s;
                require(bool(row>>a>>s.rep>>s.address>>s.read>>s.write) && a>=0 && s.rep>=0 &&
                        (s.read==0 || s.read==1) && (s.write==0 || s.write==1) &&
                        nodes.emplace(a,s).second,"invalid local event");
            }
            else if(kind=='I' || kind=='O')
            {
                require(bool(row>>a>>b),"bad block direction");
                if(kind=='O') within.emplace(a,b); else reverse.emplace(b,a);
            }
            else if(kind=='D')
            {
                Key key; char status;
                require(bool(row>>key[0]>>key[1]>>key[2]>>key[3]>>status) &&
                        (status=='M' || status=='C' || status=='U'),"invalid D1 declaration");
                auto r=declarations.emplace(key,status);
                require(r.second || r.first->second==status,"contradictory declaration delta");
            }
            else throw std::runtime_error("unknown declaration table row");
            row>>std::ws; require(row.eof(),"trailing declaration fields");
        }
        require(f.eof() && within==reverse,"inconsistent block direction tables");
        for(const auto &item:nodes)
            require(nodes.at(item.second.rep).rep==item.second.rep,"non-final representative");
        for(auto p:within)
            require(nodes.at(p.first).rep==nodes.at(p.second).rep && p.first!=p.second,"order outside block");
    }
};

// Scalar comparisons and exact unions of the conditions used by the premises.
// Facts about order, guard truth and conditional contradictions live in different sorts.
enum Sort { BaseFact, Before, Active, Contradiction };
struct Judgement {
    Sort sort;
    int from,to;
    std::vector<int> conditions;
};
struct TheoryAudit {
    const GraphModel &m;
    Analysis &a;
    ProofStore &g;
    std::vector<unsigned> index;
    std::vector<Judgement> facts;
    explicit TheoryAudit(const GraphModel &model,Analysis &analysis)
        :m(model),a(analysis),g(a.g),index(g.nodes.size(),UINT32_MAX) {}

    const TheoryRecord &record(ProofId id) const { return g.theory_records.at(index.at(id)); }
    void replay()
    {
        auto &counts=a.metrics;
        counts["discharge_missing"]=g.discharge_stats[0];
        counts["discharge_mismatch"]=g.discharge_stats[1];
        counts["discharge_matched"]=g.discharge_stats[2];
        counts["complete_theory_reasons"]=0;
        counts["opaque_theory_reasons"]=0;
        size_t next=0;
        uint64_t opaque_boundaries=0;
        for(ProofId i=1;i<g.nodes.size();++i)
        {
            auto kind=g.nodes[i].kind;
            if(kind==TheoryDeclaration || kind==TheoryInference)
            {
                require(next<g.theory_records.size() && g.theory_records[next].id==i,"theory directory out of order");
                index[i]=static_cast<unsigned>(next);
                const auto &r=g.theory_records[next++];
                const uint32_t begin=g.edgeBegin(i),end=g.nodes[i].edge_end;
                require(g.litBegin(i)==g.nodes[i].lit_end,"unexpected Boolean conclusion in a relation");
                std::vector<ProofId> ps;
                for(auto j=begin;j<end;++j)
                {
                    auto parent=g.edges[j].parent;
                    require(parent<i && index.at(parent)!=UINT32_MAX,"non-theory premise in relation");
                    ps.push_back(parent);
                }
                try { facts.emplace_back(relation(r,kind,ps)); }
                catch(const std::exception &e) {
                    throw std::runtime_error("theory node "+std::to_string(i)+" op "+std::to_string(r.op)+": "+e.what());
                }
                ++counts["op_"+std::to_string(r.op)];
            }
            else if(kind==TheoryLemma)
            {
                require(g.nodes[i].edge_end==g.edgeBegin(i)+1,"lemma arity");
                auto parent=g.edges.at(g.edgeBegin(i)).parent;
                const auto &f=facts.at(index.at(parent));
                require(f.sort==Contradiction,"open relation published as lemma");
                auto clause=f.conditions;
                for(int &lit:clause) lit^=1;
                require(normalized(clause)==normalized(content(g,i)),"discharged theory clause differs at "+std::to_string(i));
                ++counts["complete_theory_reasons"];
                ++counts["lemma_op_"+std::to_string(record(parent).op)];
            }
            else if(theory(kind))
            {
                ++counts["opaque_theory_reasons"];
                if(kind==TheoryConflict || kind==TheoryReason) ++opaque_boundaries;
            }
        }
        require(next==g.theory_records.size(),"extra theory directory entries");
        require(counts["complete_theory_reasons"]==g.discharge_stats[2] &&
                g.discharge_stats[0]<=opaque_boundaries &&
                g.discharge_stats[1]==opaque_boundaries-g.discharge_stats[0],"invalid native discharge counters");
    }

    Judgement relation(const TheoryRecord &r,uint32_t kind,const std::vector<ProofId> &ps)
    {
        const auto op=r.op;
        const int x=r.a,y=r.b,z=r.c;
        const Key key{{int(op),x,y,z}};
        if(kind==TheoryDeclaration)
        {
            require(ps.empty() && op>=Config && op<=BlockDecl,"bad declaration op or arity");
            const char status=m.declarations.at(key);
            a.decl_matched.push_back(status=='M');
            if(status!='M') a.causes[r.id] |= status=='C' ? 256 : 512;
            switch(op) {
            case Config: require(x==-1 && y==-1 && z==-1,"config payload"); break;
            case PODecl: case APODecl:
                require(m.nodes.count(x) && m.nodes.count(y) && z==-1,"order endpoint");
                break;
            case RFDecl: require(m.nodes.at(x).write && m.nodes.at(y).read && z>=0,"RF binding"); break;
            case GuardDecl: require(m.nodes.at(x).write && y==-1 && z>=-2,"guard binding"); break;
            case SchemaDecl: require(m.nodes.count(x) && y==-1 && z==-1,"event schema"); break;
            case AddressDecl: require(x<=y && m.nodes.at(x).address==m.nodes.at(y).address && z==-1,"same address"); break;
            case BlockDecl: require(m.nodes.at(x).rep==x && y==-1 && z==-1,"block certificate"); break;
            default: throw std::runtime_error("unsupported declaration");
            }
            return {BaseFact,x,y,{}};
        }
        auto arity=[&](size_t n){require(ps.size()==n,"rule arity");};
        auto at=[&](unsigned i)->const Judgement&{return facts.at(index.at(ps.at(i)));};
        auto bound=[&](unsigned i,TheoryOp expected,int u,int v,int raw) {
            const auto &d=record(ps.at(i));
            require(d.op==expected && d.a==u && d.b==v && d.c==raw,"rule refers to a different premise");
        };
        auto ordered=[&](unsigned i,int u,int v) {
            require(at(i).sort==Before && at(i).from==u && at(i).to==v,"order endpoints");
        };
        auto config=[&](){bound(0,Config,-1,-1,-1);};
        auto address=[&](unsigned i,int u,int v) {bound(i,AddressDecl,std::min(u,v),std::max(u,v),-1);};
        Judgement result={Before,x,y,{}};
        for(auto p:ps) {
            const auto &conds=facts.at(index.at(p)).conditions;
            result.conditions.insert(result.conditions.end(),conds.begin(),conds.end());
        }
        switch(op) {
        case POEdge: case APOEdge:
            arity(2); config(); bound(1,op==POEdge ? PODecl : APODecl,x,y,-1);
            require(z==-1,"PO edge payload"); break;
        case RFEdge: {
            arity(5); config();
            int lit=record(ps[1]).c;
            bound(1,RFDecl,x,y,lit); bound(2,SchemaDecl,x,-1,-1); bound(3,SchemaDecl,y,-1,-1);
            address(4,x,y);
            require(lit>=0 && z==-1 && x!=y && m.nodes.at(x).write && m.nodes.at(y).read,"RF endpoint schema");
            result.conditions.push_back(lit); break;
        }
        case GuardOn: {
            arity(2); config(); int lit=record(ps[1]).c; bound(1,GuardDecl,x,-1,lit);
            require(y==-1 && z==-1 && (lit==-1 || lit>=0),"inactive or invalid guard");
            result.sort=Active;
            if(lit>=0) result.conditions.push_back(lit);
            break;
        }
        case Lift: {
            arity(3); const auto &source=at(0);
            require(z==-1 && source.sort==Before,"lifted edge");
            int u=m.nodes.at(source.from).rep,v=m.nodes.at(source.to).rep;
            bound(1,BlockDecl,u,-1,-1); bound(2,BlockDecl,v,-1,-1);
            require(u!=v && m.nodes.at(x).rep==u && m.nodes.at(y).rep==v,"atomic block lift"); break;
        }
        case Transitive: {
            require(z==-1 && !ps.empty() && ps.size()<=3,"transitive chain length");
            int cursor=x;
            for(unsigned j=0;j<ps.size();++j) {
                require(at(j).sort==Before && at(j).from==cursor,"disconnected order chain");
                cursor=at(j).to;
            }
            require(cursor==y,"transitive endpoint"); break;
        }
        case WSRule: case FRRule:
            arity(6); require(x!=y && x!=z && y!=z && m.nodes.at(y).write,"competing write schema");
            bound(0,RFEdge,x,z,-1);
            if(op==WSRule) ordered(1,y,z); else ordered(1,x,y);
            bound(2,GuardOn,x,-1,-1); bound(3,GuardOn,y,-1,-1);
            bound(4,SchemaDecl,y,-1,-1); address(5,x,y);
            result.from=op==WSRule ? y : z; result.to=op==WSRule ? x : y;
            break;
        case CycleRule:
            arity(x==y ? 1 : 2); require(z==-1,"cycle payload"); ordered(0,x,y);
            if(x!=y) ordered(1,y,x);
            result.sort=Contradiction; break;
        case PreventRF:
            arity(2); require(z==-1,"prevention payload"); ordered(0,y,x); bound(1,RFEdge,x,y,-1);
            result.sort=Contradiction; break;
        case TripletRule:
            require(g.triplets,"triplet inference reserved in D3");
            arity(6);
            require(x!=y && y!=z && x!=z && m.nodes.at(x).write && m.nodes.at(y).write &&
                    m.nodes.at(z).read,"triplet event roles");
            ordered(0,x,y); ordered(1,y,z); bound(2,RFEdge,x,z,-1);
            bound(3,GuardOn,y,-1,-1); bound(4,SchemaDecl,y,-1,-1); address(5,x,y);
            result.sort=Contradiction; break;
        default: throw std::runtime_error("unsupported inference");
        }
        result.conditions=normalized(std::move(result.conditions));
        return result;
    }

    void witness(const std::string &dir)
    {
        if(!a.mixed_witness) return;
        std::vector<ProofId> stack{a.mixed_witness}; std::set<ProofId> used;
        while(!stack.empty()) {
            auto i=stack.back();stack.pop_back();
            if(used.insert(i).second)
                for(auto j=g.edgeBegin(i);j<g.nodes[i].edge_end;++j) stack.push_back(g.edges[j].parent);
        }
        std::ofstream out(dir+"/mixed-witness.tsv");out.exceptions(std::ios::failbit|std::ios::badbit);
        out<<"ROOT\t"<<a.mixed_witness<<'\n';
        for(auto i:used) {
            const auto &n=g.nodes[i];
            out<<"NODE\t"<<i<<'\t'<<n.kind<<'\t'<<n.flags<<"\tL";
            for(auto j=g.litBegin(i);j<n.lit_end;++j) out<<'\t'<<g.lits[j];
            out<<"\tP";
            for(auto j=g.edgeBegin(i);j<n.edge_end;++j) out<<'\t'<<g.edges[j].parent<<'/'<<g.edges[j].pivot;
            if(index[i]!=UINT32_MAX) {
                auto &r=record(i);out<<"\tT\t"<<r.op<<'\t'<<r.a<<'\t'<<r.b<<'\t'<<r.c;
                out<<"\tC"; for(auto c:facts.at(index[i]).conditions) out<<'\t'<<c;
            }
            out<<'\n';
        }
    }
};
}

int main(int argc,char **argv)
{
    if(argc!=7) return 2;
    try {
        ProofStore g;
        const int status=g.read(argv[1]);
        require(g.d3 && (status==0 || status==10),"requires a completed D3 archive");
        Analysis a(g);
        GraphModel m(argv[5]);
        require(m.graph_receipt==g.graph_receipt,"P0 native graph receipt mismatch");
        verifyGraph(g,a.metrics,true);
        TheoryAudit audit(m,a);
        audit.replay();
        checkNative(g,argv[4]);
        a.inputs(argv[2]);
        readMapping(a,argv[3]);
        a.classify(argv[6],true);
        audit.witness(argv[6]);
    }
    catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
