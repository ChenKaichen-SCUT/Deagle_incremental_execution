# 数据来源与冻结规则

论文第 6 节比较 Poct、Deagle 和 Theta。作者给出的上限为 900 秒和 24 GB。Poct 使用 Z3 User Propagator。本阶段的求解工作进程使用项目固定的原生 MiniSAT + ClosureSolver。原论文的 weak-SC 表格、作者归档中的 Deagle 和本项目固定的 Deagle 是三种不同证据。[FM 2026 论文](https://doi.org/10.1007/978-3-032-26204-2_26) · [作者归档](https://doi.org/10.5281/zenodo.18616443)

归档外层 2,615,597,088 字节，整包 MD5 与 Zenodo 记录相同。解压出的 Docker tar SHA-256 与作者 README 所列相同。读取镜像各层时找到了最终文件系统中已由 whiteout 隐藏的两张原始成绩表。两表各 1,063 项，键唯一且一致。按作者 run-fm26.py 的目录、YAML 与实际 input_files 重建 1,063 个任务键，逐一核对。层索引、历史文件位置、whiteout、脚本哈希和输入哈希见 selection.json。归档读取程序只解析数据文件。

两表只有 bench 和 runtime 两列。数字列是作者设置下的端到端秒数，Exception 等文本保留原值。作者 Deagle 分支对特定错误退出也会取得最后一行，但输出表只写时间。数字不能证明被验证性质或正确 verdict。作者 Deagle 命令含 --unwind 2 和 --allow-pointer-unsoundness。本项目使用 YAML 位宽、固定 Closure 并保留指针健全性和展开检查。两套时间只在各自配置下解释。

预选取任一工具端到端数值至少 10 秒的全部条目，得到 13 项，未查看本原型表现。另保留 butterfly、wsc、arithmetic_prog_bad，wsc 对 Deagle 使用作者指定的 wsc.rewrite.i。五线程 ticket 是六线程任务的同族规模参照。源码中的目标和所有假设保持原状。该对没有修复成功率含义。独立的 stack_longest-1 人工修补保留原性质与所有执行循环，失败的求解记录也进入报告。

Python 提取器保留原始 .i/.c 及 YAML 的字节。部分源码带各自的 SV-Benchmarks 版权说明，复现包与记录保留其出处。Weaver ticket 的代码头列出 F. Schuessele、D. Klumpp，许可证署名 Anthony Vandikas。项目随附 Apache 和 GPL 文本。[SV-Benchmarks 2025](https://gitlab.com/sosy-lab/benchmarking/sv-benchmarks/-/tree/svcomp25) · [Weaver 许可](../versions/LicenseRef-BSD-3-Clause-Attribution-Vandikas.txt) · [通用许可目录](../../../../cases/svcomp26)
