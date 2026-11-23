# Deagle 并发程序增量建模与增量验证：给代码大模型的完整执行指引

## 使用方法

将本文件交给能够操作服务器、阅读源码、编辑代码和执行命令的代码大模型，并发送：

> 请完整阅读这份指引。现在只执行阶段 0。完成后提交该阶段报告并停止，等我明确确认后再执行下一阶段。阶段内的环境检查、实现和必要调试可以自主完成。不要一次性执行全部阶段。

这是一份**待执行的工程任务书**。其中的上游入口已依据公开源码和官方文档核查，但没有在用户的目标服务器上进行构建、集成或性能测试。文中的项目模块、缓存格式、会话协议和 `incdeagle` 命令都是**要求你新增实现的设计**，不是 Deagle 已有功能。实际执行时以固定提交的源码为准，并记录与本文的差异。

---

## 0. 项目目标与已确定的约束

### 0.1 你要完成什么

从一个空的项目目录开始，构建可运行的工具链：

1. 对并发 C 程序 `P0` 验证原性质 `phi`，确认其确实有错误，取得反例 `cex0`。
2. 在这次验证中保留可复用的模型信息和理论推理结果。
3. 将 `P0 + phi + cex0 + 验证配置` 交给修复模块，产生一个候选程序 `P1`。
4. 对 `P1` 增量更新模型，并复用仍然有效的旧理论约束，验证同一性质 `phi`。
5. 用独立的全量 Deagle 对**同一个 `P1`**从头构建、从头验证。
6. 比较结果一致性、反例信息、实际复用情况、运行时间和内存。

核心开发内容是：

- **第一创新点：增量事件顺序模型构建。** 真正跳过一部分已完成的符号执行或事件约束构建；维护发生变化的模型部分。
- **第二创新点：跨版本有效理论约束复用。** 识别旧理论推理结果在新版本中是否仍有效，重新绑定后供新求解过程使用。
- **协同工具链。** 用同一套版本、事件、约束标识和变化报告连接以上两个模块。

项目以可用、可检查、可复现为目标，不以证明学术首创为前提。

### 0.2 已获得的环境与使用授权

- 服务器：Ubuntu 22.04，root 权限，可访问网络。
- CPU 架构、有效核数、内存、磁盘、cgroup 限制和 Docker 状态由你检查，不将口头硬件配置当作实际资源上限。
- 允许下载工具、安装必要依赖、构建和修改 Deagle，以及实现必要的适配器。
- DeepSeek 使用官方 API；密钥位于项目根目录 `apikey.txt`。
- 用户未设置费用硬上限，要求选用能力较好的模型、避免无效调用。
- 每一阶段结束后必须停止，收到用户明确确认后才进入下一阶段。

阶段内无需为每条安装命令、每次编译、每个局部修复重复请求确认；仍须遵守执行环境本身的访问控制。遇到真实权限阻碍要报告原因，不修改规则规避限制。

### 0.3 第一版范围

第一版以并发 C/pthreads、顺序一致性 SC、指定断言性质为对象，采用明确、可复现的展开配置。选择能被所固定 Deagle 版本正确处理的小型程序。

本轮只研究单次变化：

`P0（已确认有错） → 一个最终修复候选 P1`。

`P1` 可以满足原性质，也可以仍然违反原性质。修复失败的有效候选同样保留，用于检查增量结果是否一致。

**本轮暂不实现或安排实验：**

- `P0 → P1 → P2 → …` 的连续版本修复循环。
- “旧程序正确，修改后错误”的版本对实验。
- 任意内存模型、任意 C 特性的通用支持。
- 完整的全流程消融研究、论文级大规模评测。

修复 agent 内部可以阅读、编辑和做语法检查，但外层只接收一个最终 `P1`；不得将本工具对 `P1` 的验证结果继续反馈为下一轮 `P2`。源码、缓存重绑定等必要的实现级检查不受上述实验暂缓限制。

### 0.4 必须保持的语义边界

固定验证配置 `Gamma`，至少包含：入口、目标性质、harness、输入假设、内存模型、C 类型/位宽、编译与预处理选项、库模型、循环与线程界限、求解后端。

增量路径与全量路径必须使用相同的 `P1、phi、Gamma`。每条路径都要验证新程序的完整目标性质，不能只回放旧反例、只检查修改行或只考虑旧反例中的线程。

旧反例是修复线索；它既不是安全证明，也不能直接转成禁止该执行的约束。旧反例不能在 `P1` 重现，只说明该条执行不再成立。

不要把“两个验证器打印了同一个单词”当作正确性的完整证据。需要结合模型构建检查、缓存有效性契约、确定结果对照以及可取得的反例信息。

### 0.5 结果分类

实现自己的规范化结果类型，并保留 Deagle 的原始输出：

| 结果 | 含义 |
|---|---|
| `VIOLATION` | 找到目标性质的可行违反执行。 |
| `NO_VIOLATION_WITHIN_BOUND` | 所选展开范围内没有目标性质反例。 |
| `SAFE` | 仅在已检查满足所选配置的完整性条件时使用，仍须注明模型假设。 |
| `INCOMPLETE_UNWINDING` | 展开检查未通过，不能据此给出完整安全结论。 |
| `UNKNOWN` | 工具不能确定。 |
| `TIMEOUT` / `OOM` / `ERROR` | 资源或执行失败，不等同于性质真或假。 |
| `INVALID_PATCH` | 候选语法失败、改动受保护内容等，不是验证器的性质结论。 |

目标断言和展开断言分别记录，按性质解析，不能只看进程返回码。目标断言通过但展开断言失败时，不得输出无条件 `SAFE`。Deagle README 对此及竞赛包装脚本的默认展开策略有明确说明。[R1]

---

## 1. 阶段控制与总体路线

### 1.1 阶段表

| 阶段 | 任务 | 阶段结束必须回答的问题 |
|---|---|---|
| 0 | 探测服务器，初始化项目，制定资源和环境方案 | 实际环境是什么？能否开始部署？ |
| 1 | 下载、固定版本、构建并独立跑通工具和 API | Deagle、DAMER、mini 各自是否运行成功？哪些接口可用？ |
| 2 | 准备首批程序、提取反例、试用修复方式、冻结版本对 | AI 修复是否适合？传统工具是否有可接入实现？样例是否适合增量原型？ |
| 3 | 建立全量基线、可观测接口、稳定标识与会话骨架 | 能否清楚观测模型和推理过程？后续缓存契约是否明确？ |
| 4 | 实现第一创新点：增量建模 | 哪些构建工作真的被跳过？DAMER 实际接入了什么？ |
| 5 | 实现第二创新点：有效理论冲突子句复用 | 哪些旧推理结果真的导入新求解器？为何有效？ |
| 6 | 串联完整单次修复工具链 | 是否从 `P0` 到 `P1` 完整跑通？两条验证路径是否使用同一输入？ |
| 7 | 运行有限规模对比，交付复现入口和报告 | 正确性证据如何？是否提速？什么情况下回退或没有收益？ |

### 1.2 每阶段停止协议

每阶段开始先确认上一阶段已有用户明确批准。默认只执行阶段 0。

阶段完成后：

1. 保存代码、版本锁定信息、实际运行命令、日志与结果。
2. 写 `reports/stage-NN.md`，按第 12 节模板反馈。
3. 将状态写为 `READY_FOR_REVIEW`、`PARTIAL` 或 `BLOCKED`。
4. 结束该阶段启动的工作进程，不在后台继续下一阶段。
5. 向用户报告结论，最后明确写：**“本阶段已停止，等待你确认是否进入阶段 N+1。”**

不得自动替用户批准，不得设置计时器自动继续，不得把“接下来可以……”理解为已经获得确认。用户可以明确批准带限制继续；报告中的已完成范围仍须保持真实。

若遇到会改变技术路线的障碍，例如无法安全恢复检查点、DAMER 无法适配、理论原因无法审计，先完成本阶段仍可完成的检查，再提交具体证据和替代路线，停止等待选择。

### 1.3 推荐目录

以下目录由你创建，不要求用户预先准备：

