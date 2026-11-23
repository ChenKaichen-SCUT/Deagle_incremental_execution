# 阶段 5 · 跨版本复用经审核的排序一致性理论子句

**状态　`READY_FOR_REVIEW`**

## 一、结论

`batch_total` 的错误旧版在正常验证中产生了一条排序一致性（OC）冲突子句。把乘数从 2 修成 3 后，新建的 ClosureSolver 实际接收了这条子句，在根层传播出冲突，目标断言有界通过。把同一旧程序的乘数改成仍然错误的 5，新求解器也实际使用了该子句，随后找到 62 步反例。两次运行均跳过 60 条旧符号指令并执行 13 条候选指令。模型复用和旧理论子句复用同时发生在同一个真实版本对上。[正式验收汇总](evidence/stage-05/acceptance.json) · [修正乘数的原生回执](evidence/stage-05/batch_total/candidate-import.json) · [错误乘数的原生回执](evidence/stage-05/witnesses/batch_retained_error-import.json)

| 病例与修改 | 模型构建（跳过 / 实际执行） | 导出 | 支持 | 去重移除 | 接受 | 拒绝 | 实际导入 | 候选目标性质 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `batch_total`，乘数 2 → 3 | 恢复检查点，60 / 13 | 1 | 1 | 0 | 1 | 0 | 1 | 有界通过 |
| `threshold_guard`，`<` → `<=` | 恢复检查点，61 / 23 | 2 | 2 | 0 | 0 | 2 | 0 | 有界通过 |
| `split_counter`，合并临界区 | 全量回退，0 / 156 | 6 | 6 | 0 | 0 | 6 | 0 | 有界通过 |
| `partial_counter`，仅修复左线程 | 全量回退，0 / 176 | 6 | 6 | 0 | 0 | 6 | 0 | 仍违反，156 步 |
| 补充 `batch_retained_error`，乘数 2 → 5 | 恢复检查点，60 / 13 | 1 | 1 | 0 | 1 | 0 | 1 | 仍违反，62 步 |

四个主病例导出 15 条，旧端均能证明，候选接受并实际导入 1 条，因理论结构改变拒绝 14 条。补充病例用独立目录重跑同一个旧程序，单列计数。五个旧程序均产生目标反例，五个候选及其旧版的目标性质结果均与独立全量 Deagle 一致。[逐病例记录](evidence/stage-05/cases) · [原始运行归档](evidence/stage-05/full-runs.tar.gz)

## 二、已完成的工作

阶段 5 原生提交为 `0be9e2167d46c66ea12ca7f9f801063a03873625`，父提交为阶段 4 的 `3e5472e8`。开发检出与从 Git bundle 新建的独立检出都完成了构建，两份二进制逐字节相同，SHA-256 为 `8822a71be05f754b1fb5551d88561fe2cece35704d0660b753fca4920d4eb057`。在单独的 Git 索引中向父版本应用文本补丁，得到同一源码树 `9cc77368`。独立基线 `a159f992` 和阶段 3、4 可执行文件的摘要均通过原锁核对。[版本锁](../configs/stage05.lock.json) · [构建、树及摘要记录](evidence/stage-05/build.json) · [带分支的 Git bundle](../patches/deagle-stage05.bundle) · [原生源码补丁](../patches/deagle-stage05-theory.patch)

原生补丁实现冲突采集、新求解器创建、交图前快照和正式加子句接口。Python 将原始 literal 对应到类型化的 RF（读自哪次写）或 guard（事件发生条件），冻结完整理论结构，生成和核查顺序证书，再把通过审核的子句映射到候选本地槽位。阶段 4 的会话和全量核对入口新增可选的二进制及采集器参数，原入口已经单独回归。[理论结构与绑定](../incdeagle/theory/context.py) · [证明规则](../incdeagle/theory/certificate.py) · [记录、去重与审核](../incdeagle/theory/cache.py) · [服务器会话](../scripts/stage5/session.py) · [阶段 4 回归](evidence/stage-05/stage4-regression.json)

在具备阶段 1 至 4 工具链的目标 Ubuntu 项目根目录，可按下列已运行的入口复现。每次使用新目录。单独调用 `scripts/stage5/session.py` 仅执行旧版和候选的在线验证。[准备脚本](../scripts/stage5/prepare_deagle.sh) · [构建脚本](../scripts/stage5/build.sh) · [验收入口](../scripts/stage5/verify.py)

