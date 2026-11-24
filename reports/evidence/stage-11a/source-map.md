# 论文、公理和固定源码对照

源位置均为阶段 10 实际链接所用工作树，基于 `a2ba2f01fcc8dc83261f614039141017fb846178` 加阶段 10 观测补丁。下文的 `Closure.cc` 等位于 `minisat-2.2.1/minisat/core/`。该树另有 `include/minisat/core/Solver.h`，清单分别给出两个同名头文件的指纹。用阶段 10 的构建入口恢复此树后，可逐行定位。研究驱动只经公开的 `save_raw_graph` 和 `solveLimited` 提交声明与 RF assumptions，链接原有 `solvers.a` 和 `util.a`。[实际源文件 SHA-256](native/rank/source.sha256) · [构建指纹](native/control.sha256) · [阶段 10 原生补丁](../stage-10/native.patch) · [固定树重建说明](../../stage-10.md)

## 理论谱系

| 文献 | 可以据以使用的规则 | 固定版中的对应与差异 |
|---|---|---|
| He、Sun、Fan，PLDI 2021，``3–5，Axioms 1–3 | Zord 的有类型 PO/WS/RF/FR、给定 RF 和 WS 推导 FR、其并集的传递闭包不得有环。写序选择包含在编码中。路径理由可合成冲突子句，逐赋值扩展图。 | 固定 Closure 的 `set_graph` 在 `ClosureSolver.cc:57` 分类 PO/APO/RF/RACE，显式 WS 表的处理是注释。`Closure.cc:385` 从 RF/顺序触发 CO 和 FR；`ClosureSolver.cc:818` 在搜索后期添加 CO。两个版本内建图的“增量”都不提供跨版本删边契约。 |
| Sun、Fan、He，OOPSLA 2022，``4–5，Algorithms 2、3 | Axiom 1 为传递，2 为带 guard 的 WS 推导，3 为带 guard 的 FR 推导。两类预防模式为反向 RF 以及写插入 RF 两端之间。用即将形成矛盾的证据传播被禁止的 RF 或第三写的 guard。 | `Closure.cc:390–488` 处理新 RF，`644–762` 从新边继续传递／推导，`788–1046` 处理新亮起的 guard。`254–336` 及 `582–642` 用三元组、vital 边和反向 RF 检查，`PROPAGATE_INTENSITY=1`。`ClosureSolver.cc:724–793` 把结果变成 SAT 单位／理由子句。论文对伪代码稳定性、fragile 判定和所述模型的定理不能直接赋给这份实现或严格 SC。 |
| Bajczi、Telbisz、Szekeres、Vörös，TACAS 2025，``3–5，图 1–4、Algorithms 1–3 | 图 1 两次 RF 触发后，后来得到的新顺序需要重新触发旧 RF 的 derive；单次伪代码漏掉 `rx3 < wx2`。回顾式迭代至稳定，或前瞻式在每个新增顺序上重触发相关规则。规则饱和和严格 SC 完整性是两个问题。 | `ClosureSolver.cc:435–596` 先消费 Boolean trail，再激活边／guard；`one_more_time` 的具体条件是有待布尔赋值的 `literals_to_assign`，`587` 递归。正向边本身还在 `Closure.cc:385–766` 内扩展。不能把这个标志解释为每次无条件重扫全部 RF。研究驱动中图 1 为 SAT，额外给 `wx2 < rx3` 后为 UNSAT。此负向对照验证必要顺序，未测每个中途调用结束时的全部内部可达边。 |
| Cai、Sun、He，FM 2026，``3–5，图 3、7、9，Theorems 2–4 | 每址活动写序须为全序。恢复 WS 的使能、可选方向和顺序连接，同时保留推导；检测块内及商图环。广义预防包括 Self-Reversal、Stale-Read、RMW-Broadcast、RF-Join。论文给出可靠性与不完备边界。 | 固定代码有块收缩、反向边和陈旧读检测。未找到一套与论文四种模式、显式 WS 前端逐项等价的实现。现有后期 CO 由 `ClosureSolver.cc:325,818` 和 `Closure.cc:1244–1281` 负责，guard 已亮、同址且不同块的两个写尚未定序时才补对。在存在 race 表时直接退出该检查。该策略与 FM 的 Poct 前端、传播器和理论保证分别记录。 |

原文与可核对的版本如下。

