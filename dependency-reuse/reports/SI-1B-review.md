# SI-1B-review · 稳定身份的有限离线诊断

**READY_FOR_REVIEW · PARTIAL_IDENTITY_COVERAGE**

审查基线为 `4ddaf2843f6f51f1d0621ef2fa155783d402dac2`，分支为 `codex/stable-model-identity`。离线复算程序与原始派生证据固定于 `d502b6e06f121e70cefe77c99ecfdcf7ba1bf327`。四例的 A 逐出生复现 D4.3-E 的 **395 条精确候选和 322 条 Compact 候选**。在 A 上加入经 SI-1B 认证的普通 Boolean 对应后，C 达到 **2,154 条精确候选和 2,060 条 Compact 候选**。三个真实 SAT→UNSAT 修复病例分别贡献 **77 条新增精确候选和 94 条新增 Compact 候选**。本次测量的是旧证明在给定映射下的逻辑准入潜力，原生求解、P1 导入、SAT、RUP 和 Closure 逐条重证调用均为 0。[分队列总表](evidence/si1b-review/summary.json) · [文件校验索引](evidence/si1b-review/files.json) · [阶段状态](SI-1B-review-status.json)

## 四个审查问题

1. **3,679 个新增 UsedLeaf 对应能支持多少新出生？** C 相对 A 增加精确 **1,759**、Compact **1,738**。C 共增加 5,694 个带符号对应。逐条检查新出生后，所需的新结论位和新证明叶位全部位于那 3,679 个实际 UsedLeaf 原子中。所有恢复的 Boolean 槽也由其中的对应解释，A 与 C 的逐声明理论判定完全一致。其余 2,015 个对应对这些新增出生均非必要。这项归因来自已固定映射的叶、结论和同槽成员见证。两个计数描述不同准入集合，不能相加。[见证归因](evidence/si1b-review/summary.json)
2. **有多少来自真实修复？** 三个修复新增 403 个 UsedLeaf 对应。Fibonacci 贡献精确 76、Compact 94，airline 贡献精确 1、Compact 0，circular-buffer 两项均为 0。Fibonacci 的 94 条里有 18 条在 A 下已经精确合格，C 清除了其标签所碰到的其他失配成员。历史 `fib-snapshot-11` 单独贡献精确 1,682、Compact 1,644，新增均为纯 Boolean，继续标记 `INCOMPLETE_UNWINDING`。[新增出生及分组归因](evidence/si1b-review/summary.json)
3. **原有映射为何大量丢失？** 两类原因都有直接见证。circular-buffer 改写循环，SI-1B 将循环来源纳入执行实例键，导致本地已认证的读、写与 Guard 跨版键不同。历史 Fibonacci 则有大量本地表达式和编码角色已经记录，连接器却要求外层模板先获认证。单个无生产者的 Guard 可挡住完整的子表达式。指针对象编码、union 视图及同键多值又各有独立的拒绝条件。[循环事件诊断](evidence/si1b-review/circular-buffer/interface-summary.json) · [历史辅助原子诊断](evidence/si1b-review/fib-snapshot-11/loss-summary.json)
4. **有低成本改善的明确路径吗？** 有一个可做小范围验证的入口。历史 Fibonacci 的 81,127 个失去的辅助原子全部已有本地返回或角色值，75,719 个分配模板具有完整表达式，但缺少可认证的本地根路径。可以优先检查现有 Guard 生产者的来源，或让已经有独立、唯一认证依据的子模板获得自己的根。仍须认证双方的 owner、操作数、符号、位宽和角色唯一性。重用现有目录使这一路径有希望限制新增记录量，尚无其生产开销或净性能收益的实测结论。[逐原子记录](evidence/si1b-review/fib-snapshot-11/lost-atoms.tsv.gz) · [两侧原生模板核对](evidence/si1b-review/fib-snapshot-11/historical-frame-check.json)

## 固定映射与原生坐标

