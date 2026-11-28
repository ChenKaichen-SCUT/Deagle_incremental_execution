/*******************************************************************\

Module:

Author: Daniel Kroening, kroening@kroening.com

\*******************************************************************/


#include <util/stable_identity.h>
#include "boolbv.h"

bvt boolbvt::convert_if(const if_exprt &expr)
{
  std::size_t width=boolbv_width(expr.type());

  if(width==0)
    return bvt(); // An empty bit-vector if.

  literalt cond=convert(expr.cond());

  const bvt &true_case_bv = convert_bv(expr.true_case(), width);
  const bvt &false_case_bv = convert_bv(expr.false_case(), width);

  bvt result=bv_utils.select(cond, true_case_bv, false_case_bv);
  if(stable_identity::enabled)
  {
    stable_identity::role("select-condition",0,width,cond.get());
    for(unsigned i=0;i<width;++i)
    {
      stable_identity::role("select-true",i,width,true_case_bv[i].get());
      stable_identity::role("select-false",i,width,false_case_bv[i].get());
      stable_identity::role("select-result",i,width,result[i].get());
    }
  }
  return result;
}
