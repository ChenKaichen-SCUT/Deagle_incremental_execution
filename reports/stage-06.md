# 阶段 6　串联完整单次修复工具链

状态为 **READY_FOR_REVIEW**。本阶段以 `batch_total` 现场生成 AI 候选，以五个不同版本对检查增量与独立全量路径。下列命令和计数均可在归档中复核。[验收汇总](evidence/stage-06/acceptance.json) · [代码和二进制锁](../configs/stage06.lock.json)

## 一、结论

mini-SWE-agent 将真实的 62 步反例压缩成与修复相关的观测，向 DeepSeek 官方 API 请求修复。线程 1 在第 53 步将 `shipped_units` 写成 4，主线程在第 61 步违反 `harness.c:21` 的断言 `shipped_units == 6`。模型将 `boxes * 2` 改为 `boxes * 3`。同一次原生会话沿用 60 步有效前缀，仅执行 13 步，复用 2 组读事件约束，并向新的 Closure 求解器实际导入 1 条旧理论子句。增量与独立全量对相同候选均给出 `NO_VIOLATION_WITHIN_BOUND`。[发送给模型的项目数据](evidence/stage-06/ai/model-input.json) · [AI 补丁](evidence/stage-06/ai/patch.diff) · [原生模型检查](evidence/stage-06/ai/model-check.json) · [独立全量结果](evidence/stage-06/ai/independent-full.json)

9 次完成两路验证的运行共覆盖 5 个不同的 `P0→P1` 版本对。按不同版本对计，3 对修复后有界通过，2 对仍违反原性质，两路在 5 对上均一致。一次额外的付费尝试没有产生候选，单独计为修复失败。性能评价留待更复杂的基准。[9 次运行及失败尝试](evidence/stage-06/acceptance.json)

## 二、已完成的工作

控制器在取得目标违例、当前反例和旧缓存后调用修复器。候选只能修改 `program.c`，控制器重新应用 diff、核对受保护输入和候选的字节哈希，并要求新 GOTO 中存在唯一的原断言。修复和前端检查期间原生检查点保持存活。增量会话关闭后，控制器使用另一套固定二进制启动独立全量基线。启用 `--check-model` 时，第三个进程在两路结束后才生成全量诊断模型。[控制器](../incdeagle/workflow.py) · [候选冻结与前端检查](../incdeagle/repair.py) · [独立全量与诊断](../incdeagle/comparison.py) · [AI 运行时间线](evidence/stage-06/ai/timeline.jsonl)

服务器执行了以下入口。`--key-stdin` 的输入经控制端已有的加密连接传给受信控制器，命令行与服务器项目目录均不保存 API Key。这次实际运行以输入摘要锁定获准外发的项目数据。[CLI 源码](../incdeagle/cli.py) · [服务器工具检查](evidence/stage-06/doctor.json)

```bash
python3 -B -m incdeagle.cli doctor
python3 -B -m incdeagle.cli inspect-case --case cases/batch_total/task.yaml
python3 -B -m incdeagle.cli run-case --case cases/batch_total/task.yaml \
  --repair mini --key-stdin \
  --repair-input-sha256 b498931c50135bd413985bd013e423edd146f29e1aca10f2e4cc8272ddfe5a7f \
  --check-model --out runs/stage-06/release/ai-single-edit
python3 -B -m incdeagle.cli replay-pair --case cases/batch_total/task.yaml \
  --from-run runs/stage-06/release/ai-single-edit --check-model \
  --out runs/stage-06/release/replay-ai
python3 -B -m incdeagle.cli summarize --runs runs/stage-06/release
```

**复现。** 在配置好固定二进制的项目根目录，运行下一条命令即可从新会话重放。本次 AI 候选与仓库冻结的 `batch_total/candidate/program.c` 逐字节相同，SHA-256 为 `8617eb79a6d7a7e87967adf39d041a465bb708f9dba1221dcefd31c58fde78cd`。上面的 `--from-run` 入口则直接读取实际 AI 运行冻结的文件。两种重放都重新准备 `P0` 缓存，API 调用为零。[AI 冻结记录](evidence/stage-06/ai/frozen.json) · [实际执行的 AI 候选重放](evidence/stage-06/cases/replay-ai.json)

```bash
python3 -B -m incdeagle.cli replay-pair --case cases/batch_total/task.yaml --check-model
```

## 三、可检查证据

下表按不同版本对计数。第一行的五次运行分别为 AI 修复、其冻结重放、人工现场提交、人工现场提交的重放，以及用已知 diff 的人工入口。其余每行各一次。“跳过 / 执行”来自 C++ 原生符号执行统计。“导出 / 拒绝 / 导入”来自旧求解器的理论冲突与新求解器回执。[逐次运行及六项理论计数](evidence/stage-06/acceptance.json)

