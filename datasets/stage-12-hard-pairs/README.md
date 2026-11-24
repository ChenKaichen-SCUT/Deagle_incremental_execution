# 在本地使用冻结的并发版本对

Windows 项目根目录为 E:\Deagle_incremental_execution。PowerShell 中运行以下命令，启动器会使用已经安装的 Ubuntu 22.04 WSL2 发行版 Deagle-Jammy、普通用户 deagle 和现有的冻结二进制。每次验证先校验性质文件、完整源码和二进制 SHA-256，两端分别冷启动并检查该版本全部原生性质。原生输出保存在命令打印的 WSL ext4 目录。以下操作可以断网执行。

~~~powershell
.\deagle-local.cmd doctor
.\deagle-local.cmd hard-pair circular-buffer
.\deagle-local.cmd hard-pair fib-snapshot-11
~~~

病例名称及分类见 [清单](manifest.json) 和 [表格](dataset.csv)。每个目录的 task.yaml 是合法的 YAML 1.2（采用 JSON 表示），带有完整原生命令、位宽和展开界限。old/new 目录各含原生实际使用的完整翻译单元和来源 YAML。新生成的版本沿用其父版本的原始 YAML，来源中的 expected_verdict 描述公开程序；每端实际结论见 baseline.json。还可从源码补丁重建 P1。当系统 Git 自动换行时，在独立目录对源码禁用换行转换，再以 -p1 应用 patch.diff。发布检查按字节重放了每一项补丁。[阶段报告](../../reports/dataset-preparation.md)

## 恢复公式、理论图与原始记录

在项目根目录运行以下示例。Python 恢复器仅使用标准库，逐卷核对压缩包，再检查文件内容哈希。一个病例的所有正式输入、独立结果和证据会写到指定的新目录。CNF 使用原生 s8-input.bin 的有序操作流；s8-graph.tsv 和 native-bindings.json 记录静态声明，bits.tsv、GOTO、SSA 和 full_model.json 记录语义绑定。search.bin 是真实搜索轨迹。后续实验可以直接从这些文件开始。

~~~powershell
python -B scripts/hard_pairs/restore_evidence.py runs/restored-stage12 --case fib-snapshot-11
python -B scripts/hard_pairs/check_delivery.py
~~~

在 Linux 下指定自己的验证二进制和输出目录也可以独立全量运行。此入口要求二进制 SHA-256 与冻结版本相同，默认配置使用每进程 7 GiB 地址空间，队列为宿主保留 1.5 GiB 可用内存。

~~~sh
python3 -B scripts/hard_pairs/replay.py datasets/stage-12-hard-pairs/circular-buffer /tmp/deagle-circular-buffer "$HOME/runtime/native/src/cbmc/deagle_exe" --host local-linux
~~~

完整服务器归档位于本机 runs/hard-pairs-admin/all-attempts.tar.gz，SHA-256 为 **2b60a268c4e2e60fc2e3be602a44218bd70f3b9e68d187c98c6083d61e3b8fde**。它比公开分卷另外包含探索阶段的完整诊断与搜索二进制。核对所有原始成员可使用下面的命令。脚本按每次尝试的收据逐项验证，只将发布分析需要的子集展开到工作目录。公开分卷里每份筛选输入都可以用 --prefix inputs/样本名 恢复。[原始归档收据](../../reports/evidence/stage-12/transfer.json) · [公开对象索引](../../reports/evidence/stage-12/raw/files.json)

~~~powershell
python -B scripts/hard_pairs/audit_transfer.py runs/hard-pairs-admin/all-attempts.tar.gz runs/hard-pairs-admin/checked-copy
~~~

## 源码、重建与研究边界

本机另存有 runs/hard-pairs-admin/stage-12-project.bundle，可在没有服务器和 GitHub 的情况下恢复本阶段分支、前置迁移分支和原生源码分支。其哈希和分支列表在同目录的 offline-backup.json 中。原有 runs/local-runtime 中的 WSL 环境包、早期 Git 归档和工具链也仍可用于重建。

~~~powershell
git bundle verify runs/hard-pairs-admin/stage-12-project.bundle
git clone -b stage-12-hard-pairs runs/hard-pairs-admin/stage-12-project.bundle E:\Deagle-restored
~~~

阶段 11C、此前构建补丁和本地离线依赖沿用原迁移。Windows 项目保有完整 Git 历史；完整 C++ 原生源码另外固定在 native-source-11c。原版、原生增强版、11C worker 以及本地重建及对照的证据见迁移文档。独立编译得到的可执行文件可能与正式计时用的冻结文件哈希不同，正式重放会检测这一差异。[迁移与构建说明](../../docs/local-runtime.md) · [完整原生源码](https://github.com/ChenKaichen-SCUT/Deagle_incremental_execution/tree/74e652ea7b76ec4e5d3fd5db40cf95784dbf600d)

正式数据以服务器串行运行作为难度分组。小型病例可作正确性控制；同一 Fibonacci 补丁的三个规模适合在完整新旧模型上研究有符号变量对应和冲突证明依赖。它们没有变更原可达性断言。严格小于的 Fibonacci 和第一次读写锁修补保留原断言反例。ticket 六到七线程属于规模对照。各自的 README、源码、SHA 和上下文位于病例目录。

本轮翻译单元来自 SV-Benchmarks 或 FM Artifact，各自保留其来源和归属。Fibonacci 原始源码注记为 Apache-2.0 AND GPL-3.0-or-later，环形缓冲区来源注明 SCTBench / ESBMC；Weaver ticket 附作者的 BSD 归属文本。保留的既有 SV-COMP 材料及其上游许可文本见 cases/svcomp26，历史 Fibonacci 源头和头文件位于阶段证据目录。[上游基准](https://gitlab.com/sosy-lab/benchmarking/sv-benchmarks) · [许可证文本](licenses) · [历史来源](../../reports/evidence/stage-12/historical-fib)