```text
项目根目录/
  apikey.txt                 # 用户提供，禁止纳入版本控制
  README.md
  EXECUTION_GUIDE.md         # 本任务书副本
  project_state.json
  configs/
    project.yaml
    toolchain.lock.json
    deepseek.yaml            # 只存模型、地址、限制；不存密钥
  third_party/
    deagle-baseline/
    deagle-work/
    damer-camc/
    mini-swe-agent/
    yogar-cbmc-inc/          # 选取版本对/研究适配时使用
  incdeagle/                 # 自建 Python 调度、适配和报告代码
  scripts/
  schemas/
  patches/                   # 可复现的上游兼容补丁、功能补丁
  cases/
    CASE_ID/
      task.yaml
      old/
      candidate/
      patch.diff
      evidence/
  tests/                     # 只放与正确性契约有关的必要检查
  runs/                      # 每次运行的独立目录
  reports/
```

主项目和 Deagle 修改分支分别管理版本；不误提交依赖仓库、密钥、整个虚拟环境或大型运行日志。保留修改后的 Deagle 提交和可导出的补丁，确保能在固定的上游提交上重建。

---

## 2. 阶段 0：环境探测与项目初始化

### 2.1 执行内容

1. 确认当前工作目录；若只有 `apikey.txt`，保留它，从这里初始化项目。
2. 检查 `/etc/os-release`、`uname -m`、CPU、内存、磁盘、cgroup 配额、当前工具链、Docker 可用性和网络。
3. 只确认密钥文件存在、非空、可读取，不打印内容，不执行 `cat apikey.txt`，不将内容写入报告。
4. 建立目录、`.gitignore`、初始 `README.md` 和 `project_state.json`。
5. 写 `reports/environment.json`，包含检查时间、实际有效资源和工具版本。
6. 制定安装计划和资源默认配置，不在阶段 0 自动开始大规模下载、构建或付费修复。

资源初始策略：

- 编译并行度从不超过 4 开始，同时考虑有效 CPU 和可用内存；记录实际值。
- 正式验证和计时先单任务运行，不让两个对比任务争抢 CPU。
- 初始单次验证超时建议 300 秒，可按具体样例调整并固定到配置。
- 内存上限按探测到的有效可用内存设置；为系统和控制进程保留余量。
- 检查点有数量和内存预算；不能无上限复制大型符号状态。

### 2.2 本阶段产物与验收

- 环境报告、目录和初始配置存在。
- 没有泄漏密钥，未修改原始密钥内容。
- 能说明依赖将采用系统包、虚拟环境还是容器，以及原因。
- 已列出阶段 1 计划使用的仓库、安装方案和资源参数。

**停止并反馈。** 用户确认后再进入阶段 1。

---

## 3. 阶段 1：下载工具、配置环境并独立跑通

### 3.1 固定上游版本

使用官方/作者仓库，检出实际可取得的明确提交；记录 URL、commit、许可证、构建工具与补丁，不始终跟随 `main` 自动更新。

| 工具 | 仓库 | 本项目角色 |
|---|---|---|
| Deagle | `https://github.com/thufv/Deagle` | 可修改的核心验证器和独立全量基线。 |
| DAMER-CAMC | `https://github.com/shirleylee03/damer-camc` | 独立跑通，评估变化分析和增量构建方法的可复用部分。 |
| mini-SWE-agent | `https://github.com/SWE-agent/mini-swe-agent` | 调用 DeepSeek 生成修复候选。 |
| Yogar-CBMC-Inc | `https://github.com/yinliangze/yogar-cbmc-inc` | 小规模版本对和已有增量思路的补充来源。 |

不要为了工具数量再部署完整 SWE-agent、整个 SWE-bench 或与目标无关的验证器。Yogar 的公开 artifact 是否包含所需源代码要现场检查；二进制、脚本存在不代表可以移植其内部实现。[R2][R3][R4]

Deagle 基线和修改分支必须从同一上游提交开始，使用相同的必要兼容补丁。基线之后保持算法不变。

### 3.2 安装和构建

先检查依赖，再按需安装。Ubuntu 上预期会涉及编译器、make、CMake、Git、flex、bison、Python venv，以及 DAMER 使用的 tcmalloc 等；架构不支持的 multilib 包不能照抄安装。

依据上游源码核实的构建入口如下；这些是待执行命令，尚未在目标服务器验证，路径按实际目录调整：[R1][R2][R5]

```bash
make -C third_party/deagle-baseline/src -j"$INCDEAGLE_BUILD_JOBS"
make -C third_party/deagle-work/src -j"$INCDEAGLE_BUILD_JOBS"
cmake -S third_party/damer-camc -B third_party/damer-camc/build
cmake --build third_party/damer-camc/build -j"$INCDEAGLE_BUILD_JOBS"
python3 -m venv .venv
.venv/bin/python -m pip install -e third_party/mini-swe-agent
```

`INCDEAGLE_BUILD_JOBS` 应由阶段 0 的资源配置产生，不是上游自带变量。

Deagle README 提到 g++、flex、bison、gcc-multilib，产物是 `src/cbmc/deagle_exe`。若较新 bison 导致生成代码的警告被 `-Werror` 升为错误，依据实际日志采用最小兼容修补或项目内旧版本工具；记录补丁并同步用于基线。[R1]

DAMER 的 CMake 目标为 `PDNet2_0`，链接 tcmalloc。优先检查系统包能否满足依赖；不要直接以 root 照抄其旧 README 中修改全局动态链接器配置等安装步骤。实际命令、工作目录和样例以固定版本的 `-help`、源码和存在的文件为准，不拼凑未验证的参数组合。[R2][R5]

mini 使用独立 venv，并保存 Python 版本、mini 提交和实际解析出的依赖版本。当前 v2 使用原生 tool calling，不能混用旧版配置、轨迹格式和结束标记。[R6]

### 3.3 工具 smoke test

分别完成：

- Deagle：一个明确违反断言的微型程序、一个明确通过的微型程序，确认结果解析和线程支持。这里是工具安装检查，不是“旧正确→新错误”的版本实验。
- Deagle 反例：核实 `--trace`、`--json-ui`，必要时检查 `--graphml-witness`；记录实际可取得的信息。
- DAMER：运行其原生小样例和性质，保存实际结果；若其增量模式有可取得的原生版本对，再运行一次该模式。将“能运行原生示例”和“已接入 Deagle”区分开。
- mini：在隔离的临时病例目录内完成一次无害的小文件修改，确认命令执行和最终提交能被控制器识别。

Deagle 的输出可能混有调试文本。先检查真实输出；需要时修正日志出口或建立严格解析器，解析失败应报错，不能默默截取一段看似 JSON 的文本并继续。

### 3.4 DeepSeek 配置

由控制进程读取：

```python
api_key = (project_root / "apikey.txt").read_text(encoding="utf-8").strip()
if not api_key:
    raise RuntimeError("apikey.txt 为空")
```

这段值只传给模型客户端。配置文件、命令行参数、提示词、报告和运行轨迹不保存密钥。

使用官方基址 `https://api.deepseek.com`，执行当天查官方模型说明，并通过 `GET /models` 核实可访问的 ID。本文核查时，官方列有 `deepseek-v4-pro`；优先从当时官方的高能力模型选择，验证适配后固定。不要永久硬编码过期别名，也不要仅因某模型便宜而默认切换。[R7][R8]

通过 LiteLLM 时，区分客户端路由名与服务器接受的模型 ID。按固定 mini/LiteLLM 版本配置，验证实际请求；不能凭印象添加配置字段。

**API 验收必须是一次完整工具调用往返：**

1. 模型发出无害的 bash 工具调用。
2. 在临时目录执行。
3. 将工具结果交回模型，取得下一轮有效响应。
4. 记录模型 ID、接口配置、token、调用次数和估计费用。

DeepSeek 当前 thinking + tool calls 对历史 `reasoning_content` 的回传有要求，适配器应遵循官方协议；不能只用一次“hello”证明修复 agent 已经可用。[R9]

mini v2 默认有费用限制。用户没有设置费用硬上限，因此应显式配置，而不是误用默认值使任务无故截断。允许将费用硬限制关闭，同时保留 token/费用统计，用以下调度限制防止浪费：[R10]

- 初始每个修复任务最多 40 次模型调用、30 分钟；这是可调整的工程限制，不是用户费用上限。
- 暂时性网络/限流错误最多重试 3 次，并退避；401、模型不存在、参数错误先修配置，不能循环付费重试。
- 连续出现相同错误或无代码进展时停止该候选，报告原因。
- 一次样例只产出一个最终补丁，不开多模型、多候选、大规模随机采样。
- 新模型若不在价格表中，单独记录 token 并按核实的价格估算；无法估算就标为未知，不能记成 0 元。

