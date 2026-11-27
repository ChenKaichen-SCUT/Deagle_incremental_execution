#include "dependency_group_sources.h"
#include "dependency_manifest.h"
#include <cstring>
#include <stdexcept>

namespace dependency_manifest {
group_sourcest *group_sources=nullptr;
namespace {
std::string quote(const std::string &s)
{
  std::string out="\"";
  for(char c:s) {
    if(c=='"' || c=='\\')out+='\\';
    out+=c;
  }
  return out+'"';
}
}
void group_sourcest::row(const char *tag,const std::vector<std::string> &v)
{
  if(!std::strcmp(tag,"X")) {
    contexts.emplace(std::stoi(v.at(0)),std::make_pair(std::stoi(v.at(1)),std::stoi(v.at(2))));
  } else if(!std::strcmp(tag,"E")) {
    int ctx=std::stoi(v.at(1));auto it=contexts.find(ctx);
    std::string key;
    if(it!=contexts.end() && it->second.second>=0)
      key="["+std::to_string(it->second.first)+","+std::to_string(it->second.second);
    else if(ctx==-2)key="[\"initial\",-2";
    if(!key.empty())key+=","+quote(escape(v.at(2)))+","+quote(escape(v.at(3)))+","+quote(escape(v.at(5)))+"]";
    auto put=events.emplace(v.at(0),key);
    if(!put.second && put.first->second!=key)put.first->second.clear();
  }
}
void group_sourcest::enter(const char *name,int ctx,unsigned thread)
{
  phase=name;auto it=contexts.find(ctx);
  owner=it==contexts.end()?nullptr:intern("[\"B\",\"ssa\","+quote(name)+","+
            std::to_string(it->second.first)+","+std::to_string(thread)+"]");
}
void group_sourcest::gate(const char *op,int raw)
{
  if(raw<2)return;
  size_t atom=unsigned(raw)/2;
  if(atom>=gates.size())gates.resize(atom+1);
  if(!gates[atom].second)gates[atom]={++sequence,owner?owner:
    intern("[\"B\",\"gate\","+quote(op)+","+std::to_string(atom)+"]")};
}
const std::string &group_sourcest::boolean(const int *raw,size_t n)
{
  if(owner)return *owner;
  std::pair<uint32_t,const std::string*> best{};
  for(size_t i=0;i<n;++i)
    if(raw[i]>=2 && size_t(raw[i]/2)<gates.size() && gates[raw[i]/2].first>best.first)best=gates[raw[i]/2];
  return best.second?*best.second:*intern("[\"B\",\"fallback\","+quote(phase)+"]");
}
void group_sourcest::node(int id,const std::string &name)
{
  if(size_t(id)!=node_names.size())throw std::logic_error("nonsequential Closure node");
  node_names.push_back(name);
}
std::string group_sourcest::theory(int op,int a,int b) const
{
  static const char *const names[]={"Config","PO","APO","RF","Guard","Schema","SameAddress","Block"};
  if(op<0 || op>7)throw std::logic_error("invalid structural premise");
  std::string rule=quote(names[op]), result="[\"T\",\"decl\","+rule;
  if(op==0)return result+"]";
  auto event=[&](int x){
    auto it=events.find(node_names.at(x));return it==events.end()?std::string{}:it->second;
  };
  auto x=event(a);bool pair=op==1||op==2||op==3||op==6;auto y=pair?event(b):std::string{};
  if(x.empty()||(pair&&y.empty()))return "[\"T\",\"fallback\","+rule+"]";
  if(op==6 && y<x)std::swap(x,y);
  return result+","+x+(pair?","+y:"")+"]";
}
}