```bash
bash scripts/stage5/prepare_deagle.sh
bash scripts/stage5/build.sh
out=$(mktemp -d "$PWD/runs/stage-05/recheck.XXXXXX")
for case_name in batch_total threshold_guard split_counter partial_counter; do
  python3 -B scripts/stage5/verify.py "$case_name" --out "$out/$case_name"
done
python3 -B scripts/stage5/verify.py batch_total --batch-error-probe --out "$out/batch_retained_error"
python3 -B scripts/stage5/diagnostics.py "$out/batch_total" --out "$out/diagnostics.json"
```

在只有 Python 标准库的机器上，`python -B scripts/stage5/check_evidence.py` 可核对归档全部 448 个文件的摘要，通过原始数据重建新旧理论结构，复核证书、极性与候选回执，重新解析独立验证器的性质结果并运行顺序枚举。[离线核对脚本](../scripts/stage5/check_evidence.py) · [归档清单](evidence/stage-05/archive.json)

## 三、可检查证据

**一条真实旧引理的来源。** `batch_total` 旧程序在找到 62 步反例前，ClosureSolver 报告一次理论环。原生记录位置为 `ClosureSolver::propagate/pre-analyze`，来源为 `self_cycle`，子句编码为 `[1897, 1919]`，两个 literal 的旧决策层为 `[0, 75]`。上游在构造冲突子句时已对前提各取反一次，观察器记录同一个即将交给分配器的 literal 向量。对应的语义是以下两个读自选择不能同时成立。[原始冲突](evidence/stage-05/batch_total/original-conflict.jsonl) · [带极性子句和 18 步证书](evidence/stage-05/batch_total/lemma-cache.json) · [旧版受保护的测试程序](../cases/batch_total/harness.c)

1. 主线程的 `pthread_join` 从工作线程的完成写读取 `__CPROVER_threads_exited`。
2. 主线程在 join 之后检查断言时，从初始化写读取 `shipped_units`。

工作线程在报告完成前已经写过 `shipped_units`。顺序一致性要求读取得到顺序中最近的有效写。这一约束与乘数的具体数值无关。旧、新理论结构的完整内容相等，SHA-256 均为 `bd81c4e241687a3e227d48257f474589a102ddd1a39b4beeb45e3e32b27a8394`。结构记录 24 个 SSA 事件、24 条 PO、1 条 APO、10 个 RF 候选及 16 个写 guard。[可读理论结构](evidence/stage-05/batch_total/old-context.json) · [候选审核记录](evidence/stage-05/batch_total/candidate-validation.json)

**新求解器实际使用了什么。** 正式修复的旧、新求解器 PID 分别为 111564 与 111546。二者在生成方程后、CNF 转换前的变量、赋值、原始子句、学习子句和求解次数均为 0。重新绑定后，新子句编码为 `[1901, 1923]`，两个变量号都发生变化，极性保持。通过 adapter 的 `lcnf` 提交后，根层赋值从 780 增至 848，求解器从可继续搜索转为冲突。错误乘数候选上，根层赋值从 780 增至 850，求解器继续搜索并报告 `shipped_units == 6` 失败。这两次 MiniSat 都在根层处理了子句，持久子句表均保持 2,304 条。[旧图转换结果](evidence/stage-05/batch_total/old-bindings.json) · [新图转换结果](evidence/stage-05/batch_total/candidate-bindings.json) · [修复前后的新求解器状态及回执](evidence/stage-05/cases/batch_total.json) · [仍有错误时的原生结果](evidence/stage-05/cases/batch_retained_error.json)

`exported` 取原生观察次数，`supported` 要求来源和旧证书通过，`deduplicated` 统计移除的语义重复项。`accepted` 要求新结构、绑定、证书全部通过，`rejected` 汇总旧端拒收和候选拒收。`imported` 仅统计原生接口实际造成持久附加、根层入队或新冲突的子句。已蕴含、已矛盾而跳过、审核通过但未提交的情况分别记账。四个主病例的审核数、实际接口调用数及原生效果可逐条核对。[计数汇总](evidence/stage-05/acceptance.json) · [原生导入记录](evidence/stage-05/batch_total/candidate-import.json)

## 四、工具接入与技术选择

