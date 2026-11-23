"""Build a passive full-equation exporter into a separate F0 worktree for model checks."""
import subprocess
import sys
from pathlib import Path


def install(base, enhanced):
    rev='0be9e2167d46c66ea12ca7f9f801063a03873625'
    data=subprocess.check_output(['git','-C',enhanced,'show',rev+':src/goto-symex/stage3_observer.cpp'],text=True)
    helpers=data[data.index('json_numbert number('):data.index('\n}\n\nbool enabled()')]
    begin=data.index('void equation(const char *name')
    fn=data[begin:data.index('\n}\n',begin)+3]
    fn=fn.replace('  const auto before = clockt::now();','')
    fn=fn.replace('    row["visit"] = number(s.observer_visit);\n','')
    a=fn.index('    const auto found = event_names.')
    b=fn.index('    rows.push_back',a)
    fn=fn[:a]+fn[b:]
    fn=fn.replace('  timing("equation_export", before, clockt::now());','')
    pre='''#include <util/json.h>
#include <goto-symex/symex_target_equation.h>
#include <fstream>
#include <cstdio>
#include <cstdlib>
#include <unordered_map>
namespace stage8_full_model {
const std::string directory=std::getenv("S8_MODEL_OUT")?std::getenv("S8_MODEL_OUT"):"";
'''
    target=base/'src/goto-checker/stage8_full_model.h'
    target.write_text(pre+helpers+'\n'+fn+'\n}\n')
    p=base/'src/goto-checker/multi_path_symex_only_checker.cpp'
    text=p.read_text()
    token='  postprocess_equation(symex, equation, options, ns, ui_message_handler);'
    assert text.count(token)==1
    p.write_text('#include "stage8_full_model.h"\n'+text.replace(token,token+'\n  if(!stage8_full_model::directory.empty()) stage8_full_model::equation("full_model",equation);'))


if __name__=='__main__':install(*map(Path,sys.argv[1:]))
