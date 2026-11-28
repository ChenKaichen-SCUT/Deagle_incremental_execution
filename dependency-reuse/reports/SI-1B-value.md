# SI-1B-value · 已认证新增学习子句的搜索价值

**READY_FOR_REVIEW · 真实修复搜索价值门槛未通过**

**fib_updates_8 新增的 94 条子句中有 72 条实际命中，New 批次的搜索仍然变慢。** 命中的新增出生包括 24 条纯 Boolean 子句和 48 条混合子句。New 相对 Cold 的“批次读取＋导入＋搜索”耗时增加 **26.00%**，相对原 A 批次增加 **16.28%**。两个比较均为 **0/3 轮改善**。相对 A，决策减少 5,807 次，同时冲突增加 623 次、Boolean 传播增加 6,865,921 次。[逐轮配对差值](evidence/si1b-value/paired-baseline-minus-new.tsv) · [不同子句命中](evidence/si1b-value/batch-membership-use.tsv)

**历史 first512 也没有显示正搜索价值。** New 附着 512 条、实际使用 459 条。502 条仅在 New 中被选中的出生里有 456 条命中。相对 Cold 的配对中位耗时增加 **81.07%**，相对 A 增加 **67.72%**，均为 **0/3 轮改善**。原 A 独有的 6 条里，有 5 条在 A 臂确实被用过。历史结果单列为 `INCOMPLETE_UNWINDING`。[历史批次交集](evidence/si1b-value/frozen/fib-snapshot-11/seal.json) · [使用回执](evidence/si1b-value/native-imports.tsv.gz)

**当前数据给新增身份登记、库读写和 P1 身份准备留下的联合成本预算为 0 秒。** 真实修复按配对中位数已经对 Cold 多支出 **0.515 秒**、对 A 多支出 **0.348 秒**。即使三项新增成本都设为零，两个参照下的搜索账仍为负。历史对照对应多支出 **32.308 秒**和 **29.002 秒**。以前 SI-1B 在真实修复病例测得的双目录读取、连接至输出为 0.276 秒，未计入本轮任何一臂。按本次预注册工程门槛，结果不支持继续投入全面生产集成。局部模板根保留为既有诊断线索。[成本余额与门槛](evidence/si1b-value/summary.json) · [既有 SI-1B 成本数据](evidence/si1b/cost.tsv)

## 三轮配对结果

时间单位为秒。节省率采用 `(参照时间 − New 时间) / 参照时间`，按同轮配对后取中位数。验收要求真实修复相对 Cold 和 A 的中位节省率各至少 5%，且各有至少两轮改善。

| 病例 | 轮 | Cold 读取＋导入＋搜索 | A | New | New 对 Cold 节省率 | New 对 A 节省率 |
|---|---:|---:|---:|---:|---:|---:|
| fib_updates_8 | 1 | 1.953 | 2.135 | 2.483 | −27.15% | −16.28% |
| | 2 | 1.982 | 2.173 | 2.497 | −26.00% | −14.92% |
| | 3 | 1.993 | 2.148 | 2.503 | −25.55% | −16.49% |
| fib-snapshot-11 | 1 | 38.949 | 42.423 | 71.425 | −83.38% | −68.36% |
| | 2 | 39.916 | 43.062 | 72.224 | −80.94% | −67.72% |
| | 3 | 39.612 | 43.238 | 71.725 | −81.07% | −65.88% |

**工作量与原生结果。** 下表的原生计数各自在三轮重复中相同。两例所有诊断臂的导入期根 Boolean 传播、理论传播和根冲突均为 0，没有因根冲突提前结束的样本。Fibonacci 的根赋值前后均为 2,670，历史对照均为 1,617。历史 New 的 511 条附着子句发生过 allocator GC 重定位，回执继续按原生出生编号对应。[逐轮原生计数](evidence/si1b-value/runs.tsv) · [带分配引用的附着账本](evidence/si1b-value/native-imports.tsv.gz)

