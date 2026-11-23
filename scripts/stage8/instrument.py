"""Apply narrowly anchored diagnostic probes to the two pinned Deagle source trees."""
import argparse
import re
import shutil
from pathlib import Path


def apply(root, enhanced):
    files = {}
    def source(path):
        if path not in files:
            inc = '../../../src/util/stage8_meter.h' if path.startswith('minisat-') else '../util/stage8_meter.h'
            files[path] = '#include "'+inc+'"\n' + (root/path).read_text()
        return files[path]
    def replace(path, before, after):
        data = source(path)
        if data.count(before) != 1:
            raise ValueError(f'{path}: expected one anchor {before!r}, found {data.count(before)}')
        files[path] = data.replace(before, after)
    def entry(path, signature, body):
        data=source(path)
        matches=list(re.finditer(r'^'+re.escape(signature)+r'[^{;]*\n\{',data,re.M))
        if len(matches)!=1:
            raise ValueError(f'{path}: expected unique definition {signature}, found {len(matches)}')
        i=matches[0].end()
        files[path]=data[:i]+'\n  '+body+data[i:]
    def measure(path,signature,name):
        entry(path,signature,'s8::Scope s8_timer(s8::'+name+');')
    goto='src/cbmc/cbmc_parse_options.cpp'
    entry(goto,'int cbmc_parse_optionst::doit(', 's8::Finish s8_finish;')
    measure(goto,'int cbmc_parse_optionst::get_goto_program(', 'front')
    measure(goto,'bool cbmc_parse_optionst::process_goto_program(', 'goto_process')
    ansi='src/ansi-c/ansi_c_language.cpp'
    measure(ansi,'bool ansi_c_languaget::preprocess(', 'preprocess')
    replace(ansi,'  std::istringstream i_preprocessed(o_preprocessed.str());',
            '  s8::Scope s8_parse(s8::parse);\n  std::istringstream i_preprocessed(o_preprocessed.str());')
    init='src/goto-programs/initialize_goto_model.cpp'
    replace(init,'if(language_files.typecheck(symbol_table))','s8::Scope s8_types(s8::typecheck);\n    if(language_files.typecheck(symbol_table))')
    convert='src/goto-programs/goto_convert_functions.cpp'
    measure(convert,'void goto_convert_functionst::goto_convert(', 'goto_convert')
    step='src/goto-symex/symex_main.cpp'
    dispatch='s8::Scope s8_dispatch(s8::state().detail && s8::state().dispatch++ < s8::state().prefix ? s8::prefix_dispatch : s8::other_dispatch);'
    if enhanced:
        anchor='if(stage4::configured()) stage4::before_step(state,target,path_storage);'
        replace(step,anchor,anchor+'\n  '+dispatch)
    else:
        entry(step,'void goto_symext::symex_step(',dispatch)
    model='src/goto-symex/memory_model_sc.cpp'
    measure(model,'operator()(', 'sc')
    measure(model,'void memory_model_sct::program_order(', 'po')
    anchor='const event_listt &events=t_it->second;'
    replace(model,anchor,anchor+'\n    s8::Scope s8_po_key(s8::po_selected,s8::state().detail && s8::chosen(s8::state().po_keys,std::to_string(t_it->first)));')
    mem='src/goto-symex/memory_model.cpp'
    measure(mem,'void memory_model_baset::read_from(', 'rf')
    anchor='for(const auto &address : address_map)\n  {'
    replace(mem,anchor,anchor+'\n    s8::Scope s8_rf_key(s8::rf_selected,s8::state().detail && s8::chosen(s8::state().rf_keys,id2string(address.first)));')
    measure('src/goto-symex/partial_order_concurrency.cpp','void partial_order_concurrencyt::build_event_lists(', 'event_list')
    bmc='src/goto-checker/bmc_util.cpp'
    measure(bmc,'std::chrono::duration<double> prepare_property_decider(', 'encode_graph')
    measure(bmc,'void convert_symex_target_equation(', 'ssa_convert')
    sat='minisat-2.2.1/minisat/core/Solver.cc'
    entry(sat,'bool Solver::addClause_(', 's8::clause(ps);')
    entry(sat,'Var Solver::newVar(', 's8::variable(nVars(),toInt(upol),dvar);')
    closure='minisat-2.2.1/minisat/core/ClosureSolver.cc'
    entry(closure,'void ClosureSolver::save_raw_graph(','''s8::Scope s8_timer(s8::graph_load);
    if(s8::state().detail){
      std::ofstream f(s8::state().out+"/s8-graph.tsv");
      for(const auto &e:_oc_edge_table) f<<"edge\\t"<<e.first.first<<"\\t"<<e.first.second<<"\\t"<<e.second.second<<"\\t"<<e.second.first.x<<"\\n";
      for(const auto &g:_oc_guard_map) f<<"guard\\t"<<g.first<<"\\t"<<g.second.x<<"\\t"<<_oc_location_map.at(g.first)<<"\\n";
      for(const auto &v:_oc_result_order) f<<"order\\t"<<v.first<<"\\t"<<v.second<<"\\n";
    }''')
    entry(closure,'lbool ClosureSolver::solve_(', 's8::first_search();')
    measure(closure,'lbool ClosureSolver::search(', 'search')
    replace(closure,'conflicts++; conflictC++;','conflicts++; conflictC++;\n            if(s8::state().detail && s8::state().first_conflicts<16) s8::conflict(decisionLevel(),ca[confl]);')
    replace(closure,"// Increase decision level and enqueue 'next'","if(s8::state().detail && s8::state().first_decisions<32) s8::decision(decisionLevel(),next.x);\n            // Increase decision level and enqueue 'next'")
    anchor='std::cout << "ClosureSolver finishes'
    replace(closure,anchor,'if(s8::state().detail) std::ofstream(s8::state().out+"/s8-search.tsv")<<starts<<"\\t"<<conflicts<<"\\t"<<decisions<<"\\t"<<propagations<<"\\t"<<theory_propagation<<"\\t"<<conflict_cycle<<"\\n";\n    '+anchor)
    if enhanced:
        obs='src/goto-symex/stage3_observer.cpp'
        measure(obs,'void goto_model(', 'goto_json')
        measure(obs,'void equation(', 'observer_equation')
        inc='src/goto-symex/stage4_incremental.cpp'
        anchor='const pid_t child=fits?fork():-1;'
        replace(inc,anchor,'const uint64_t s8_parent=s8::state().detail ? s8::ns(CLOCK_PROCESS_CPUTIME_ID)-s8::state().cpu_born : 0;\n        '+anchor+'\n        if(child==0 && s8::state().detail){s8::state().inherited_cpu=s8_parent;s8::state().cpu_born=0;}')
        for sig,name in [('void save_irep(', 'irep_write'),('irept load_irep(', 'irep_read'),('std::string rebind(','rebind'),('std::string check_prefix_symbols(','prefix_symbols')]:
            measure(inc,sig,name)
        anchor='          std::string request;\n          if(!std::getline(std::cin,request))'
        replace(inc,anchor,'          std::string request;\n          bool s8_received=bool(std::getline(std::cin,request));\n          s8::reset_at_command(base+"/candidate");\n          s8::state().prefix=0;\n          if(!s8_received)')
        f='src/goto-symex/stage4_sc.cpp'
        anchor='(stage4::collecting() || stage4::restoring())'
        replace(f,anchor,'(stage4::collecting() || (stage4::restoring() && !s8::only("I1")))')
        for sig,name in [('void stage4_sct::replay_reads(','rf_replay'),('bool stage4_sct::check(','sc_check'),('bool stage4_sct::thread(','sc_thread')]:
            measure(f,sig,name)
        lemma='src/goto-checker/theory_lemma.cpp'
        for sig,name in [('bool run_audit(', 'lemma_worker'),('void submit(', 'lemma_submit'),('void prepare_order_lemma_cache(', 'lemma_prepare')]:
            measure(lemma,sig,name)
        anchor='      json_objectt result; json_arrayt lits, levels;'
        replace(lemma,anchor,'      s8::Scope s8_record(s8::conflict_record);\n'+anchor)
        anchor='  if(!valid) plan.clear();'
        replace(lemma,anchor,anchor+'\n  if(s8::only("I1") || s8::only("I2") || s8::only("F2")) plan.clear();')
    for name,body in files.items():
        (root/name).write_bytes(body.encode())
    shutil.copyfile(Path(__file__).with_name('meter.h'),root/'src/util/stage8_meter.h')
    print('Instrumented',len(files),'translation units, enhanced =',enhanced)


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('tree',type=Path)
    p.add_argument('role',choices=['baseline','enhanced'])
    a=p.parse_args()
    apply(a.tree,a.role=='enhanced')
