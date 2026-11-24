# 阶段 10　原生 ClosureSolver 跨版本增量求解可行性

**状态为 `READY_FOR_REVIEW`。同一个 `Minisat::ClosureSolver` 已连续求解三个真实程序版本对。** P1 实际沿用 P0 分配器中的 64、64 和 132 个原始子句。三个候选的性质结果均与同一增强版 Deagle 的独立全量求解一致。18 组配对中，P1 的完整决策与冲突轨迹均与新建求解器相同，持久路径的求解侧总时间在 18 组中均更长。[原生对象和子句证据](evidence/stage-10/mechanism.json) · [逐次数据](evidence/stage-10/trials.csv)

| 冻结病例 | P0 → P1 原断言 | 同一对象重挂原始子句 | P1 纯搜索 F / S（ms） | P1 求解侧总时间 F / S（ms） | 同轮总时间 S−F 中位数 |
| --- | --- | ---: | ---: | ---: | ---: |
| `batch_total` | 违反 → 有界通过 | 64 | 0.381 / 0.407 | 8.34 / 26.53 | +18.18 ms |
| `batch_retained` | 违反 → 仍违反 | 64 | 0.406 / 0.407 | 8.39 / 26.31 | +17.92 ms |
| `fib_updates_8` | 违反 → 有界通过 | 132 | 2432.08 / 2471.58 | 2492.73 / 2629.68 | +141.57 ms |

F 在原 Deagle 决策器内直接求解，每个版本新建一个原生对象。S 在同一 Linux 工作进程持有原生对象，输入来自两次独立运行的完整 Deagle 编码器。小例各 5 组，Fibonacci 8 组。表中两路分别取中位数，最后一列先做配对差。正式实验固定项目基线 `d02f0e1327fa748be0f76f381c3d9a1fa450e9de`、冻结补丁、SC、64 位、CPU 0–7、20 GiB 和每程序 300 秒。两个计数程序的展开界限为 4，Fibonacci 为 10，均带 `--unwinding-assertions`。[时间边界、波动与资源](evidence/stage-10/performance.md) · [冻结性质与参数](evidence/stage-10/mechanism.json)

## A　现有 ClosureSolver 的跨版本障碍

`solver_factoryt::get_solver` 为当前决策器建立求解器。位级编码器按照本次表达式访问顺序分配变量，随后 `bmc_util` 向求解器提交图、guard 和目标。`Solver::addClause_` 会按当时的根赋值忽略或缩短输入，把单元放入 trail。一次搜索还会创建 CO 变量和约束。`clauses` 中因此同时存在程序输入和原生算法生成的对象。单靠数组、变量号或 CRef 数值，无法确定某条约束的跨版本来源。`solve_` 返回时保留根赋值、活动子句和部分图状态，根层冲突又可能永久置 `ok=false`。阶段 5 的理论证书没有为一般 CDCL 子句记录可跨版本验证的前提。[开发前源码检查](evidence/stage-10/source-review.md) · [所查原生文件指纹](evidence/stage-10/fingerprint.json)

## B　各类内部状态的处置

| 状态 | P0 → P1 的处理和依据 |
| --- | --- |
| 原始非单元子句 | 仅准入仍然活动、来自可追溯的 P0 提交、未被根赋值缩短、带符号文字全部可对应、且 P1 实际提交相同内容的对象。P1 在原生 `addClause_` 中取回同一 CRef 并重新挂接 watcher。 |
| CDCL、理论原因与动态 CO | P0 活动学习库封存后逐字检查完整性，切换时清空。由旧 CO 关系、冲突分析或改变的根事实产生的子句均不随同一数组传入 P1。八轮 Fibonacci 原有 3,450 条活动学习子句，沿用数为 0。 |
| 分支启发式 | 活动度、变量堆、相位、决策资格、种子和活动增量重新初始化，随后使用 P1 原生注册的 polarity 与决策标记。启发式可影响搜索顺序，尚未验证其跨版收益。 |
| 搜索状态 | 撤销根赋值、理由、trail、决策层、传播位置、watcher、旧模型和冲突。清空中断和预算状态。累积统计用本次求解入口与出口之差读取。 |
| 理论状态与输出 | 在原求解器中销毁并重建 Closure 子对象。丢弃旧节点、可达边、guard 激活、RF/CO、待传播文字、冲突原因与输出指针。P1 使用自己的图输入、调用方排名表和写入顺序。 |

为保持 P0 的 CRef 来源可追踪，S 在 P0 推迟分配器回收，并关闭删除已满足原始子句的简化分支。P1 按正常策略搜索。二者的实际搜索轨迹在本矩阵中均与 F 相符。旧分配器保留到交接，随后原生 GC 可以迁移新一轮的活动对象。报告中的物理复用指同一分配器在 P1 挂接时返回原 CRef。C++ 虚拟地址不能单独证明子句复用。[原生切换实现](../scripts/stage10/epoch.hpp) · [原生补丁](evidence/stage-10/native.patch)