| 病例 | 臂 | 附着 / 不同子句命中 | 决策 | 含根冲突 | Boolean 传播 | 理论传播 | 理论环冲突 | 重启 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| fib_updates_8 | stock | 0 / 0 | 60,369 | 22,702 | 28,170,688 | 7,979 | 23 | 80 |
| | Cold | 0 / 0 | 60,369 | 22,702 | 28,170,688 | 7,979 | 23 | 80 |
| | A | 295 / 255 | 68,036 | 24,775 | 28,634,343 | 9,642 | 54 | 91 |
| | New | 389 / 329 | 62,229 | 25,398 | 35,500,264 | 9,791 | 42 | 92 |
| fib-snapshot-11 | stock | 0 / 0 | 388,360 | 130,707 | 158,011,347 | 445,118 | 34 | 354 |
| | Cold | 0 / 0 | 388,360 | 130,707 | 158,011,347 | 445,118 | 34 | 354 |
| | A | 16 / 9 | 380,387 | 127,484 | 165,654,004 | 376,332 | 58 | 346 |
| | New | 512 / 459 | 494,065 | 168,479 | 225,872,837 | 476,965 | 77 | 455 |

**子句如何参与搜索。** 下表为每轮真实使用计数，纯理论 T 三轮均为 0。真实修复 New 独有的 94 条合计产生 27,381 次 watcher 单位传播、47 次 watcher 冲突、9,481 次分析使用、6,696 次成功最小化使用。此前 295 条共同出生在 A 中命中 255 条，在 New 中命中 257 条。因而比较 A 和 New 测到的是加入新知识后的整条搜索轨迹，不能用命中数直接折算节省时间。[按家族回执](evidence/si1b-value/family-use.tsv) · [按批次成员回执](evidence/si1b-value/batch-membership-use.tsv)

| 病例 | 臂和家族 | 附着 / 命中 | 单位传播 | watcher 冲突 | 分析使用 | 成功最小化 |
|---|---|---:|---:|---:|---:|---:|
| fib_updates_8 | A · B | 31 / 31 | 13,649 | 25 | 4,095 | 3,160 |
| | A · M | 264 / 224 | 29,081 | 333 | 12,981 | 55,733 |
| | New · B | 55 / 55 | 25,477 | 31 | 8,323 | 6,544 |
| | New · M | 334 / 274 | 49,544 | 471 | 24,151 | 70,461 |
| fib-snapshot-11 | A · B | 16 / 9 | 756 | 0 | 25 | 2 |
| | New · B | 512 / 459 | 217,017 | 522 | 63,965 | 80,872 |

**完整 P1 时间与内存。** 下表各列独立取三轮中位数。诊断准备包含控制设置与整个准备器进程。原生导入列单列 `importAtRoot`。峰值 RSS 单位为 KiB。stock 的墙钟和 RSS 来自未修改进程，纯搜索时间来自轨迹核对通过的独立观察进程。真实修复相对 stock 的同轮完整墙钟中位差为 New 多用 0.792 秒，历史对照为多用 36.487 秒。诊断复用已封存知识，计时未计入新的生产身份登记或跨版本映射，因此本轮仅用于搜索价值判断。[原始计时与 RSS](evidence/si1b-value/runs.tsv) · [配对口径](evidence/si1b-value/paired-baseline-minus-new.tsv)

| 病例 | 臂 | 诊断准备 ms | 原生导入 ms | 纯搜索 s | P1 完整 s | 峰值 RSS KiB |
|---|---|---:|---:|---:|---:|---:|
| fib_updates_8 | stock | — | — | 1.902 | 2.007 | 29,184 |
| | Cold | 240.331 | 0.007 | 1.982 | 2.287 | 30,464 |
| | A | 231.280 | 0.439 | 2.148 | 2.446 | 29,312 |
| | New | 234.991 | 0.619 | 2.496 | 2.798 | 28,800 |
| fib-snapshot-11 | stock | — | — | 36.958 | 37.082 | 225,736 |
| | Cold | 1,096.432 | 0.007 | 39.612 | 41.160 | 274,900 |
| | A | 1,095.235 | 0.143 | 43.062 | 44.675 | 281,348 |
| | New | 1,097.288 | 1.211 | 71.723 | 73.307 | 299,360 |