A 读取 D4.3-E 所有三轮均一致的真实带符号映射。B 独立读回封存的 SI-1B 直接映射，对全部 42,149 个对应解析两侧完整类型键及带符号原生端口。C 保留 A 的全部键、映像和极性，仅接受 B 中通过端口回读、且两端均为普通 Boolean 的新提案。两端分别检查原生 EDGE、Guard、CO、接口别名和逆映射。理论声明对三组均用同一套冻结的静态事件与来源认证器，传入的变量绑定分别是各自的 μ。B 的绑定表只来自 SI-1B。[映射与边界检查器](../scripts/si1b_review_space.py) · [独立端口检查器](../scripts/si1b_witness.py)

| 病例 | A 映射 | B 映射 | B 与 A 同符号重合 | C 新增普通对应 | 其中 UsedLeaf | C 映射 |
|---|---:|---:|---:|---:|---:|---:|
| fib_updates_8 | 10,416 | 8,953 | 8,705 | 248 | 245 | 10,664 |
| circular-buffer | 37,067 | 473 | 473 | 0 | 0 | 37,067 |
| airline_reservations_6 | 15,310 | 3,319 | 2,737 | 582 | 158 | 15,892 |
| fib-snapshot-11（历史） | 191,450 | 29,404 | 24,540 | 4,864 | 3,276 | 196,314 |

四例合计 36,455 项已由 A 同符号覆盖，5,694 项新增提案通过。正向冲突、反向占用、极性冲突和理论接口覆盖各 0 项。每一项 B 提案均保留 A 映像、当时的逆向占用者、类型键和处置。SI-1B 直接连接阶段拒绝的原子有自己的逐原子原因，未作为 C 的候选提案。C 的结果以已知 A 为条件。独立稳定身份方案的实际覆盖由 B 列给出。[四例组成账本索引](evidence/si1b-review/files.json) · [直接身份的原始处置](evidence/si1b/scope-summary.tsv)

八个首查询边界逐一核对原生分配流、带符号命名端口、永久输入的内容及出现位置、门、已安装理论图、查询边界与静态模型指纹。每个 P0 的 Audit 原始叶按原始文字与作用域逐 occurrence 核对，每条出生按原生 Audit ID 核对，永久出生再逐文字对齐 Compact 结论。Audit 的安装图回执与本轮重新构造的声明图逐字节一致。SI-1B 的原生影子文件还独立核对实际安装的 RF 端点、Guard 及所有 244,714 个命名 Boolean 端口行。[坐标核对代码](../scripts/si1b_review_space.py) · [影子端口核对代码](../scripts/si1b_review_detail.py) · [Fibonacci 的原始坐标收据](evidence/si1b-review/fib_updates_8/wire-coordinates.json)

历史 P0 的 **74** 个查询辅助变量采用 D4.2 已认证的默认编码→manifest 双射。1,001,471 条永久输入在原 occurrence 上相等，722 条查询输入在置换后保持完整多重集合，175,376 个门在置换后保留定义、输出极性、操作数和重数。原生门顺序确有差异。74 个编号与真实映射、理论端口、UsedLeaf 和可导出结论交集全部为空。历史 P1 的置换大小为 0。其余六个边界直接通过原坐标核对。查询限定和未知出生始终不能准入。[实际置换及八边界检查结果](evidence/si1b-review/fib-snapshot-11/results.json) · [历史置换原件](evidence/d42/encoding.json)

## 按实际支持重算

每个 μ 单独翻译旧 UsedLeaf 对应 occurrence 的全部带符号文字，在 P1 永久输入中查整条子句，并记录目标 occurrence。对理论声明重新核对事件、RF/Guard 绑定、地址、候选写域、原子块及规则配置。由各臂自己的失败前提构造 DirtyB 和 DirtyT。精确判定沿封存的完整 Audit 父边传播，在同一 μ 下再用冻结的离线 `select42 semantic` 独立核对。所有出生的精确准入结果一致，Compact 超出精确集合的出生数为 0。四个病例均未溢出 Dense 槽。[前提和准入复算](../scripts/si1b_review.py) · [独立 Audit 读取与传播](../scripts/si1b_review_proof.py)

