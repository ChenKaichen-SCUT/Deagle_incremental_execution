#include <util/c_types.h>
#include <util/namespace.h>
#include "boolbv.h"
#include <util/arith_tools.h>
#include <util/pointer_expr.h>
#include <util/stable_identity.h>
#include <functional>
#include <set>

// Record the layout the native flattener actually uses. References are local shape IDs.
// Cyclic pointee/tag graphs are described once, without evaluating any additional expression.
void boolbvt::describe_stable_layouts() const
{
  namespace si=stable_identity;
  std::set<si::Word> visited;
  std::function<void(const typet &)> visit=[&](const typet &t) {
    const auto id=si::type(t);
    if(!visited.insert(id).second) return;
    const auto k=t.id();
    const bool supported=k==ID_bool || k==ID_c_bool || k==ID_signedbv || k==ID_unsignedbv ||
      k==ID_pointer || k==ID_array || k==ID_struct || k==ID_union || k==ID_struct_tag || k==ID_union_tag;
    const auto width=supported ? bv_width.get_width_opt(t).value_or(0) : 0;
    si::row('K',{id,si::text(id2string(k)),si::Word(width)});
    auto child=[&](const typet &sub,const std::string &name,unsigned offset,unsigned size,bool padding) {
      si::row('M',{id,si::type(sub),si::text(name),offset,size,unsigned(padding)});visit(sub);
    };
    if(k==ID_struct_tag)
      child(ns.follow_tag(to_struct_tag_type(t)),"tag",0,width,false);
    else if(k==ID_union_tag)
      child(ns.follow_tag(to_union_tag_type(t)),"tag",0,width,false);
    else if(k==ID_struct || k==ID_union)
    {
      for(const auto &member:to_struct_union_type(t).components())
      {
        unsigned offset=0;
        unsigned size=bv_width.get_width_opt(member.type()).value_or(0);
        if(k==ID_struct)
        {
          const auto &place=bv_width.get_member(to_struct_type(t),member.get_name());
          offset=place.offset;size=place.width;
        }
        child(member.type(),id2string(member.get_name()),offset,size,member.get_is_padding());
      }
    }
    else if(k==ID_array)
      child(to_array_type(t).element_type(),"element",0,bv_width.get_width_opt(to_array_type(t).element_type()).value_or(0),false);
    else if(k==ID_pointer)
      child(to_pointer_type(t).base_type(),"pointee",0,0,false);
  };
  for(const auto &v:map.get_mapping()) visit(v.second.type);
}