**性质与展开义务。** 全部主实验原生退出码为 0。真实修复的 `main.assertion.1` 为 `SUCCESS / BOUNDED_PASS`。历史的 `reach_error.assertion.1`、`fib.unwind.0`、`t1.unwind.0` 和 `t2.unwind.0` 均报告 `SUCCESS`，保留原生的第 25 次展开停止记录及 `INCOMPLETE_UNWINDING` 分类。各臂的性质全集、展开记录、VCC 与可见反例集合均与同轮 stock 一致，两例本轮均没有失败性质的可见反例。18 个实际原生边界通过本例固定模型和批次检查，超出相应精确证明准入集的出生为 0。[性质与模型一致性检查](evidence/si1b-value/property-model-checks.json) · [阶段状态](SI-1B-value-status.json)

## 批次与模型边界

审查基线为 `85065a8729fe7547f56e7b55048a1222338d7ddf`。首次 P1 求解前，诊断计划、批次、轮换顺序与原生边界驱动已在 `644b3d9632ca547cecb533af5c9ef1b1871942bc` 封存。四个原生批次共享一个固定校验索引。circular-buffer 与 airline 的 Compact 批次沿用此前审查证据。本次 P0 求解次数为 0。[预注册计划](../configs/si1b-value.json) · [批次与模型摘要索引](evidence/si1b-value/frozen/batches.json)

| 病例 | A 逻辑合格 → 选中 | New 逻辑合格 → 选中 | New 选中家族 B / M / T | A 与 New 选中交集 | 仅 A / 仅 New |
|---|---:|---:|---:|---:|---:|
| fib_updates_8，SAT→UNSAT 修复 | 295 → 295 | 389 → 389 | 55 / 334 / 0 | 295 | 0 / 94 |
| fib-snapshot-11，历史对照 | 16 → 16 | 1,660 → 512 | 512 / 0 / 0 | 10 | 6 / 502 |

两例都从旧 P0 完整 Audit、Compact 库、实际带符号映射和 P1 永久模型重新推导准入。复算器核对原生出生编号、Audit ID、旧结论、翻译文字及家族，逐条与相同 μ 下的独立精确选择器对照。fib_updates_8 的 B 与 C 全部 389 条及其顺序相等，New 使用 B。历史 New 使用 C，按出生顺序取前 512 条。原 A 中的出生 54669、82921、82922、99037、99038、100970 在 C 逻辑池中的排名依次为 1,233、1,472、1,473、1,596、1,597、1,612。第 512 名是出生 15598。完整逻辑池与实际选中池都已保存。[Fibonacci 映射与批次收据](evidence/si1b-value/frozen/fib_updates_8/seal.json) · [历史映射与批次收据](evidence/si1b-value/frozen/fib-snapshot-11/seal.json) · [复算入口](../scripts/si1b_value_freeze.py)

诊断使用 D4.3-E 已冻结的原生 ELF 和 `ClauseImports`。P1 完成自己的原始输入、变量分配和 Closure 静态图后，第一次查询的原生 root boundary 调用独立诊断准备器。它核对实际父进程的二进制、参数、CPU、内存限额、工作目录内的源文件，以及当前首查询的完整规范模型。永久 B 子句、Q 子句、门、带符号端口、已安装图和查询边界还有各自的有序摘要。模型规范化沿用已审计的规则，处理工作目录、项编号与无序提示。每个诊断臂都校验本例的 A、New 两个固定批次。Cold 将 New 批次送入原生 `record-cold` 检查模式，A 和 New 使用原生 `reuse` 模式。全部原生记录器保持关闭，实验使用已经认证的身份知识。[诊断边界入口](../diagnostics/si1b-value/d43_prepare.py) · [模型校验](../scripts/si1b_value_boundary.py) · [故障拒绝回执](evidence/si1b-value/preflight-controls.json)

Fibonacci 的 P1 首边界为 12,058 个原生变量槽、45,757 条永久输入、2,572 条查询输入、686 行静态图记录。历史 P1 对应为 200,370、1,001,473、722、8,174。真实修复使用 LP64、20 GiB、300 秒上限，历史对照使用 ILP32、7 GiB、660 秒上限。全部诊断臂分别匹配本例的同一个完整模型。[真实修复模型](evidence/si1b-value/frozen/fib_updates_8/seal.json) · [历史模型](evidence/si1b-value/frozen/fib-snapshot-11/seal.json)

