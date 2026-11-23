# 阶段 0 · 环境探测与项目初始化

**状态　`READY_FOR_REVIEW`**

## 一、结论

可以在用户确认后开始阶段 1 部署。目标服务器允许以 root 登录，有 8 个有效逻辑 CPU，采样时可用内存 29.18 GiB，项目文件系统可用 70.92 GiB。APT 已成功模拟解析编译和 Python 依赖。部署中需要处理两项实测限制，分别是 GitHub 的 Git 连接偶发超时，以及 Docker 未安装且 Docker Hub 探测超时。

本阶段完成的是环境和安装方案验收。Deagle 与 DAMER 构建、mini 工具调用往返、模型复用和性能测量均为**未执行**。

## 二、已完成的工作

- 完整阅读原始指南 1,111 行，将其按字节复制到 `EXECUTION_GUIDE.md`。控制端初始目录中有指南和 `apikey.txt`，已在原目录初始化 Git。
- 以认证 SSH 连接服务器，在 `/root/Deagle_incremental_execution` 建立项目。控制端和服务器均用 `scripts/init_workspace.py` 创建指南约定的目录。空的上游检出目录供阶段 1 使用。
- 建立 README、Git 忽略规则、项目状态，以及资源、上游和 DeepSeek 三份配置。上游提交号和模型 ID 暂存为 `null`。
- 仅在控制端检查密钥文件存在、为普通文件、非空且可打开。检查没有读取文件内容。服务器项目中没有密钥副本。两端的目录和文件检查有独立记录。[控制端记录](evidence/stage-00/controller-layout.json) · [服务器记录](evidence/stage-00/server-layout.json)

以下是服务器上实际执行的主要命令。探测程序运行的各条子命令、退出码、标准输出、错误输出和耗时保存在证据文件中。

```bash
cd /root/Deagle_incremental_execution
python3 -B scripts/init_workspace.py
python3 -B scripts/probe_environment.py \
  --apt-inrelease http://repo.huaweicloud.com/ubuntu/dists/jammy/InRelease
apt-get -s --no-install-recommends install cmake flex bison python3-venv libgoogle-perftools-dev
apt-cache policy docker.io bubblewrap
```

## 三、可检查证据

服务器主采样窗口为 **2026-11-23 07:56:21–07:56:23 UTC**。下表的内存和磁盘容量使用 GiB。[原始环境快照](environment.json)

| 项目 | 实际观测 |
|---|---|
| 系统 | Ubuntu 22.04.5 LTS，Linux 5.15.0-186-generic，x86_64 / amd64，64 位，KVM，UID 0 |
| CPU | `nproc=8`，进程亲和性为 0–7。来宾拓扑为 1 个插槽、4 核、每核 2 个逻辑 CPU |
| cgroup | v2。从 SSH 会话逐级读到挂载根目录。`user.slice/cpu.max` 为 `max 100000`，可见祖先无有限 CPU 配额或内存硬上限 |
| 内存 | 总量 30.04 GiB，有效可用 29.18 GiB，Swap 为 0。`RLIMIT_AS` 软硬限制均无限 |
| 项目磁盘 | ext4，总量 78.63 GiB，可用 70.92 GiB，`df` 占用率 6% |
| 已有工具 | Git 2.34.1，GCC/G++ 11.4.0，GNU Make 4.3，Python 3.10.12，pip 22.0.2，build-essential 12.9ubuntu3 |
| 待装依赖 | CMake、Flex、Bison、python3-venv、tcmalloc 开发包。五项一起进行 APT 模拟解析，退出码 0，预计新增 18 个包，升级 0，移除 0 |
| 隔离环境 | Docker、Podman、bubblewrap 命令均缺失，Docker 服务 inactive，本地 Docker socket 不存在。APT 缓存列有 bubblewrap 和 docker.io 候选版本 |

有效 CPU 取进程亲和性与可见祖先有限配额的最小值。有效可用内存取 `MemAvailable` 与各有限 cgroup 硬上限剩余额度的最小值。原始快照中 cgroup 文件的 `null` 表示该层没有这个文件，`max` 是内核返回的原文。

| 服务器网络检查 | 结果 |
|---|---|
| 首次 GitHub 探测 | Deagle 的 Git 服务公告返回 200，内容类型为 `application/x-git-upload-pack-advertisement`。GitHub API 元数据和 codeload 归档响应头均为 200 |
| GitHub 复查 | 08:03 UTC 对主页和本项目 Git 公告各等待 8 秒，均超时，curl 退出码 28。同次复查的 API 和 codeload 仍为 200 |
| 包索引 | PyPI 的 pip 索引和服务器实际使用的华为云 Ubuntu Jammy InRelease 均返回 200 |
| DeepSeek | 对官方基址发送一次不带凭据的 HEAD，收到 HTTP 401，证实 HTTPS 可达。模型列表和推理端点留待阶段 1 验证 |
| Docker Hub | 官方 Registry 的 HTTPS 探测超时，curl 退出码 28，没有拉取镜像 |

