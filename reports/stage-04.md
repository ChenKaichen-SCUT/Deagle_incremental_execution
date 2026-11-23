# 阶段 4 · 从符号执行检查点增量构建事件顺序模型

**状态　`READY_FOR_REVIEW`**

## 一、结论

`batch_total` 修改乘数后，候选从旧程序的函数调用前恢复，跳过 60 条符号指令，只执行余下的 13 条。`threshold_guard` 修改条件后跳过 61 条，只执行 23 条。两个病例都在进入求解器之前复用了旧读约束和线程顺序边。新进程从头生成的候选模型与在线模型逐阶段一致。两个同步修改均自动转入完整重建，`partial_counter` 保留的计数错误被检出。[验收汇总](evidence/stage-04/acceptance.json) · [实际开发顺序](evidence/stage-04/pilot-order.json)

| 病例及候选变化 | 候选构建路径 | 全量派发 | 实际跳过 | 候选实际派发 | 同一断言的结果，旧 → 新 |
|---|---|---:|---:|---:|---|
| `batch_total`，每箱单位数 2 → 3 | 检查点恢复 | 73 | 60 | 13 | 违反 → 有界通过 |
| `threshold_guard`，`amount < 3` → `amount <= 3` | 检查点恢复 | 84 | 61 | 23 | 违反 → 有界通过 |
| `split_counter`，把读与写合入同一临界区 | 全量回退 | 156 | 0 | 156 | 违反 → 有界通过 |
| `partial_counter`，只修复左线程 | 全量回退 | 176 | 0 | 176 | 违反 → **仍违反，156 步反例** |
| `batch_retained_error`，独立副本上将乘数 2 → 5 | 检查点恢复 | 73 | 60 | 13 | 违反 → **仍违反，62 步反例** |

最后一行专门检查复用旧前缀时能否发现候选错误。候选在反例第 53 个索引处写入 `shipped_units = 10`，索引 61 处的 `shipped_units == 6` 失败。`partial_counter` 则覆盖回退路径。线程 2 在索引 83 读取快照 0，线程 1 在索引 96 写入 1，线程 2 在索引 109 根据旧快照再写入 1。两个候选的在线结果和独立全量反例均已保存。[增量反例原始输出](evidence/stage-04/witnesses/batch_retained_error-online.json) · [增量病例的独立反例](evidence/stage-04/witnesses/batch_retained_error.json) · [部分修复的独立反例](evidence/stage-04/witnesses/partial_counter.json)

## 二、已完成的工作

以阶段 3 开发提交 `edd8dfc8` 为父提交，阶段 4 原生提交为 `3e5472e8edb93491acd6263596eea681c64c1549`。在开发目录和从 Git bundle 新建的干净检出中实际构建，两个二进制逐字节相同，SHA-256 为 `cc0e91e9d698b57754c28686f3d267e2f16e6df081c924d907512b9af88583da`。将补丁应用到父提交的独立索引，也得到同一 Git 树 `1791c8af`。独立基线 `a159f992` 及阶段 3 可执行文件的摘要均与原锁一致。[版本锁](../configs/stage04.lock.json) · [构建记录](evidence/stage-04/build.json) · [原生补丁](../patches/deagle-stage04-incremental.patch) · [Git bundle](../patches/deagle-stage04.bundle)

在具备阶段 1 至 3 工具链的 Ubuntu 项目根目录可按下列顺序重跑。`verify.py` 先结束在线旧版和候选会话，再启动全量核对。单独运行 `session.py` 可只执行在线路径。每次使用新目录以保留原始输出。[会话入口](../scripts/stage4/session.py) · [验收入口](../scripts/stage4/verify.py) · [回退探针](../scripts/stage4/probe_fallback.py)

```bash
bash scripts/stage4/prepare_deagle.sh
bash scripts/stage4/build.sh
out=$(mktemp -d "$PWD/runs/stage-04/recheck.XXXXXX")
for case_name in batch_total threshold_guard split_counter partial_counter; do
  python3 -B scripts/stage4/verify.py "$case_name" --out "$out/$case_name"
done
python3 -B scripts/stage4/verify.py batch_total --batch-error-probe --out "$out/batch_retained_error"
python3 -B scripts/stage4/probe_fallback.py --out "$out/probes"
python3 -B scripts/stage4/probe_damer.py --out "$out/damer"
```

已有归档也可以在只有 Python 标准库的控制机上核对。`python -B scripts/stage4/check_evidence.py` 会重新计算每份归档成员的 SHA-256、从原始方程计算四阶段摘要、读出两个验证器的性质结果，并逐条比较派发轨迹。[离线核对脚本](../scripts/stage4/check_evidence.py) · [归档清单](evidence/stage-04/archive.json) · [完整原始运行数据](evidence/stage-04/full-runs.tar.gz)