## 计量口径

三轮均固定 Linux 逻辑 CPU 0，每次启动独立进程，按原病例锁定源文件、性质、SC、ABI、展开界与资源限制。每轮先做真实修复，再做历史对照。四臂执行顺序依次为 `stock / Cold / A / New`、`A / New / stock / Cold` 和 `New / A / Cold / stock`。24 次主实验结束后另外串行执行 6 次 stock 计时观察器，对齐同轮未修改 stock 的性质、可见见证及确定性轨迹。stock 整体验证时间、工作量与 RSS 直接取自主实验的未修改进程。stock 搜索时间和重启数单独来自观察器。[运行驱动](../scripts/si1b_value_run.py) · [完整原始数据索引](evidence/si1b-value/raw/files.json)

主指标为同进程的 **原生批次读取 + 原生导入 + CDCL 搜索**。原生导入计时涵盖 `importAtRoot` 内的根传播与可能的提前冲突。逐轮表另外给出不含批次读取的导入加搜索、纯搜索、准备器全过程、控制文件设置、到首查询的时间、进程墙钟和峰值 RSS。诊断完整验证时间为控制设置加整个 P1 进程墙钟，包含建模、准备和输出。另列从控制器开始（包含夹具复制与校验）至原生进程退出的一致口径。各阶段墙钟均来自单次实际运行。工作量使用最终原生累计值，导入期间已经计入的根传播只计一次，遗漏于原生冲突计数器的根冲突则补回。[逐轮计时与工作量](evidence/si1b-value/runs.tsv) · [配对差值](evidence/si1b-value/paired-baseline-minus-new.tsv)

每条导入子句保留原始出生编号、家族、翻译结论、实际附着文字、根缩短／满足、分配引用及 GC 变化。不同子句命中由真实 watcher 单位传播、watcher 冲突、作为冲突分析父句或成功最小化四类回执确认。相同子句的不同使用类型分别计数，不同子句合计只计一次。按出生编号可区分共同批次、仅 A 与仅 New 的贡献。[全部附着回执](evidence/si1b-value/native-imports.tsv.gz) · [首次使用与对应 Clause](evidence/si1b-value/first-uses.tsv.gz) · [B/M/T 分类](evidence/si1b-value/family-use.tsv) · [共同与独有出生](evidence/si1b-value/batch-membership-use.tsv)

## 离线复算

从仓库根目录在 Linux 下运行以下命令，可恢复原始模型、标准输出、原生工作量、逐条导入与命中事件，并重算逐轮与配对表。下面的复算只读取封存数据。

```sh
set -eu
s=dependency-reuse/scripts
e=dependency-reuse/reports/evidence
t=$(mktemp -d)
python3 "$s/d43b_archive.py" restore "$e/si1b-value/raw" "$t/raw"
python3 "$s/d43b_archive.py" restore "$e/d43d/raw" "$t/D"
python3 "$s/si1b_value_analyze.py" "$t/raw/matrix" "$t/D" "$t/summary"
for f in "$t/summary"/*; do cmp "$f" "$e/si1b-value/$(basename "$f")"; done
```

也可从封存的完整证明复算批次，再与本次固定批次逐字节比较。

```sh
python3 "$s/d43b_archive.py" restore "$e/d43b/raw" "$t/B" --prefix accepted
chmod +x "$t/D/offline-tools/select42"
python3 "$s/si1b_value_freeze.py" "$t/D" "$t/B/accepted" "$t/offline" "$t/frozen"
diff -qr "$t/frozen" "$e/si1b-value/frozen"
```

完整恢复校验覆盖 426 个原始文件、294,807,981 字节。由恢复文件重算的 8 份结果与账本逐字节一致，重新读取全部旧 Audit 和 Compact 后生成的两例批次也逐字节复现。原始证据与分析程序固定于 `d12c7076395aa99e0daa45d4e5b547f2dbaec05c`。[证据索引](evidence/si1b-value/files.json) · [复算回执](evidence/si1b-value/replay.json)

本阶段停在 **READY_FOR_REVIEW**，等待审查。