- PLDI 2021，*Satisfiability Modulo Ordering Consistency Theory for Multi-threaded Program Verification*，第 1264–1279 页。作者版 PDF SHA-256 为 838aa0ba376aeb2a119e8882f0cb3cd1dadf38b5b66680c49edeccbd18b5040e。Axiom 2 使用已给定的 WS，不能与 OOPSLA 的 Axiom 2 对号入座。[作者全文](https://feihe.github.io/materials/pldi21.pdf) · [出版记录](https://doi.org/10.1145/3453483.3454108)
- OOPSLA 2022，*Consistency-preserving propagation for SMT solving of concurrent program verification*，文章 158，特别是 158:8–16。项目本地阅读本 SHA-256 为 `4a376ebde292216f6158ea2f2990c497469afc37f8ae0564fca6653cfd0521a4`。[出版记录](https://doi.org/10.1145/3563321)
- TACAS 2025，*On Stability in a Happens-Before Propagator for Concurrent Programs (Reproducibility Study)*，第 3–19 页；本地作者版图 1–3 在印刷页码 5，图 4 在 6，`5.1 还比对了该研究所取的源码和发行二进制。本地 PDF SHA-256 为 `c41a56e83ff2e8d8f1b8ad6fb3dcc0fe2ba47914b74cb2da271bd31027604002`。[出版社全文](https://link.springer.com/chapter/10.1007/978-3-031-90643-5_1)
- FM 2026，*A Refined Ordering Consistency Theory: Full Sequential Consistency and Generalized Preventive Reasoning*，图 3(b) 在第 506 页，严格 SC 与 WS 总序论证在 507–509 页，四种预防模式和完备性边界在 511–512 页。论文 `6 对特定发布工具和竞赛程序的观察与本实验的固定原生库和手工图输入有不同的实验对象。本地 PDF SHA-256 为 `c2c6b48b23cb7be49fb7b500fdcbb094a35a05402271fa3cde1bcce5807b88cc`。[出版社全文](https://link.springer.com/chapter/10.1007/978-3-032-26204-2_26)

## 逐层源码定位

| 位置 | 本阶段核实的行为 | 对跨版本的约束 |
|---|---|---|
| `src/goto-symex/memory_model_sc.cpp:175–217`；`src/goto-checker/bmc_util.cpp:490–527` | 构造出生／线程边、写 guard；调用数组更新、同指针和同源行 APO 候选处理，按 `is_apo` 分类。决策器把文字、位置和外部排名表交给 `save_raw_graph`。 | C 源码中显式原子块、SSA section、原生 APO 分量不能互相代替。 |
| `ClosureTypes.h:18–73`；`Closure.h:26–85` | 节点同存出入边及位索引、vital、RF、guard 灯、原子代表和块内方向。五组 trail 分别管边、RF、vital、亮起的 guard、triplet。 | 当作一个内存对象复制会同时复制动态搜索结果。 |
| `ClosureSolver.h:26–43`；`ClosureSolver.cc:39–192` | 复制原始边和 guard，保存调用者排名表指针。先登记节点、写位置及 guard，再处理 race、APO、候选 RF、PO 和 CO 候选。 | 输入形状、初始化次序、布尔绑定和输出容器的生命周期都要重新核对。 |
| `Closure.cc:49–88,111–119,769–786` | 路径压缩并查集及块内方向集合；查询可达边时按代表元访问位索引。 | 旧块拆开后原根的位索引和 `atomic_in/out` 没有删除逆操作。 |
| `Closure.cc:179–229,338–385,385–529` | 记录候选 RF 的 literal 到端点；激活 RF 时更新 `in_rf/out_rf`；区分自环及块内逆序，再在代表元图上挂接边。 | `declared RF` 与 `chosen RF` 须分账。永久 PO/APO 的空 reason 仍带有真实静态前提。 |
| `Closure.cc:582–762,788–1046` | 同址读写和亮起的写触发新推导；三元组检查可推出 RF/guard 否定。`ClosureSolver.cc:550–579` 把环理由取反，分配冲突子句。 | 推导除 literal 外依赖读写种类、地址等价、块代表、方向和旧路径。 |
| `Closure.cc:1051–1106,1478–1540`；`ClosureSolver.cc:527–537,598–623` | 逐层回退。根层已消费的 RF 可从候选表删除，已处理的 guard 映射也可擦除。回到 level 0 仍保留根。 | `cancelUntil(0)` 不能用作新版本的初始化。 |
| `Closure.cc:1244–1281`；`ClosureSolver.cc:325–329,818–853` | 接近完成赋值时查遗漏的 CO 对；新建两个方向变量，把含两个 guard 条件的析取用 `ca.alloc(...,false)` 放入 `clauses` 并挂接。 | 运行期理论子句可以出现在原始子句数组。CO 的原子名必须含版本、端点、方向、地址和 guard。 |
| `ClosureSolver.cc:359–430,625–718,742–793`；`Solver.h:178–199`；`Solver.cc:120–188,223,288,423,454,553,605,909` | assumptions 逐层决定，根 UNSAT 可清 `ok`，冲突分析消解原因并可能最小化；单位传播可直接入 trail。简化、删除学习子句和垃圾回收会改变引用。 | 当前 CRef、学习标志、子句字面量分布或相同变量编号都不能还原完整证明。 |
| `Closure.cc:1283–1335`；`ClosureSolver.cc:416–423,797–800` | SAT 时清全局顺序向量再重填，外部映射以 `insert` 写键；同键旧值保持。UNSAT 分支不发布新的拓扑序。 | 输入相同也需要 fresh result，每个查询独占输出，详细对照见 [排名记录](native/rank/rf-direction.tsv)。 |

## 阶段 5 证书

`incdeagle/theory/context.py:26,80` 在实际提交图之前核对 SSA、调用位置、类型及原子绑定，保存常量、别名与极性。`certificate.py:10,76,128` 在子句的反面假设下构造、逐步检查先后推理。其规则为 static、rf、transitive、atomic_block、from_read、coherence，最后必须出现自环。`cache.py:73–112` 先核对版本、模式及完整上下文，再验 DAG、重绑定本轮 slots。`src/goto-checker/theory_lemma.cpp:90,140,186` 负责分别记录导入和原生冲突。原生传播 reasons、理论冲突子句与全部 CDCL 学习子句不是同一份证书集合。[上下文](../../../incdeagle/theory/context.py) · [证书](../../../incdeagle/theory/certificate.py) · [导入审核](../../../incdeagle/theory/cache.py)

本阶段重新调用冻结的审核代码。`batch_total` 的一份真实 18 步证书原样通过，删除它读取的静态边后失败。只改一处 guard 诊断行号时，证明本身仍成立，原有整上下文入口仍拒绝。冻结的原生导入回执记为 `contradiction`，本次研究没有把弱化审核写回阶段 5。[输入指纹、证书和复核结果](stage5-replay.json)
