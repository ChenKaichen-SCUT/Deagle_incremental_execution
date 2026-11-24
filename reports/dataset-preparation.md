# 服务器关闭前的困难并发版本对筛选

**READY_FOR_REVIEW**。冻结 10 对，其中 9 对来自真实程序修改，1 对是公开规模对照。3 对真实修改的 P1 在服务器串行复核中超过 30 秒，全部来自上游同一个 Fibonacci 同步补丁的三个规模。它们适合研究修改前后的搜索知识迁移；不能把它们当成三个独立缺陷家族。[冻结清单](../datasets/stage-12-hard-pairs/manifest.json) · [含失败项的 CSV](../datasets/stage-12-hard-pairs/dataset.csv)

## 筛选范围与来源

复用 SV-COMP 2026 的 725 条 Deagle 并发可达性官方记录，以及 FM 2026 两张各含 1,063 个任务的运行时间表。回看 FM 先前按任一工具总耗时至少 10 秒选出的全部 13 个任务。对 SV-COMP 2025 定向下载 9 项重叠任务的固定文件，9 个翻译单元与对应的新材料逐字节相同，7 份 YAML 相同；另两份 YAML 的原始差异一起保留。2025 标签的提交为 **1e5856db49f3a4766f416cc60382aa92012b2939**，2026 标签的提交为 **7efe28dd29576b46927b7a34e8f742bd90966a75**。未重复下载整套基准。[2026 逐题成绩与出处](evidence/svcomp26/all-records.csv) · [2025 比对和下载地址](evidence/stage-12/svcomp25/overlap.json) · [FM 原始筛选](evidence/stage-11b/panel/selection.json) · [论文实验归档](https://zenodo.org/records/18616443)

服务器实际执行 **43 个不同的上游任务路径、55 份不同 SHA-256 的源程序、124 次冷启动验证**。一个任务路径可以有多个历史版本或修补版本。9 对真实修改中，4 对从违反变为通过，2 对在修改后仍违反，3 对在同步修补前后都通过所选可达性性质。自动修补预实验已有的三个相邻版本对直接沿用冻结补丁，本次 DeepSeek 调用为 0。每一对使用两端相同的 ILP32、原可达性性质、SC、展开界限和原生 Closure 后端；同时检查原生报告的所有断言和展开义务。[版本与官方成绩索引](evidence/stage-12/inventory.json) · [全部运行](evidence/stage-12/all-runs.json.gz)

## 服务器串行全量结果

时间单位为秒。SAT 表示发现原断言反例，UNSAT 表示固定后端在该任务配置下排除了违反。每个正式版本有一次独立单工作进程复核。有前期复跑的版本，在各自 baseline.json 中同时给出逐次数据。搜索时间取 native search 计时器各次 CDCL 搜索的和，排除前端、CNF 转换与图加载，包含该原生观察配置在搜索中的记录成本。每次均使用新进程和全新模型。[计时实现](../scripts/stage8/meter.h) · [队列及并发时间线](evidence/stage-12/queues.json) · [实际调度计划与执行顺序](evidence/stage-12/plans.json.gz)

| 病例 | 修改及结果 | P0 搜索 | P1 搜索 | P0 产生的第一 UIP 子句 | P0 理论冲突 |
|---|---|---:|---:|---:|---:|
| circular-buffer | 修正成功事务编号，SAT → UNSAT | 0.393 | 13.081 | 343 | 18 |
| ldv-publication | 合并状态发布与检查，SAT → UNSAT | 0.00069 | 0.00046 | 4 | 0 |
| unwind-limit | 修正生产端发布的请求上限，SAT → UNSAT | 0.00082 | 0.00080 | 15 | 0 |
| rw-acquire | 读写锁第一轮修改仍有残错，SAT → SAT | 0.00597 | 0.00593 | 185 | 13 |
| rw-release | 原子释放读锁，SAT → UNSAT | 0.00593 | 0.00652 | 185 | 13 |
| **fib-snapshot-10** | 上游同步修补，UNSAT → UNSAT | 18.891 | **40.862** | 69,448 | 42 |
| **fib-snapshot-11** | 同一补丁的 11 轮实例，UNSAT → UNSAT | 32.603 | **44.508** | 108,788 | 116 |
| **fib-snapshot-12** | 同一补丁的 12 轮实例，UNSAT → UNSAT | 53.273 | **75.633** | 144,119 | 63 |
| fib-strict-12 | 保持严格上界的公开同步修改，SAT → SAT | 27.621 | 28.901 | 85,382 | 63 |
| ticket-6-7 | 公开规模对照，UNSAT → UNSAT | 12.152 | 116.431 | 140,777 | 1,543 |

按 P1 搜索分组，4 对不足 10 秒，2 对为 10～30 秒，4 对为 30～300 秒。最后一组包含 3 个真实同步修改实例和 1 个规模对照；没有合格对超过 300 秒。P0 较快而 P1 变慢的实例如环形缓冲区和 10 轮 Fibonacci；11、12 轮 Fibonacci 的两端均超过 30 秒。本次没有找到 P0 不足 10 秒且 P1 超过 30 秒的真实修复。以前发布的 ticket 五到六线程也在这台服务器复核，作为额外校准，未计入十对。[额外校准](evidence/stage-12/calibration/ticket-5-6.json)

### 历史关系与反例

- 上游 **5110fee06e4466b05ac4ffab744e1f57ef498b37** 相对直接父提交 **de30d1d37df637a9f45a8fcefce8816bb1372f00**，把比较两个共享值的动作放入一个原子区，两端均检查 i ≤ correct 且 j ≤ correct。两个线程仍各执行 N 次原更新，计算参考值的循环仍执行 2N+2 次。三个规模各自的两个 .i、原 .c、头文件、YAML 及性质已固定。测量对象是原生 SC 编码；旧版检查时的共享读取存在竞态，不能据此宣称旧程序满足 C11 无数据竞争语义。[上游修补](https://gitlab.com/sosy-lab/benchmarking/sv-benchmarks/-/commit/5110fee06e4466b05ac4ffab744e1f57ef498b37) · [原始文件](evidence/stage-12/historical-fib)
- 严格上界另用上游 **324a403a… → 30b58c81…**，两端均为严格小于。中间提交 **11e0dee8…** 同时把严格小于改成了小于等于，已排除为合格端点。12 轮独立枚举覆盖 2,704,156 个完整工作线程顺序及其所有前缀。交替更新可以到达 121,393，正好达到参考上界，解释了为什么改成原子快照后严格断言仍会失败。非严格版本在相同算术下满足上界。枚举是对该程序更新和断言的独立检查。[上游恢复原意](https://gitlab.com/sosy-lab/benchmarking/sv-benchmarks/-/commit/30b58c811fa1c87ed9a5103c81bb35bc1bbc2dc3) · [枚举输入与结果](evidence/stage-12/fib-functional.json)
- 环形缓冲区的新 P1 来自本次 P0 反例。两侧仍各轮询七次，成功事务才推进载荷编号。独立枚举 3,432 种持锁轮询交错，原版有 3,304 种发生载荷错配，P1 为 0，且存在成功接收全部七个载荷的顺序。LDV 修补保留原始断言、工作线程和 join，将发布和立即检查合入同一原子区。两项原始反例均与隔离复核中的目标相关赋值和失败位置一致。[缓冲区枚举](evidence/stage-12/buffer-functional.json) · [LDV 操作次序](evidence/stage-12/ldv-functional.json) · [两个原生反例的投影](evidence/stage-12/manual-witnesses.json)

## Boolean 与 Closure 模型差分

十个目录均含完整新旧翻译单元、可重放补丁、实际命令与结果、model-delta.json 和压缩的明细。模型原件包括 GOTO、原始 SSA、SC 输入、完整模型、变量位绑定、理论声明、原始编码流及搜索轨迹。SHA-256 绑定到每个运行的 receipt。独立读取每条原始 CNF 声明，包括空子句、单元子句和重复项；代入有符号的变量对应后按多重集求交。只在两端都可解释的子空间报告确定新增和删除，其余计入 unknown。变量身份对应不要求两程序对它给出相同的值。[差分程序](../scripts/hard_pairs/delta.py) · [原始对象索引](evidence/stage-12/raw/files.json)

| 病例 | 可确认的变化 | 有符号变量对应 | 确认保留的原始子句 | 已匹配事件 / P0 事件 |
|---|---|---:|---:|---:|
| circular-buffer | B 改变，T 的全图等价未确定 | 0 | 0 | 36 / 481 |
| ldv-publication | B 与 T | 0 | 0 | 13 / 40 |
| unwind-limit | B 与 T | 0 | 0 | 12 / 38 |
| rw-acquire | 原始有序 Boolean 流完全相同，T 改变 | 0 | 0 | 14 / 81 |
| rw-release | 原始有序 Boolean 流完全相同，T 改变 | 135 | 11 | 81 / 81 |
| fib-snapshot-10 | B 与 T | 7,584 | 75 | 540 / 546 |
| fib-snapshot-11 | B 与 T | 8,640 | 81 | 584 / 590 |
| fib-snapshot-12 | B 与 T | 9,760 | 87 | 628 / 634 |
| fib-strict-12 | B 与 T | 0 | 0 | 0 / 634 |
| ticket-6-7 | B 与 T | 0 | 0 | 0 / 150 |

事件依据函数内相对指令、类型、对象、生成和调用上下文、保护条件及动态出现次数建立保守对应。已有审查过的锁或 ticket 角色仅在两端都能核对相应原始证据时启用。原子块按显式分区和实际 APO 连通分量分别比较。差分文件逐项列出 PO、APO、RF、Guard、访问类型、地址、别名、换号和反极性。表中的零表示该检查器确认了零项；未匹配项仍在原始输入中。没有一个病例获准推断整体语义单调加强。例如 12 轮非严格 Fibonacci 的原始子句数由 1,171,282 变为 1,171,284，APO 由 111 变为 112；这些计数本身不能推出新公式蕴含旧公式。[12 轮差分](../datasets/stage-12-hard-pairs/fib-snapshot-12/model-delta.json) · [读写锁差分](../datasets/stage-12-hard-pairs/rw-release/model-delta.json)

## 旧搜索知识

学习产生数来自单查询原生 search.bin。固定 ClosureSolver 在每次冲突处记录深度；根层冲突返回 FALSE，正层冲突调用一次 analyze 产生第一 UIP 子句。逐次解析整条轨迹并与原生冲突计数相等后才计数。求解结束时数据库中尚存的学习子句另记。RF / Guard 在分支选择中被置真、置假的次数也可从带符号的原生绑定读出；全程的理论传播、理论环冲突与 Boolean 传播使用 native-state.tsv 的查询起止差。固定采集没有给每一次理论传播附上 RF / Guard / 动态 CO 的分类；这些细粒度字段保留为空。静态图中没有独立 WS / CO 声明的记录，不代表动态 CO 没有发生。[固定搜索源码](https://github.com/ChenKaichen-SCUT/Deagle_incremental_execution/blob/74e652ea7b76ec4e5d3fd5db40cf95784dbf600d/minisat-2.2.1/minisat/core/ClosureSolver.cc) · [采集与核对脚本](../scripts/hard_pairs/delta.py)

P0 学习信息最多的真实修改是非严格 Fibonacci 的 12 轮和 11 轮，分别产生 144,119 和 108,788 条第一 UIP 子句。规模对照 ticket-6-7 的 P0 产生 140,777 条，理论环冲突 1,543 次。rw-release 的原始流、图和搜索轨迹与阶段 11C 的 lock12 捕获一致，故可引用该次 P0 已证明的 90 条理论记录及 13 条混合记录。没有为本次候选逐条求解旧子句，也没有把候选记录数当作可复用数。[阶段 11C 证明库存](evidence/stage-11c/clause-inventory.json.gz) · [当前 P0 核验](../datasets/stage-12-hard-pairs/rw-release/model-delta.json)

## 排除、资源与时间边界

- 三个中档栈在充足内存下均再次出现目标反例，同时无限创建线程导致展开失败。两个大栈在较低地址空间上还发生了真实分配失败；提高上限后得到可解释的结果。公开配对文件反转断言，无法作为同一性质的修复版本。六组 Weaver 的源码存在合理同步改动，但无界或输入相关循环的展开检查失败；即便修补版本的目标报告 SUCCESS，仍保留为待解决。[逐运行性质](evidence/stage-12/all-runs.json.gz)
- 五个 FM 指针任务和其他共享指针候选在安全配置下停于并发指针写入。官方竞赛日志使用 refined pointer analysis；固定源码在启用这个参数时也置 allow-pointer-unsoundness，随后会执行第二次符号执行。现有证据不能证明它对这些程序足够安全，故保留拒绝。四个无可达性性质的 FM YAML 和两个既有严格 SC 差异对照也保留原排除理由。[官方运行日志](evidence/svcomp26/official/logs) · [命令行实现](https://github.com/ChenKaichen-SCUT/Deagle_incremental_execution/blob/74e652ea7b76ec4e5d3fd5db40cf95784dbf600d/src/cbmc/cbmc_parse_options.cpp#L165) · [指针拒绝点](https://github.com/ChenKaichen-SCUT/Deagle_incremental_execution/blob/74e652ea7b76ec4e5d3fd5db40cf95784dbf600d/src/goto-symex/goto_symex_state.cpp#L110)
- 两个先前 60 秒超时的 FM 病例结局不同。七线程 ticket 获得完整结论。NetBSD 在 180 秒仍超时，660 秒上限下最终返回；私有输出复核的搜索为 454.319 秒，仍有失败的展开义务，未纳入高难通过样本。arithmetic 在展开 5 和 8 都有等待循环展开失败；保留真实反例、多查询信息及每条性质的结果，未送进单查询复用路径。[阶段 11B 原筛选](evidence/stage-11b/panel/selection.json) · [本轮归档](evidence/stage-12/all-runs.json.gz)
- 服务器实际为 8 个逻辑 CPU（4 核、每核 2 线程）、32,254,509,056 字节内存、无交换分区。任务固定单个 CPU，队列按可用内存和每项地址空间上限动态放行，最高并行 8 项。初筛主要用 22 秒和 3 GiB，第二层采用 160～180 秒，部分历史项为 300 秒，第三层上限 660 秒；串行完整采集留出 740 秒。峰值进程 RSS 为 7,378,156 KiB。11 个队列活跃区间合计约 1,809 秒，从首次开始到最后结束约 1,922 秒。原始记录保留超时、分配失败和完整匹配的全部结论。[资源与结束标记](evidence/stage-12/host) · [逐次核与内存](evidence/stage-12/queues.json)
- 在早期并行诊断中发现，旧原生观察器在只设置 S10_DIR 时会向根目录写诊断副本。保留这批探索记录。交付采用两种独立输出配置：轻量筛选关闭该诊断钩子；全模型采集把 S10 和观察器都定位到各自私有尝试目录。55 个输入均有私有复核或串行全模型复核。正式搜索时间来自后者，人工修补另核对了引发原断言的赋值投影。[固定观察器](https://github.com/ChenKaichen-SCUT/Deagle_incremental_execution/blob/74e652ea7b76ec4e5d3fd5db40cf95784dbf600d/src/goto-checker/theory_lemma.cpp#L150) · [最终运行器](../scripts/hard_pairs/run.py)

## 本地迁移与交付

Windows 的 Deagle-Jammy WSL2 环境已通过 doctor 检查，使用 GCC 11.4.0、Python 3.10.12、已核对的原生 Deagle 和阶段 11C 工具。断网独立验证了 circular-buffer（SAT → UNSAT）、ldv-publication（SAT → UNSAT）和 fib-snapshot-11（UNSAT → UNSAT）。三对的两个版本都与服务器具有相同的源文件 SHA、参数、完整性质结果、CNF 输入、静态图和原生搜索轨迹。WSL 的环形缓冲区两端分别为 0.231 / 7.827 秒、11 轮 Fibonacci 为 26.093 / 35.706 秒，作为本机结果单列。十对均可由同一入口离线恢复和运行。[本地核验](evidence/stage-12/local-verification.json) · [本地操作与恢复](../datasets/stage-12-hard-pairs/README.md) · [阶段 11C 迁移和原生构建](../docs/local-runtime.md)

E 盘保存所有 124 次服务器尝试的原始归档，304,429,243 字节，已按服务器收据逐一核对 1,521 个原始文件，原始文件合计 1,333,483,317 字节。GitHub 分卷采用内容寻址，含正式完整模型、运行记录、筛选原始输出、可重放输入及本地交叉核验。分卷清单记录每卷和重组档的 SHA-256。本机重新提交同一缓冲区队列后，两份原收据和尝试目录逐一相同，没有重新启动求解。7 个调度批次均有完成标记，研究任务已停止，服务器关机由用户决定。[完整传输收据](evidence/stage-12/transfer.json) · [公开分卷](evidence/stage-12/raw/parts.json) · [续跑检查](evidence/stage-12/resume-check.json)

项目分支为 **stage-12-hard-pairs**，起点为 **ad51830bf5614c51f173527bcc534a6c7877b67a**。对应的完整原生源码为 **74e652ea7b76ec4e5d3fd5db40cf95784dbf600d**。数据冻结提交由本分支中首次加入本报告的提交标识，可执行下面的命令取出。[项目分支](https://github.com/ChenKaichen-SCUT/Deagle_incremental_execution/tree/stage-12-hard-pairs)

~~~sh
git log --diff-filter=A -1 --format=%H -- reports/dataset-preparation.md
~~~

数据冻结提交为 **06510d4999c4b1030945e83a50c9ef73e3db690b**。十对源码、正式模型、计时和原始分卷均可从该提交取得。[GitHub 固定提交](https://github.com/ChenKaichen-SCUT/Deagle_incremental_execution/commit/06510d4999c4b1030945e83a50c9ef73e3db690b)
