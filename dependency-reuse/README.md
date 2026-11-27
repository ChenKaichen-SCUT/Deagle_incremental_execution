# D4.3-B 原生 P0 记录

从仓库根目录执行 `make -C src -j7 cbmc.dir`。可执行文件为 `src/cbmc/deagle_exe`。以下开关加在四例各自固定的原生参数之前。模型清单使用 `--d1-manifest DIR/model.tsv --d3-layouts --d41-identities`。每次运行使用独立的空输出目录。

| 模式 | 清单基础上的附加参数 |
| --- | --- |
| off | 无 |
| audit | `--d3-proof DIR/proof.bin --d41-triplets` |
| light42 | `--d3-proof DIR/proof.bin --d41-triplets --d42-light` |
| compact | `--d43-record DIR/dense.bin` |
| compact-audit | `--d43-record DIR/dense.bin --d3-proof DIR/proof.bin --d41-triplets` |

`--d43-boundaries DIR/boundaries.bin` 顺序记录 SAT 边界的原生理论子句及 CDCL 出生，用于比较两个运行。Light 的 `--d43-no-quality` 关闭 P0 质量统计。Light 或 compact 的诊断开关 `--d43-opaque-theory` 保留原生 Closure 推理和理由，关闭理论依赖采集。诊断与生产分别计费。

`scripts/run_d43b.py BINARY NEW_DIRECTORY` 运行固定四例，保存完整命令、输入和 ELF 摘要、性质及展开结果、确定性计数、时间、RSS 和封存回执。生产库包含模型清单、稠密目录、单调 UsedLeaf 位图及永久出生的有符号结论和标签。作用域受限的出生仅占一个带序号和标志的处置记录。双观察模式另存 `dense.bin.scoped`，供审计所有出生使用。D43DNS2 的目录顺序就是 P0 的首次注册顺序，读取时验证完整键、位号、边界和封存哈希。

离线复算、同次 Audit 核对、夹具和证据恢复命令见 [D4.3-B 报告](reports/D4.3-B.md)。
