// Exercise the actual BV converter twice with the same nested expression and swapped owners.
#include <solvers/flattening/boolbv.h>
#include <solvers/sat/satcheck_minisat2.h>
#include <util/bitvector_types.h>
#include <util/message.h>
#include <util/namespace.h>
#include <util/stable_identity.h>
#include <util/std_expr.h>
#include <util/symbol_table.h>
#include <iostream>
#include <stdexcept>

int main(int argc, char **argv)
{
  namespace si = stable_identity;
  if(argc != 2 || !si::enabled) return 1;
  const bool swapped = std::string(argv[1]) == "BA";
  null_message_handlert messages;
  symbol_tablet symbols;
  namespacet ns(symbols);
  satcheck_minisat_no_simplifiert sat(messages);
  const unsignedbv_typet byte(8);
  for(unsigned line = 1; line <= 5; ++line)
  {
    source_locationt loc;
    loc.set_file("ports.c");
    loc.set_line(line);
    if(line <= 3)
    {
      const std::string name(1, char('a'+line-1));
      symbolt decl;
      decl.name=name;
      decl.type=byte;
      decl.mode=ID_C;
      decl.base_name = name;
      decl.location = loc;
      si::declaration(decl);
      si::value(name, "", -2, "write", "6:symbol1:"+name, name, byte, true);
      symbols.add(decl);
    }
    else
    {
      si::Lower lowering(loc,"fixture-owner");
      si::site(line,si::current_origin,"fixture",loc,"convert");
      si::row('X',{line,line,0,0});
    }
  }
  const plus_exprt inner(symbol_exprt("a",byte),symbol_exprt("b",byte));
  const plus_exprt outer(inner,symbol_exprt("c",byte));
  // Reconstruct the converter to exercise destruction and object/address reuse.
  for(unsigned generation=0;generation<2;++generation)
  {
    boolbvt converter(ns,sat,messages);
    for(unsigned visit=0;visit<2;++visit)
    {
      unsigned ctx=(visit==unsigned(swapped)) ? 4 : 5;
      si::Owner owner(generation==0?"primary":"after-clear",ctx,0,0,"");
      const auto &result=converter.convert_bv(outer);
      if(result.size()!=8) throw std::runtime_error("width");
      std::cout<<generation<<" "<<ctx<<" "<<sat.no_variables();
      for(auto literal:result) std::cout<<" "<<literal.get();
      std::cout<<"\n";
    }
  }
  si::seal(sat.no_variables());
}
