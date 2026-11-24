#pragma once
// Compare alternating assumptions on an unchanged native graph against a fresh native object each time.
static int repeat_graph(const std::string &capture,const std::string &out){
  auto shared_input=std::unique_ptr<Input>(new Input(capture));
  ClosureSolver shared;
  Stage10Epoch scope(shared);vec<Lit> goals;
  deliver(shared,scope,*shared_input,goals);
  std::ofstream rows(out+"/unchanged.tsv");
  rows<<"test\tlit\tshared\tfresh\tshared_ok\told_order_keys\tcurrent_keys\twritten_order\tfresh_order\n";
  std::vector<int> rf;
  for(const auto &e:shared_input->edges)if(e.second.second=="rf" && e.second.first.x>=0)rf.push_back(e.second.first.x);
  require(!rf.empty(),"no live RF atoms");
  for(int i=0;i<7;++i){
    int x=i==0?-1:rf[(i-1)/2]^((i-1)%2);
    Input control(capture);ClosureSolver fresh;Stage10Epoch reset(fresh);vec<Lit> fg,sg;
    deliver(fresh,reset,control,fg);goals.copyTo(sg);
    if(x>=0){fg.push(literal(x));sg.push(literal(x));}
    auto initial=shared_input->order;
    s10::where()=out+"/shared-"+std::to_string(i);
    int a=toInt(shared.solveLimited(sg));
    auto ranked=shared.get_write_order();
    s10::where()=out+"/fresh-"+std::to_string(i);
    int b=toInt(fresh.solveLimited(fg));
    rows<<i<<"\t"<<x<<"\t"<<a<<"\t"<<b<<"\t"<<shared.okay()<<"\t"<<initial.size()<<"\t"<<shared_input->order.size()
       <<"\t"<<ranked.size()<<"\t"<<(shared_input->order==control.order)<<"\n";
    if(a!=b)rows<<"disagreement\t"<<i<<"\n";
  }
  // A single nonempty native graph with two contradictory RF orders. Each selected
  // order is satisfiable on its own. The output map is owned by the caller.
  ClosureSolver toy;oc_edge_tablet edges;oc_guard_mapt guards;oc_location_mapt loc;
  std::map<std::string,int> order;
  auto a=mkLit(toy.newVar()),b=mkLit(toy.newVar());
  edges.push_back({{"obj#1","obj#2"},{a,"rf"}});
  edges.push_back({{"obj#2","obj#1"},{b,"rf"}});
  toy.addClause(~a,~b);
  toy.save_raw_graph(edges,guards,loc,order);
  std::ofstream file(out+"/rf-direction.tsv");
  for(int i=0;i<2;++i){
    vec<Lit> g;g.push(i?b:a);g.push(i?~a:~b);
    s10::where()=out+"/direction-"+std::to_string(i);
    int result=toInt(toy.solveLimited(g));
    file<<i<<"\t"<<result<<"\t"<<order["obj#1"]<<"\t"<<order["obj#2"]<<"\t";
    for(auto &n:toy.get_write_order())file<<n<<" ";
    file<<"\n";
  }
  return 0;
}