## 三、可检查证据

原生计数点位于 `goto_symext::symex_step` 入口。旧程序先完成一次带检查点的验证。候选恢复时，父进程将本次派发计数归零，此后每次进入该入口才记录一条 `(thread, function, pc)`。验收程序将旧程序实际运行的前缀与候选实际运行的后缀拼接，逐条核对另一个进程完整执行候选所得的序列。阶段 3 的 `visits.json` 和 `metrics.symbolic_instruction_dispatches` 保留逻辑上的完整访问序列，供 SSA 来源索引使用。候选新执行的条数取自 `native-stats.json` 的 `executed_dispatches`。[乘数例三段原生轨迹](evidence/stage-04/dispatches/batch_total.json) · [条件例三段原生轨迹](evidence/stage-04/dispatches/threshold_guard.json) · [保留错误时的三段轨迹](evidence/stage-04/dispatches/batch_retained_error.json)

| 原生候选端计数 | `batch_total` | `threshold_guard` |
|---|---:|---:|
| 检查点保存的原始 SSA 行／其中的读、写、创建线程及屏障事件 | 102／20 | 105／22 |
| 检查点保存的程序线程／符号执行新增符号表项 | 2／1 | 2／1 |
| 核对的 GOTO 节点／程序符号／可解析的不同前缀符号 | 72／94／93 | 77／95／96 |
| 复用／重新生成的完整读约束包 | 2／4 | 2／8 |
| 复用的 RF 边／读值公式 `rf-val`／候选覆盖析取 `rf-some` | 4／4／2 | 4／4／2 |
| 复用／重建的线程内 PO、APO 边 | 18／3 | 20／9 |
| 完整模型事件数，旧 → 新 | 24 → 24 | 28 → 32 |
| 完整模型 RF 边／覆盖析取数，旧 → 新 | 10／6 → 10／6 | 13／8 → 19／10 |

两个病例都命中了 `__CPROVER_next_thread_id`、`main::1::worker!0@1` 的读约束，以及线程 0 的顺序片段。`batch_total` 重建了 `shipped_units` 地址桶。`threshold_guard` 的新条件允许边界值 3 进入分支，`accepted` 和 `units` 两桶重新生成，候选覆盖析取从 8 个增加到 10 个。线程创建等独立生成的边未计入复用数。[乘数例原生计数与四阶段摘要](evidence/stage-04/cases/batch_total.json) · [条件例原生计数与四阶段摘要](evidence/stage-04/cases/threshold_guard.json) · [条件例模型变化](evidence/stage-04/deltas/threshold_guard.json)

每个候选都用相同源码字节、`harness.c`、`main.assertion.1`、64 位、SC、Closure、展开 4 及展开断言做两项独立检查。第一项用开发版从头生成 GOTO、原始 SSA、SC 输入和最终方程，对每阶段做规范化比较，并另核对带类型、位宽、guard、读值、PO/APO/RF、覆盖和性质的结构摘要。保留参与 SC 的来源和同一行分组。第二项用锁定的原始全量 Deagle 重跑旧版与候选，比较目标位置、全部性质状态、展开性质、总结果和退出码。五个候选的四阶段摘要和模型摘要均相等，独立基线逐项一致。`ModelDelta` 在这两条路径之外生成，用于查看新旧模型差异。[验收脚本](../scripts/stage4/verify.py) · [四阶段规范化](../incdeagle/model/repeat.py) · [五个候选的完整结果](evidence/stage-04/cases)

## 四、工具接入与技术选择

**Deagle。** 在原生 GOTO、`goto_symex_statet`、`symex_target_equationt` 及 SC 构建器上实现检查点和片段恢复，使用 `irep_serializationt` 传递类型化 GOTO 映像和读约束。旧版 SC 收集实际生成的公式和边。候选按其当前顺序重建地址／线程注册表、事件编号和 guard 映射。一个地址的全部读写都必须来自同一检查点，且顺序、类型、guard、原子区、来源及端点均相符，才能跳过该桶的原生生成器。命中时分配候选的 RF 选择变量，重绑定候选事件迭代器与选择原子，然后写入本次求解使用的方程。缺少成员或多出成员时，整桶重新生成，覆盖公式随之整体替换。线程片段另核对当前 APO 成员关系，按当前事件端点重放 PO/APO。[原生实现及调用位置](../patches/deagle-stage04-incremental.patch) · [实际命中和重建的区域](evidence/stage-04/cases/threshold_guard.json)

