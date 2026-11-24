# 原生源码检查与实验设计

开发基线为阶段 9 的 d02f0e13。原生观察基线为阶段 8 增强输入流提交 a2ba2f01，其父系是 Deagle 的 0be9e216 和已批准的诊断补丁。本设计先于原型编写。

| 原生位置 | 生命周期与实验边界 |
| --- | --- |
| Solver.h，Solver.cc 的 newVar、addClause_、attachClause、simplify、relocAll | clauses 和 learnts 保存 ClauseAllocator 中的 CRef。提交会按根赋值缩短或忽略子句。单元直接入 trail，空子句置 ok=false。简化会移除已满足子句，GC 会迁移引用。相同数字偏移或相同提交次数都不能证明复用。 |
| Solver.cc 的 pickBranchLit、uncheckedEnqueue、analyze、analyzeFinal、reduceDB | activity、user_pol、polarity、decision、order_heap 决定启发式。assigns、trail、trail_lim、vardata 及 qhead 是本次赋值、理由和传播位置。watches 引用具体分配器对象。普通与理论冲突均可参加 UIP 分析，学习结果没有可供删除旧约束的完整依赖证书。 |
| ClosureSolver.cc 的 search、solve_、cancelUntil、addMissingCoClauses | assumptions 逐层引入，假设冲突经 analyzeFinal 返回。无假设核心的根 UNSAT 可把 ok 永久置假。SAT 返回前复制 model 并调用 final_check。撤回到零层保留根传播。动态 CO 扩展 newVar 并直接向 clauses 添加约束。普通输入子句与运行期 CO 不能只按 clauses/learnts 区分。 |
| Closure.h、Closure.cc 的 init、push_scope、pop_scope、use_available_info、remove_rf、final_check | 节点持有可达边、RF、vital、原子分组与 guard 状态。五组 trail 回退决策层操作。根层对 RF 和 guard 映射的移除、常设 PO/APO 及动态 CO 不会因 cancelUntil(0) 而恢复。结果顺序还写入外部容器。保守原型重新建立整张运行期图。 |
| satcheck_minisat2.h/.cpp、solver_factory.cpp、bmc_util.cpp | 工厂分配带原生 ClosureSolver 的位向量决策器，先转换完整 SSA，再将 RF、guard、PO/APO 的文字及位置传入 save_raw_graph，最后提交目标和 assumptions。适配器通过 model 返回赋值，理论结果顺序参与反例还原。 |
| boolbv.cpp、boolbv_map.h/.cpp、prop_conv_solver.h | 位向量表保存标识符、类型及逐位 literal，布尔表达式缓存还含临时 Tseitin 变量。指针对象、位宽、符号与路径的改变都可能使数字重合。试验只准入由事件、来源、类型、guard、端点与别名组完整绑定的变量，其他变量重新解释为 P1 私有。 |
| theory_lemma.cpp、incdeagle/theory/context.py | 阶段 5 在搜索前审核符号化理论子句再导入。这里仅读取转交求解器的原始绑定，关闭导入和导出。 |

拟验证的最小机制是同一进程及同一 ClosureSolver 对象的两次真实求解。只保留仍驻留、且与两版完整输入子句和语义映射均匹配的原始 CRef。切换时解绑旧约束、清理整个动态 SAT 状态与 Closure 图，按候选输入重新挂接。所有非准入变量当作候选新变量。单独验证 assumptions 切换与根 UNSAT，记录批准与拒绝路径。完整模型生成与历史阶段归档独立。