若新模型不在 LiteLLM 成本登记中，优先登记经官方核实的价格；若暂时无法登记，显式配置对应成本错误处理模式，由控制器独立统计 token 和未知费用。固定版本若支持 `cost_tracking: ignore_errors`，可用于这项兼容处理，但不能把返回的占位 0 当作真实免费。模型响应可能已付费成功，不能因费用登记失败反复重新请求同一内容。[R21]

API 客户端留在控制进程中；修复命令优先在容器或等效文件系统隔离中运行，只挂载候选目录和必要只读工具，不挂载项目根目录或 `apikey.txt`。若使用独立本地用户，须同时落实文件权限和可访问目录限制；仅换成非 root 用户不等于完成隔离。密钥文件仅由控制器用户读取，传给修复 shell 的环境中清除密钥。默认本地环境可能继承父进程环境，因此仅把密钥放进环境变量并不足以隔离。[R11]

### 3.5 阶段结论

提交工具表：固定版本、是否构建成功、运行命令、实际输出、可用接口、失败原因。

必须明确回答：

1. Deagle 是否足以进入后续开发？实际使用哪个求解后端？
2. DAMER 原生模式是否跑通？它输出和更新的模型是什么？
3. mini + DeepSeek 是否完成工具调用往返和文件修改？
4. 有哪些兼容问题需要后续处理？

任一核心工具未跑通都要如实报告。Deagle 未跑通时不得进入核心算法实现；DAMER 或 mini 的阻塞可以提出替代路径，由用户在阶段结束时决定。

**停止并反馈。**

---

## 4. 阶段 2：程序、反例、修复方式与版本对

### 4.1 建立首批病例

从 3–5 个小程序开始。优先选择 Deagle 可处理的并发程序；再按需选用 SV-Benchmarks，或 Yogar 的 origin/regression 版本对。[R3][R12]

每个 `P0` 必须由独立基线确认违反目标性质，且能取得反例。数据集的 `expected_verdict` 可用于筛选，但不能替代这次实际验证。

Yogar 的 regression 文件是“修改后版本”，不能自动当作修复；DAMER 的程序和性质也必须重新适配并验证。不要先下载整个大型数据集再随机批量运行。

为每个病例保存 `task.yaml`，至少包括：

```yaml
schema_version: 1
case_id: example_case
source_origin: "实际 URL / 自建诊断用例说明"
old_source: old/program.c
candidate_source: candidate/program.c
entry: main
property:
  description: "原断言的实际含义"
  protected_files: ["实际 harness 或性质文件"]
  original_assertion_fingerprint: "实际计算值"
semantics:
  memory_model: sc
  backend: closure
  target_bits: 64
  unwind: "执行时确定的具体配置"
  check_unwinding: true
  compiler_flags: []
limits:
  timeout_seconds: 300
  memory_bytes: "由服务器有效资源计算"
repair:
  method: manual
  allowed_files: ["program.c"]
```

这些是本项目的 manifest 字段，不是 Deagle 原生 CLI。位宽等值必须根据实际任务核实，不能因模板填写了 64 就悄悄改变原任务。

### 4.2 实现反例适配器

建议新增 `incdeagle/adapters/deagle.py` 和 `incdeagle/counterexample.py`。

原始输出完整保存；规范化反例至少包含：

- 失败的目标性质和源位置。
- 线程标识、可获得的执行步骤与变量赋值。
- 验证配置和 `P0` 内容哈希。
- 原始 trace / witness 路径。
- 字段是否完整、哪些信息无法取得。

Deagle 的 trace 相关入口可从 `cbmc_parse_options.cpp`、`bmc_util.cpp`、`json_goto_trace.cpp` 核实。[R13]

不要假定公开 trace 已经完整给出 RF、PO 和所有内存顺序信息；后续如果需要，另从本项目事件模型导出。不能靠普通本地执行偶然未复现就否定形式反例。

### 4.3 先做人工/已知补丁，再试 AI

先为小程序准备至少一个明确说明意图的人工或已知补丁，用来排除修复器本身的影响。人工补丁属于受控输入，不称作传统自动修复算法。

然后用 1–2 个病例接入 mini + DeepSeek，生成真实候选。给修复器的信息包括：

```text
原程序快照；原性质；受保护的 harness 和输入假设；
SC 与展开等验证配置；规范化反例和原始反例；
允许修改的源文件；最终候选与 patch 的输出位置。
```

给修复器的任务要求：

> 根据反例修复原程序，使其满足给定性质并保留原功能。允许阅读、编辑和进行语法检查。不要修改性质、harness、验证配置，不要通过删除断言、增加排除错误输入的 assume、删除线程工作或绕过目标代码让验证通过。最终提交一份候选和修改说明。此任务不进行跨版本连续修复。

控制器须做提交后的完整性检查：受保护文件哈希、断言指纹、diff 白名单、语法状态和候选内容哈希。明显改变功能或绕过性质的补丁标记为无效或需要人工确认；满足断言本身不等于所有功能都已正确。

程序中的验证器内建函数和并发语义应按所选工具的模型处理。语法检查与真实运行 harness 要分清，不能把普通 GCC 对抽象验证程序的某次执行当作 SC 模型的正确性依据。

候选能否进入验证，以固定 Deagle 前端在同一 `Gamma` 下能否解析、类型检查并生成所需 IR 为依据。GCC/Clang 是辅助检查，应配置必要的验证器内建声明；不能因宿主编译器不认识 `__VERIFIER_*` 或 `__CPROVER_*` 就判补丁无效。该检查只需前端，不提前全量求解；正式计时时如复用其产物，必须明确计入产物生成成本。

### 4.4 传统修复的评估方式

查找一个与所选错误类型匹配、可以取得实现的传统并发修复工具。记录语言、错误类型、输入 trace 格式、代码/二进制可取得性、构建状态和适配成本。

CFix 可作为方法背景：它研究根据失败交错形成同步修复；不能据此直接声称有可接收 Deagle trace 的即插即用接口。[R14]

如果有可运行实现，就在同一小病例上实际尝试；如果没有，不为接入传统方法额外开发一个完整修复算法。可以得出“首版采用 mini，传统方法暂未找到低成本可接入实现”的结论。

此阶段只评估可用性，不依据一两个样例宣布 AI 或传统方法普遍更好。

### 4.5 冻结病例

对每个有效候选冻结：`P0、P1、patch、phi、Gamma、cex0` 及内容哈希。`P1` 无需已经修复成功；全量结果用于分类。

优先覆盖：

- 数据/常量变化，事件结构可能保持。
- 条件修改，guard 或可达事件可能变化。
- 一个实际并发修复相关的修改，例如同步范围调整；初版可不支持增量，但须保留适配观察。

暂不要求三类都能增量成功，也不强制所有补丁来自 AI。报告真实来源。

注意：本阶段的原版 Deagle 只能提供结果与反例，**不会自动产生未来要用的检查点和理论缓存**。阶段 3–5 实现完成后，要用增强版重新验证 `P0`，生成真实缓存；该成本属于后续统计。

### 4.6 阶段结论

回答：AI 是否能产出可编译的有效候选？传统工具是否值得接入？反例是否足够指导修复？已选补丁类型与首版增量支持范围是否匹配？

**停止并反馈。**

---

## 5. 阶段 3：全量基线、稳定标识和可观测接口

### 5.1 保留可信的全量路径

保留兼容修补后的 Deagle 基线，不应用新的模型缓存、增量构建或 lemma 导入逻辑。

为了得到时间分项，可加入只计时、不改变算法的观测补丁，并记录其影响。开发版本也提供禁用所有复用的全量模式，用于定位集成问题；正式主对比仍使用独立基线。

版本锁定至少记录：

```text
上游提交；兼容补丁哈希；功能补丁/分支提交；
编译器、构建选项、依赖版本；二进制哈希；
内存模型、后端、目标性质、展开配置和资源参数。
```

### 5.2 已核实的源码导航

读取实际提交并绘制简要调用关系，重点是以下位置；不要仅按文件名打补丁：

