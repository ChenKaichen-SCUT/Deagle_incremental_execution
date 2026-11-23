// Compile against the pinned DAMER sources and link its existing parser/matcher objects.
#include "AST_compare.h"
#include <iostream>

int main(int argc,char **argv)
{
  if(argc!=3) return 2;
  auto *old_tree=create_tree(argv[1]);
  cut_tree(old_tree);
  auto *new_tree=create_tree(argv[2]);
  cut_tree(new_tree);
  std::vector<Mapping> matches;
  top_down(old_tree,new_tree,matches);
  auto statements=get_MatchStatement(matches);
  std::cout<<"matches "<<matches.size()<<" statements "<<statements.size()<<std::endl;
  for(const auto &s:statements)
    std::cout<<"statement "<<s.map1->row<<" "<<s.map2->row<<"\n";
  auto changes=extract_change(old_tree,new_tree,matches,statements);
  std::cout<<"changed_blocks "<<changes.size()<<"\n";
  for(const auto &c:changes)
  {
    std::cout<<"block "<<c.m.map1->row<<" "<<c.m.map2->row<<"\n";
    for(const auto &v:c.modify) std::cout<<"modify "<<v.first<<" "<<v.second<<"\n";
    for(const auto &v:c.add) std::cout<<"add "<<v.first<<" "<<v.second<<"\n";
    for(const auto &v:c.del) std::cout<<"delete "<<v.first<<" "<<v.second<<"\n";
    for(const auto &v:c.move) std::cout<<"move "<<v.first<<" "<<v.second<<"\n";
  }
}