## C　Assumptions 与旧约束失效

在同一原生求解器加入 `(¬a ∨ x)` 和 `(¬a ∨ ¬x)`。依次以 `a, ¬a, a` 为假设，结果为 UNSAT、SAT、UNSAT。另一实验直接加入互相矛盾的根单元，首次 UNSAT 后改换假设仍为 UNSAT。新建对象只加载候选单元后得到 SAT。选择子可以控制预先受到保护的布尔约束。它无法撤销已进入零层的事实、解除无条件 `ok=false` 或恢复理论图里的可变关系。原型采用显式版本切换，先撤去全部活动旧约束，再以完整 P1 提交重建活动集合。P1 第一次提交前原生检查根赋值数、学习子句数和图节点数均为零。[原生 assumptions 对照](evidence/stage-10/controls.json) · [运行入口](../scripts/stage10/driver.cpp)

## D　跨版本变量映射

对 RF 和 guard，以动态线程、事件来源、调用帧、端点、地址、guard 表达式、类型布局及固定顺序的 PO/APO/RF 声明建立语义身份。对可确认的有名整数 SSA 定义，把来源、线程、动态访问、lhs、rhs、guard、类型、有无符号、宽度和位序一并绑定。一个 SAT 槽可能有多个别名，准入时比较整组标签及其极性。遇到歧义、指针、未覆盖的位级临时量或已换号的绑定，P1 按本版完整编码处理。图语义摘要也覆盖工具配置、性质和边声明。带数字的原始图和 CNF 在 P0/P1 间可以不同。[语义注册和准入实现](../scripts/stage10/bind.py) · [原图来源审核](../incdeagle/theory/context.py)

| 病例 | P0 / P1 登记的 SAT 槽 | 语义相同且编号相同，可用于重挂 | 语义相同但编号改变，排除 | P0 现场符合登记条件的 CRef → P1 实际重挂 |
| --- | ---: | ---: | ---: | ---: |
| `batch_total` | 234 / 234 | 192 | 10 | 66 → 64 |
| `batch_retained` | 234 / 234 | 192 | 10 | 66 → 64 |
| `fib_updates_8` | 2303 / 2303 | 575 | 1472 | 231 → 132 |

第一次试验把两版放在不同工作目录。原生类型 IREP 的 `#source_location.working_directory` 改变，系统对稳定图作了保守拒绝。正式试验在每个会话专用的同一源目录依次放入冻结的 P0 和 P1，分别启动新的建模进程并保留独立输出。类型摘要和准入条件保持完整。第一次拒绝的输入和差异在原始索引 `failures/initial-model-directories`、`failures/type-differences.json` 中。[首轮对象与映射证据](evidence/stage-10/mechanism.json) · [原始索引](evidence/stage-10/raw-index.json.gz)

## E　同图连续求解与理论传播

一个真实 `batch_total` 图上，原目标与六次 RF 正反假设共七次调用同一对象，与七个独立新对象的 SAT/UNSAT 逐次一致。每次 SAT 得到 23 个事件顺序条目。但在一张含两个方向相反 RF 的最小图上，先强制正向、再强制反向，两次均为 SAT。`get_write_order()` 从 `obj#1 obj#2` 变为 `obj#2 obj#1`，而外部排名两次都为 `obj#1=0, obj#2=1`。`closure::final_check` 使用 `insert` 写入已有键，保留了第一次的值。这一反例直接涉及 SAT 见证的顺序输出，两次布尔可满足性结论均与测试预期一致。[逐次假设与反向 RF 的原生结果](evidence/stage-10/controls.json) · [最小测试源码](../scripts/stage10/repeat_graph.hpp)

`cancelUntil(0)` 结合 `pop_scope` 处理决策层的 edge、RF、vital、guard、triplet 五组撤销记录。零层已消费的 RF/guard、静态顺序和动态 CO 另有生命周期。这些测试支持在已核对的语义声明上重新建图。直接沿用求解过的闭包、传播缓存和调用方输出，尚缺一般正确性依据。[原生状态分析](evidence/stage-10/source-review.md)

## F　同一对象与独立完整建模

首轮 `batch_total` 的 P0、P1 建模 PID 分别为 384878 和 384892，两轮实际搜索均在 PID 384877、原生对象地址 94150872208640 完成，对象代数保持 1。F 则在两个独立 Deagle 进程内直接求解。36 个正式会话共启动 72 个不同的完整建模进程，实际搜索涉及 54 个 PID。每一版都执行原生前端、GOTO、全部动态 dispatch 和实际 SC/RF/PO 生成。两个小例各访问 73 条动态指令，Fibonacci 各访问 239 条。检查点读取、前缀恢复、RF 重放及阶段 5 导入路径均未触发。两路同一版本的 GOTO、原始 SSA、SC、最终模型结构、整个有序求解输入、原始理论图和性质结论分别核对。候选模型还与阶段 7 冻结结构摘要核对。[建模及对象逐次记录](evidence/stage-10/trials.json) · [建模与搜索入口](../scripts/stage10/experiment.py) · [停止记录](evidence/stage-10/stop.json)