| 位置 | 要检查的内容 |
|---|---|
| `src/goto-symex/goto_symex.h`、`symex_main.cpp` | 符号执行入口、恢复执行接口和调用关系。 |
| `src/goto-symex/goto_symex_state.h`、`path_storage.h` | 状态、命名计数器、路径与分析缓存。 |
| `src/goto-symex/symex_target_equation.h/.cpp` | SSA、共享事件、OC 边、guard、性质。 |
| `src/goto-symex/partial_order_concurrency.*` | 地址分组、事件列表及顺序约束基础。 |
| `src/goto-symex/memory_model_sc.cpp`、`memory_model.cpp` | PO/APO、RF 选择、读值和覆盖约束。 |
| `src/goto-checker/bmc_util.cpp` | 模型后处理、公式转换、事件图交给求解器。 |
| `src/goto-checker/solver_factory.cpp` | 选择实际求解后端。 |
| `src/solvers/sat/satcheck_minisat2.*` | SAT adapter 和添加子句接口。 |
| `minisat-2.2.1/minisat/core/ClosureSolver.*`、`Closure.*` | 理论图、原始理论冲突及 reason。 |

上述接口存在并不代表已经支持跨程序版本复用。[R15–R19]

### 5.3 新增数据契约

建议实现以下结构，C++ 侧使用类型化对象，Python/文件侧使用带 schema 的 JSON：

**VersionManifest**

保存源码和依赖头文件哈希、预处理配置、目标架构与类型布局、harness/性质、展开配置、工具提交、后端和 schema。

区分“整个版本的身份”和“某片段的可复用条件”。如果要求整个源文件哈希相同才复用，就不能处理真实修改；片段复用应检查其依赖。

**SourceNodeMap / GotoInstructionMap**

保存旧新来源节点和 GOTO 指令的映射。函数、语句结构、角色和上下文共同确定匹配，不以行号定义跨版本身份。行号可用于定位；如它参与所选版本的建模规则，须另外保留为语义依赖。重复语句无法唯一匹配时拒绝映射，不能强行按最近行号配对。

**EventKey**

```text
来源节点持久身份
线程创建上下文
函数调用上下文
循环展开/出现次数上下文
该源码节点降低后产生的读、写等操作角色
```

**EventFingerprint**

保存事件种类、对象/类型、guard、值表达式、原子区和相关顺序元数据。

事件身份和语义指纹必须分开。例如 `x=1` 改为 `x=2` 可以仍对应同一来源事件，但其数值语义已改变，相关约束必须更新。

**ConstraintFragment**

保存约束类型、类型化表达式、语义符号、所属线程/地址桶、依赖对象、指纹。不能把旧 C++ 指针、SSA 整数后缀或 SAT 变量号当跨版本身份。

**ModelDelta**

```text
events_added / events_removed / events_changed / events_retained
affected_threads / affected_address_buckets
constraints_added / constraints_removed / constraints_retained
source_mapping_summary / analysis_changes
checkpoint_used / invalidation_reasons / fallback_reason
```

### 5.4 观测和基线检查

提供诊断导出：原始 SSA、共享事件、guard、PO/APO/RF、数值与 RF 覆盖约束、目标性质、展开性质。将“内存模型处理之前的原始 SSA”和“处理之后的完整模型”分开。

分别计时：解析/GOTO、符号执行、事件约束构建、CNF 转换、求解、输出。记录实际执行的符号指令数量、事件数、约束数。

增加一个单病例会话骨架，能保留建模对象并按命令响应。建议新增的语义操作为：

```text
LOAD_OLD → BUILD_OLD → VERIFY_OLD → WAIT_FOR_CANDIDATE
UPDATE_CANDIDATE → VERIFY_CANDIDATE → EXPORT_RESULT → SHUTDOWN
```

这些是本项目协议，不是现有 Deagle 参数。协议输出与调试日志分流；不要求首版把整个 C++ 符号状态序列化到磁盘。

每个病例完成后关闭会话。阶段结束不保留后台 worker；下一阶段需要缓存时在新会话中重建 `P0`，如实记录预热成本。

### 5.5 阶段验收

- 增量尚未启用时，开发分支和独立基线在已选病例上的确定结果一致。
- 模型导出能定位到真实代码，原始 SSA 和后处理模型没有混淆。
- 同一输入重复构建可得到可对照的规范化结构。
- 能说明稳定标识、配置指纹和会话生命周期。

**停止并反馈。**

---

## 6. 阶段 4：第一创新点——增量事件顺序模型构建

### 6.1 首版采用的实现路线

先实现：

> 复用经过验证的符号执行检查点和已有 SSA 前缀，重新执行受影响后缀，再按线程和地址分组更新事件约束。

允许第一版重新解析 `P1`、重新生成 GOTO；必须明确这时增量化的是符号执行与事件模型阶段，尚未实现增量解析/增量编译。**如果仍完整执行新程序的全部符号执行，再比较两个完整模型，只能算变化检测原型，不能宣布完成源程序到模型的增量构建。**

不要求第一版把任意函数 SSA 当成可独立拼接的摘要。并发、别名、调用和 SSA 命名可能跨越函数，不能只凭函数文本没改就直接拼接。

### 6.2 DAMER 接入的具体工作

阅读 `AST_compare.h/.cpp`、`changeConstruct.h/.cpp` 和依赖类型，实测能否提取：

- 语句/AST 对应关系。
- 修改、增加、删除、移动分类。
- 变化影响范围的组织方法。

DAMER 的 `changeConstruct` 接受 PDNet/CPN 和其自身 AST 变化对象；它更新的是 places/arcs 等 PDNet 数据，不能直接交给 Deagle 的 equation。[R20]

实现一个本项目的 `ChangeProvider` 接口，统一输出 `SourceChangeSet`。在以下路线中根据实际适配工作选择：

1. 封装可独立抽出的 DAMER 匹配代码，并保留来源和许可证。
2. 使用 Deagle 规范化 GOTO 比较，必要时辅以已有 AST diff 工具。
3. 使用简单而保守的函数/语句匹配实现首版。

优先使用能保证匹配正确的最小方案。若加入 GumTree，先验证 C parser/generator 是否可用；AST diff 只提供变化位置，不能替代语义依赖分析。不为接入 DAMER 先造一个 PDNet→Deagle 翻译器。

阶段报告必须写“实际复用了哪些代码/接口”；仅阅读论文不能称作工具接入。

### 6.3 实现完整检查点，而不是只复制一个 state

Deagle 有 `resume_symex_from_saved_state(...)` 和 `path_storaget::patht`，但它们原本用于同程序的暂停恢复。[R15][R16]

建议新增模块：

- `IncrementalCheckpointManager`：采集、选择、验证、恢复检查点。
- `GotoReferenceRebinder`：将保留状态内的指令引用重绑定到新程序。
- `AnalysisDependencyTracker`：记录前缀依赖的静态分析与配置。
- `IncrementalSymexDriver`：恢复前缀并执行新后缀。

检查点至少审计并保存：

- memory-model 后处理之前的 SSA 前缀。
- 所有线程状态、PC、调用栈、分支/合并状态、循环与递归上下文。
- SSA L1/L2、nondet 等命名状态和动态对象计数。
- 符号表及新增符号、guard manager 的正确生命周期。
- `path_storage` 的路径及 dirty/safe-pointer/loop 等分析状态。
- `goto_symext` 中影响恢复的执行器级状态。

建立一张“状态字段—来源对象—是否复制—是否重绑定—如何检查”的审计表。没有审计完的状态不能靠猜测跳过。

检查点独立且不可变。旧程序的后处理和求解不得通过浅复制、共享可变容器或迭代器修改它的 SSA、`ignore/converted` 标志和索引。审计旧对象生命周期：保留的引用在完成重绑定前必须有效；恢复时不仅重绑定当前 PC，还要重绑定 SSA 来源和其他结构内的 GOTO 引用。

特别检查恢复函数的符号表语义：所核查的 `symex_with_state()` 会将传入的 `new_symbol_table` 赋给状态中的符号表。恢复调用必须从检查点正确恢复符号执行新增符号，并与新版本所需符号协调，不能传空表或拿新 GOTO 的全局表替代。恢复后检查前缀表达式引用的全部符号可解析且类型一致。[R15]

检查点优先放在函数/线程体进入点；首版在首次进入受影响函数之前恢复，减少跨修改控制流的旧合并状态。初期只保留有限个检查点，例如最多 8 个且受总内存预算约束；不足时回退，不无限复制。