实际运行参数沿用病例锁定的 `--deagle-closure --mm sc --64 --unwind 4 --unwinding-assertions`。源码中的 Closure adapter 实例化 `Minisat::ClosureSolver`，继承 MiniSat core 的标准加子句路径。普通 `SimpSolver` 的变量替换和消元不参与这条路径。候选在方程完成后通过 `solver_factoryt` 重新创建 solver，旧分支的赋值栈、闭包和学习子句随旧求解器结束。[病例配置](../cases/batch_total/gamma.json) · [固定版本的 solver 工厂](https://github.com/thufv/Deagle/blob/d8c79eaba5df03b1a013dc6ffbb3a1e249485c1e/src/goto-checker/solver_factory.cpp) · [固定版本的 SAT adapter](https://github.com/thufv/Deagle/blob/d8c79eaba5df03b1a013dc6ffbb3a1e249485c1e/src/solvers/sat/satcheck_minisat2.cpp)

`bmc_util` 完成 RF 和 guard 转换之后，先读取将要交付的边、guard、位置和本地绑定。源码中的 `save_raw_graph` 随即调用 `init/set_graph`，会激活 APO 和 PO、登记 RF 并可传播。因此候选的理论结构冻结及审核放在交图之前。正式加子句放在首次 `ClosureSolver::solve_` 入口，此时新程序的数据、性质及图已编码，搜索尚未启动。C++ 再次检查候选槽位、类型、极性及重复变量，调用 `satcheck_minisat2_baset::lcnf`，记录 `Solver::addClause_` 的可见效果。[固定版本的交图调用](https://github.com/thufv/Deagle/blob/d8c79eaba5df03b1a013dc6ffbb3a1e249485c1e/src/goto-checker/bmc_util.cpp) · [Closure 初始化与原始冲突](https://github.com/thufv/Deagle/blob/d8c79eaba5df03b1a013dc6ffbb3a1e249485c1e/minisat-2.2.1/minisat/core/ClosureSolver.cc) · [MiniSat 加子句实现](https://github.com/thufv/Deagle/blob/d8c79eaba5df03b1a013dc6ffbb3a1e249485c1e/minisat-2.2.1/minisat/core/Solver.cc) · [锁定源码的行号和文件摘要](evidence/stage-05/source-audit.json) · [阶段 5 原生改动](../patches/deagle-stage05-theory.patch)

理论结构保存事件的线程创建链、调用位置、动态区分信息、类型和地址分区，边的实际初始化顺序、原子分组、guard 表达式及 solver 行号。带符号的 alias 组按语义代表规范化，声明常真、常假分别记录。配置、ABI、前端输入、原生提交和二进制，以及审核实现的文件摘要都参与比较。旧端从原始前提和图声明构造严格先后顺序的证明，最终得到某个事件先于自身；候选逐步重放该证明。旧数据 RHS 中与这些声明无关的数值可变化。候选端对每条引理的正常审核只重放证书，独立求解和顺序枚举均在在线会话结束后进行。[完整结构实现](../incdeagle/theory/context.py) · [证明构造与核查](../incdeagle/theory/certificate.py) · [上游 Closure 的顺序规则](https://github.com/thufv/Deagle/blob/d8c79eaba5df03b1a013dc6ffbb3a1e249485c1e/minisat-2.2.1/minisat/core/Closure.cc)

## 五、正确性和范围

- **保留第 0 层前提。** 对真实两项子句，独立枚举器取图中 23 个端点，只保留 PO、把 APO 作为先后边、选中的 RF 和必定发生的写。去掉候选数据、性质和原子非交错等限制后，穷尽 31 个前缀状态仍找不到同时满足两个读自选择的顺序。删除旧第 0 层的那个前提后，原证书被拒，枚举器在该放宽模型中访问 30 个状态即找到顺序。无前提时访问 24 个状态即可找到顺序。[枚举结果](evidence/stage-05/diagnostics.json) · [独立枚举器](../scripts/stage5/diagnostics.py)
- **两种失效路径。** 条件修改仍复用符号执行前缀，但事件、RF/guard 绑定、边和 guard 元数据变化，两条旧引理全部拒收。两个同步修改还改变了原子分组，各拒收六条，模型构建分别以 `synchronization_calls_changed:record_one` 和 `synchronization_calls_changed:record_left` 自动回退。候选全量构建和求解照常完成。[条件修改](evidence/stage-05/cases/threshold_guard.json) · [同步修改](evidence/stage-05/cases/split_counter.json) · [部分修复](evidence/stage-05/cases/partial_counter.json)
- **极性和来源。** 离线诊断将同一别名组从 `[20,21,20]` 重命名并整体反向为 `[103,102,103]`，旧子句 `[21]` 正确重绑为 `[102]`。改变一个反向别名、声明常量、边、后端、schema 或编码版本会拒收。未知动态 CO literal、普通 CDCL 来源、传播 reason、无证书的子句、空子句和错误来源版本也被拒收。将一条真实原始记录复制两次的诊断得到导出 2、支持 2、移除重复 1、留下 1。该人工重复未计入病例结果。四个主病例的旧端日志均记录 `Added co clauses: 0`；未知 CO 的拒收由注入未映射 literal 的诊断覆盖。[诊断记录](evidence/stage-05/diagnostics.json)
- **原性质与仍然存在的错误。** 五个候选的 GOTO、原始 SSA、SC 输入及完整模型四层摘要均与后启动的全量构建相同。独立阶段 1 基线使用相同输入字节、受保护 harness、性质和配置。部分修复仍在 `harness.c:31` 违反 `counter == 2`，错误乘数仍在 `harness.c:21` 违反 `shipped_units == 6`。两条候选原始反例及独立基线反例都已保存。三个冻结版本对的 Git 树、补充计数器的独立目录均通过核对，既有 9 项回归全部通过。[部分修复的反例](evidence/stage-05/witnesses/partial_counter.json) · [错误乘数的反例](evidence/stage-05/witnesses/batch_retained_error.json) · [冻结检查与回归](evidence/stage-05/frozen-tests.txt)

目前的证书限于已审核的 SC 顺序规则、清晰的自环或原子顺序环来源，并在旧端对最多 256 个观察事件尝试构造。未能证明的 unit、无稳定映射的动态 CO、race 和其他来源均保守拒绝，候选独立求解。当前可确认的是这些有界版本对的结果一致和两次原生导入效果。通用 C 程序的健全性、每条候选反例的受约束重放、较大理论图的命中率和性能仍待检验。[审核和拒绝路径](../incdeagle/theory/cache.py) · [原生诊断及两路原始输出](evidence/stage-05/full-runs.tar.gz)

## 六、成本

下表为同一次正式验收的实测数值。旧版预热包含正常验证和缓存采集，在线候选包含候选前端、模型维护、理论审核、求解和性质结果解析。新端审核总时长已包含新指纹和绑定；原生导入单列，空计划也有回调计时。独立基线列为原版 Deagle 的单次验证墙钟。各列有嵌套且测量边界不同。[纳秒级分项及墙钟](evidence/stage-05/acceptance.json)

| 病例 | 旧版预热 s | 在线候选 s | 独立候选 s | 旧指纹 / 旧审核 ms | 新指纹 / 新审核总计 ms | 绑定 / 原生导入 µs |
|---|---:|---:|---:|---:|---:|---:|
| `batch_total` | 0.2342 | 0.3370 | 0.0703 | 6.605 / 1.273 | 6.048 / 12.702 | 3.34 / 10.10 |
| `threshold_guard` | 0.2429 | 0.3371 | 0.0714 | 7.000 / 3.606 | 7.159 / 15.583 | 0 / 1.33 |
| `split_counter` | 0.3528 | 0.5414 | 0.0808 | 13.805 / 34.398 | 11.140 / 37.658 | 0 / 1.27 |
| `partial_counter` | 0.3554 | 0.5927 | 0.0888 | 14.225 / 35.485 | 13.231 / 47.315 | 0 / 1.17 |
| `batch_retained_error` | 0.2341 | 0.3370 | 0.0729 | 6.351 / 1.345 | 5.949 / 12.427 | 3.33 / 12.50 |

本次小程序的在线候选墙钟均长于独立基线；本阶段只做功能验收，未开展正式加速比实验。旧端记录的是包含正常验证的预热成本，单独归因于采集的增量内存和时间尚未测量。服务器用 4 路编译，每次运行 1 个验证任务，限制 20 GiB。锁定源码后的开发构建用时 3.13 秒，独立检出用时 3.05 秒，均使用已有 ccache；独立构建的 `time -v` 最大 RSS 为 150,188 KiB。开发初期一次长编译超过 SSH 客户端等待时限，随后显式向构建服务传入 ccache 环境并完成了双检出构建。从阶段工作目录创建至结束原生实验、归档和进程检查共 20 分 35 秒，不含后续报告整理与上传。DeepSeek 调用 0 次，输入、输出 token 和 API 费用均为 0。[构建日志摘要](evidence/stage-05/build.json) · [停止检查](evidence/stage-05/stop-check.json)

## 七、下一阶段建议

获准后，阶段 6 可把旧反例、一次候选生成、模型更新、引理审核和独立全量对照串为单次修复流程。`batch_total` 可验收同一病例的两种复用，`partial_counter` 可验收修复后仍失败时的反例交付。当前阶段已归档，停止检查时没有本阶段构建、求解或会话进程。[项目状态](../project_state.json) · [停止记录](evidence/stage-05/stop-check.json)

本阶段已停止，等待你确认是否进入阶段 6。
