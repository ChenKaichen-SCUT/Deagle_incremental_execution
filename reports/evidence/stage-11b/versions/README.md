# 版本与性质

| 组 | P0/P1 来源 | 性质及解释 |
|---|---|---|
| lock01、lock12 | 预实验 read_write_lock-2 的公开原版、冻结 AI P1、冻结 AI P2。锁审查注册表绑定相邻版本的完整编码与图。 | reach_error.assertion.1，ILP32、展开 4、检查 unwind。P0→P1 残错，P1→P2 目标有界通过。 |
| fib_updates_8 | 阶段 7 固定八轮程序、harness 与常量修补 | LP64、展开 10；两线程各八次更新，目标与展开见原 gamma。 |
| batch_retained | 阶段 7 固定的部分修复及原 harness | LP64、展开 4；独立全量与增量均应继续检出违反。 |
| stack | FM 归档的 pthread/stack_longest-1.i，人工增加成功出栈后的占用标志更新 | 保留原有 push/pop、两侧循环、数组容量、错误分支及互斥范围。记录指针处理拒绝，完整程序没有获得修复通过结论。 |
| ticket | FM 归档公开的 weaver/parallel-ticket-5.wvr.c 和 parallel-ticket-6.wvr.c | ILP32、展开 2；两版共同的原断言仍是检查 b。增加一个真实发布的工作线程，用于规模变化对照。 |

extra-pairs.json 和 diff 文件给出新增两对的源码和完整改动哈希。锁与原阶段 7 病例使用原固定版本，原始补丁无需重新生成。阶段 7 sources 可从归档恢复，每个被提交给正式求解的版本也保留了输入字节。读写锁 P0 使用 YAML 指定的原始 .i，P1/P2 使用预实验 versions 中的 .i。完整性质输出、各版本哈希、参数及独立 GOTO/SSA/SC 模型摘要可从 trials 与 raw 获取。[预实验冻结版本](../../../../cases/svcomp26/versions/read_write_lock-2) · [阶段 7 固定清单](../../stage-07/matrix.json) · [阶段 7 原始材料](../../stage-07/archive.json)