### 6.4 判断检查点是否可以复用

建议按以下顺序实现：

1. 解析 `P1`，生成新 GOTO 和来源映射。
2. 比较源码、类型、符号、初始化、调用/线程结构、配置和分析依赖。
3. 找到受影响函数集合及最早受影响的构建位置。
4. 从候选检查点中选取该位置之前、依赖全部有效的一点。
5. 检查所有保留的 GOTO 引用能够唯一映射；建立新对象绑定。
6. 恢复前缀及所有必要状态，重新执行后缀。

**仅检查“前面执行过的源码没变”不够。** 后面的源码变化也可能改变全程序 dirty、escape、safe-pointer 等分析，从而影响此前的建模结果。分析摘要改变时必须扩大失效范围或回退。

初版先支持保守的函数体内数据修改：不改变声明、类型、线程拓扑、取地址行为和相关静态分析的常量/RHS 修改。先跑通后，再尝试条件、局部事件插删或同步范围变化中的至少一种实际并发修复形式。

是否满足支持条件，要检查实际新旧 GOTO 和相关分析，不能只靠源码 diff 白名单。文本上仅改常量，也可能改变前端折叠、CFG 或事件生成条件；依实际影响扩大失效范围，超出能力时回退。

新增锁或修改控制流是否可支持，要通过上述依赖与引用检查决定，不预先宣称都支持。

### 6.5 明确的回退条件

遇到下列情况，无法证明不影响缓存时全量重建并记录原因：

- 宏、头文件、类型布局、全局声明/初始化或验证配置变化。
- 线程创建上下文无法稳定映射。
- 取地址、指针/别名、dirty 等分析变化影响缓存前缀。
- 保留状态中的 PC、调用栈、分支合并点或循环分析无法重绑定。
- 事件来源重复、映射有歧义。
- 检查点未覆盖所需执行器状态。
- 修改类型超出首版支持范围。

回退是正确行为，但如果每个真实修改都回退，就没有完成有用的增量建模。

### 6.6 实现事件与约束分组缓存

建议新增 `EventRegistry`、`ConstraintFragmentStore`、`AffectedRegionCalculator`、`IncrementalSCModelBuilder`。

从新旧 SSA 和来源映射计算 `ModelDelta`，将约束按线程与地址桶分组。缓存存语义表达式和依赖，不能依赖旧容器迭代器。

| 变化 | 必须更新的内容 |
|---|---|
| 写入值/表达式变化 | 数据等式、受影响的值传播，以及必要的 RF 值约束。 |
| guard 变化 | 事件 guard 和依赖它的约束；重新检查事件是否存在和常量折叠。 |
| 事件插入/删除 | 相关线程的 PO/APO、有关地址的读写集合和 RF 候选。 |
| 某地址新增/删除写 | 该地址各读的 RF 候选、读值一致性及候选覆盖析取。 |
| 线程内顺序变化 | PO/APO、受其影响的 RF 候选过滤和关系。 |
| 原子区/同步变化 | 原子分组与同步关系，必要时扩大影响范围或回退。 |
| 地址/别名变化 | 新旧相关地址桶；无法界定影响时回退。 |

特别检查每个读的“至少选择一个候选写”约束。候选集改变时，要替换整个聚合约束，不能仅增加/删除一条 RF 边。未修改线程中的读也可能受到影响。[R17]

首版可保守地重建整个受影响地址桶、整个受影响线程顺序片段，不急于追求最小逐边变化。

建议给一个读保存类似如下的结构，而非散落的无归属子句：

```text
ReadConstraintBundle
  read_event
  candidate_write_events
  rf_choice_atoms
  value_constraints
  guard_dependencies
  coverage_constraint
  dependency_fingerprint
```

更新时完整替换失效 bundle。继承片段中的符号必须映射到新版本符号空间。

### 6.7 组装与状态清理

为新版本创建新的最终 equation/事件图容器，用有效缓存片段和新片段组装。容器复制、表达式重绑定的开销计入增量维护。

不要把添加过 init-write、RF 等内容的完整 equation 再当作原始 SSA 送入原建模器，否则可能重复生成约束。不要假定现有 `clear()` 会清除全部 OC 字段；按实际源码逐字段审计或构造新对象。[R18]

来源信息不能一律作为显示字段忽略。所核查 SC 路径会调用 `build_same_line_atomic_set()`，行/语句关系可能参与原子关系生成；这类字段必须重绑定、重算或纳入依赖检查。只有证明未参与当前建模规则的元数据，才可从规范化比较中去除。[R17]

允许首版重新进行最终 CNF 编码。必须在报告中明确：复用了 SSA/事件/逻辑表达式，不代表已经复用了所有 bit-blasting 或 CNF 转换。

### 6.8 本阶段的正确性检查

目标契约：在同一 `P1、phi、Gamma` 下，增量模型与全量模型表示相同的违反行为。

开发检查优先利用相同生成器达到辅助符号重命名后的结构一致：

1. 独立生成新程序的全量诊断模型。
2. 使用可靠的来源映射对齐事件和辅助符号。
3. 比较类型、位宽、guard、值表达式、PO/APO/RF、覆盖约束、目标性质和展开性质。
4. 仅忽略确认不影响语义的显示元数据，不能为了比较通过而删掉 guard 或性质。
5. 再比较同配置求解结果。

无法建立辅助变量的一一对应时，不能简单把两个公式 XOR 后求 SAT 就宣布完成模型等价检查。先定位编码差异；确有必要再设计带明确变量投影的语义检查。

诊断的全量构建在独立检查路径运行；不能偷偷用全量新模型计算完一切，再仅对差分操作计时。

### 6.9 验收门槛与阶段结论

最低功能门槛：

- 至少一个 `P0` 有真实错误、`P1` 有真实语义修改的病例走增量路径。
- `reused_prefix_symex_steps > 0`，且日志能证明这些指令在新版本未重新执行。
- 实际复用事件/约束片段，而非仅生成一个 diff 文件。
- 增量与全量模型的规范化检查及结果对照通过。
- 至少一个不支持的修改正确触发回退。
- 注释/空白变化只能作辅助检查，不能作为核心验收。

分别报告解析、GOTO、符号执行、事件构建、CNF 编码哪些仍为全量。尝试实际同步/条件修复后如仍只能支持数值修改，报告限制及对修复流程的影响，由用户决定是否以该范围进入下一阶段。

**停止并反馈。**

---

## 7. 阶段 5：第二创新点——跨版本有效理论约束复用

### 7.1 首版设计决定

首版采用：

> 旧版本导出原始 Ordering Consistency Theory 冲突子句；新版本建立全新的 ClosureSolver，经有效性检查和语义重绑定后导入。

这是真实的推理结果复用，不要求持久化旧求解器。先不实现任意 CDCL 学习子句复用、旧赋值栈恢复、整个旧理论图原地修改或通用激活变量框架。

锁定 SC 和实际 closure 后端。根据固定版本的 CLI/工厂接口显式选择并记录；不要猜一个未存在的后端参数。

### 7.2 导出位置和范围

在 `ClosureSolver::propagate()` 中，理论图发现冲突后使用 `graph.conflict_lv` 形成冲突子句；在进入一般 CDCL 分析之前增加 observer/recorder。[R19]

若冲突前提为 `a、b、c`，记录的子句应是 `¬a ∨ ¬b ∨ ¬c`。按实际源码的 literal 极性处理，不进行二次取反。

首版只接受来源清晰的 `oc-cycle` 原始理论冲突；暂不导出 `analyze()` 之后融合数据、性质等信息的通用学习子句。理论传播 reason 的极性约定不同，也暂缓加入。

### 7.3 新增五个模块

1. `TheoryAtomRegistry`：将 RF、guard 等语义 atom 与本次求解器的带符号 literal 对应。
2. `TheoryContextFingerprint`：规范化影响理论推理的完整结构并计算指纹。
3. `TheoryLemmaRecorder`：记录、过滤、去重原始理论冲突子句。
4. `TheoryLemmaValidator`：检查版本、结构、事件映射、alias 和常量模式。
5. `TheoryLemmaImporter`：绑定到新 literal，通过正规加子句接口导入。

