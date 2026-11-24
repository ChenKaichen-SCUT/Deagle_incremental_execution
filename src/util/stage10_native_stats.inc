if(!s10::directory().empty()) {
  std::ofstream os(s10::directory()+"/native-state.tsv", std::ios::app);
  os<<s10::now()<<"\t"<<reinterpret_cast<uintptr_t>(this)<<"\t"<<getpid()<<"\t"<<nVars()<<"\t"<<nClauses()
    <<"\t"<<nLearnts()<<"\t"<<nAssigns()<<"\t"<<decisionLevel()<<"\t"<<(ok?1:0)<<"\t"<<ca.size()*sizeof(uint32_t)
    <<"\t"<<starts<<"\t"<<decisions<<"\t"<<conflicts<<"\t"<<propagations<<"\t"<<theory_propagation<<"\t"<<conflict_cycle
    <<"\t"<<graph.nodes.size()<<"\t"<<s10::rss_kib()<<"\n";
}