| 版本对与修改 | 双路候选结果 | 跳过 / 执行 | 导出 / 拒绝 / 导入 | 原生路径或候选反例 |
|---|---|---:|---:|---|
| `batch_total`，乘数 2→3 | 有界通过 | 60 / 13 | 1 / 0 / 1 | 检查点恢复 |
| `threshold_guard`，条件修改 | 有界通过 | 61 / 23 | 2 / 2 / 0 | 检查点恢复，理论上下文变化 |
| `split_counter`，同步修改 | 有界通过 | 0 / 156 | 6 / 6 / 0 | `synchronization_calls_changed:record_one` |
| `partial_counter`，部分同步修复 | 仍有违例 | 0 / 176 | 6 / 6 / 0 | `synchronization_calls_changed:record_left`，156 步反例 |
| `batch_total`，乘数 2→5 | 仍有违例 | 60 / 13 | 1 / 0 / 1 | 检查点与旧子句均命中，62 步反例 |

AI 运行中，旧求解器 PID 为 `124102`，等待候选的检查点进程 PID 为 `124085`，后者恢复后构造新求解器。以语义读写事件重新绑定后，旧冲突文字 `[1897, 1919]` 对应新 CNF 文字 `[1901, 1923]`。原生添加操作当场得到 `contradiction`，根层赋值由 780 变为 848，持久子句数保持 2304。本例导入计数为 1，依据是求解器实际接受并处理了这条子句。四个阶段 `goto`、`raw_ssa`、`sc_input`、`full_model` 的摘要以及完整结构摘要均与独立诊断相符。[原生导入回执](evidence/stage-06/ai/native-import.json) · [新旧符号和阶段摘要](evidence/stage-06/ai/model-check.json) · [检查点与反例绑定](evidence/stage-06/ai/repair-input.json)

归档包含 1,158 个文件，含原始 JSON、两路反例、命令、程序快照、GOTO、事件模型、理论证书和原生回执。在 Ubuntu 和 Windows 上均已用下列命令离线核对。脚本从原始结果重建反例，重新应用补丁，按每条子句检查证明与带符号的映射，并从冻结代码重建成功请求的工具参数，与供应商回执所记的参数哈希比对。[完整归档](evidence/stage-06/full-runs.tar.gz) · [逐文件 SHA-256](evidence/stage-06/archive.json) · [离线复核源码](../scripts/stage6/check_evidence.py)

```bash
python -B scripts/stage6/check_evidence.py
```

## 四、工具接入与技术选择

**AI 修复。** 首次外发申请因数据范围尚未获准被执行环境拒绝。用户随后明确授权，控制器将本例的项目数据限定为 853 字节，包含 4 行 C 函数、3 行调用上下文、性质、边界和反例摘要。首次获批运行发出 6 次请求，其中 3 个工具命令被适配器拒绝，最后一个响应触及输出上限，mini 返回 `RepeatedFormatError`，没有产生 `P1`。修复适配器后，用同一份项目数据再次申请并获准。模型通过一次原生 bash 工具调用提交了正确的一行。成功请求的初始消息含固定操作说明，共 1,869 字节，另有固定工具定义。首次失败与重试均保留了响应 ID、工具参数哈希和供应商 token 计数。[失败记录](evidence/stage-06/ai/first-attempt/model.json) · [成功调用和工具回执](evidence/stage-06/ai/model.json) · [输入选择代码](../incdeagle/repair_input.py)

mini 复用阶段 1 验证的 `setpriv` 与 Bubblewrap，以 UID 65534 运行，沙箱无网络路由。工具可读范围限于经过核对的上下文和候选文件。控制器通过私有标准输入接收凭据，使用官方认证参数；工具观测与候选代码均有内容检查。隔离测试实测了读写、原生提交、7 种越界或组合命令，以及提交前的输入指纹校验。[隔离实测](evidence/stage-06/ai/sandbox-check.json) · [工具适配代码](../scripts/stage6/mini_tools.py) · [模型控制器](../scripts/stage6/mini_repair.py)

**人工与传统修复。** 人工入口支持已有 diff，也支持在旧检查点等待时依据当次反例提交。现场人工提交与这次 `P0` 的 62 步轨迹哈希绑定。传统方案沿用阶段 2 的实测结论，ConRepair 的作者版前端拒绝此项目计数器中的 `pthread_mutex_t`，Liss 在固定依赖下未构建成功。阶段 6 实际接入了 mini 和人工适配器。[人工提交](evidence/stage-06/live/manual-submission.json) · [人工现场时间线](evidence/stage-06/live/timeline.jsonl) · [传统工具的命令与诊断](evidence/stage-02/traditional.json)