在 `bmc_util.cpp` 转换 `oc_edges`、guard 并向 solver 交图时建立 atom registry；通过 SAT adapter 的正式接口添加子句，避免直接操作旧 clause arena。[R13][R19]

### 7.4 为什么首版采用完整理论结构检查

只检查“子句提到的事件还存在”不够。理论推理可能依赖未显式出现在 reason 中的静态 PO、APO、原子分组等。

首版用完整 `TheoryContext` 的规范化同一性作为保守条件：

```text
schema / backend / memory_model / 影响语义的选项
事件节点、读写类别、地址/别名分区
线程及创建结构
PO、APO、原子分组和其他实际参与推理的静态关系
RF 候选 atom
事件发生 guard atom
atom 到 literal 的带极性等价/别名组
atom 的常真、常假及特殊绑定状态
其余实际影响理论图初始化/推理的元数据
```

不能只对边数量或事件名称排序后取 hash。保留可读的规范化结构，便于解释失效原因；重要比较可同时核对结构内容，不能靠一个短哈希替代语义检查。

`TheoryContext` 来自送入理论求解器的声明式结构和 atom 绑定，并在理论图被初始化传播/搜索动态修改之前冻结。不能从求解后被裁剪、闭包化的图或旧 trail 反推；atom 的声明常量状态也不能由当前赋值代替。身份还包含固定的 Deagle 提交、本项目影响编码/推理的代码版本、相关编译开关和记录格式版本；实现改变后旧理论缓存默认失效。

一般数据 RHS 不必机械包含进理论结构，否则 `x=1` 改为 `x=2` 会使所有复用失效。但只有确认该变化不改变理论 atom 的解释、静态关系、地址、alias、常量折叠等时，才允许排除这些数据内容。

无法判断某元数据是语义信息还是启发式信息时，保守纳入指纹或拒绝复用。

### 7.5 正确性契约

设旧、新理论结构为 `H0、H1`，语义重命名为 `rho`。只有以下条件成立才导入：

```text
旧导出子句 L0 是 H0 的逻辑后果；
H1 与 rho(H0) 的理论语义相同；
新子句 L1 = rho(L0)，所有 atom 均正确绑定。
```

这要求 `L0` 来自纯理论推理；不能仅因它是旧完整公式的后果就复用。新的数值约束可以变化，而纯理论子句在相同理论结构下仍有效。

结构改变时首版丢弃整批理论缓存，继续验证新模型。这不妨碍第一创新点命中；两种增量不必每次同时命中。

### 7.6 缓存格式

建议新增格式：

```json
{
  "schema_version": 1,
  "kind": "oc-cycle",
  "origin_version": "实际旧版本标识",
  "theory_context_hash": "实际规范化结构指纹",
  "dependency_mode": "whole_theory_context",
  "clause": [
    {"atom": {"kind": "rf", "write": "稳定事件ID", "read": "稳定事件ID"}, "negative": true},
    {"atom": {"kind": "guard", "event": "稳定事件ID"}, "negative": true}
  ],
  "export_site": "ClosureSolver::propagate"
}
```

实际实现使用类型化 atom，不依赖有歧义的拼接字符串。旧数值变量号可以作为调试信息，但绝不用于跨版本恢复。

### 7.7 必须正确处理的情况

**literal 别名与反向别名。** 多个语义 atom 可能映射同一个 literal，甚至不同极性；保存带极性的等价组，检查新版本仍满足对应关系。不能简单建立 `旧 var → 一个事件` 的字典。

**动态生成的 CO 变量。** 当前 closure 路径可能在搜索中创建初始 `oc_edges` 中不存在的变量。首版遇到无法稳定语义映射的 literal，整条子句拒绝；不搬运旧数字编号。[R19]

**常量与 level-0 事实。** 旧数据约束导致的顶层赋值不自动成为理论公理。检查 reason 是否遗漏了这类前提；无法恢复时拒绝。不要按旧赋值把原子句化简成 unit 或空子句再导入。

先审核原始理论子句及完整绑定信息，再依据新版本的真实常量绑定化简。因旧常量而省略的前提须由冻结的 `TheoryContext` 明确覆盖，并在新版本核实。首版无法给出来源证据的 unit/空子句直接拒收；不能依据旧求解结果补造它们。

**预处理、替换和消元。** 若无法追踪映射，禁用相关优化或冻结需要的变量，并在两条相关路径保持一致配置；否则拒收该缓存。不能假定所有变量编号在求解前后保持不变。

**理论图重置。** 新版本创建新的 solver 和新的图。`save_raw_graph()` 是进程内交图接口，不是现成跨版本持久化 API。单独使用 activation literal 不能自动清理旧图的静态边和闭包状态。[R19]

### 7.8 导入流程

```text
新模型已组装
→ 新建 solver
→ 转换新数据/性质约束和图 atom
→ 建立新语义 atom registry
→ 构建/核查 TheoryContext
→ 审核旧 lemma
→ 重绑定并加入通过审核的子句
→ 执行正常的新版本验证
```

审计图初始化与加子句的具体顺序；如果初始化会传播，应保证 registry 和规则在首次使用前完整建立。

首版不在每次更新时用全量求解逐条证明 lemma，这会把重复验证开销藏进缓存。开发验收可对少量导出子句进行独立检查；正常路径依靠已审计的来源、结构契约和映射检查。

### 7.9 必要检查与验收

检查以下具体风险，不扩展为暂缓的版本演化实验：

- 新旧 CNF 编号不同，语义重绑定仍然正确。
- 理论结构、后端、schema 不符时拒绝。
- guard 常量/带极性 alias 改变时拒绝或作有依据的转换。
- 无映射 CO、无法审计的 reason 被拒绝。
- 导入和拒绝计数与实际加入子句一致。

在真实有错的 `P0` 中寻找会产生理论冲突的病例，检查其补丁后的实际导入。记录：

`exported、supported、deduplicated、accepted、rejected、imported`，以及指纹、审核、绑定和导入耗时。

不能承诺每个有错程序都产生可复用知识。有些程序很快找到反例，`exported=0` 是正常现象。不得把真实反例变成禁止约束，不得在找到反例后无声地额外搜索来制造缓存收益。

阶段理想验收为：至少一个真实 buggy 病例经过一次修改后导入了真实旧 lemma，结果与全量路径一致。若仅在独立求解器诊断样例中验证了导出/导入机制，而真实病例暂无命中，报告 `PARTIAL` 和具体数据，由用户决定是否继续，不冒称已证明真实场景收益。

**停止并反馈。**

---

## 8. 阶段 6：串联完整单次修复工具链

### 8.1 协调逻辑

实现 Python 控制器，协调 C++ session、修复 adapter 和独立全量基线。建议新增接口：

```text
verify_old(case) -> old_result + counterexample + live_session_handle
produce_candidate(repair_input) -> frozen_candidate + patch + repair_metadata
update_model(session, candidate) -> model_delta + new_model_handle
verify_updated(session, new_model) -> incremental_result
verify_fresh(candidate, same_config) -> baseline_result
compare_results(...) -> comparison_report
```

上述 handle 只在会话中有效，不把 C++ 地址写入磁盘后假装能重新加载。

### 8.2 完整运行顺序

1. 校验病例和配置，创建独立运行目录。
2. 启动增强版 session，构建并验证 `P0`，真实采集检查点、模型缓存和理论子句。
3. 如果 `P0` 不是目标性质 `VIOLATION`，该病例不进入本轮修复对比；记录原因。
4. 提供反例给选定修复 adapter；session 保持建模缓存，但旧 solver 可以释放。
5. 接收一份 `P1`，检查受保护内容、语法和 diff，冻结内容哈希。
6. 增量更新模型；审核旧理论子句；新建 solver 验证 `P1`。
7. 保存结果和缓存统计，关闭增量 session。
8. 独立启动全量基线验证相同 `P1`，避免与增量任务同时争抢资源。
9. 对照性质级结果、反例和统计，输出报告。

为了正式计时可重放已冻结的版本对，避免每次重新付费调用 AI。在线完整链路至少实际演示一次；其余重复测量使用同一 `P1`，不重新生成随机补丁。

修复器只修改独立候选目录；修复前后重新核对 `P0`、原性质和配置的哈希，避免旧快照被原地编辑。前端预检查若已产生可复用 GOTO/IR，正式比较须计入其生成成本，或两路均从冻结源码重新执行对应前端步骤；不能仅让增量路径免费使用预生成的新模型。