**DAMER-CAMC。** 在固定提交 `c005ebbde3672fff77c6d91da2f91d1daa45d746` 上，将薄探针与作者的解析和匹配对象文件实际链接，调用 `create_tree`、`cut_tree`、`top_down`、`get_MatchStatement`、`extract_change`。插入、删除、移动三个小样例分别返回一项对应操作，退出码均为 0。对附加全局声明后的真实 `record_batch`，匹配器给出两个 AST 匹配、零个语句匹配，随后 `extract_change` 收到 `SIGSEGV`。源码中的 `changeConstruct` 修改 PDNet/CPN 的 places 和 arcs。本阶段在线使用自己的 `ChangeProvider`，它将源行映射到降低后的 GOTO，再由原生类型化程序和静态分析检查决定是否恢复。DAMER 的结果只用于上述适配试验。[实际调用代码](../scripts/stage4/damer_probe.cpp) · [编译、链接、原始返回值及匹配行](evidence/stage-04/damer.json) · [在线变化检测](../scripts/stage4/change_provider.py) · [固定版 DAMER 源码](https://github.com/shirleylee03/damer-camc/tree/c005ebbde3672fff77c6d91da2f91d1daa45d746)

**调试中修正了两个会影响验收的问题。** Deagle 同时保存函数符号上的 C 函数体和其降低后的 GOTO。只更新 GOTO 会引起符号映像不一致，现同时安装两者，再逐字段重查整份候选映像。Deagle 自建的布尔 guard 也需要按前缀中真实的 GUARD 定义校验。另一次调试中，JSON 数组清空后失去了数组类型，逐条派发对照拒绝通过，改用新的原生空数组后重新完成验收。[原生补丁](../patches/deagle-stage04-incremental.patch) · [按顺序通过的试运行](evidence/stage-04/pilot-order.json)

## 五、正确性和范围

检查点选在旧运行首次直接调用含 `program.c` 指令的函数前。此时需要单宿主线程，程序本身可以已有多个被模拟的线程。Linux `fork` 将整个活动执行现场按写时复制隔离。子进程继续旧程序直至验证完毕。父进程停留在调用前，取得候选前端映像、核对依赖并安装允许的修改后，从当前派发点继续。每个会话最多一个这样的检查点，依赖持有现场的进程存活。[原生检查点实现](../patches/deagle-stage04-incremental.patch) · [原版符号执行代码](https://github.com/thufv/Deagle/blob/d8c79eaba5df03b1a013dc6ffbb3a1e249485c1e/src/goto-symex/symex_main.cpp)

| 状态与来源对象 | 保存方式 | 候选端的绑定和检查 |
|---|---|---|
| 原始 SSA 与来源，`symex_target_equationt::SSA_steps` | 父进程保留 SC 之前的链表、guard、`ignore/converted` 和索引。旧版后处理写入子进程私有页 | 保留原地址与前缀槽位，核对来源指令与前缀表达式。只向候选的原始 SSA 追加新后缀 |
| 程序线程、PC、调用栈、返回位置、分支合并、循环与递归，`goto_symex_statet` | 全部模拟线程、栈帧及执行器当前 C++ 栈一并保留 | 候选装入原 GOTO 指令节点。全程序检查节点种类、目标与前驱、标签、循环号、源码位置，保持所有引用和末端迭代器有效 |
| SSA L1/L2、nondet、动态对象及原子区计数，执行状态及原生命名器 | 计数器、值集和对象所有者一起保存 | 从原值发放新名称。在候选完整模型中重查类型与表达式，前缀不得引用未解析或类型不符的符号 |
| 全局表、新增符号、命名空间、`guard_managert` | 保留 guard 管理器的所有者、引用、状态新增表和全局表 | `symex_with_state` 会用 `new_symbol_table` 覆盖状态表。恢复沿既有调用栈继续派发。逐个核对全局符号、函数体及新增表，并通过命名空间或前缀类型化定义核验表达式符号 |
| `path_storaget` 的等待路径、dirty、safe-pointer、循环分析 | 保存队列、分析缓存及其引用。仅在等待队列为空、目标函数尚未进入时建立检查点 | 比较两个完整 GOTO 上的全程序取地址 dirty 集合、各函数 safe-pointer 集合及其 CFG，拒绝失配。已进入函数的循环位置保持同一节点 |
| `goto_symext` 的值集、`try_finding_value_set`、展开与性质计数、选项及目标对象 | 保留执行器及引用的对象。检查点处尚未向候选求解器转换 SSA | 固定前端、头文件、ABI、性质和内存模型。屏蔽路径枚举、惰性加载等未覆盖配置。原生配置或重绑定未获确认时走回退 |
| SC 容器、RF 选择、PO/APO 与图索引 | 旧版 SC、CNF、Closure 的可变状态留在子进程，仅导出带类型的合格逻辑片段 | 候选从独立的前置方程重建 init-write、当前事件图、同一行原子关系及候选选择变量，按验证过的桶／线程加入缓存。重新编码 CNF 并独立求解 |

增量资格目前覆盖未进入函数中的一次类型化标量算术字面量修改，或相同纯整数操作数上的 `<`／`<=`、`>`／`>=` 边界切换。要求实际 GOTO 拓扑、相关源码位置、静态依赖、类型、声明和全局初始化均匹配。两条增量路径均从头做预处理、解析和 GOTO 构造，部分复用符号执行和 SC 逻辑片段，完整运行最终的位级转换、CNF 和 Closure。完整解析后识别不了的修改、预算不足或未获确认的恢复会转入独立的新进程重建。无完整性质输出或预算耗尽的运行不能作为有界通过。此范围尚未给出对任意并发 C 程序的模型等价性证明。[会话与回退](../scripts/stage4/session.py) · [性质分类](../incdeagle/adapters/deagle.py)

| 实测回退 | 拒绝原因及行为 |
|---|---|
| `split_counter` | `record_one` 的 lock 和 unlock 各从两处变为一处。记录 `synchronization_calls_changed:record_one`，从头派发 156 条 |
| `partial_counter` | `record_left` 的 lock 和 unlock 各从零处变为一处。记录 `synchronization_calls_changed:record_left`，从头派发 176 条 |
| 检查点预算仅 1 字节 | `checkpoint_budget_or_multithreaded_host`，无法容纳现场，实际全量派发 73 条 |
| 候选新增 `<limits.h>` | 实际预处理依赖变化，记录 `config_headers_or_layout_changed`，全量派发 73 条 |
| 候选将 `boxes * 2` 改为 `boxes + 4` | 原生 RHS 结构检查拒绝该修改，记录 `non_scalar_or_address_sensitive_assignment`，随后从头构建、求解 |

三个探针均在独立输入副本上运行，逐项核对候选与锁定全量 Deagle 的性质。三个阶段 2 冻结病例的树仍为 `6d3a21f391836d5dc846b7d63123ba28d721a5dd`，阶段 3 的 `partial_counter` 副本亦通过完整性检查，原有 9 项回归测试通过。[同步变化 1](evidence/stage-04/source-changes/split_counter.json) · [同步变化 2](evidence/stage-04/source-changes/partial_counter.json) · [三项额外回退](evidence/stage-04/probes.json) · [冻结检查](evidence/stage-04/frozen-tests.txt)

## 六、成本

下表为固定二进制的一次正式运行，单位为毫秒。候选在线墙钟从提交候选到得到完整官方结果，包含预处理记录器、解析和 GOTO、变化检测、缓存读取与重绑定，以及必要的全量回退。候选前端已包含在在线墙钟内。独立基线使用阶段 1 的原始验证路径。用于模型对照的开发版全量运行另行计时。[精确墙钟与分项](evidence/stage-04/acceptance.json)

| 病例 | 旧版验证及建立检查点 | 候选在线 | 其中候选前端 | 独立基线候选全量 | 另行运行的开发版全量诊断 |
|---|---:|---:|---:|---:|---:|
| `batch_total` | 220.7 | 255.5 | 214.1 | 72.6 | 80.5 |
| `threshold_guard` | 220.6 | 256.0 | 214.1 | 71.7 | 82.9 |
| `split_counter` | 256.5 | 492.4 | 214.1 | 82.6 | 98.2 |
| `partial_counter` | 256.2 | 493.5 | 214.2 | 91.4 | 109.6 |
| `batch_retained_error` | 215.2 | 255.6 | 214.1 | 70.5 | 81.4 |

以 `batch_total` 的候选为例，原生后缀符号执行 0.441 ms，SC 事件建模 1.602 ms，CNF 与图装载 1.873 ms，求解 0.247 ms。在这些小病例上，单次在线墙钟高于独立全量，实际性能仍需在更复杂的并发基准上评估。

构建并行度 4，正式验证串行，单次候选活动预算 300 秒、会话 cgroup 上限 20 GiB。检查点预算 2 GiB，采集时检查进程整个虚拟地址空间上界，加载前另计序列化片段大小。`batch_total` 和 `threshold_guard` 的现场上界分别为 28,246,016 和 28,262,400 字节。从控制端创建本阶段工作目录（11:39:31 UTC）到服务器完成最后的运行状态检查（12:21:24 UTC）共 41 分 53.00 秒，含实现、调试、复跑和取证。DeepSeek API 调用 0 次，费用 0。本阶段使用冻结候选和明确构造的测试副本。停止检查时无活动的阶段构建、验证器或会话进程。[构建资源记录](evidence/stage-04/build.json) · [停止检查](evidence/stage-04/stop-check.json)

## 七、下一阶段建议

获得确认后，阶段 5 可沿用这两个可复用前缀，先核对历史理论引理的来源、依赖和候选端绑定，再以仍然错误的候选检验导入引理后是否保留反例。本阶段每次都使用新的求解过程。复杂基准的端到端性能测量留待后续评测。

本阶段已停止，等待你确认是否进入阶段 5。
