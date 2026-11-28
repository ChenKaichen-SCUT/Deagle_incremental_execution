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

## D4.3-C 同次理论边界审计

默认构建及生产 compact 沿用 B 阶段命令。另取一棵干净的同提交源码树，执行 `make -C src -j7 D43C_AUDIT=1 cbmc.dir`，用此 ELF 运行 `scripts/run_d43b.py AUDIT_ELF OUTPUT --modes compact-audit`。两个构建使用各自的对象目录。审计构建在同时具有完整 Audit、dense 标签和边界输出的查询中，额外写出 `boundaries.bin.cert`。每个边界保留原生有序子句、实际 Audit 理由 ID、来源推理 ID、队列票号以及原始和 SAT 端标签。生产构建在预处理时移除这些观察点。

从仓库根目录可独立构建边界检查器。链接器只保留读库所需的对象节。

```sh
g++ -std=c++17 -O2 -ffunction-sections -fdata-sections -I src -I minisat-2.2.1 \
  dependency-reuse/d4/boundary43_check.cpp minisat-2.2.1/minisat/core/ProofStore.cc \
  -Wl,--gc-sections -o /tmp/boundary43-check
```

`scripts/audit_d43c.py` 将四例逐一对齐到冻结的 B 图和原生文字流；`scripts/control_d43c.py` 检查三种整模型置换；`tests/d43c/check.py` 从未损坏的原生夹具生成故障并核对具体拒绝原因；`scripts/gate_d43c.py` 汇总边界、准入、UsedLeaf、旧回归和生产检查。数据恢复、复核命令和固定提交见 [D4.3-C 报告](reports/D4.3-C.md)。

## D4.3-D 生产复用

从仓库根目录用 `make -C src -j7 cbmc.dir` 构建默认原生 ELF，用 `bash dependency-reuse/scripts/build43d.sh "$PWD" /tmp/compact-tools` 构建独立生产工具目录。P0 使用 `--d43-record` 和 B 阶段相同的身份清单，`scripts/run_d43d.py` 为其生成 D43D 生产封存回执。P1 使用 `--d43-load LIB --d4-mode reuse --d4-out OUT --d4-tools TOOLS --d41-identities`；`record-cold` 在相同 root boundary 完成相同验证和选择后跳过附着。每次准备全新的 OUT，其 `control43.json` 绑定指定 P0 回执的 SHA-256。生产库中的 `dense.bin` 和 `model.tsv` 与回执在一起。airline 的已认证源行对应还使用两版源码和冻结补丁。

`compact-structure` 接收原始 occurrence 的 UsedLeaf/overflow 标志及两份静态模型。输出 `input-matches.tsv` 给出完整 P1 永久子句的首个对应 occurrence；0 表示完整译出但缺少成员，−1 表示无法译全。读取旧组目录、校验整库并筛完所有出生后，worker 用一次重命名发布按出生序选择的 `ready.tsv`。P1 自己分配和监测导入子句。独立图检查器、历史映射和完整 Audit 均只在离线复核命令中使用。四例运行、回执、恢复与复核步骤见 [D4.3-D 报告](reports/D4.3-D.md)。