下表的 UsedLeaf 原子取实际 Boolean 子句变量与实际 RF/Guard 声明端口的并集。输入按 occurrence 计数，声明按封存的原子声明计数。结论为完整永久学习结论的带符号全译数。最后两列依次为纯 Boolean、混合 CDCL、纯理论的逻辑准入数，均在 512 条选择上限之前。

| 病例 | μ | UsedLeaf 原子匹配 / 总数 | Boolean 前提保持 / 实用 | 理论声明保持 / 实用 | 完整结论可译 / 永久出生 | 精确 B / M / T | Compact B / M / T |
|---|---|---:|---:|---:|---:|---:|---:|
| fib_updates_8 | A | 6,515 / 8,062 | 8,382 / 12,858 | 779 / 851 | 956 / 1,307 | 31 / 282 / 0 | 31 / 264 / 0 |
| | B | 5,629 / 8,062 | 8,385 / 12,858 | 753 / 851 | 1,006 / 1,307 | 55 / 334 / 0 | 55 / 334 / 0 |
| | C | 6,760 / 8,062 | 9,847 / 12,858 | 779 / 851 | 1,015 / 1,307 | 55 / 334 / 0 | 55 / 334 / 0 |
| circular-buffer | A | 8,860 / 36,467 | 6,385 / 35,367 | 4,692 / 6,414 | 146 / 188 | 20 / 22 / 0 | 7 / 4 / 0 |
| | B | 172 / 36,467 | 67 / 35,367 | 2,577 / 6,414 | 0 / 188 | 0 / 0 / 0 | 0 / 0 / 0 |
| | C | 8,860 / 36,467 | 6,385 / 35,367 | 4,692 / 6,414 | 146 / 188 | 20 / 22 / 0 | 7 / 4 / 0 |
| airline_reservations_6 | A | 8,140 / 31,858 | 8,343 / 33,230 | 801 / 2,248 | 2 / 41,800 | 0 / 0 / 0 | 0 / 0 / 0 |
| | B | 1,707 / 31,858 | 870 / 33,230 | 594 / 2,248 | 0 / 41,800 | 0 / 0 / 0 | 0 / 0 / 0 |
| | C | 8,298 / 31,858 | 8,506 / 33,230 | 801 / 2,248 | 3 / 41,800 | 1 / 0 / 0 | 0 / 0 / 0 |
| fib-snapshot-11（历史） | A | 100,348 / 105,940 | 120,203 / 138,446 | 13,378 / 13,534 | 19,416 / 54,606 | 40 / 0 / 0 | 16 / 0 / 0 |
| | B | 22,360 / 105,940 | 19,897 / 138,446 | 13,376 / 13,534 | 25,463 / 54,606 | 44 / 0 / 0 | 7 / 0 / 0 |
| | C | 103,624 / 105,940 | 135,523 / 138,446 | 13,378 / 13,534 | 54,382 / 54,606 | 1,722 / 0 / 0 | 1,660 / 0 / 0 |

永久记录实际用过的证明祖先是 UsedLeaf 的子集。比如 airline 的 17,411 条永久证明 Boolean 基础 occurrence，在 A、B、C 下分别保持 1,837、407、1,993 条。全部原生出生数依病例顺序为 1,442、343、42,244、108,788，共 152,817 条，其中 97,901 条永久。每种 μ 的永久证明祖先数、已改变／未知／完整可译但 P1 不含该子句的处置，以及两域的实际 Dirty 位均已列出。[Fibonacci](evidence/si1b-review/fib_updates_8/results.json) · [circular-buffer](evidence/si1b-review/circular-buffer/results.json) · [airline](evidence/si1b-review/airline_reservations_6/results.json) · [历史对照](evidence/si1b-review/fib-snapshot-11/results.json)

## 新增与退役的出生

