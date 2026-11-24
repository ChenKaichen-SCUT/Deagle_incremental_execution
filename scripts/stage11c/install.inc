  void install_dynamic(const std::string &dir,const std::string &mode,int variables,const std::string &approved){
    auto &state=c11::state();auto start=c11::now();
    std::istringstream in(approved);
    for(std::string row;std::getline(in,row);){
      std::istringstream fields(row);std::string id;int size;fields>>id>>size;
      session10::require(!id.empty() && (id[0]=='t'||id[0]=='c') && size>=1 && size<=128 &&
          (mode=="TC" || (id[0]=='t' && mode=="T") || (id[0]=='c' && mode=="C")),"bad import type");
      vec<Lit> clause;std::set<int> used_vars;int x;
      while(fields>>x){session10::require(x>=0 && x/2<variables && used_vars.insert(x/2).second,"bad import literal");clause.push(session10::literal(x));}
      session10::require(fields.eof() && clause.size()==size,"bad import length");
      int before=s.nClauses(),roots=s.nAssigns();
      s.addClause_(clause);
      std::string action="redundant";
      if(s.nClauses()>before){
          auto cr=s.clauses.last();state.imported[cr]={id,c11::sorted(c11::lits(s.ca[cr]))};action="attached";
      }else if(s.nAssigns()>roots || !s.okay()){action="root_propagation";++state.hits[{id,action}];}
      state.usage<<"import\t"<<id<<'\t'<<action<<'\t'<<before<<'\t'<<s.nClauses()<<'\t'<<roots<<'\t'<<s.nAssigns()<<"\n";
    }
    state.install_ns=c11::now()-start;
  }
