# 九例独立全量与增量回归

阶段 9 每个病例均有带观察的独立 F1、实际 I3，另有相同条件下的阶段 8 对照。逐项重算 GOTO、原始 SSA、SC 输入及最终模型，将前缀分派与恢复后分派拼接后和独立全量访问顺序核对。每份理论证书重算上下文和有符号绑定，并读取原生导入回执。

| 病例 | P1 | 路径 | 跳过 / 步 | 执行 / 步 | 复用 PO/APO | 复用 RF | 审核通过 | 实际导入 | 回退原因 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| batch_total | NO_VIOLATION_WITHIN_BOUND | incremental | 60 | 13 | 18 | 4 | 1 | 1 | — |
| threshold_guard | NO_VIOLATION_WITHIN_BOUND | incremental | 61 | 23 | 20 | 4 | 0 | 0 | — |
| fib_updates_8 | NO_VIOLATION_WITHIN_BOUND | incremental | 95 | 144 | 28 | 12 | 14 | 14 | — |
| split_counter | NO_VIOLATION_WITHIN_BOUND | full_fallback | 0 | 156 | 0 | 0 | 0 | 0 | synchronization_calls_changed:record_one |
| airline_reservations_6 | NO_VIOLATION_WITHIN_BOUND | full_fallback | 0 | 467 | 0 | 0 | 0 | 0 | synchronization_calls_changed:reserve_seat |
| partial_counter | VIOLATION | full_fallback | 0 | 176 | 0 | 0 | 0 | 0 | synchronization_calls_changed:record_left |
| batch_retained | VIOLATION | incremental | 60 | 13 | 18 | 4 | 1 | 1 | — |
| fib_updates | NO_VIOLATION_WITHIN_BOUND | incremental | 95 | 88 | 28 | 12 | 7 | 7 | — |
| airline_reservations | NO_VIOLATION_WITHIN_BOUND | full_fallback | 0 | 323 | 0 | 0 | 0 | 0 | synchronization_calls_changed:reserve_seat |

所有旧程序都违反原目标。两类候选残错均从原生结果重建反例并核对保留的失败交错。具体次数见核验回执。

[模型及证书核验计数](verification.json) · [各模式有序求解输入](solver-inputs.json) · [负向控制](negative-results.json)