| 队列 | B 相对 A 新增精确 / Compact | B 相对 A 退役精确 / Compact | C 相对 A 新增精确 / Compact | C 相对 A 退役 |
|---|---:|---:|---:|---:|
| fib_updates_8 | 76 / 94 | 0 / 0 | 76 / 94 | 0 |
| circular-buffer | 0 / 0 | 42 / 11 | 0 / 0 | 0 |
| airline_reservations_6 | 0 / 0 | 0 / 0 | 1 / 0 | 0 |
| fib-snapshot-11（历史） | 37 / 7 | 33 / 16 | 1,682 / 1,644 | 0 |
| 合计 | 113 / 101 | 75 / 27 | 1,759 / 1,738 | 0 |

真实修复的 C 增量中，精确为纯 Boolean 25、混合 52，Compact 为纯 Boolean 24、混合 70。历史 C 的 1,660 条 Compact 逻辑合格，按冻结顺序应用 512 条上限时可选 512 条。真实修复三例的 C 逻辑合格数均在上限内。历史使用回执未参与构造映射、准入、排序或归因。[按病例、家族和选择上限统计](evidence/si1b-review/summary.json)

- **Fibonacci，出生 901，Audit ID 70462，混合。** P0 原子 2596 的正映像为 P1 文字 4200。两侧真实 `adder-carry` 端口给出文字 5192 和 4200，类型键 27729。完整证明访问 33 个 DAG 节点，需要 13 个实际 Boolean occurrence 和 11 项理论声明，包含两个 RF 绑定、事件模式、同址关系、块证书及规则配置。C 保留全部支持并清除 Boolean 槽 17。该槽在 A 下有 1,465 个不保持的成员。另有 18 条混合出生属于只恢复 Compact 的情形，逐条账本链接到槽内所有修复成员及其身份见证。[完整新增证明](evidence/si1b-review/fib_updates_8/gains.jsonl.gz) · [槽成员与新身份](evidence/si1b-review/fib_updates_8/slot-repairs.jsonl.gz)
- **airline，出生 41890，Audit ID 2506519，纯 Boolean。** 旧结论 `[49341,18574,18572,18580,19927,19973]` 翻译为 `[36225,13430,13428,13436,13503,13549]`。13 个基础 occurrence 均找到完整 P1 子句，其中 8 个在 A 中无法翻译。9 个新原子对应均有原生见证，包括比较前缀键 23190。精确准入后，Compact 仍因 Boolean 槽 31 的 3 个成员和槽 92 的 7 个成员退役，其中分别包括 occurrence 10947 和 38459。[完整证明及退役成员](evidence/si1b-review/airline_reservations_6/gains.jsonl.gz) · [原生端口](evidence/si1b-review/airline_reservations_6/added-witnesses.tsv.gz)
- **历史 Fibonacci，出生 2，Audit ID 1084750，纯 Boolean。** 旧结论 `[9371,9434]` 由两个实际 Boolean occurrence 支撑。对应由 `compare-prefix` 键 110395 和返回端口键 110394 分别认证。两版文字编码恰好相同仍须回读两端见证。C 精确准入，Boolean 槽 14 的其他 52 个不保持成员继续阻止 Compact 准入。[该例逐出生记录](evidence/si1b-review/fib-snapshot-11/gains.jsonl.gz) · [新增身份读回](evidence/si1b-review/fib-snapshot-11/added-witnesses.tsv.gz)
- **circular-buffer。** B 无完整可译的永久结论。C 与 A 逐出生相同，保留 42 条精确及 11 条 Compact。[全部出生](evidence/si1b-review/circular-buffer/births.tsv.gz)

## 丢失对应的直接原因

