# 阶段 1 · 固定版本、构建与独立运行

**状态　`READY_FOR_REVIEW`**

## 一、结论

三项核心工具均已在目标服务器独立跑通。Deagle 可以进入下一阶段的病例准备。两份 Deagle 二进制在相同 SC 配置下报告了同一断言违反和同一有界通过。DAMER 在自带版本对上更新了 PDNet 并重新检查了性质。mini 使用官方 DeepSeek API 完成一次有工具结果回传的文件修改，控制器收到了原生 `Submitted`。工程进度停在阶段 1。

| 工具 | 固定版本 | 本阶段实际验收 |
|---|---|---|
| Deagle | 4.2.0，上游 `d8c79eab`，共同兼容提交 `a159f992` | 两份独立工作树均从源码构建并链接，最终二进制 SHA-256 相同。运行输出与求解器工厂源码共同确认 MiniSat 2.2.1 的 Deagle Closure 后端 |
| DAMER-CAMC | `c005ebbd` | CMake 目标 `PDNet2_0` 构建成功，实际链接系统 `libtcmalloc.so.4`。`-help`、原版直接建模、新版直接建模和原生 `-CIA -PDNetSlice` 均运行成功 |
| mini-SWE-agent | v2.4.6，`a83fcae8` | Python 3.10.12 独立 venv，LiteLLM 1.110.2、OpenAI SDK 3.57.0。成功运行中收到两次官方工具调用响应，在隔离 shell 修改文件并提交回执 |
| Yogar-CBMC-Inc | `6e1d4eac` | 现场清点 164 个跟踪文件，含两个验证器二进制和 150 个 C / 预处理输入。固定树中未发现验证器的 C/C++ 实现文件或许可证文件。本阶段只清点材料 |

完整提交、树对象、分支、许可证文件哈希、编译目标和二进制哈希均已锁定。Deagle 主体声明 BSD 4-Clause，附有 CBMC 和 MiniSat 各自的条款。DAMER 为 BSL-1.0，mini 为 MIT。[工具锁](../configs/toolchain.lock.json) · [实际检出与构建记录](evidence/stage-01/inventory.json)

## 二、已完成的工作与复现入口

