# SV-COMP 2026 并发候选筛选与 AI 修复预实验

**状态为 READY_FOR_REVIEW。** 固定阶段 10 提交为 `dca9eb78250426fe5b2aab22aea5ef91025dd24d`。从赛方成绩筛出 291 个已确认的错误检出，其中 3 个进入 10～300 秒优先组。实际审查 11 题，对有原生反例的 6 题调用修复模型，得到 3 条版本链、4 个相邻版本对。两题最终有界通过原可达性目标，只有简单边界修复也保住了本次可确认的其他性质。读写锁 P2 仍有新引入的数据竞争。4 对的跨版本求解器实际复用数均为零。[正式候选](evidence/svcomp26/candidates.csv) · [冻结版本和补丁](../cases/svcomp26/versions) · [分母与调用数](evidence/svcomp26/pilot-counts.json)

## 1　官方候选与初筛

以赛方最终逐题表、同一批次原始 BenchExec XML 和最终计分 XML 三方核对可达性类别。筛选条件为 YAML 与原始记录均预期 false、原始和计分状态均为 false(unreach-call)、两者类别均为 correct、最终表实得 1 分。分组使用 CPU 秒，另保留未取整的墙钟秒和内存字节。CPU 小于 1 秒有 272 题，1≤CPU<10 有 16 题，10≤CPU≤300 有 3 题，CPU>300 有 0 题。另有 16 个原始检出在最终表为 correct-unconfirmed，得 0 分，其中中档 4 个。超时、未知、内存耗尽及无有效见证的行保留在总表。[赛方逐题表](https://sv-comp.sosy-lab.org/2026/results/results-verified/C.unreach-call.Concurrency.table.html) · [赛方规则](https://sv-comp.sosy-lab.org/2026/rules.php) · [未确认清单](evidence/svcomp26/unconfirmed.csv)

收集了普通 C 并发四个 run set 的 3,177 条记录，可达性 725 条、数据竞争 1,030 条、溢出 669 条、内存安全 753 条。赛方 Deagle 4.1.0、BenchExec 3.32、4 个处理单元、900 CPU 秒、15,000,000,000 字节。逐行表含 YAML、输入、属性路径和逐文件 SHA-256，另有 8 份原始与计分 XML、冻结的可达性 HTML 和原生日志 ZIP。svcomp26 注释标签对象为 `d3c6ac0522e86d2b37c7add407db4aedf88559bf`，解引用提交为 `7efe28dd29576b46927b7a34e8f742bd90966a75`。2,120 个唯一路径中 2,118 个取到原始字节。内存安全 run set 中 goblint-regression/09-regions_12-arraycollapse_rc-deref 的 YAML 和 C 文件在最终标签中缺失，该行保留赛方记录和明确空哈希。[官方标签](https://gitlab.com/sosy-lab/benchmarking/sv-benchmarks/-/tags/svcomp26) · [完整记录](evidence/svcomp26/all-records.csv) · [来源及哈希](evidence/svcomp26/official-provenance.json) · [文件锁](evidence/svcomp26/original-files.json)

| 人工核对的任务 | 最终官方记录 | 官方 CPU 秒 | 固定 Closure 的独立 P0 |
|---|---|---:|---|
| pthread-ext/25_stack_longer-1 | 已确认检出 | 16.148250 | 目标违反，8.128 s |
| pthread-ext/25_stack_longest-2 | 已确认检出 | 40.021514 | 目标违反，22.952 s |
| pthread-ext/26_stack_cas_longer-1 | 已确认检出 | 34.403372 | 目标违反，41.381 s |
| pthread-complex/bounded_buffer | 内存耗尽 | 62.157374 | 指针处理拒绝，退出 6 |
| pthread-complex/elimination_backoff_stack | 内存耗尽 | 234.088848 | 同上 |
| pthread-complex/safestack_relacy | invalid task (unknown) | 43.367979 | 120 s 超时 |
| pthread-complex/workstealqueue_mutex-1 | 数据竞争类别的错误见证缺失 | 20.761545 | YAML 仅登记 no-data-race，按该性质复跑也因指针处理退出 6 |
| pthread-atomic/read_write_lock-2 | 已确认检出 | 0.239140 | 目标违反，0.264 s |
| pthread-deagle/arithmetic_prog_bad | 已确认检出 | 6.273308 | 目标违反，3.770 s |
| pthread-theta/unwind1-1 | 已确认检出 | 5.208159 | 目标违反，0.114 s |
| pthread/stack-2 | 已确认检出 | 0.844727 | 指针处理拒绝，退出 6 |

每道实名预选均使用准确的 svcomp26 文件。官方日志为 read_write_lock-2 指定 --32。上述 11 个 YAML 的输入均为 ILP32 的 .i 文件。独立实验直接使用原始预处理字节，设置 SC、Closure、main、YAML 位宽和固定展开界限，并启用 --unwinding-assertions。官方驱动还使用 refined pointer analysis 和自己的展开策略。两套时间分别用于赛方筛选和本机实验。原生拒绝文本为 “pointer handling for concurrency is unsound”。若目的在于研究该组大型指针程序，可以另设官方工具与研究工具的指针分析对照。[人工审查与 YAML](evidence/svcomp26/panel.json) · [11 份官方逐题日志](evidence/svcomp26/official/logs) · [本地性质明细](evidence/svcomp26/local-properties.json) · [展开界限](../scripts/svcomp26/config.py)

## 2　实际修复与失败样本

六道题都先取得 reach_error.assertion.1 的原生失败轨迹。三道中档栈题各有独立失败的 main 展开义务。指名检查原断言后，研究版仍会报告动态生成的展开义务。最长的栈题有两个线程在同一条目标轨迹中触发同一断言，复核按事件和线程验证两次命中。另对三份冻结源码运行 32 位单线程合法前缀。初始栈为空，push(17) 成功后 top 指向载荷 17、下一节点为 0、isEmpty() 返回假，随后原检查进入 reach_error。三次受控执行均从原断言钩子退出 42。这表明只要保留成功入栈与 isEmpty 的含义，原检查要求成功入栈后仍为空的条件便有反例。三题的模型请求都用完输出额度，未提交补丁，均保留在失败分母。[功能对照程序](../scripts/svcomp26/functional.py) · [原始轨迹与编译运行记录索引](evidence/svcomp26/raw/raw-index.json.gz)

| 冻结版本对 | AI 实际改动 | 独立全量与功能结果 |
|---|---|---|
| arithmetic_prog_bad P0→P1 | 删除完成三次交接后额外执行的 total += j | 目标断言成功，生产和消费等待循环仍各有失败的展开义务。12 组初值及启动顺序都完成 3 次交接，增量从 6 修正为 3。结论为展开不完整。 |
| unwind1-1 P0→P1 | 两个原分支先计算局部值，发布前将超过 _N 的值钳制到 _N | 目标与 f2 的展开均成功。对 N 为 0、1、4、17，两种非确定分支及两种线程先后关系共检查 16 组，工作量与完成次数符合契约。 |
| read_write_lock-2 P0→P1 | 去掉读写线程内多处显式原子区，读者继续用两条语句回写引用计数 | 原目标再次失败。强制两个读者交错时，两者都完成，4 个不同 x 初值均留下 r=1。此残错用于生成 P2。 |
| read_write_lock-2 P1→P2 | 将两步释放替换为命名原子函数 __VERIFIER_atomic_release_read_lock，在函数内递减 r | 固定 Deagle 原断言有界通过。双读者仍可重叠执行，4 组检查均留下 r=0，后续写者能写入 3。GCC 11 默认 GNU11 语法检查通过并发出警告，严格隐式声明检查失败，原因是新增函数的定义位于调用之后。 |

各版完整源文件、父版本和补丁哈希均已冻结。源文件以 .i 为准。保持原始 main、目标断言、线程启动/汇合、假设及展开界限；阶段 10 所用 Deagle 二进制和原生 worker 逐字节核对。功能探针独立于正式验证，读写锁探针按验证器的原子函数语义模拟互斥并安排确定性交错。严格编译诊断作用于未经探针变换的原文件。[逐版本差异](../cases/svcomp26/versions) · [独立结果](evidence/svcomp26/local-properties.json) · [冻结文件核对](evidence/svcomp26/release-checks.json)

**注册的其他安全性质改变了读写锁的验收结论。** 对形成版本链的 3 题共 7 个版本，另按各自 YAML 执行了 21 次数据竞争、溢出和内存安全检查。读写锁 P0 有界通过数据竞争检查；P1 有 24 项失败，涉及 r、w、x、y；P2 有 15 项失败，涉及 w、x、y，均可追溯到原生反例。P2 修复了释放计数，保留了 P1 去掉其他原子区的修改。该版本归为**原目标通过、并发安全回归**。unwind1 的旧版和候选均有界通过数据竞争和溢出检查。算术题的对应检查仍受展开限制。三个程序的内存安全检查在所有版本上均由固定后端以指针处理不可靠为由拒绝。按“通过原目标且无已观察到的其他性质回归”计为 **1/6**；要求所有登记安全性质均有正面验证证据时为 **0/6**。数据竞争和内存安全等独立检查使用官方日志的性质选择参数。主可达性验证始终保留原断言。[21 次独立结果](evidence/svcomp26/secondary-properties.json) · [源码、原生反例和标准输出](evidence/svcomp26/secondary-raw.tgz) · [复跑入口](../scripts/svcomp26/secondary.py)

## 3　修复率、调用与周期

分母为 6 道实际发往 mini-SWE-agent 2.4.6 和 DeepSeek 官方 API 的题。首个 API 回复即产生通过版本为 **0/6**，第一轮生成结束时通过也为 **0/6**；以第一份真正冻结的 P1 计为 **1/6**，只看生成过 P1 的题为 **1/3**。经过后续请求，最终有 **2/6** 通过原可达性和功能检查。P1 中仍有原断言反例的比例为 **1/3**；全部 4 份候选有 **1/4** 残错。按每题最后状态，2 题通过原目标，1 题展开不完整，3 题保留有反例的 P0。最后三个有补丁的任务中，已确认的残错为 0 个，仍有 1 个未完成证明。[分母](evidence/svcomp26/pilot-counts.json) · [逐次模型结果](evidence/svcomp26/repair-outcomes.json)

每题安排至多 4 次请求、320 s AI 控制器时间和 0.14 美元，两轮各至多 2 次和 160 s。六题实际 11 个互异服务响应。按回报的缓存命中、未命中与输出 token 计算，高峰价合计 0.068086744 美元，低峰价为 0.034043372 美元，两者为费率估算。首轮五题在思考输出耗尽时未提交；读写锁、边界题后来各用一次请求返回了未被初版工具接受的操作。在原始错误独立复现后，两题改用受限整段文本编辑，均取得 P1。读写锁余下的一次请求使用 P1 真实反例与功能检查结果取得 P2。预算计入所有失败调用。模型只看到经哈希核对的公开源码片段、契约和反例摘要；文件操作沿用无网络的 uid 65534 沙箱。计时试验从冻结版本直接启动。[调用控制器](../scripts/svcomp26/rounds.py) · [模型与工具约束](../scripts/svcomp26/repair.py) · [官方费率](https://api-docs.deepseek.com/quick_start/pricing/)

| 任务 | API 请求 | AI 活动秒 | P0、复查和各候选独立验证秒 | 修复活动合计秒 | 含批次排队的实测经过秒 |
|---|---:|---:|---:|---:|---:|
| 25_stack_longer-1 | 1 | 46.585 | 16.205 | 62.790 | 1232.097 |
| 25_stack_longest-2 | 1 | 54.248 | 45.754 | 100.003 | 1278.154 |
| 26_stack_cas_longer-1 | 1 | 50.091 | 82.864 | 132.955 | 1305.230 |
| arithmetic_prog_bad | 1 | 16.690 | 6.087 | 22.777 | 1468.913 |
| unwind1-1 | 3 | 61.940 | 0.342 | 62.281 | 1460.301 |
| read_write_lock-2 | 4 | 93.200 | 0.606 | 93.806 | 2652.625 |

活动列使用已测量的 AI 控制器与独立原生运行区间；实测经过时间从 P0 输入就位，到最后一个独立性质回执或最后一次失败的模型提交，包含批次排队、控制器调试和审阅间隔。功能测试与重复的 F/S 性能试验另行保存。按轮可查 P0、P1、P2、复查和生成耗时。[分项和 UTC 边界](evidence/svcomp26/per-task-cycle.json) · [机器与实际资源](evidence/svcomp26/machine.json)

将同一任务实测的 AI、独立原目标检查、一个试验重复中的完整 F 或 S 会话串行相加，得到含输入采集和核验的周期估计。三次配对的中位数分别为算术题 F 37.017 s、S 36.564 s，边界题 F 62.564 s、S 62.563 s，读写锁 F 94.777 s、S 95.098 s。读写锁计入两个相邻会话，P1 在第二个会话中再次作为旧版建模。附加的 21 次安全性质诊断另耗原生墙钟合计 55.015 s。[周期逐次重组](evidence/svcomp26/per-task-cycle.json) · [附加性质耗时](evidence/svcomp26/secondary-properties.json)

## 4　四个相邻版本对的 Closure 对照

F 每版从同一增强版 Deagle 内新建 ClosureSolver。S 使用冻结的阶段 10 双版本会话，或在准入失败后完整重建。每对 3 次，每次交替 F→S、S→F、F→S。48 次独立建模均检查原生 dispatch、SC/RF/PO 调用和旧前缀/片段计数。逐版核对 GOTO、原始 SSA、SC 输入、最终模型、有序求解输入、理论图和独立性质回执。跨版本准入的变量、可实际重挂的旧原始子句及实际导入的学习子句均为 0，**Solver 复用率为 0/4 对、0/12 个 S 会话**。[单次原始计数](evidence/svcomp26/trials.csv) · [独立审计](../scripts/svcomp26/analysis.py)

| 版本对 | CNF 变量数，旧→新 | 原始子句提交数，旧→新 | 理论图节点，旧→新 | 每版决策查询数 | 实际 S 处置 |
|---|---:|---:|---:|---|---|
| arithmetic P0→P1 | 1,264,650→1,264,409 | 6,228,985→6,227,993 | 235→233 | 3、3 | 阶段 10 每版只接收一次求解，两个版本均走独立整程序重建 |
| unwind1 P0→P1 | 2,553→2,723 | 6,031→6,399 | 38→39 | F 各 1 次，含两个性质义务 | 保留额外展开目标，无法预先保证 SAT 后不会追加查询，走整程序重建 |
| 读写锁 P0→P1 | 7,879→7,879 | 25,842→25,842 | 81→81 | 1、1 | 工作进程拒绝变图并新建第 2 代对象 |
| 读写锁 P1→P2 | 7,879→7,879 | 25,842→25,842 | 81→81 | 1、1 | 同上 |

读写锁三个版本的有序布尔流 SHA-256 相同，理论图另行传入。P1→P2 将 PO 从 97 条变为 95 条，APO 从 15 条变为 17 条，RF 保持 131 条。两个版本达成了相反的可达性结论。这对版本直接检验了只按布尔输入身份复用的风险。算术题减少 6 条 RF 和 4 条 PO；unwind1 增加 3 条 RF 和 2 条 PO。四对的语义图摘要均改变。带签名的完整别名组在相同 SAT 槽位上确认相等的数目也均为 0。[图元素、保留与增删](evidence/svcomp26/graph-deltas.json) · [语义注册和原生处置](evidence/svcomp26/solver-summary.json)

两次读写锁切换的旧库各有 383 条活动学习子句，签名快照均可审核。通过完整绑定的条目和可据此证明的 P1 子句均为 0。算术题与 unwind1 的旧求解器结束时分别有 90,884 和 12 条活动学习子句；整程序回退路径只提供活动数，没有最终库的有符号快照，迁移后逻辑上仍有效的总量无法确定。四对实际沿用的学习子句数均有明确的零值。[学习库范围与统计](evidence/svcomp26/solver-summary.json)

| 候选版本 | F / S 求解侧中位 ms | 配对 S−F 中位 ms | F / S 纯搜索中位 ms | 决策 / 冲突 / 传播，F 与 S 相同 |
|---|---:|---:|---:|---:|
| arithmetic P1 | 3047.780 / 3058.818 | −18.741 | 1140.463 / 1156.043 | 671,948 / 276 / 5,936,683 |
| unwind1 P1 | 17.490 / 17.339 | −0.150 | 0.930 / 0.897 | 472 / 25 / 4,363 |
| 读写锁 P1 | 50.959 / 112.437 | +61.478 | 6.225 / 6.339 | 3,015 / 185 / 46,044 |
| 读写锁 P2 | 50.559 / 111.610 | +61.174 | 6.674 / 6.625 | 1,335 / 209 / 53,273 |

求解侧时间沿用阶段 10 的工厂创建加模型就绪至决策器返回；各自中位数与逐次相减后取中位数是两种统计量。算术题三次配对差为 +22.455、−619.890、−18.741 ms，两路实际均完整重建。两次读写锁切换均付出了约 61 ms 的配对中位额外开销。3 次重复足以发现机制和回退，尚不足以把微小墙钟差推广到其他任务。完整进程耗时、原生 solve、理论传播、冲突、内存及逐次波动均可重算。固定钩子每次 solve 重新打开 search.bin，多查询时只有最后一次查询的详细轨迹；每次查询的前后计数均保存在 native-state.tsv。[逐次性能](evidence/svcomp26/trials.csv) · [钩子源码](evidence/stage-10/native.patch)

## 5　复现与审查

在项目根目录运行以下命令。首条从提交内的官方原件和固定 GitLab 提交重新生成候选清单。接下来三条只需要本地字节。Linux 服务器与 Windows 工作区已分别从原始结果复算出相同的 5 份汇总文件。主归档含 2,153 个原始路径、6 个内容寻址分卷，合计 84,794,370 字节，包含早期控制器错误、失败尝试、原始 SAT 输入和诊断。[原始索引](evidence/svcomp26/raw/raw-index.json.gz) · [原件和源码哈希](evidence/svcomp26/release-checks.json)

```bash
python -B scripts/svcomp26/replay_dataset.py runs/sv26-inputs runs/sv26-official
python -B scripts/svcomp26/archive.py unpack reports/evidence/svcomp26/raw runs/sv26-restored
python -B scripts/svcomp26/analysis.py runs/sv26-restored runs/sv26-derived
python -B scripts/svcomp26/review.py runs/sv26-restored reports/evidence/svcomp26
```

需要重新计时时，在新的 Linux 输出目录运行以下命令，先将 DEAGLE、CLOSURE_WORKER 设为阶段 10 两个二进制的绝对路径。本实验在 CPU 0–7、15,000,000,000 字节 cgroup 下运行。独立原目标检查每版 120 s，带原生观测的每版 180 s。复跑从已冻结补丁开始，调用数为零。[阶段 10 构建脚本](../scripts/stage10/build.sh) · [构建锁](../configs/stage10.lock.json) · [本次重跑入口](../scripts/svcomp26/replay_frozen.py)

```bash
systemd-run --wait --pipe --collect -p "WorkingDirectory=$PWD" -p MemoryMax=15000000000 -p CPUAffinity=0-7 /usr/bin/python3 -B scripts/svcomp26/replay_frozen.py runs/sv26-restored runs/sv26-new "$DEAGLE" "$CLOSURE_WORKER"
```

**供阶段 11 审查的选择。** 读写锁 P1→P2 适合检验同步边变化时的正确拒绝，P0→P1 提供同一断言持续失败的对照。算术题提供 620 余万条提交、同一模型多次查询的真实工作负载，使用它评估修复成功仍受展开义务限制。unwind1 适合作为有完整展开证据的简单修复。三道中档栈题与命名的排除题保留用于筛选回归。这批数据支持先决定是否覆盖多查询生命周期、怎样审核理论图变化，再决定深入实现范围。项目状态停在预实验审查点。[状态](../project_state.json)