**循环执行实例和理论端口。** circular-buffer 有 2,115 个 A 已认证的 RF、124 个 Guard 未被 B 恢复。2,107 个 RF 和全部 124 个 Guard 在两侧都有本地已认证的事件。对每个旧原子比较完整带符号接口，2,239 项都存在缺失或差异。对 RF，1,939 项的第一处差异位于调用者的循环元组，168 项位于当前循环元组，另 8 项缺少内部事件的声明／对象路径。Guard 的两类循环差异分别为 110 和 14 项。原子 406 的 Guard `m#5` 在两侧均为文字 812，但事件键为 3424 和 41391。原子 44275 的 RF 在写端 `first#1` 的键相同，读端 `first#3` 却为 3850 和 41827。原子 854 的循环回边在 P0 `program.i` 第 724 行和 P1 第 725 行，迭代数都为 0，但循环来源键 2661 和 40870 不同。补丁把 `i` 控制的循环改为 `attempt` 控制，并把 `i++` 移入条件体。直接身份按其既定定义保守拒绝这次绑定。相同变量编号、相同事件名称或相同迭代数不能消除该差异。[循环补丁](../bench/circular-buffer/patch.diff) · [逐事件的第一处键差异](evidence/si1b-review/circular-buffer/interface-divergences.jsonl.gz) · [实例键入口](../scripts/si1b_catalog.py#L145) · [RF / Guard 安装入口](../../src/solvers/sat/satcheck_minisat2.cpp#L549)

**来源和执行实例缺项。** circular-buffer 原子 44191 的 RF 引用了 `__CPROVER_next_thread_id#1` 等内部事件，SI 源目录缺少该基对象的声明。airline 的 207 个旧 RF 损失中，188 个只涉及声明／对象路径，7 个只涉及执行实例，12 个同时涉及两者。Fibonacci 还可定位到 `left#2` 的执行上下文 77，首个缺失来源为 `harness.c` 第 40 行断言的 token。生成的事件、隐藏 Guard、动态实例或派生角色需要各自的来源证据。[airline 逐端点记录](evidence/si1b-review/airline_reservations_6/lost-theory-ports.jsonl.gz) · [Fibonacci 来源见证](evidence/si1b-review/fib_updates_8/loss-examples.json) · [生产者认证入口](../scripts/si1b_catalog.py#L173)

**外层 `all(values)` 和缓存模板根。** 历史 81,127 个辅助原子中，5,408 个分配模板本身有未认证子表达式，75,719 个的本地表达式完整但缺少可认证根路径。用 A 仅定位对侧分配帧后，这 75,719 个均有两侧一致的完整类型表达式，且可追溯到 owner 有效、外层表达式失败的根。73,112 个还具有相同的单值角色与相符极性的原生文字。这些见证用于定位级联损失，未生成第四组映射。81,127 个原子全部能在分配模板的返回或角色值中找到。只有 216 个按连接器主原因落入 `CACHED_INTERNAL_ORIGIN_MISSING`，其余 80,911 个为 `UNCERTIFIED_OWNER_RECIPE_OR_PEER`。73,112 个由历史分配观察点 `solvers/sat/cnf.cpp:334` 的等式路径产生。原子 25502 在帧 9457 已有完整等式 1630 和 `equal-bit` 第 0 位的有符号原生值 51005。其外层帧 9454 的 owner 12990、上下文 259 均有效，根 `and` 却因 `goto_symex::\guard#27` 等子项缺身份而未注册，连接停止于可认证子模板之前。`all(values)` 对完整复合表达式本身有语义作用。这里可避免的损失发生在完整子项被连带阻断的路径上，修复需要独立认证入口。[原子与模板实例](evidence/si1b-review/fib-snapshot-11/loss-examples.json) · [全操作数检查](../scripts/si1b_catalog.py#L319) · [根注册](../scripts/si1b_catalog.py#L340) · [连接器的子模板门槛](../scripts/si1b_join.py#L156)

**原生端口、指针和别名。** `cnf_result` 只在当前布尔表达式与门操作匹配时登记门返回值，位向量另靠带位号的角色。`named` 会把无可认证 lane 的实际别名记为阻断，理论端口缺键也会阻断普通提案，连接器再把同一冲突分量上的歧义传播给所有成员。实际 UsedLeaf 中，circular-buffer 有 10,648 个布局拒绝，其中 10,368 个带 union 标签、280 个为指针。airline 对应为 6,679 和 336 个。原子 42880 是 circular-buffer 的 `symex::args::0` 第 24 位，属于 32 位指针的对象编码区，两侧可比较的编号宇宙没有被认证。另有 1,034 个 circular-buffer 和 399 个 airline 的指针／聚合原子确实由 A 映射而 B 丢失，其直接原因均为缓存来源缺失。把它们全部归因于布局会误导优化。[实际端口登记](../../src/util/stable_identity.cpp#L267) · [布局与别名阻断](../scripts/si1b_catalog.py#L231) · [circular-buffer 的实际拒绝](evidence/si1b-review/circular-buffer/actual-blocks.json) · [airline 的实际拒绝](evidence/si1b-review/airline_reservations_6/actual-blocks.json)

**同键多值。** circular-buffer 的 783 个 UsedLeaf 辅助原子因同键多值被拒绝，它们原先也没有 A 对应。原子 9665 所在的帧 3905 在同一 `adder-carry` 角色、同一位 31 下发出了包括 19330、19512、19690 在内的 31 个不同实际文字。这样的键不能单独认证某一原子。冻结的别名控制另覆盖一对多、多对一、极性冲突、常量／变量变化和理论接口冲突。本次 C 提案集中这些冲突的实测数为零。[实际多值见证](evidence/si1b-review/circular-buffer/actual-blocks.json) · [连接器的冲突分量](../scripts/si1b_join.py#L163) · [原有控制](evidence/si1b/controls.json)

## 证据索引与复算

每例的 `births.tsv.gz` 保存全部出生的作用域、家族、Audit ID 和 A/B/C 判定。`boolean-leaves.tsv.gz` 中正数是匹配的 P1 永久子句 occurrence，`0` 表示可译但 P1 无该子句，`-1` 表示不可译。`theory-leaves.tsv.gz` 保留每个注册声明的实际使用位、永久祖先位和三组判定。`composition.tsv.gz` 覆盖每一项直接身份提案，`added-witnesses.tsv.gz` 给出双方带符号原生值、类型键及对应帧。[逐文件字节数与 SHA-256](evidence/si1b-review/files.json)

每个相对 A 新增精确或 Compact 准入的出生都在 `gains.jsonl.gz` 中，带有完整旧结论、翻译结论、所有实际 Boolean 叶及对应 P1 occurrence、所有理论叶、原先失败的前提、新身份键，以及仍阻断 Compact 的槽。`gain-attribution.tsv.gz` 用出生编号连接 `slot-repairs.jsonl.gz`，后者给出恢复同槽准入所需的全部旧失配成员及身份见证。所有压缩表均可流式读取。`lost-atoms.tsv.gz` 保存全部已失旧对应，含分配位置、实际使用位、局部表达式、模板可达性及原生阻断原因。[真实修复 Fibonacci](evidence/si1b-review/fib_updates_8/gain-attribution.tsv.gz) · [真实修复 airline](evidence/si1b-review/airline_reservations_6/gain-attribution.tsv.gz) · [历史对照](evidence/si1b-review/fib-snapshot-11/gain-attribution.tsv.gz)

以下命令在 Linux 的仓库根目录执行。`select42` 是冻结的离线证明图选择器。它读取完整旧 Audit、静态模型、给定映射和本轮重建的声明表。三条诊断脚本均不运行 Deagle。

```sh
set -eu
s=dependency-reuse/scripts
e=dependency-reuse/reports/evidence
t=$(mktemp -d)
python3 "$s/d43b_archive.py" restore "$e/d43d/raw" "$t/D"
python3 "$s/d43b_archive.py" restore "$e/d43b/raw" "$t/B" --prefix accepted
chmod +x "$t/D/offline-tools/select42"
python3 "$s/si1b_review.py" "$t/D" "$t/B/accepted" "$t/review" "$t/work"
python3 "$s/si1b_review_losses.py" "$t/D" "$t/work" "$t/review"
python3 "$s/si1b_review_summary.py" "$t/D" "$t/review"
cmp "$e/si1b-review/files.json" "$t/review/files.json"
```

阶段状态为 **READY_FOR_REVIEW**。本次交付仅含离线诊断、复算代码和已有证据的派生数据，后续阶段等待审查。
