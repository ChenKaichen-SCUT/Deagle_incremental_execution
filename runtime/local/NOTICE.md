# 原生运行包来源

正式项目依据阶段 11C 提交 `7d2d08ecbf6e643d3537131489ab6ba23c327c52`。清单记录每个迁移包的字节数和 SHA-256。恢复时还会核对早期发布锁中的 Git commit、tree、编译配置、可执行文件及输入散列。[迁移清单](lock.json) · [项目工具锁](../../configs/toolchain.lock.json)

| 文件 | 来源和用途 |
|---|---|
| `deagle-stages.pack`、`deagle-refs.json` | Deagle 上游浅克隆边界和五个本项目固定检出，含完整源码树。原始 Git 对象身份可恢复。核验时从阶段 10 补丁及所附源码覆盖恢复用于阶段 11C 的前端。 |
| `stage10-prebuilt.tar.gz`、`thin-members.tar.gz` | 冻结前端、F0、配置、静态库、源码覆盖及静态库引用的 263 个目标文件。成员的相对路径和哈希见 [thin-members.json](thin-members.json)。 |
| `stage11c-binaries.tar.gz` | 发布时的 worker 和辅助程序，配套源码在原生源码分支与项目中的阶段 11C 构建目录。 |
| `legacy-tools.tar.gz` | 阶段 3、4、5 的 Deagle，DAMER 可执行文件及 72 个冻结的实验输入文件。 |
| `damer-camc/`、`mini-swe-agent/` | 各工具的固定 Git 对象及引用。源树保留了上游许可证、版权声明及其附带文件。 |
| `historical-overlays.zip` | 对服务器八个项目目录的 1,150 条源码路径按内容去重，共 316 份。295 份已存在于项目 Git 历史，其余 21 份工作稿在此单独归档。每个成员的原始位置和 SHA-256 均有[记录](historical-overlays.json)。复现采用正式发布版。 |

Deagle 及其内含 CBMC 和 MiniSAT 的分发条款见许可原文。[Deagle 项目](https://github.com/thufv/Deagle) · [Deagle 和 CBMC 许可](licenses/Deagle-CBMC.txt) · [MiniSAT 许可](licenses/MiniSAT.txt)

DAMER 固定到 `c005ebbde3672fff77c6d91da2f91d1daa45d746`。mini-SWE-agent 固定到 `a83fcae82d2a08f0ee0c688f9d137b3566c097f8`。[DAMER 源码](https://github.com/shirleylee03/damer-camc) · [DAMER 许可](licenses/DAMER.txt) · [mini-SWE-agent 源码](https://github.com/SWE-agent/mini-swe-agent) · [mini-SWE-agent 许可](licenses/mini-SWE-agent.md)

Python 依赖的发行文件、版本和散列见[经核对的 wheel 清单](../../reports/evidence/stage-01/verified-wheels.json)。本机另存了可离线安装的 wheel 包和早期辅助研究工具源码。
