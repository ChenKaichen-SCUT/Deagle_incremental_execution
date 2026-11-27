// Stable provenance for the small subset of native learnt clauses imported from P0.
#ifndef MINISAT_CLAUSE_IMPORTS_H
#define MINISAT_CLAUSE_IMPORTS_H

#include "SolverTypes.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <fstream>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

namespace Minisat
{
enum ImportUse { WatchUnit, WatchConflict, AnalyzeParent, MinimizeParent, ImportUseCount };
struct ImportRow
{
    uint32_t id;
    char family;
    std::vector<int> translated, installed, removed_false;
    std::string disposition;
    CRef first_ref=CRef_Undef, current_ref=CRef_Undef;
    int root_witness=-1;
    uint64_t moves=0;
    std::array<uint64_t,ImportUseCount> hits{};
    ImportRow(uint32_t id,char family): id(id),family(family) {}
};

struct ImportWitness
{
    size_t row;
    ImportUse use;
    CRef ref;
    int level, literal;
    uint64_t conflict;
    std::vector<int> clause;
};

// Records only successful watcher actions, visited UIP parents and reasons in
// successful minimization. Clause relocation changes references, never row IDs.
class ClauseImports
{
    std::map<CRef,size_t> live;
    CRef low=CRef_Undef, high=0;
    std::vector<size_t> trial;
    void range()
    {
        low=live.empty()?CRef_Undef:live.begin()->first;
        high=live.empty()?0:live.rbegin()->first;
    }
public:
    std::vector<ImportRow> rows;
    std::vector<ImportWitness> witnesses;
    uint64_t import_ns=0;
    unsigned collections=0;
    void read(const std::string &path,int expected_vars)
    {
        std::ifstream in(path);
        std::string magic;
        int vars;
        size_t count;
        if(!rows.empty() || !(in>>magic>>vars>>count) || magic!="D4-selected-v1" || vars!=expected_vars)
            throw std::runtime_error("D4 candidate batch belongs to a different boundary");
        for(size_t i=0;i<count;++i)
        {
            uint32_t id; char family; size_t length;
            if(!(in>>id>>family>>length) || length>size_t(vars)*2)
                throw std::runtime_error("invalid selected row");
            rows.emplace_back(id,family);
            for(size_t j=0;j<length;++j)
            {
                int raw;
                if(!(in>>raw)) throw std::runtime_error("truncated selected clause");
                rows.back().translated.push_back(raw);
            }
        }
        in>>std::ws;
        if(!in.eof()) throw std::runtime_error("extra selected literals");
    }
    void bind(size_t row,CRef ref)
    {
        if(!live.emplace(ref,row).second) throw std::logic_error("duplicate live import reference");
        rows[row].first_ref=rows[row].current_ref=ref;
        range();
    }
    void forget(CRef ref)
    {
        if(ref<low || ref>high) return;
        auto it=live.find(ref);
        if(it==live.end()) return;
        rows[it->second].current_ref=CRef_Undef;
        live.erase(it);
        range();
    }
    void relocated(const ClauseAllocator &old)
    {
        ++collections;
        std::map<CRef,size_t> moved;
        for(const auto &entry:live)
        {
            const auto &c=old[entry.first];
            if(!c.reloced()) throw std::logic_error("live import missing from relocated database");
            auto ref=c.relocation();
            auto &row=rows[entry.second];
            if(!moved.emplace(ref,entry.second).second) throw std::logic_error("import relocation collision");
            row.moves+=entry.first!=ref;
            row.current_ref=ref;
        }
        moved.swap(live);
        range();
    }
    void hit(CRef ref,ImportUse use,int level,int literal,uint64_t conflict,const Clause &c)
    {
        if(ref<low || ref>high) return;
        auto it=live.find(ref);
        if(it==live.end()) return;
        auto &row=rows[it->second];
        if(row.hits[use]++==0)
        {
            witnesses.push_back({it->second,use,ref,level,literal,conflict,{}});
            for(int i=0;i<c.size();++i) witnesses.back().clause.push_back(c[i].x);
        }
    }
    void beginTrial() { trial.clear(); }
    void visitTrial(CRef ref)
    {
        if(ref<low || ref>high) return;
        auto it=live.find(ref);
        if(it!=live.end()) trial.push_back(it->second);
    }
    void commitTrial(const ClauseAllocator &ca,int level,uint64_t conflict)
    {
        for(auto index:trial)
        {
            CRef ref=rows[index].current_ref;
            hit(ref,MinimizeParent,level,ca[ref][0].x,conflict,ca[ref]);
        }
        trial.clear();
    }
    void write(const std::string &dir) const
    {
        std::ofstream out(dir+"/imports.tsv"), first(dir+"/hits.tsv");
        out.exceptions(std::ios::failbit|std::ios::badbit);
        first.exceptions(std::ios::failbit|std::ios::badbit);
        out<<"id\tfamily\tdisposition\tfirst_cref\tcurrent_cref\tmoves\troot_witness\twatch_unit\twatch_conflict\tanalyze\tminimize\ttranslated\tinstalled\troot_false\n";
        auto lits=[&](const std::vector<int> &v) {
            out<<'\t';
            for(size_t i=0;i<v.size();++i){ if(i)out<<' '; out<<v[i]; }
        };
        for(const auto &r:rows)
        {
            out<<r.id<<'\t'<<r.family<<'\t'<<r.disposition<<'\t'<<r.first_ref<<'\t'<<r.current_ref
               <<'\t'<<r.moves<<'\t'<<r.root_witness;
            for(auto h:r.hits) out<<'\t'<<h;
            lits(r.translated);lits(r.installed);lits(r.removed_false);out<<'\n';
        }
        first<<"id\tuse\tcref\tlevel\traw_literal\tconflict_counter\tclause\n";
        for(const auto &e:witnesses)
        {
            first<<rows[e.row].id<<'\t'<<int(e.use)<<'\t'<<e.ref<<'\t'<<e.level<<'\t'<<e.literal<<'\t'<<e.conflict<<'\t';
            for(size_t i=0;i<e.clause.size();++i){if(i) first<<' ';first<<e.clause[i];}
            first<<'\n';
        }
        out.close();first.close();
    }
};
}
#endif