S 从原生工作进程返回整套 SAT 模型赋值、事件排名和写入顺序，原 Deagle 性质适配器据此生成反例。对每个 SAT 解逐条检查完整输入 CNF 和目标 assumptions。`batch_retained` 候选中，线程 1 写入 `shipped_units = 10`，主线程在 `harness.c` 第 21 行违反 `shipped_units == 6`。该候选的五次 F 和五次 S 都报告原断言失败。总计 72 次正式求解和 12 次程序负向对照，重建 52 份违反性质的原生反例。[候选完整反例](evidence/stage-10/retained-counterexample.json) · [离线核验计数](evidence/stage-10/verification.json)

## G　原生子句沿用与失效证据

| 病例 | SAT 输入变量 P0 → P1 | 提交原始 CNF 子句 P0 → P1 | 切换前根赋值 | P1 重挂示例，首项为 CRef，其余为有符号编码文字 |
| --- | ---: | ---: | ---: | --- |
| `batch_total` | 1203 → 1205 | 2482 → 2489 | 848 | `2013 → [12, 551]` |
| `batch_retained` | 1203 → 1205 | 2482 → 2489 | 848 | `2013 → [12, 551]` |
| `fib_updates_8` | 12554 → 12058 | 50065 → 48329 | 2715 | `168 → [311, 313, 441]` |

原型在 P0 的 `ca.alloc` 后记录真实 CRef，并在 P0 搜索结束后检查该对象仍在活动原始库中。P1 逐条校验原槽的准入绑定、当次完整提交、根层规约后的文字和分配器中的实际内容。匹配后，`addClause_` 直接取已有 CRef，依照 P1 的文字次序正常挂入 watcher，从而省掉该次 Clause 分配。每个 CRef 在本次切换只可领取一次。18 个 S 会话累计重挂 1,696 条。额外的数值对照显示，Fibonacci P0 有 46,937 次子句提交在 P1 的同编号多重集中消失，P1 独有 45,201 次。变量可能换号，这两个数仅刻画原始输入差异。[逐例原生证据](evidence/stage-10/mechanism.json) · [分配器接入补丁](evidence/stage-10/native.patch)

三个负向对照都在 P1 新建第二个原生对象，旧 CRef 重挂数均为零。同步修改的 `split_counter` 触发 `refuse_changed_graph`。`batch_total` 故意错配两个已登记的变量，触发 `refuse_unverified_variable_mapping`。Fibonacci 将 P0 一条实际存活的学习子句首文字反转，封存核对触发 `refuse_damaged_learning`。三次回退均独立全量求解并与对应 F 一致。[负向结果](evidence/stage-10/controls.json)

## H　实际节省的工作与净成本

三个候选均省去表列的 Clause 分配。两种模式仍做完整位级编码，接收 P1 的每次变量、子句、图和目标提交。S 还要在工作进程解码、再次提交及校验。在 P1，小例的语义登记与准入中位约 14.2 ms，Fibonacci 为 72.45 ms，后者的输入读取为 12.01 ms、原生状态切换为 2.17 ms、再提交为 9.06 ms。F 的决策器工厂仅约 0.06 ms。由完整 SC 模型到求解结束的配对净开销见首表。[逐项墙钟、CPU 与内存](evidence/stage-10/performance.md)

八轮 Fibonacci 的候选每轮都执行 64,162 次决策、23,391 次冲突、28,462,067 次传播、84 次重启、8,215 次理论传播和 17 次理论冲突。两路完整决策与冲突轨迹的 SHA-256 相同。S 的纯搜索在八轮都较慢，配对中位差 +41.78 ms，范围 +12.34 至 +85.56 ms。计入维护后，差值为 +111.41 至 +182.97 ms。Fibonacci 的 S 候选分配器使用 8,785,216 字节，F 为 7,822,596 字节。数据能定位语义登记、额外提交及搜索墙钟的差额。搜索计数和轨迹没有显示逻辑工作量下降，实验也未隔离出纯搜索耗时变化的单一硬件原因。[分布和逐次配对](evidence/stage-10/summary.json)