如果预热 `P0` 需要重新执行，要明确计入初始成本；不能声称缓存来自之前未增强的 Deagle。

### 8.3 建议新增的用户入口

以下 CLI 由你实现后才能使用：

```bash
python -m incdeagle.cli doctor
python -m incdeagle.cli inspect-case --case cases/CASE_ID/task.yaml
python -m incdeagle.cli run-case --case cases/CASE_ID/task.yaml --repair manual
python -m incdeagle.cli run-case --case cases/CASE_ID/task.yaml --repair mini
python -m incdeagle.cli replay-pair --case cases/CASE_ID/task.yaml
python -m incdeagle.cli summarize --runs runs/
```

`run-case` 只处理一个 `P0→P1`；没有自动循环生成 `P2`。`replay-pair` 使用冻结版本，重新准备 `P0` 缓存再验证 `P1`，不调用修复 API。

### 8.4 失败处理

- API/修复失败：保存原因和有效工作，不伪造候选。
- 缓存不适用：记录回退原因，允许从头建模/不导入 lemma。
- 增量与全量确定结果冲突：标记严重正确性问题，停止扩大运行规模，保留最小复现并修复。
- UNKNOWN/TIMEOUT/OOM 与确定结果不同：记录覆盖/资源差异，不直接归类为逻辑矛盾。
- 反例不同：允许；各自必须指向新程序的同一目标性质，而非要求轨迹逐字相同。

### 8.5 阶段验收

- 至少一个完整链路从 `P0` 反例经修复生成 `P1`，进入增量和全量两路。
- 增量构建和 lemma 审核使用同一套版本/事件身份。
- 保留真实复用证据，而不只是流程连通。
- 候选固定、原性质固定、配置固定、状态分类清楚。
- 一条命令能重放版本对，日志中能解释每个回退。

完整协同效果的理想验收是在同一真实 `P0→P1` 病例上，观察到非零模型复用和非零旧理论子句导入，并与全量路径结果一致。若两个模块只在不同病例分别命中，报告各自已完成的功能，并将“同一病例协同命中”列为未完成，交用户决定是否接受；不无限寻找样例或制造命中数据。

**停止并反馈。**

---

## 9. 阶段 7：正确性与性能对比

### 9.1 实验单位

一个实验单位是：`(P0, cex0, P1, phi, Gamma)`。

正式比较两条路径：

- **Full：** 对冻结的 `P1` 从头解析、构建、编码和验证。
- **Incremental：** 已有 `P0` 的有效状态，分析变化、更新模型、检查并导入有效 lemma，再验证同一 `P1`。

先在现有 3–5 对上完成检查。确有需要再扩展到约 10 对，选择能说明支持范围的病例即可，不为了样本量自动启动大规模下载、修复或运行。

所有有效修复候选都应保留，包括 `P1` 仍有错误的情况。按修复来源和补丁类型分组，如实报告支持/回退数量，不筛掉不利于增量的结果。

### 9.2 正确性统计

分别报告：

1. **模型检查通过情况：** 增量模型与全量诊断模型的结构/语义检查。
2. **确定结果一致性：** 双方有可比较确定结果时，目标性质结论是否一致。
3. **候选修复通过比例：** 有效候选中，满足原性质的数量；有界通过单独标注。
4. **未知和资源失败比例：** UNKNOWN/TIMEOUT/OOM/ERROR 分别统计。
5. **覆盖范围：** 增量路径命中、模型回退、lemma 全失效分别多少。

不要把这些合成一个含义不明的“正确率”。分母必须明确；无结果、无效补丁不静默删除。

对 `VIOLATION`，核实目标性质和新版本位置，检查可取得的执行信息；如实现受约束 trace replay，应检查该 trace 能在新程序语义下成立。独立全量验证也报告 `VIOLATION` 只能支持该程序有错，不自动证明某条特定增量 trace 合法。

本阶段给出的是实现正确性的实验与契约证据，不把有限样例上的一致率表述为算法健全性的完整证明。

### 9.3 时间统计

记录完整的修改后耗时：

```text
T_full = 读取/解析与GOTO + 全量symex + 全量事件约束
       + CNF转换 + 求解 + 必要结果输出

T_inc  = 变化识别 + 缓存/依赖检查 + 仍需全量的前端步骤
       + 检查点恢复/重绑定 + 后缀symex + 事件约束更新/组装
       + CNF转换 + lemma审核/绑定/导入 + 求解 + 必要结果输出
```

缓存读写、哈希、复制、映射、失效和回退都计入实际所在路径。不要只比较 solver 时间，也不要把增量维护开销排除。

主值使用控制器单一外层墙钟测量，分项用于解释瓶颈。`T_full` 从启动全量进程前到必要结果已解析为止；`T_inc` 从向已准备好的 `P0` session 提交冻结 `P1` 前到必要结果已解析为止，包含 IPC、输入读取、维护、导入和结果处理。旧 session 的建立和缓存采集计入初始成本与完整周期。嵌套计时标明包含关系，不把重叠分项相加当作总时间。

同时报告单次修复周期总成本：

```text
Full cycle = 普通P0验证 + 同一次修复成本 + P1全量验证
Inc cycle  = 带缓存采集的P0验证 + 同一次修复成本 + P1增量验证
```

修复成本单列；同一已冻结补丁的重复计时不重新调用 AI。记录初始缓存采集增加的时间与内存，不能仅展示预热之后的最好数字。

开发用的全量模型一致性检查作为正确性检查成本单列。正式性能模式关闭该额外诊断，但保留正常运行必需的缓存验证。不能一边依赖全量诊断生成答案，一边把它排除在增量耗时外。

### 9.4 测量方法

- 相同二进制构建模式、资源配置和验证语义；禁用会改变语义的实验性不健全选项。
- 同一时间只跑一个正式测量任务；顺序交替或随机化，避免固定顺序偏差。
- 每对默认运行 3 次，足以观察基本波动；极短程序如噪声明显可少量增加并说明原因。
- 每次增量测量从同一 `P0` 重新准备状态，不能偷偷复用上一次 `P1` 求解留下的信息。
- 冷/热文件系统缓存条件写清楚，不通过全局清缓存影响其他工作。
- 记录 wall time、CPU time、峰值 RSS 和必要的子进程资源。长驻 session 的峰值包含旧状态，不能把不可重置的进程峰值当成仅更新阶段内存。
- 编译和 API 调用时间不混进 `P1` 验证时间；它们在全链路成本中另列。
- 超时案例不凭空补一个完成时间来计算精确加速比。

对双方完成且有可比较结果的病例计算：

`speedup = T_full / T_inc`。

给每个病例数据、总体中位数；需要汇总时可给几何平均，但说明纳入哪些病例。既报告所有有效病例，也可另列实际复用命中子集，不能只保留加速样例。

### 9.5 必须输出的实验字段

```text
case_id, patch_origin, patch_type, old_hash, new_hash, config_hash
old_result, full_result, incremental_result, agreement_status
full_time, incremental_time, old_full_time, old_instrumented_time
parse_time, symex_time, event_model_time, cnf_time, solve_time
change_analysis_time, checkpoint_restore_time, constraint_update_time
lemma_validate_time, lemma_import_time, cache_io_time
full_symex_steps, executed_new_symex_steps, reused_prefix_steps
events_reused, events_rebuilt, constraints_retained, constraints_rebuilt
lemmas_exported, lemmas_imported, lemmas_rejected
fallback_reason, peak_rss, api_calls, input_tokens, output_tokens, estimated_api_cost
```

缺失字段用明确的 `null/unsupported` 和说明，不能用 0 代替未测量。

### 9.6 如何写结论

按证据回答：

- 工具是否可运行、可复现？
- 第一创新点在哪些层和哪些修改类型上真实工作？
- 第二创新点在哪些病例产生实际旧 lemma 复用？
- 与全量路径有无确定结果冲突？
- 修改后验证是否提速？初始采集成本是否抵消收益？
- 哪些补丁导致全量回退或理论缓存失效？
- 若未提速，是原程序太小、反例太快、重绑定开销高、CNF仍全量，还是其他实际瓶颈？
- AI/传统修复与当前增量支持范围是否匹配？

允许结论是“功能可行但当前规模下没有性能收益”。不为了达到预设加速比删减检查、改变性质或调整两路语义。

