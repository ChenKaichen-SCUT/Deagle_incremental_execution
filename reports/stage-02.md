# 阶段 2 · 程序、反例、修复方式与版本对

**状态　`READY_FOR_REVIEW`**

## 一、结论

三个自建 pthreads 病例已各冻结一对版本。独立 Deagle 基线在全部原版上找到了指定断言的反例；两份人工候选和一份 mini + DeepSeek 候选均通过固定 Deagle 前端，并在相同断言和配置下得到 `NO_VIOLATION_WITHIN_BOUND`。随后在新目录重新执行六条验证，性质编号、源位置和分类逐项一致。[独立重跑](evidence/stage-02/replay.json) · [发布前验收](evidence/stage-02/acceptance.json)

| 病例及冻结清单 | 原版目标断言及反例 | 最终候选来源与改动 | 候选全量结果 |
|---|---|---|---|
| [batch_total](../cases/batch_total/freeze.json) | 两箱应合计 6 件，线程 1 写入 4。第 21 行断言失败，62 步 | 人工。把每箱件数从 2 改成 3，保留按箱数累加的运算 | 有界通过 |
| [threshold_guard](../cases/threshold_guard/freeze.json) | 依次处理 1、3、4，只累计了第一笔。第 24 行断言失败，74 步 | 人工。把数量上限从小于 3 改为小于等于 3，保留正数检查和两个累加器 | 有界通过 |
| [split_counter](../cases/split_counter/freeze.json) | 两个线程都读到 0，各写回 1。两个线程结束后，第 31 行的 `counter == 2` 失败，166 步 | DeepSeek。把一次贡献的读和写放进同一个互斥区，保留两个工作线程 | 有界通过 |

前两例各有一条工作线程，用于观察常量与条件的变化。第三例的反例依赖两条工作线程的交错。传统工具 ConRepair 的作者版二进制可以启动，但在同一个原版程序上解析失败。三例中各自只有一个最终候选。[修复来源与源码复核](evidence/stage-02/repair-review.json) · [传统工具实测](evidence/stage-02/traditional.json)

## 二、已完成的工作

每例保存 `old/program.c`、`candidate/program.c`、`patch.diff`、原断言 `phi.json`、验证配置 `gamma.json`、受保护的 `harness.c`、任务说明和规范化反例。原版和候选分别在独立临时目录以相同文件名编译，均以 `harness.c` 为翻译单元并包含 `program.c`。冻结清单记录输入、差异、执行结果和原始日志摘要。将补丁应用到干净的原版副本，三个结果都与提交的候选逐字节一致。[病例目录](../cases) · [冻结检查](../scripts/stage2/freeze.py)

在主仓库根目录可复查以下三项。前两条只需 Python、PyYAML 和 Git，可离线运行。最后一条使用阶段 1 已构建的 Ubuntu 服务器基线，另建本次运行目录，全程无需 API 密钥。

```bash
python3 -B scripts/stage2/freeze.py
python3 -B -m unittest discover -s tests/stage2 -v
python3 -B scripts/stage2/replay.py
```

单独复查某一版本时，可运行下列命令，输出目录须为新目录。原始记录中的临时路径可通过各例 `run.json` 查到。

```bash
python3 -B scripts/stage2/check_case.py split_counter old \
  --out runs/stage-02/check-split-old
```

## 三、可检查证据

六个冻结版本分别完成 GCC 辅助语法检查、Deagle 的 GOTO 中间表示生成、独立 Deagle 全量求解。三条原版最终验证均退出 10，目标性质均为 `main.assertion.1: FAILURE`。三条候选最终验证均退出 0，原目标均为 `SUCCESS`。每条运行的完整 stdout、stderr、专用 JSON 文件、命令、用时和 SHA-256 都在相应病例的 `evidence` 下。[计数器原版记录](../cases/split_counter/evidence/old/run.json) · [计数器候选记录](../cases/split_counter/evidence/candidate/run.json)

