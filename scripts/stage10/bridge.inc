// Included in the native ClosureSolver::solve_ after the complete goal stream has been emitted.
if(std::getenv("S10_BRIDGE_FD")) {
    if(before_first_search) throw std::runtime_error("unexpected historical lemma callback");
    auto &stream=s8::state().sequence;
    if(!stream || std::fflush(stream)) throw std::runtime_error("missing complete solver input");
    int channel=std::stoi(std::getenv("S10_BRIDGE_FD"));
    char byte='R';
    if(::write(channel,&byte,1)!=1 || ::read(channel,&byte,1)!=1 || byte!='D')
        throw std::runtime_error("native solver worker disconnected");
    std::ifstream result(s10::directory()+"/answer.txt");
    int rc,n;
    if(!(result>>rc>>n) || (rc!=0 && rc!=1) || n!=nVars()) throw std::runtime_error("native reply shape");
    model.clear();conflict.clear();
    if(rc==0) {
      model.growTo(nVars());int val;
      for(int i=0;i<n;++i){if(!(result>>val)||val<0||val>2)throw std::runtime_error("bad native bit");model[i]=lbool(uint8_t(val));}
      int count; if(!(result>>count)||count<0)throw std::runtime_error("missing event order");
      oc_result_order->clear();
      for(int i=0;i<count;++i){std::string node;int order;if(!(result>>node>>order))throw std::runtime_error("bad event order");(*oc_result_order)[node]=order;}

      if(!(result>>count)||count<0)throw std::runtime_error("missing write order");
      ::write_order.clear();for(int i=0;i<count;++i){std::string name;if(!(result>>name))throw std::runtime_error("bad write order");::write_order.push_back(name);}
    }
    std::string extra;if(result>>extra)throw std::runtime_error("excess native reply");
    return rc==0?l_True:l_False;
}