**停止并反馈，等待用户决定后续工作。** 此时不自动开展连续修复或旧正确→新错误实验。

---

## 10. 建议的实现模块与边界

此表供代码大模型落到源码文件；实际文件名可顺应仓库组织，但职责必须可定位。

| 模块 | 具体职责 | 不应承担的职责 |
|---|---|---|
| `ProjectController` | 阶段状态、病例调度、会话、报告。 | 代替用户批准下一阶段。 |
| `DeagleAdapter` | 命令/协议、结果和反例解析。 | 靠字符串猜测安全结论。 |
| `RepairAdapter` | 构造修复输入、调用mini或已有工具、冻结一个候选。 | 自动开始跨版本修复循环。 |
| `ChangeProvider` | 来源/语句/GOTO映射与语法变化。 | 单凭文本差分判断全部语义影响。 |
| `AnalysisDependencyTracker` | 类型、配置、静态分析依赖与失效。 | 默认未修改代码一定可复用。 |
| `IncrementalCheckpointManager` | 完整检查点及恢复条件。 | 序列化裸指针并假装可跨进程恢复。 |
| `IncrementalSCModelBuilder` | 更新SSA后缀、事件关系和逻辑约束。 | 只更新OC边而遗漏数值与覆盖约束。 |
| `TheoryAtomRegistry` | 语义atom、常量、带极性literal别名。 | 将旧SAT变量号作为稳定身份。 |
| `TheoryLemmaCache` | 原始理论冲突的记录、审核、绑定与导入。 | 不加区分搬运所有CDCL子句。 |
| `ResultComparator` | 性质级结果、模型诊断、性能统计。 | 将补丁成功率当成验证器正确率。 |

增量状态尽量通过显式数据结构传递；每个病例使用隔离目录，旧快照不可被补丁覆盖。复用失败时携带具体原因返回，不在深层默默调用全量流程并隐藏。

---

## 11. 最终交付清单

阶段 7 结束时交付：

1. 从空目录可重建的安装与构建脚本、固定提交/依赖版本和必要补丁。
2. 修改后的 Deagle 源码分支及复现说明。
3. 修复、反例、结果解析和单病例运行入口。
4. 真实实现的模型增量更新及理论约束复用模块。
5. 首批冻结版本对、原性质、配置、反例和补丁来源。
6. 阶段报告、原始运行数据及可读的最终比较报告。
7. 明确的支持范围、回退条件、已知限制和未完成项。
8. 后续可扩展列表，仅列建议：连续修复、safe→unsafe、细粒度理论依赖、更广同步补丁等；不在本轮自动实现。

只有下载成功、只封装原版 Deagle CLI、每次全量建模后做差分、把旧反例当缓存、或者所有病例都全量回退，均不能作为本项目核心功能完成的证据。

---

## 12. 所有阶段统一反馈模板

```text
阶段编号与名称：
状态：READY_FOR_REVIEW / PARTIAL / BLOCKED

一、结论
本阶段实际证明了什么？尚未证明什么？

二、已完成的工作
新增/修改的具体文件、固定的版本、实际运行的命令。

三、可检查证据
日志路径、病例、真实输出、模型/约束统计、耗时。
未执行的事项必须标为未执行。

四、工具接入与技术选择
现有工具实际复用了什么？哪些不能直接接？为什么？
本阶段若涉及修复，AI与传统方案的实际可用性结论是什么？

五、正确性和范围
性质/配置是否保持？哪些修改受支持？哪些回退？
是否存在解析失败、结果冲突或未解决的状态依赖？

六、成本
本阶段实际耗时、资源、API调用及费用估计。

七、下一阶段建议
建议执行什么；如有替代路线，写出具体工作与代价。

本阶段已停止，等待你确认是否进入阶段 N+1。
```

---

## 13. 资料与源码入口

这些链接用于执行时核实源码和接口。仓库 `main` 会变化；实际实施必须记录并使用固定提交。本文提出的缓存格式、模块划分、增量算法组合及验收规则属于本项目设计，不表示这些工具已原生提供该功能。

- **[R1] Deagle README：** [源码或文档](https://github.com/thufv/Deagle/blob/main/README.md)
- **[R2] DAMER-CAMC：** [源码或文档](https://github.com/shirleylee03/damer-camc)
- **[R3] Yogar-CBMC-Inc：** [源码或文档](https://github.com/yinliangze/yogar-cbmc-inc)
- **[R4] mini-SWE-agent：** [源码或文档](https://github.com/SWE-agent/mini-swe-agent)
- **[R5] DAMER CMake：** [源码或文档](https://github.com/shirleylee03/damer-camc/blob/main/CMakeLists.txt)
- **[R6] mini v2 迁移与配置：** [源码或文档](https://mini-swe-agent.com/latest/advanced/v2_migration/)
- **[R7] DeepSeek 模型与官方基址：** [源码或文档](https://api-docs.deepseek.com/quick_start/pricing/)
- **[R8] DeepSeek 模型列表接口：** [源码或文档](https://api-docs.deepseek.com/api/list-models/)
- **[R9] DeepSeek thinking/tool calls：** [源码或文档](https://api-docs.deepseek.com/guides/thinking_mode/)
- **[R10] mini AgentConfig 与循环：** [源码或文档](https://github.com/SWE-agent/mini-swe-agent/blob/main/src/minisweagent/agents/default.py)
- **[R11] mini 本地环境：** [源码或文档](https://github.com/SWE-agent/mini-swe-agent/blob/main/src/minisweagent/environments/local.py)
- **[R12] SV-Benchmarks：** [源码或文档](https://github.com/sosy-lab/sv-benchmarks)
- **[R13] Deagle 反例与求解衔接：** [源码或文档](https://github.com/thufv/Deagle/blob/main/src/goto-checker/bmc_util.cpp) ；[源码或文档](https://github.com/thufv/Deagle/blob/main/src/cbmc/cbmc_parse_options.cpp) ；[源码或文档](https://github.com/thufv/Deagle/blob/main/src/goto-programs/json_goto_trace.cpp)
- **[R14] CFix 原论文入口：** [源码或文档](https://www.usenix.org/conference/osdi12/technical-sessions/presentation/jin)
- **[R15] 符号执行接口：** [源码或文档](https://github.com/thufv/Deagle/blob/main/src/goto-symex/goto_symex.h) ；[源码或文档](https://github.com/thufv/Deagle/blob/main/src/goto-symex/symex_main.cpp)
- **[R16] 状态与路径：** [源码或文档](https://github.com/thufv/Deagle/blob/main/src/goto-symex/goto_symex_state.h) ；[源码或文档](https://github.com/thufv/Deagle/blob/main/src/goto-symex/path_storage.h)
- **[R17] SC 与 RF 建模：** [源码或文档](https://github.com/thufv/Deagle/blob/main/src/goto-symex/memory_model_sc.cpp) ；[源码或文档](https://github.com/thufv/Deagle/blob/main/src/goto-symex/memory_model.cpp)
- **[R18] SSA 与 OC 数据：** [源码或文档](https://github.com/thufv/Deagle/blob/main/src/goto-symex/symex_target_equation.h) ；[源码或文档](https://github.com/thufv/Deagle/blob/main/src/goto-symex/symex_target_equation.cpp)
- **[R19] closure 后端与 adapter：** [源码或文档](https://github.com/thufv/Deagle/blob/main/minisat-2.2.1/minisat/core/ClosureSolver.cc) ；[源码或文档](https://github.com/thufv/Deagle/blob/main/minisat-2.2.1/minisat/core/Closure.cc) ；[源码或文档](https://github.com/thufv/Deagle/blob/main/src/solvers/sat/satcheck_minisat2.h) ；[源码或文档](https://github.com/thufv/Deagle/blob/main/src/goto-checker/solver_factory.cpp)
- **[R20] DAMER 变化与构建接口：** [源码或文档](https://github.com/shirleylee03/damer-camc/blob/main/AST_compare.h) ；[源码或文档](https://github.com/shirleylee03/damer-camc/blob/main/changeConstruct.h) ；[源码或文档](https://github.com/shirleylee03/damer-camc/blob/main/changeConstruct.cpp)
- **[R21] mini 模型与费用适配：** [源码或文档](https://github.com/SWE-agent/mini-swe-agent/blob/main/src/minisweagent/models/litellm_model.py)