**固定运行版本。** 增强版 Deagle 为 `0be9e216`，独立基线为 `a159f992`，两者运行前均校验二进制 SHA-256。mini-SWE-agent 使用阶段 1 固定的 `a83fcae8` 检出和 Python 3.10.12。阶段 6 新增 Python 协调层，复用阶段 4 的检查点与阶段 5 的 TheorySession、证书审核和原生导入接口。构建证据沿用相应阶段，现场另跑了阶段 5 原入口验证兼容性。[本阶段环境](evidence/stage-06/environment.json) · [阶段 5 入口回归](evidence/stage-06/stage5-regression.json) · [固定工具链](../configs/toolchain.lock.json)

## 五、正确性和范围

增强版和独立全量读取相同的 `P1`、harness、原性质和配置。AI 例使用 SC、64 位、展开界 4，并启用展开检查。`partial_counter` 的两份 156 步反例分别指向新候选的同一断言。乘数 2→5 的例子在导入旧子句后仍给出新程序的 62 步反例。离线复核验证了两路轨迹的来源、目标、输入哈希与原始观测，特定反例的独立受约束重放尚未实现。这些结果支持上述有限输入与配置。[部分修复的增量反例](evidence/stage-06/witnesses/replay-partial_counter-online.json) · [独立全量反例](evidence/stage-06/witnesses/replay-partial_counter-baseline.json) · [带子句复用的残留错误](evidence/stage-06/cases/manual-retained.json)

五项单独的实际运行覆盖了语法错误（`program.c:3`，前端退出码 6）、试图修改 harness、缺少凭据、外发输入哈希不符，以及旧程序已满足有界性质。它们均在候选冻结和启动基线前结束。比较器另以 6 项受控输入检查确定结论矛盾及 `UNKNOWN/TIMEOUT/OOM/ERROR/INCOMPLETE_UNWINDING` 的分类。实际双路运行中确定冲突数为 0。原阶段 2 冻结的三个版本对与阶段 3 补充病例的 Git 树均已核对。[失败和资格检查](evidence/stage-06/probes.json) · [既有 9 项回归及冻结检查](evidence/stage-06/frozen-tests.txt) · [冻结树与停止记录](evidence/stage-06/stop-check.json)

## 六、成本

服务器从创建阶段运行目录到归档、进程复查耗时 **31 分 32 秒**，含开发、审批等待、调试和验证。服务器可用 CPU 亲和集为 8 核，开始时可用内存约 29 GiB、磁盘空余约 66 GiB。验证使用同一病例配置，单次资源上限为 20 GiB、300 秒。[环境采样](evidence/stage-06/environment.json) · [停止时间](evidence/stage-06/stop-check.json)

| 实际付费尝试 | 请求 | 输入 token | 其中缓存命中 | 输出 token | 按峰时费率估算 USD | 按低谷费率估算 USD |
|---|---:|---:|---:|---:|---:|---:|
| 首次，未产生候选 | 6 | 7,447 | 5,632 | 3,226 | 0.015418568 | 0.007709284 |
| 增加单行提交后生成候选 | 1 | 711 | 0 | 356 | 0.002348280 | 0.001174140 |
| **合计** | **7** | **8,158** | **5,632** | **3,582** | **0.017766848** | **0.008883424** |

金额根据供应商 usage 与阶段 1 记录的两档单价估算，实际结算以供应商账单为准。重放、人工修复、隔离测试和失败门槛检查的模型调用均为 0。[锁定费率](../configs/deepseek.yaml) · [首次尝试用量](evidence/stage-06/ai/first-attempt/model.json) · [成功调用用量](evidence/stage-06/ai/model.json)

成功的 AI 链路用 **0.234 秒**建立并验证旧版本与缓存，**9.245 秒**生成并封存候选。新版本增量路径 **0.338 秒**，其中前端 **0.214 秒**。独立全量 **0.093 秒**，额外的全量诊断 **0.102 秒**。整次运行墙钟 **10.209 秒**，各分项存在包含关系。该次增量验证墙钟长于全量验证；微型程序的这次功能验收只支持报告该次实测值。现场人工修复等待 **91.380 秒**，另有独立记录。[AI 链路计时](evidence/stage-06/cases/ai-single-edit.json) · [人工链路计时](evidence/stage-06/cases/live-batch.json)

## 七、下一阶段建议

经明确确认后，可在阶段 7 对冻结候选交替运行两条路径，将旧模型预热、修复、修改后验证和开发诊断分项计时。再引入较复杂的并发程序，检验非零模型与子句复用能否转化为端到端收益。本阶段结束时已关闭验证会话，正式性能对比尚未执行。[阶段状态](../project_state.json) · [服务器停止检查](evidence/stage-06/stop-check.json)

本阶段已停止，等待你确认是否进入阶段 7。