P0 本身也有代价。S 相对 F 的 P0 求解侧配对中位差依次为 +15.49、+15.05、+81.98 ms。Fibonacci 单次封存中位 0.826 ms，封存索引载荷 266,588 字节，工作进程 P0 结束时 PSS 中位约 10.03 MiB。S 的 P0 进程启动与建模重叠，未另行计入求解侧壁钟。表格分别列出 P0、P1 的纯搜索 CPU、当前 RSS/PSS、分配器与进程峰值。[P0 与 P1 的完整资源表](evidence/stage-10/performance.md)

## I　阶段 11 的候选架构与风险

下一阶段可先让原生编码器和持久求解对象共享一份有来源的变量注册表，在提交处产生可验证的稳定语义键，并保留新版本独立全量输入作对照。这直接针对本次测出的重复解码和 Python 注册开销。随后再给永久约束和版本专有约束建立明确所有权。学习子句只有在可验证的推导前提仍对 P1 有效时才准入。理论图声明与每次求解的可变状态应分开，根层传播、动态 CO、外部排名输出各自需要重置或带有可验证的版本依赖。建议先用本次的换号、损坏学习、反向 RF 和残错反例验收每一步，再扩展理论图更新。这些是设计建议，尚无相应实现和性能结论。[实测成本](evidence/stage-10/performance.md) · [已复现的失效条件](evidence/stage-10/controls.json)

## J　本阶段边界、构建和复现

本实现限于两版、可确认的相同理论结构、同槽稳定文字和仍存活的原始子句。通用的增量 CNF 编码、跨编号重写旧子句、跨版保留 CDCL 学习与启发式、Closure 图的增量维护、多版本长期回收和广泛性能回归均留待阶段 11 审批。Fibonacci 的阶段 5 历史 14 条引理导入数为 0。阶段 10 的官方 API 调用数为 0。四个实验服务已停止，正式实验 PID 均已退出。[当前状态](../project_state.json) · [停止凭据](evidence/stage-10/stop.json)

原生基线为阶段 8 已发布输入流工作树 `a2ba2f01fcc8dc83261f614039141017fb846178`。构建使用 GCC 11.4.0，最终 Deagle SHA-256 为 `b84a95d9d02e9fc48217373bf71564db1cb8ce4029644936a893aaaaef0a529e`，工作进程为 `c474a95f9d668619bdc138382bd59b1f070190c8197fa91071f9aca49075c204`。原生补丁已在干净 Git 索引重新应用，12 个生成或修改的原生文件另从干净源码生成并逐一核对。原始归档保留编译器报错、首次统计边界不一致的预试、源码目录变化的保守拒绝及修正后的独立测量。正式数字只取 `final/formal`。所有负向对照取 `final/controls`，开发试跑不混入统计。[补丁](evidence/stage-10/native.patch) · [指纹](evidence/stage-10/fingerprint.json) · [构建入口](../scripts/stage10/build.sh) · [文件锁](../configs/stage10.lock.json)

已发布的分卷可在项目根目录用标准库离线核验。程序重新检查输入、模型、子句、学习快照、轨迹、反例及计时，重算六份发布输出。两份原始分卷含 7,401 个路径，索引给出每个原始文件及分块的 SHA-256。[原始索引](evidence/stage-10/raw-index.json.gz) · [分卷一](evidence/stage-10/raw-001.zip) · [分卷二](evidence/stage-10/raw-002.zip) · [Linux 重算](evidence/stage-10/offline-linux.txt) · [Windows 重算](evidence/stage-10/offline-windows.txt)

```bash
python -B scripts/stage10/evidence.py
```

在原有阶段 7/8 Linux 构建环境中，`NATIVE_STREAM_TREE` 指向上述固定的增强输入流工作树，`NATIVE10` 是新的专用工作树路径，`STAGE7_DATA` 指向已还原的阶段 7 数据。若需重建前置输入，可使用阶段 7 的 `restore` 及阶段 8 的增强构建和输入流构建脚本。以下实验写入新的输出目录。CPU 集合应覆盖 0–7。[阶段 7 还原入口](../scripts/stage7/check_evidence.py) · [阶段 8 增强构建](../scripts/stage8/build.sh) · [输入流基线构建](../scripts/stage8/replay_build.sh) · [本阶段实验入口](../scripts/stage10/reproduce.sh)

```bash
git -C "$NATIVE_STREAM_TREE" worktree add --detach "$NATIVE10" a2ba2f01fcc8dc83261f614039141017fb846178
cp "$NATIVE_STREAM_TREE/src/config.inc" "$NATIVE10/src/config.inc"
systemd-run --wait --pipe --collect -p "WorkingDirectory=$PWD" -p MemoryMax=21474836480 \
  /usr/bin/taskset -c 0-7 /bin/bash scripts/stage10/reproduce.sh \
  "$NATIVE10" "$STAGE7_DATA" "$PWD/runs/stage10-reproduction/final"
python3 -B scripts/stage10/evidence.py --raw runs/stage10-reproduction --write runs/stage10-reproduction/derived
```