两次 GitHub 探测使用了不同的仓库路径，覆盖 Git 服务公告、元数据和归档入口。完整仓库传输及镜像导入均待部署阶段实测。[首次探测](environment.json) · [网络复查](evidence/stage-00/network-recheck.json) · [APT 模拟、隔离包和 Registry 探测](evidence/stage-00/package-plan.json)

## 四、工具接入与技术选择

构建计划使用服务器原生 GCC、Make 和 APT，补齐缺失的编译依赖。mini 单独使用项目 `.venv`，先按固定版本的 `pyproject.toml` 核对 Python 要求，再安装并记录实际依赖。用 APT 提供的 bubblewrap 隔离候选命令，可以避开本次遇到的镜像下载问题。该隔离方案的运行验收留在阶段 1。

| 计划上游 | 阶段 1 工作 |
|---|---|
| [thufv/Deagle](https://github.com/thufv/Deagle) | 从同一提交建立独立基线及修改树，核实 Make 入口，以 4 个并行作业分别构建。需要的兼容补丁同步到两份源码 |
| [shirleylee03/damer-camc](https://github.com/shirleylee03/damer-camc) | 核实 CMake 目标和 tcmalloc 链接，构建后运行原生样例 |
| [SWE-agent/mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) | 固定源码和 venv 依赖，实测隔离命令、一次官方 API 工具调用往返及无害的文件修改 |
| [yinliangze/yogar-cbmc-inc](https://github.com/yinliangze/yogar-cbmc-inc) | 清点可取得的源码、脚本、程序版本对，按需选取材料 |

当前采用的是操作系统的 cgroup、procfs、Git、APT 和 curl 检查接口。四个上游项目的构建、算法接口及 AI 或传统修复的实际可用性均待测。[上游清单](../configs/toolchain.lock.json) · [DeepSeek 计划配置](../configs/deepseek.yaml)

## 五、正确性和范围

本阶段没有程序版本对，也没有运行性质验证。性质保持、展开完整性、全量对照、反例解析及缓存命中均无实验数据。阶段进度记录为 0，阶段 1 的批准位为 `false`。[项目状态](../project_state.json)

发布前检查覆盖配置与资源快照的一致性、两份指南的字节一致性、密钥的元数据保持及 Git 排除规则，并核对待提交文件。结果可在[阶段验收记录](evidence/stage-00/acceptance.json)复查。

## 六、成本

从控制端首个记录时间 07:46:47 UTC 到 08:11:08 UTC 的发布前验收，共 **24 分 20.771 秒**，发布与交付时间另计。服务器主探测耗时 **2.416 秒**，探测程序及其子进程合计 CPU 时间 **0.482 秒**。探测主进程峰值 RSS 为 13,836 KiB，单个已等待子进程的最大峰值为 81,492 KiB。APT 模拟用时 0.863 秒。这些是环境检查的开销。

本阶段模型推理请求 **0**，输入和输出 token 均为 **0**，模型调用费用 **0 元**。流量仅涉及环境检查及项目交付，未安装系统包、未下载上游源码树、未启动构建或性能任务。

## 七、下一阶段建议

1. 用户确认后，先更新 APT 索引并复核模拟结果，安装所需原生依赖。该机为 amd64，是否需要 multilib 按固定 Deagle 源码和实际构建日志决定。
2. 限次尝试官方 Git 传输。若仍超时，可从可访问官方仓库的机器导出包含固定提交的 Git bundle，传到服务器后用 `git bundle verify` 和 `git rev-parse` 核对。只需只读研究材料时，也可按明确 SHA 取官方 codeload 归档，登记归档哈希。两份 Deagle 工作树应保留可审计的提交历史。
3. 默认编译并行度为 4。按每个作业规划 3 GiB、为系统至少保留 6 GiB，在有效 CPU、可用内存与指南的 4 个作业上限中取最小值。验证同时仅运行 1 个任务，超时 300 秒，单任务内存预算 20 GiB，按采样值尚余约 9.18 GiB。检查点最多 8 个，共用 2 GiB，计入该 20 GiB 预算。阶段 1 再验证这些限制的执行效果。[资源配置](../configs/project.yaml)
4. 在实际修复前，用非 root 进程实测 bubblewrap 对候选目录的写权限、对工具的只读访问，以及对项目根目录和凭据的隔离。若固定版本 mini 的环境接口或主机内核使此方案不可用，可通过 APT 安装 Docker，在可达机器取得可信镜像并校验后离线导入，代价是镜像传输、磁盘和运行时部署。
5. 获准接入 API 后，由受信任的控制进程读取控制端的密钥。如模型客户端运行在服务器端，可经认证 SSH 的专用输入传递给该进程。候选命令使用独立文件系统视图和不含凭据的环境。先查询当日可用模型并记录 ID，再做一次完整工具调用往返。

本阶段已停止，等待你确认是否进入阶段 1。