目标目录为 `/root/Deagle_incremental_execution`。在 Jammy 上更新 APT 后安装缺失依赖，两次事务分别新增 21、54 个包，升级 8、3 个包，两次均移除 0 个包。两份 Deagle 共享 Git 对象库，各有自己的工作树、对象文件和可执行文件。固定源码的 `cbmc.dir` 目标直接生成所需的 `src/cbmc/deagle_exe`。使用 4 个编译作业及项目运行目录中的 ccache。[上游 Makefile](https://github.com/thufv/Deagle/blob/d8c79eaba5df03b1a013dc6ffbb3a1e249485c1e/src/Makefile) · [构建脚本](../scripts/stage1/build.sh)

在同配置服务器上，从主仓库检出本阶段后，可用以下命令重建并复查原生工具。Ubuntu 系统需具备 systemd、Git、GCC/G++、Make、curl 和 Python 3.10。

```bash
python3 -B scripts/init_workspace.py
apt-get update
apt-get -y --no-install-recommends install cmake flex bison python3-venv python3-yaml \
  libgoogle-perftools-dev bubblewrap ccache time gcc-multilib graphviz
for tool in deagle damer_camc mini_swe_agent yogar_cbmc_inc; do
  bash scripts/stage1/fetch.sh "$tool" || exit 1
done
bash scripts/stage1/prepare_deagle.sh
for tree in deagle-baseline damer-camc deagle-work; do
  bash scripts/stage1/build.sh "$tree" || exit 1
done
python3 -B scripts/stage1/deagle_smoke.py
python3 -B scripts/stage1/damer_smoke.py
```

mini 的实际安装使用镜像取得 wheel，安装前逐一核对官方 PyPI 发行记录的 SHA-256。89 个 wheel 已锁定，`pip check` 通过，全部依赖的离线哈希锁解析也已通过。复现使用现有锁。以下命令的最后一步仅复查隔离环境。[依赖锁](../configs/mini-requirements.lock) · [wheel 核对表](evidence/stage-01/verified-wheels.json) · [安装后冻结清单](evidence/stage-01/pip-freeze.txt)

```bash
python3 -m venv .venv
.venv/bin/python -B scripts/stage1/install_mini.py \
  --index https://mirrors.huaweicloud.com/repository/pypi/simple/ \
  --file-mirror https://mirrors.huaweicloud.com/repository/pypi
.venv/bin/python -B scripts/stage1/mini_smoke.py --isolation-only
```

若要重新进行付费验收，先在持钥控制端执行 `python scripts/stage1/list_models.py` 并将其生成的模型列表同步至服务器。随后通过已认证 SSH，把控制端 `apikey.txt` 作为远端 `.venv/bin/python -B scripts/stage1/mini_smoke.py --key-stdin` 的标准输入。远端命令的工作目录是项目根目录。本次正是经 SSH 专用输入传递，服务器未落盘密钥，shell 环境中也没有密钥。[隔离与工具调用入口](../scripts/stage1/mini_smoke.py)

## 三、可检查证据

### Deagle 的性质、反例和输出接口

两个诊断程序分别建线程和等待线程结束。两份二进制均使用 `--deagle-closure --mm sc --64 --unwind 4 --unwinding-assertions --trace`。每个程序分别检查普通输出及结构化结果，违反程序另做 GraphML 检查，共 10 次最终运行。下表数值在两条路径相同。[违反程序](../tests/stage1/worker_violation.c) · [通过程序](../tests/stage1/join_pass.c) · [命令和性质级结果](evidence/stage-01/deagle.json)

| 程序及目标性质 | 工具原始结果 | 经核对的证据 |
|---|---|---|
| `worker_violation.c` 的 `worker.assertion.1` | `FAILURE`，退出码 10 | JSON 反例 66 步，涉及线程 0、1。线程 1 把 `flag` 写成 1，随后在第 10 行违反 `flag == 0`。归类为 `VIOLATION` |
| `join_pass.c` 的 `main.assertion.1` | `SUCCESS`，退出码 0 | 第 18 行的 `value == 7` 通过。该输出没有独立展开性质行，保守归类为 `NO_VIOLATION_WITHIN_BOUND` |

两份原版 `--json-ui` 输出在第 54 行第 4 列即无法按 JSON 解析。求解器选择日志和完整 equation 转储穿插在数组中。兼容补丁给 UI 消息处理器增加可选的专用文件出口。设置 `INCDEAGLE_JSON_OUTPUT` 并使用 `--json-ui` 时，控制器读取全份 JSON 文件，同时保留 stdout 诊断和 stderr。解析器核对目标性质、总体状态、线程和源位置。原始错误输出也已留存。补丁只改动 `src/util/ui_message.{h,cpp}` 两个文件。把文本补丁应用到上游索引所得源码树，与薄 Git bundle 中的兼容提交完全一致。另在临时目录仅取原版提交，用 bundle 成功恢复出同一提交上的两份工作树。[兼容补丁](../patches/deagle-json-output.patch) · [可恢复的 Git 提交](../patches/deagle-stage01.bundle) · [独立恢复检查](evidence/stage-01/bundle-replay.json) · [严格解析与检查](../scripts/stage1/deagle_smoke.py)

运行日志出现 `Use Deagle's closure solver` 和 `Set Deagle closure solver's graph`。固定源码显示前者对应 `deagle_closure_solvert` 的创建，后者将事件图交给该求解器。GraphML 可解析，包含 5 个节点、3 条边、1 个违反节点以及线程 0、1。其性质元数据写的是 `reach_error()`，与本例的 C 断言表述不同。本阶段据性质级 JSON 和源位置认定目标断言违反。[求解器选择](https://github.com/thufv/Deagle/blob/d8c79eaba5df03b1a013dc6ffbb3a1e249485c1e/src/goto-checker/solver_factory.cpp#L227) · [事件图交接](https://github.com/thufv/Deagle/blob/d8c79eaba5df03b1a013dc6ffbb3a1e249485c1e/src/goto-checker/bmc_util.cpp#L475)

### DAMER 原生变化分析

选用实际存在的 `test/08_Lazy.c`、`08_Lazy-new.c` 和 `08_Lazy.xml`。改动将 `data += 2` 换为 `data++`，性质要求沿所有路径始终满足 `data == 0 || data == 1`。三个调用使用独立的可写目录，分别保存生成的性质文件和 CSV。直接模式运行 `-property ../test/08_Lazy.xml <程序>`，变化分析运行 `-CIA -PDNetSlice -property ../test/08_Lazy.xml ../test/08_Lazy.c`。[原始输入](https://github.com/shirleylee03/damer-camc/tree/c005ebbde3672fff77c6d91da2f91d1daa45d746/test) · [调用、输入哈希及 CSV](evidence/stage-01/damer.json)

| 路径 | places | transitions | 搜索图节点 | 性质结果 |
|---|---:|---:|---:|---|
| 原版直接建模 | 82 | 41 | 40 | FALSE |
| 新版直接建模 | 82 | 41 | 43 | FALSE |
| 原生 CIA 更新后的受影响切片 | 44 | 26 | 27 | FALSE |

源码在 CIA 路径上用变化集调用 `changeConstruct(originCpnet, changes)`。本例日志明确记录了更新旧模型、拒绝沿用旧验证结论、重新检查切片三个步骤。其 PDNet 结果与新版直接检查一致。这里验证的是 DAMER 自身的接口，它与 Deagle equation 的适配属于后续阶段。[调用位置](https://github.com/shirleylee03/damer-camc/blob/c005ebbde3672fff77c6d91da2f91d1daa45d746/pdnet_parseoption.cpp#L858)

### mini 与 DeepSeek 的完整往返

当日官方文档列出 Pro 模型。控制端从 `GET https://api.deepseek.com/models` 收到 HTTP 200，实际可用 ID 包括 `deepseek-flash` 和 `deepseek-v4-pro`。本次固定服务端 ID 为 `deepseek-v4-pro`，LiteLLM 路由为 `deepseek/deepseek-v4-pro`，显式配置官方基址，启用 thinking，简单诊断请求使用 low effort。[模型列表实测](evidence/stage-01/models.json) · [模型配置](../configs/deepseek.yaml) · [官方工具调用协议](https://api-docs.deepseek.com/guides/thinking_mode/)

成功运行的第一次响应发出原生 `bash` 调用。隔离 shell 将 `status.txt` 从 `pending` 改为 `ready` 并读到控制器随机生成的回执。第二个请求携带相同工具调用 ID、工具执行结果和逐字保留的前一轮 `reasoning_content`。模型随后把回执原文写进提交命令，mini 返回 `Submitted`。控制器核对了落盘内容、原回执文件及提交值。证据只记录推理字段是否存在、是否完整回传。[成功运行记录](evidence/stage-01/mini-accepted.json)

## 四、工具接入与技术选择

mini 使用固定版本的 `DefaultAgent`、`LitellmModel` 和 `BubblewrapEnvironment`。模型凭据仅作为客户端请求参数传入。候选进程经 `setpriv` 降权，沙箱只挂载临时工作目录、只读命令及必要运行库，清空继承环境。实测沙箱内 UID 及沙箱新建文件的宿主 UID 均为 65534，不能访问项目根目录，网络路由表只有表头。本机原先继承的通用用户密钥读取权限已收紧为仅控制账户可读写，文件内容未修改。[固定版 mini 环境实现](https://github.com/SWE-agent/mini-swe-agent/blob/a83fcae82d2a08f0ee0c688f9d137b3566c097f8/src/minisweagent/environments/extra/bubblewrap.py) · [隔离实测](evidence/stage-01/mini-accepted.json)

首次尝试中模型先检查目录，遇到命令缺失，在第三次请求后完成文件修改，但达到当时的 3 步上限，未提交。调试时补上只读 `ls`，明确给出本次协议检查的两个命令模板，将 smoke 上限调为 6 步。新运行使用新随机回执，在 2 步内完成。两次的费用都计入下表。mini 的费用硬上限在该诊断中显式设为 0，调度步数、运行时间及错误退出仍有效。两次都关闭自动模型重试。[首次尝试](evidence/stage-01/mini-attempt-1.json) · [成功尝试](evidence/stage-01/mini-accepted.json)

## 五、正确性和范围

Deagle 验收逐个检查性质及反例，两份最终程序的 SHA-256 均为 `4566c4ae50aed3be4d68aa5450a049952b32daad88b3ac745efb72e839a318a3`。原生测试用 systemd cgroup 串行运行，内核返回 `memory.max=21474836480`，每次设置 300 秒超时。另用 1 秒限制运行 2 秒休眠，实测退出码 124。阶段 1 没有冻结项目病例、比较 AI 与传统修复质量、实现跨版本缓存或进行验证性能评测。[资源及源码树检查](evidence/stage-01/inventory.json)

## 六、成本

| DeepSeek 运行 | 模型请求 | 输入 token | 输出 token | 输入缓存命中 / 未命中 | 按峰时费率估算 USD |
|---|---:|---:|---:|---:|---:|
| 首次诊断，达到步数上限 | 3 | 1,897 | 676 | 1,024 / 873 | 0.003874376 |
| 通过验收的独立运行 | 2 | 920 | 192 | 384 / 536 | 0.001484736 |
| 合计 | **5** | **2,817** | **868** | **1,408 / 1,409** | **0.005359112** |

上述五次请求发生在 2026-11-23 周一 08:46–08:48 UTC。估算使用官方每百万 token 的美元费率，输入缓存命中 0.044、未命中 1.32、输出 3.96。另有一次模型列表查询。费用为按实际 token 计算的估算值。[当日官方定价](https://api-docs.deepseek.com/quick_start/pricing/)

原版 Deagle 基线构建用时 3 分 59.62 秒，已预热 ccache 的开发树为 3.10 秒。兼容补丁后的两次重建分别为 22.75 秒和 1.70 秒。DAMER 构建用时 28.07 秒，其构建进程树中记录的单进程最高 RSS 为 770,624 KiB。这些数值用于解释安装成本。控制端从 08:19:54 UTC 开始记录阶段执行时间，发布前验收的时间及间隔保存在验收记录中。[构建计时](evidence/stage-01/inventory.json) · [发布前验收](evidence/stage-01/acceptance.json)

完整的原生 stdout、stderr、JSON、GraphML、CSV 和构建安装日志共 100 个文件，已压缩归档并逐个核对 SHA-256。公共 PyPI 首次大 wheel 下载较慢，切换镜像后按官方摘要核验。安装辅助脚本初次还把 wheel 内嵌依赖的元数据识别为发行元数据，限定到顶层后全部通过。[原始日志包](evidence/stage-01/raw-evidence.tar.gz) · [归档清单](evidence/stage-01/raw-manifest.json)

## 七、下一阶段建议

获准后从 3–5 个并发小程序开始。先由独立 Deagle 基线确认每个旧程序违反指定断言，并保存性质级 JSON、线程、源位置及原始 trace。再准备人工补丁，选择少量病例尝试 AI 和可取得的传统修复方案。GraphML 的性质元数据需与实际断言单独核对。

服务器收尾检查时，阶段任务进程数为 0，病例目录条目数为 0。[停止状态记录](evidence/stage-01/stop-check.json)

本阶段已停止，等待你确认是否进入阶段 2。
