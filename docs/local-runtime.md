# 在 Windows 本机运行 Deagle

本机项目在 `E:\Deagle_incremental_execution`，Linux 环境是 WSL2 的 `Deagle-Jammy`。PowerShell 启动器会进入该发行版，以 `deagle` 用户执行。冻结的验证、增量实验和证据审核都可以离线运行。实验依据是阶段 11C 的 [固定提交](https://github.com/ChenKaichen-SCUT/Deagle_incremental_execution/tree/7d2d08ecbf6e643d3537131489ab6ba23c327c52)。

## 日常运行

```powershell
Set-Location E:\Deagle_incremental_execution
.\deagle-local.cmd doctor
.\deagle-local.cmd verify --deagle-closure --mm sc --32 --unwind 3 --unwinding-assertions tests\stage1\join_pass.c
```

`doctor` 校验运行包、固定二进制、薄静态库引用的 263 个对象和原生求解器补丁。示例的目标断言在给定界限内通过，退出码为 0。将最后的文件替换为 `tests\stage1\worker_violation.c` 会检出断言违反，PowerShell 的 `$LASTEXITCODE` 为 10。处理其他程序时按任务 YAML 选择 `--32` 或 `--64`、展开界限和性质。启动器接受 Windows 绝对路径和项目相对路径。

| 命令 | 读取或生成的结果 |
|---|---|
| `.\deagle-local.cmd smoke` | 重新建模并运行 Fibonacci、读写锁、订票三个版本对，分别使用 stock、F 和 TC。核对 18 次程序执行的性质、输入流、图、搜索轨迹以及 TC 的导入与命中记录。 |
| `.\deagle-local.cmd full` | 从新目录启动阶段 11C 完整矩阵、负向对照、多查询、原版 F0 复跑及独立证据审核，使用冻结补丁。 |
| `.\deagle-local.cmd check` | 重新审核 Git 中保存的阶段 11C 原始证据，包含发布清单、证明、原生导入及见证。 |
| `.\deagle-local.cmd replay` | 用阶段 6 控制器重放冻结的 `batch_total` 补丁，并运行独立全量和模型对照。可传入其他冻结病例的 `task.yaml`。 |
| `.\deagle-local.cmd shell` | 打开 Linux shell，变量 `$NATIVE`、`$F0`、`$SOURCES`、`$DEAGLE_WORKER` 指向本机工具或输入。 |

每次 `smoke` 和 `full` 会打印独立的输出目录。用资源管理器打开 `\\wsl.localhost\Deagle-Jammy\home\deagle\deagle-runs` 即可查看。迁移验收包括[快速复跑](../reports/local-runtime/smoke.json)、[源码重编译比对](../reports/local-runtime/rebuild.json)、[辅助工具](../reports/local-runtime/auxiliary.json)、[完整运行核验](../reports/local-runtime/full-verification.json)和[跨主机逐项比较](../reports/local-runtime/release-comparison.json)。

## 代码和数据在哪里

| 位置 | 内容 |
|---|---|
| Windows 工程、Git 分支 `local-runtime-11c` | 历次研究代码、冻结病例、补丁、证据和本机启动器。 |
| Linux `/home/deagle/project` | ext4 上的实验项目，有历史脚本需要的 `third_party`、`.venv` 和冻结输入链接。 |
| Linux `/home/deagle/native-source-11c` | 可编辑、可重编译的完整原生源码，包括 `src`、`minisat-2.2.1` 和实际用于 11C 的 `worker-11c`。见 [GitHub 原生源码](https://github.com/ChenKaichen-SCUT/Deagle_incremental_execution/tree/74e652ea7b76ec4e5d3fd5db40cf95784dbf600d)。 |
| Linux `/home/deagle/runtime`、`/home/deagle/build-11c` | 已校验的历史工具和前端、Python 环境、冻结前端依赖，以及本机编译的 11C 工作进程。 |
| Windows `runtime\local` | Git 管理的原生 Git 对象、构建输入、实验二进制、许可和哈希。见 [包清单](../runtime/local/lock.json)。 |
| Windows `runs\local-runtime` | 本机备份。含完整项目 Git bundle、89 个 Python wheel 的离线包、额外历史工具和服务器实验源码副本，以及本机注册发行版的 `wsl-jammy\ext4.vhdx`。这个目录需随本机环境保留。 |

Git 备份可在 PowerShell 中独立核验。从它克隆到一个新目录即可取得本机运行分支。完整本机复跑的导出证据另存于 `runs\local-runtime\local-11c-evidence.zip`，备份文件的校验值在同目录的 `backup-index.json`。

```powershell
git bundle verify .\runs\local-runtime\project.bundle
git clone --branch local-runtime-11c .\runs\local-runtime\project.bundle ..\Deagle-restored
```

独立源码分支从完整的固定 Deagle 树导出，同时保留前端所链接的 MiniSAT 和实验 worker 的实际翻译单元。要在当前电脑修改原生代码，在 Linux 中运行以下命令。

```bash
cd ~/native-source-11c
make -C src -j4 cbmc.dir
bash worker-11c/build.sh
src/cbmc/deagle_exe --version
```

本机从源代码编译的前端与 worker 的二进制哈希和冻结产物不同。用这两个重编译产物对六个程序版本重做后，退出码、逐条性质、原始求解输入、理论图、worker 答案、搜索轨迹与实际子句使用记录均与冻结工具链的本机复跑一致。正式复现入口继续使用锁定前端。完整矩阵的正确性检查不依赖两次编译产生相同的二进制字节。

阶段 6 的 mini-SWE-agent 已安装在 `~/runtime/venv`。本机检验了冻结修复输入、隔离命令及提交补丁的过程，迁移中模型请求为零。日常回归使用冻结的候选。以后执行在线生成须使用可信控制器的 `--key-stdin` 和既有的输入摘要授权，操作见[阶段 6 报告](../reports/stage-06.md)。审核记录与代码均不需要携带凭据。

## 在另一台 Windows 机器重装

先安装能运行 x86-64 Linux 的 WSL2，并克隆 `local-runtime-11c` 分支。下面示例在项目目录执行。把 Jammy 官方的 `ubuntu-base-22.04.5-base-amd64.tar.gz` 放在 `runs\local-runtime\admin`。本机用 Ubuntu 签名清单验证的 SHA-256 为 `242cd8898b33ea806ef5f13b1076ed7c76f9f989d18384452f7166692438ff1a`。[Ubuntu 官方镜像及签名](https://cdimage.ubuntu.com/ubuntu-base/releases/22.04/release/) · [微软 WSL 导入说明](https://learn.microsoft.com/en-us/windows/wsl/use-custom-distro)

```powershell
$base = '.\runs\local-runtime\admin\ubuntu-base-22.04.5-base-amd64.tar.gz'
if ((Get-FileHash $base).Hash -ne '242cd8898b33ea806ef5f13b1076ed7c76f9f989d18384452f7166692438ff1a') { throw 'Ubuntu image hash mismatch' }
New-Item -ItemType Directory -Force .\runs\local-runtime\wsl-jammy | Out-Null
wsl --import Deagle-Jammy .\runs\local-runtime\wsl-jammy $base --version 2
wsl -d Deagle-Jammy -u root --cd "$PWD" --exec bash scripts/local/provision.sh
wsl --terminate Deagle-Jammy
wsl -d Deagle-Jammy -u deagle --cd "$PWD" --exec bash scripts/local/setup.sh
.\deagle-local.cmd doctor
.\deagle-local.cmd smoke
```

`provision.sh` 在专用 Jammy 中安装系统包并建立实验用户，首次安装需要 Ubuntu 软件源。若已将本机 `runs\local-runtime\packages\mini-wheels.tar` 一并复制，`setup.sh` 从本地安装并逐个核对 wheel，否则从公共 Python 包源按锁下载。可选的 `tool-sources.tar.gz` 提供早期评估的 Liss、Yogar、ConRepair 源码。它们的支持范围和排除原因见[阶段 2 工具评估](../reports/stage-02.md)。

完整原生源也可以从 GitHub 单独克隆。在这台机器上还可以通过本地 Git bundle 恢复对应分支。历史实验的薄静态库需与归档中列出的每个对象同目录还原，`restore.py` 已实现此步骤。冻结观察器在个别对照中会向 Linux 根目录输出 `visits.json`，本机启动器为它提供普通用户拥有的临时根目录。核验的多查询对照保留原来的三个查询、4 GiB 地址空间限制和 180 秒超时。

在 32 MiB 负向测试中，Jammy 默认的 Python 分配器偶尔会在报告 `MemoryError` 时再次耗尽内存。启动器仅对负向测试脚本指定 CPython 的 `malloc` 分配器和固定哈希种子。原解析器在相同限制下连续 128 次返回预期的拒绝记录。

与服务器的 216 次版本执行比较，模型输入、理论图、求解搜索轨迹、性质和退出码相同。跨工作目录的事件标签按原生端点核对一一映射。部分 SAT 输出在同一排名内列出事件的次序不同，已逐一核对布尔赋值、事件排名、分组和独立重建的 SC 见证。[完整比较程序](../scripts/local/verify_full.py)

这次从 Windows 启动的完整运行位于 `/home/deagle/deagle-runs/full-lg9ScETt`，快速回归位于 `/home/deagle/deagle-runs/smoke-YPNv5Rd3`。完整运行导出目录包含本机逐次计时、原始日志、负向对照和原生证明对象。服务器原归档另外含 18 条早期试运行路径、两个调试日志和两个完成标记。