适配器严格读取完整原生 JSON，逐项核对性质 ID、断言位置、总体状态和退出码。规范化步骤保留原始次序、线程、可得的源位置和赋值。计数器轨迹中，第 83、96 步是线程 2、1 读取快照 0，第 109、122 步是线程 1、2 写回 1。三个反例分别记录 42、46、94 个带左值和值的赋值步骤；每例均有两步缺少源位置，归档保留了这些步骤。公开 trace 没有完整导出 reads-from 关系、程序顺序边或全体内存事件的 SC 顺序。[常量反例](../cases/batch_total/evidence/old/cex0.json) · [条件反例](../cases/threshold_guard/evidence/old/cex0.json) · [交错反例](../cases/split_counter/evidence/old/cex0.json) · [固定版原生 trace 转换源码](https://github.com/thufv/Deagle/blob/d8c79eaba5df03b1a013dc6ffbb3a1e249485c1e/src/goto-programs/json_goto_trace.cpp)

独立重跑启动新的验证器进程。另有 9 个回归测试覆盖真实反例重建、缺失和重复性质、源位置错误、混入诊断文本、退出码矛盾、展开失败、未决结果、命令参数偏离以及受保护文件和输出白名单。正式冻结证据随各例提交。附加归档收录了初筛、独立重跑、传统工具尝试和模型控制器日志，共 99 个文件。[测试结果](evidence/stage-02/tests.txt) · [附加归档](evidence/stage-02/validation-logs.tar.gz) · [逐文件哈希](evidence/stage-02/archive.json)

## 四、工具接入与技术选择

**AI 修复。** 两份人工补丁先完成验证。随后 mini-SWE-agent v2.4.6 在独立工作目录中调用官方 `deepseek-v4-pro`，只处理计数器原版。修复器获得原版、受保护的测试与性质、验证配置、完整原始 JSON、规范化反例和相关赋值摘录。模型第一次尝试访问并不存在的 `/workspace`，随后从实际目录读取输入、修改文件、完成 GCC 语法检查并提交。本轮共 6 次响应，自动重试为 0。外层控制器接收一次 `Submitted` 后才验证候选；候选验证结果没有传回模型。[真实请求、观察和提交记录](evidence/stage-02/mini-20261123T092658163058Z.json) · [候选补丁](../cases/split_counter/patch.diff)

工作进程运行于阶段 1 验证过的非特权 bubblewrap 隔离环境。实测进程 UID 为 65534，项目根目录不可见，无网络路由，输入和性质文件只读。提交后控制器逐一比较原始输入字节，并确认输出目录只有 `program.c`。6 次响应中有 2 次没有返回非空推理字段，LiteLLM 对空历史字段产生占位告警。控制器检查了后续 5 次请求对前一轮字段值的保留情况，核对记录均为真。归档只保存字段状态、工具调用及观察。[修复控制器](../scripts/stage2/repair.py) · [官方工具调用协议](https://api-docs.deepseek.com/guides/thinking_mode/)

**传统修复。** ConRepair 固定在作者提交 `55e8e8ba`。该工具从受限 C 程序合成同步或语句顺序调整，源码显示它自行启动随包的 CBMC/Z3，解析文本结果。作者版 JAR 的帮助命令成功。首次在 Java 11 上求解时，旧 Scala 库无法解析版本号。换用 OpenJDK 8 后，同一计数器原版在第 5 行的 `pthread_mutex_t` 被其 CPAchecker 前端拒绝。用 GCC 对同一翻译单元做标准预处理再试，前端在原断言的 glibc 宏展开处拒绝 `CASTExpressionList`。两次均退出 1，未产出候选。接入需要处理线程创建、互斥、join、断言及源位置映射，并验证回写的 C 补丁保持这些语义。[固定版输入约定](https://github.com/thorstent/ConRepair/blob/55e8e8ba65a98af7992611f03bc45b85b239e0cd/README.md) · [CBMC 调用源码](https://github.com/thorstent/ConRepair/blob/55e8e8ba65a98af7992611f03bc45b85b239e0cd/implementation/ConRepair/src/main/scala/at/ac/ist/con_repair/model_checker/cbmc/InvokeCBMC.scala#L82) · [命令及失败记录索引](evidence/stage-02/traditional.json)

另检查 Liss 作者提交 `ce998b2d` 及两个固定依赖。安装系统 Boost 后，CMake 已识别 Boost 1.74，仍找不到要求的 LLVM 工具链。主机包源没有相应的 3.6 开发包，作者固定的 Z3 在 GCC 11 标准库中编译失败。现场没有生成 Liss 可执行文件。上游文档和源码还表明，其输入使用自有同步操作和同时启动的线程，不解释 pthread 互斥。两种传统方案均未作为首版修复入口。[Liss 输入与构建要求](https://github.com/thorstent/Liss/blob/ce998b2d0650ec8250ef83a7a9d9082bc7a925fe/README.md) · [线程识别源码](https://github.com/thorstent/Liss/blob/ce998b2d0650ec8250ef83a7a9d9082bc7a925fe/src/cfg/program.cpp#L81)

## 五、正确性和范围

两个版本的入口、测试程序、输入、原断言和配置均已比对。使用阶段 1 的独立基线，二进制 SHA-256 为 `4566c4ae50aed3be4d68aa5450a049952b32daad88b3ac745efb72e839a318a3`。验证参数为 `--function main --deagle-closure --mm sc --64 --unwind 4 --unwinding-assertions`，输出模式为 `--trace --json-ui`。前端检查以相同语义参数调用 `--show-goto-functions`，检查原断言已进入中间表示并在选择求解器前返回。全量验证重新生成 IR，没有复用前端产物。六次输出均没有单列展开性质，因此候选结果只按有界通过记录。[固定版前端返回点](https://github.com/thufv/Deagle/blob/d8c79eaba5df03b1a013dc6ffbb3a1e249485c1e/src/cbmc/cbmc_parse_options.cpp#L754) · [命令与性质复核](../scripts/stage2/check_case.py)

三个候选都保留原测试和工作线程。常量例保留按输入数量累加，条件例仍会拒绝大于上限的请求，计数器例仍在每次调用中增加一而非直接写入最终总数。源差异和指纹检查的结论限于这些具体病例。常量例可用于后续观察结构是否保持，条件例可检验可达事件变化，同步例应保留为可能需要全量回退的样例。本阶段尚未测量事件复用、理论约束复用或增量提速。[源码复核](evidence/stage-02/repair-review.json)

## 六、成本

本阶段这一次修复使用 9,762 个输入 token，其中 7,552 个命中缓存、2,210 个未命中，另有 657 个输出 token。6 次调用发生在 2026-11-23 周一 09:26–09:27 UTC。按当日高峰期每百万 token 的美元单价 0.044、1.32、3.96，估算为 **0.005851208 美元**。全部请求计入；本阶段没有额外的模型列表或余额查询。[调用明细](evidence/stage-02/mini-20261123T092658163058Z.json) · [官方定价](https://api-docs.deepseek.com/quick_start/pricing/)

正式录取的六次全量求解串行运行，单次上限 300 秒、20 GiB，实测 cgroup 返回 `21474836480` 字节。首轮 GCC、GOTO 前端和全量求解的外层墙钟时间分别合计 0.1021、0.3849、0.4577 秒，含进程与 systemd 启动。另一次六版本重跑从检查资源到完成耗时 1.1895 秒。初筛另进行了三次短验证和三次 IR 检查。主机安装 Boost 开发包、OpenJDK 11 和 8 的三次 APT 事务分别新增 7、10、3 个包，共升级 1 个、移除 0 个。控制端从 09:15:54 UTC 开始计时，至发布前验收的实际间隔见验收文件。[重跑记录](evidence/stage-02/replay.json) · [阶段计时](evidence/stage-02/acceptance.json)

## 七、下一阶段建议

经确认后，可先用常量例对照全量建模各环节，再用条件例和同步例检查标识与回退边界。届时需要用增强版重新验证原版，生成真实检查点和理论缓存，并单独计入生成成本。若要推进传统修复，优先为计数器病例设计一份可核对的 ConRepair 线程与断言映射，先验证语义对应，再评估自动接入的成本。[阶段停止检查](evidence/stage-02/stop-check.json)

本阶段已停止，等待你确认是否进入阶段 3。
