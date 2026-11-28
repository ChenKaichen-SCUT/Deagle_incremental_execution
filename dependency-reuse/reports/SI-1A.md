# SI-1A 原生变量来源、失配原因与稳定身份方案

**状态 `READY_FOR_REVIEW`。建议批准一个范围受限的 SI-1B 影子原型。** 优先覆盖带实例的 SSA 和事件、聚合布局、算术辅助结果及缓存复绑定。airline 的 41,800 条永久学习记录中，41,504 条的旧证明同时遇到未认证前提和已确认缺失或改变的前提。只有 296 条的旧证明仅遇到认证缺口，其中 295 条的结论也有未映射变量。这个分布支持追查来源，同时限制了对恢复数量的预期。[逐出生结果](evidence/si1a/proof/) · [处置统计](evidence/si1a/proof-dispositions.tsv)

固定起点为 D4.3-E 的 `b3803564e0c9badedbdd8ca0ad8acd85a002081f`。本阶段在独立工作树、独立分支 `codex/stable-model-identity` 上完成。侦察代码提交为 `b392c62e1e6234d051f7a9b0f6881b658ba63e34`。报告所列 μ、历史候选和收益均来自冻结实现。SI-1 的新身份映射、可恢复条数、搜索和端到端收益留待以后实测。[审查基线](D4.3-E.md) · [阶段状态](SI-1A-status.json)

## 1. 对照与观测边界

| 病例 | 性质与历史结果 P0 → P1 | 原生配置 | 上限 |
| --- | --- | --- | --- |
| fib_updates_8 | `main.assertion.1`，失败 → 有界通过 | SC，64 位，展开 10，两个 worker | 300 s，20 GiB |
| circular-buffer | `reach_error.assertion.1`，失败 → 有界通过 | SC，32 位，展开 8，两个 worker | 660 s，7 GiB |
| airline_reservations_6 | `main.assertion.1`，失败 → 有界通过 | SC，64 位，展开 8，六个 agent | 300 s，20 GiB |
| fib-snapshot-11 | 两侧目标均 SUCCESS，两侧整体验证均为 `INCOMPLETE_UNWINDING` | SC，32 位，展开 25，历史对照 | 660 s，7 GiB |

四对输入、冻结补丁、共用 harness 或预处理输入、性质和展开配置均核对了摘要。逐字节重放补丁后，四份被修改输入分别有 3、762、9、728 个可验证的未修改行；共同 harness 单列。此处行数只用于检查编辑材料。原生性质、展开义务和反例沿用 E 的完整记录。历史对照单独统计。[输入、补丁与配置](evidence/si1a/frozen-inputs.json) · [原生性质和展开记录](evidence/d43e/native-properties.json)

Windows 独立工作树为 `D:/Deagle_stable_identity`，建模使用 Deagle-Jammy 的 Ubuntu 22.04.5、WSL2 内核 6.6.87.2、GCC 11.4.0、Python 3.10.12、i7-13700F，固定 CPU 0。stock、生产 ELF 及独立探针 ELF 的 SHA-256 分别以 `f8c08f37`、`91a531d0`、`d7cb3a91` 开头。探针只在私有翻译单元和静态库副本中编译。它在两版模型各自完成 Boolean 输入、Closure 静态图和变量分配后，于第一次查询根边界写出来源并以 77 退出。此退出码是建模回执。四例的 P1 求解器均未在本阶段导入子句。[环境与完整摘要](evidence/si1a/environment.json) · [编译链接命令](evidence/si1a/probe-build.json) · [八份建模回执与来源流](evidence/si1a/probe/)

八个模型共 1,184,616 个实际 SAT 原子。探针逐段核对了连续分配区间与原生 `N−1`。从模型首行到第一次 `N` 的完整规范化流均与 D 冻结归档相同。输入顺序、范围及文字、门及带符号输出、A 端口、EDGE、GUARD、NODE、N 另按原始行顺序计算摘要。规范化只处理工作目录、既有 TERM 驻留句柄及无序提示，`END/READY` 属于根边界以后。关闭探针又用既有 D0 小夹具核对了原生性质、反例步数和确定性计数，两个二进制同为 140 次决策、624 次 Boolean 传播、3 次理论传播。小夹具初次直接比较发现两个私有运行目录写入了性质的 workingDirectory；对照仅将严格等于各自 run.cwd 的这个字段规范为 @WORK@，其余性质字段逐项相等。探针时间及 RSS 仅为诊断元数据。[八组双边摘要](evidence/si1a/model-equivalence.json) · [各原生流摘要](evidence/si1a/frozen-model-fingerprints.json) · [关闭探针对照](evidence/si1a/off-control.json)

## 2. 原子从哪里来

以下均为去重原子数。UsedLeaf 变量集取实际使用的永久 Boolean occurrence 中的全部原子，并加上已用 RF/Guard 声明中实际绑定的非恒定 SAT 原子。PO/APO、块和域仍是理论前提，其本地事件编号不计作 SAT 原子。P1 的两个栏目是本版全部原子和现有 μ 的像；P1 本身没有测量 UsedLeaf。

| 病例 | P0 原子 | P1 原子 | 语义已配 + 结构补充 | P0 未配 | P0 UsedLeaf 并集 | 其中未配 | 永久结论中的未配原子 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fib_updates_8 | 12,553 | 12,057 | 10,062 + 354 | 2,137 | 8,062 | 1,547 | 326 |
| circular-buffer | 245,081 | 245,472 | 36,357 + 710 | 208,014 | 36,467 | 27,607 | 2,846 |
| airline_reservations_6 | 199,090 | 69,634 | 13,977 + 1,333 | 183,780 | 31,858 | 23,718 | 7,270 |
| fib-snapshot-11 | 200,360 | 200,369 | 191,389 + 61 | 8,910 | 105,940 | 5,592 | 1,356 |

同一原子可能是某个 SSA 名的别名、原生门的有符号结果和理论绑定。为让下表可相加，主类别依次取 RF、Guard、指针／聚合具名端口、有 V 来源的标量 BV 位、普通 Boolean、显式 fresh/free、辅助编码、其余来源未充分认证。“自由”指分配时取 fresh 位，随后仍可能受数组或其他原生约束。辅助编码包括显式 CNF 门、BV helper 和等价关系编码器。物理分配点、操作、原生语义角色及多别名另有交叉表。四例的 P0/P1 全量、旧未配、UsedLeaf、结论等完整分母都在机器表中。[互斥来源统计](evidence/si1a/cohorts.tsv) · [重叠角色](evidence/si1a/overlapping-roles.tsv) · [物理分配点与运算](evidence/si1a/allocation-sites.tsv)

| UsedLeaf 中的未配原子 | RF | Guard | 指针／聚合 | SSA 位 | 普通 Boolean | 自由 | 辅助 | 未知 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fib_updates_8 | 10 | 0 | 384 | 0 | 0 | 2 | 1,151 | 0 |
| circular-buffer | 108 | 2 | 11,489 | 194 | 0 | 0 | 15,814 | 0 |
| airline_reservations_6 | 485 | 12 | 10,635 | 0 | 0 | 6 | 12,580 | 0 |
| fib-snapshot-11 | 58 | 2 | 224 | 97 | 0 | 0 | 5,209 | 2 |

**airline。** 从旧最终 μ 回看 UsedLeaf 未配原子，11,884 个在旧语义阶段报门输入未配，7,511 个超出已认证聚合整数前缀，2,688 个报未注册符号或类型。独立类型观测将指针／聚合主类分为 2,688 个指针和 7,947 个 union-tag 原子。485 个未配 RF 中，402 个在认证端口时没有对端别名，83 个缺少可认证端点。冻结补丁确实删除了一对 unlock/lock；不能由“无对端”单独推出某个具体源操作被删。一个实际追溯例为 P0 原子 70，`and(5,10) → 140` 的第二个有符号输入指向原子 5。它在 `boolbv_index.cpp:68` 的数组索引路径分配，是原生数组约束的 fresh 返回值。这里 5、10、140 是本次模型的编码文字，原子号另取文字右移一位。[逐类失败原因](evidence/si1a/mapping-reasons.tsv) · [分配、门链与前提样例](evidence/si1a/origins.json)

**circular-buffer。** 未配 UsedLeaf 中有 10,368 个 union-tag 原子、1,120 个指针原子、1 个数组原子；14,437 个旧语义角色为 Aux 的原子因上游输入未配。原子 8,344 的 XOR 输入包含原子 8,343，后者在 `bv_utils.cpp:1220` 的比较器中产生，旧语义理由为 `no_semantic_definition`。所以补全普通门日志之外，还须给比较器结果、其内部位和被别名引用的布局位提供来源。fib_updates_8 的 326 个永久结论未配原子全部属于辅助编码。历史对照仍有 2 个 UsedLeaf 未配原子未取得充分的语义分类。[各类结论与分配来源](evidence/si1a/origins.json)

## 3. 缺少身份与实际前提缺失

每个百分比的分母是该病例、该域实际置位的旧 UsedLeaf。Boolean 成员检查把旧文字逐个带符号翻译，在**全部 P1 永久原始子句**中比对完整规范化内容，并核对命中的 occurrence 编号。Theory 使用相同 μ 下已认证的静态声明回执。U 为身份、绑定或侧条件仍不能确认，C 为该映射下声明退役。缺少身份这一栏包含潜在真实删除，当前证据无法再可靠分摊。完整翻译后缺少输入则能确认旧前提在该 P1 永久集合中不存在。

| 病例 | B 匹配 | B 不能翻译 | B 可译但不存在 | T 匹配 | T 未认证 | T 已改变／退役 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fib_updates_8 | 8,382 (65.19%) | 4,446 (34.58%) | 30 (0.23%) | 779 (91.54%) | 72 (8.46%) | 0 |
| circular-buffer | 6,385 (18.05%) | 28,928 (81.79%) | 54 (0.15%) | 4,692 (73.15%) | 1,722 (26.85%) | 0 |
| airline_reservations_6 | 8,343 (25.11%) | 24,887 (74.89%) | 0 | 801 (35.63%) | 741 (32.96%) | 706 (31.41%) |
| fib-snapshot-11 | 120,203 (86.82%) | 18,243 (13.18%) | 0 | 13,378 (98.85%) | 98 (0.72%) | 58 (0.43%) |

circular-buffer 的旧 occurrence 23,338 是一个可重复检查的反例。两个文字 `[25273,25676]` 均可译，翻译后仍为这两个文字，P1 永久输入中没有该子句。airline 的 706 个已退役理论前提包括 616 个同址、42 个 PO、24 个事件模式、12 个 APO 和 12 个块证书。两例都说明仅提高端口覆盖不足以判定旧证明存活。[原始前提分项与样例](evidence/si1a/origins.json)

另对冻结的同次 Audit 归档只读汇总。对每个实际祖先分别继承“B 不能翻译、B 可译但不存在、T 未认证、T 已改变”四个位，与 D 全部出生的作用域、旧结论可译性、精确支持存活及准入逐项核对。下表前三个处置栏与“支持完整”互斥，共计 97,901 条永久记录。另有 54,916 条查询作用域记录，出生总数为 152,817。E 三轮使用相同的实际 μ，表中每个出生只计一次。[逐出生掩码与出处](evidence/si1a/proof-read-receipts.json) · [按结论可译性细分](evidence/si1a/proof-dispositions.tsv)

| 病例 | 永久出生 | 仅有未认证前提 | 仅有已缺失／改变前提 | 两者都有 | 支持完整 | 结论全可译 | 历史 Compact 附着／命中 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| fib_updates_8 | 1,307 | 410 | 192 | 392 | 313 | 956 | 295／255 |
| circular-buffer | 188 | 69 | 77 | 0 | 42 | 146 | 11／10 |
| airline_reservations_6 | 41,800 | 296 | 0 | 41,504 | 0 | 2 | 0／0 |
| fib-snapshot-11 | 54,606 | 54,418 | 0 | 148 | 40 | 19,416 | 16／9 |

恰好在这四个模型中，“支持完整”的出生也都有可译结论。airline 仅有两个旧结论可译，均为混合学习。出生 **203** 的祖先含 B 不能翻译与 T 未认证，掩码为 5。出生 **553** 还含已改变的 T，掩码为 13。两条在当前映射下都不准入。296 只标出一个可定位的研究范围；跨版本源身份能否恢复这些祖先，尚未测量。

## 4. 生成、别名、缓存与作用域的接入位置

以下是对固定源码的调用链核对和建议改动点。新增元数据计划由独立、可关闭的编码观察接口维护，所有位置均在实际生成或返回结果时观察。

| 对象 | 已核对的原生位置与当前行为 | 拟登记的来源或拒绝条件 |
| --- | --- | --- |
| 文件、声明与 GOTO | `src/ansi-c/ansi_c_language.cpp::parse/typecheck`，`ansi_c_declarationt`，`src/goto-programs/goto_convert.cpp::goto_convert_rec/copy` 及生成指令的分支。多条指令可复制同一 source location | 解析声明／表达式时采集文件、作用域、父节点与子角色。GOTO 派生发射点携带父 SiteId 和生成角色。无可核实的宏／插入／复制来源时记为不可继承 |
| 执行实例、定义、读、合流 | `goto-symex/dependency_context.cpp::index_sites/context/birth` 使用本地 site 序号、caller、thread 和循环信息。`symex_main.cpp::symex_step`、`symex_start_thread.cpp::symex_start_thread`、`symex_function_call.cpp` 产生实例；`renaming_level.cpp::increase_generation` 与 `goto_symex_state.cpp` 发生 L2 出生／读取；`symex_assign.cpp::assign_symbol`、`symex_goto.cpp::phi_function` 及 `symex_target_equation.cpp::assignment` 可交叉核对 producer | 建本版 SSA 名到稳定定义／读发生的侧表。PHI 取合流 Site、对象、实例、角色；初始写、参数、隐藏赋值分别编号。重复出生、无上下文、缺失生成器单列原因 |
| 普通 Boolean | `solvers/prop/prop_conv_solver.cpp::get_literal/convert/set_equality_to_true` 有新建、取已有值、命中缓存、绑定带符号 RHS 或另行加约束等路径 | 在实际返回点登记当前端口。常量登记 T/F；已分配后以等式约束的两个原子继续分别登记 |
| SSA 位及布局别名 | `solvers/flattening/boolbv.cpp::convert_bv` 缓存整段 BV。`boolbv_map.cpp::get_literals/set_literals` 会逐位新建、直接引用 RHS 整段或对已有位约束相等。根前 `goto-checker/bmc_util.cpp::run_property_decider` 可核对最终 A、类型和位号 | 登记 producer、字段／切片、原生类型、布局和实际返回的有符号位。空向量、常量和零宽有显式状态。旧字符串 A 中空白类型须回到真实 `map_entry.type` |
| 门和算术内部位 | `solvers/sat/cnf.cpp::land/lor/lxor/lselect` 有恒定、重复、互否和直接返回；`gate_equal` 可用负输出调用 XOR。`new_variables(width)` 独立批量分配。`flattening/bv_utils.cpp::full_adder/carry/unsigned_divider/rel` 的 carry、sum、商余、比较前缀及结果可绕过 G | 以 owner、已版本化 lowering 模板、运算宽度／符号、操作数角色、位和阶段登记。覆盖取反的早返回、选择条件／两臂、位提取／常量折叠。只在角色与布局均唯一时接受；相同 `op,inputs` 的不同原生输出保持分立 |
| 数组、自由位、等价 helper、指针和聚合 | `boolbv_index.cpp:68` 先分配自由位再登记数组索引。`equality.cpp` 产生等价谓词和元素编码；其元素枚举属于本版。`boolbv_union.cpp` 可为 padding 生成 nondet；`boolbv_struct.cpp`、`boolbv_typecast.cpp`、`boolbv_width.cpp` 和 endianness map 决定布局。`bv_pointers.cpp` 调用 `pointer_logict::add_object` 建本地对象编号 | 索引次数、声明／分配 Site 与实例、数组域、字段路径、位宽、字节序、对齐／padding 都能认证时才建立相应端口。指针须认证对象来源及本版对象编码解释，特别是指针位要证明其位意义可以按符号置换；裸 object number、union 视图不明、UF 元素编号歧义、未绑定自由位均单列退役 |
| 静态事件、实际接口、查询 | `goto-symex/memory_model_sc.cpp` 从最终 SSA 步建立 E/V。`memory_model.cpp::register_read_from_choice_symbol(r,w)` 建 choice 后调用 `add_oc_edge`；`goto-checker/bmc_util.cpp` 转换实际 RF/Guard 文字；`solvers/sat/satcheck_minisat2.cpp::save_raw_graph/lcnf/do_prop_solve` 与 `minisat/core/Closure*` 的安装及根边界对应 | RF 取有方向的实际写、读发生和绑定角色；Guard 取事件及定义角色。与最终 NODE、RF EDGE、GUARD 带符号实参逐项核对。B/Q/U 和永久／查询／UNKNOWN 继续在原生边界裁定，临时 trail 事实不写进永久目录 |
| 准备及准入 | `dependency-reuse/scripts/d43_prepare.py` 读双模型、认证事件和端口、调用 Boolean／结构工具、再做 UsedLeaf 与 Dirty；`minisat-2.2.1/minisat/core/DependencyTags.*` 与原生导入器已审计 | 拟用 typed 目录和签名连接替换准备中的身份恢复。保留完整 P1 成员检查、理论侧条件、封存组位号、标签和第一次查询导入边界 |

源码定位均相对 `src/`，最末行及明确标出其他根目录者除外。可逐项对照实际发射位置和原生类型。[源／实例索引](../../src/goto-symex/dependency_context.cpp) · [SSA 转换阶段](../../src/goto-symex/symex_target_equation.cpp) · [RF 生成](../../src/goto-symex/memory_model.cpp) · [CNF 门及分配](../../src/solvers/sat/cnf.cpp) · [实际准备路径](../scripts/d43_prepare.py)

## 5. 建议冻结的身份方案

1. **源与 IR 谱系。** 在 P0 为逻辑文件、声明和语句／表达式分配持久且不复用的 FileId、DeclId、SiteId。文件逻辑身份来自项目谱系，内容 SHA 单独绑定输入。P1 先校验旧／新字节、补丁和受保护文件，再在同一已继承父节点下，按作用域、种类、唯一子角色及有证据的未改 token 区间继承。修改 RHS 的赋值在编辑记录或唯一结构位置证明其发生延续时可保留结果位置。移动、复制、相似调用、多重宏展开须逐项有来源；无法消歧则新发 ID 或标不可对应。`.i` 只对实际保留的预处理来源作证。利用现有前端，携带外部侧表跨 GOTO 降低与复制；任何跨越新生成器而遗漏派生信息的路径显式退役。
2. **实例与端口。** `ThreadKey=(父线程,spawn Site,出生处调用与循环实例)`；`CallKey=(父调用,调用 Site,该处展开实例)`；`LoopKey=[(Loop Site,迭代),…]`；`ContextKey=(ThreadKey,CallKey,LoopKey,SiteId)`。同一迭代号只在相同已认证循环内解释。`PortKey=(owner,context,recipe,role_path,layout,bit)`，`LocalValue=SignedLiteral | Constant(T/F) | Unavailable(reason)`。owner 可为对象、定义、合流、读写发生或带来源的内部结果。recipe 绑定编码器版本与模板分支。实际定义／约束内容另存。局部 thread_nr、SSA #、X、SAT 编号、地址、全局门次序及旧折叠逻辑组均只供本版定位。
3. **缓存内部采用角色模板。** 首次实际 lowering 在现有转换缓存项旁记录本次生成的角色到本版 LocalValue，以及到子缓存项的有类型角色引用。每次返回或缓存命中给当前 owner 绑定顶层结果；需要内部位时，按当前 owner 和 role path 在模板中复绑定，按“缓存项、owner、角色”去重。对只经子缓存取得的位也沿该子角色解释。用本版缓存生命周期管理模板；记录被擦除、模板分支改变、未捕获 carry、同角色多值时输出 `CACHED_INTERNAL_ORIGIN_MISSING`，继续保守退役。同一 literal 可获得多个不同 PortKey，原生缓存和门数量保持原义。模板写入、连接、逐角色复绑定和冲突检查均需计时及计空间。
4. **签名连接及别名。** 桶内比较完整 typed tuple 和实际内容，哈希只定位桶。对两个同一端口的带符号文字 `(v₀,s₀),(v₁,s₁)` 提议 `μ(v₀)=(v₁,s₀ XOR s₁)`。同键多值记 `SAME_KEY_MULTIBIND`，一个原子上所有有对端的别名须给出一致提议；一对多、多对一、符号冲突、常量／变量种类改变均独立报告，对冲突分量整体拒绝。相同常量可作为常量内容核对，不替代旧原子。RF、Guard、CO 和理论别名仍须通过本版实际接口及其侧条件认证。每个版本对只有一份 μ。
5. **前提及安全边界。** 区分“同一结果位置”与“旧约束在新版成立”。对 P0 UsedLeaf 逐 occurrence 翻译完整有符号 B 子句，在 P1 全部永久输入的 typed 索引上按规范化完整内容确认；重复输入保留 occurrence 见证。T 以两端稳定事件和对象为入口，重核 PO/APO、RF/Guard 实际绑定与极性、块成员／方向、同址、候选写全集和规则配置，完整域变化使依赖它的声明失效。失配置旧组 Dirty，保留同组和 overflow 的保守合并。准入还须永久、无 UNKNOWN、结论全可译、两个标签均不碰 Dirty，沿用出生顺序及 512 上限。正确性依据是同一带符号单射下，旧证明所用 B/T 前提与规则侧条件在 P1 逐项成立。
6. **目录协议。** 建议在 `dependency-reuse/stable-identity/` 定义 `source-catalog`（包括继承回执）、`port-bindings`、`used-inputs`、`theory-catalog`、`direct-map`、`dirty`、`selected`。沿用 `dense.bin`。头部绑定格式／规则／recipe 版本、ABI、SC、端序、输入／补丁／二进制摘要和旧 GroupRegistry；每段有类型、长度、行数、边界、内容摘要及封存回执。顺序编号引用 intern 表，实际相等性核对完整负载。截断、错版、表引用越界、非单射或来源缺失按归档或单项边界拒绝。外置元数据不参与 `exprt` 哈希、排序、原生变量分配或 proof/Clause 对象布局。

**缓存风险已有可定位的规模。** 观测了 Boolean/BV 转换的首次未命中、后来命中以及当时 SSA 转换阶段和已知本地 context。下表取在不同已知 owner 下再次命中的缓存项，合并它们初次转换时的原子分配区间；其中可能含嵌套运算及顶层结果。它只能说明当前变量与此类缓存行为相交。实际因内部模板缺失而单独损失的变量和出生，需要新旧绑定的逐角色对照才能识别。[缓存原始轨迹](evidence/si1a/probe/) · [缓存范围统计](evidence/si1a/overlapping-roles.tsv)

| P0 | 跨 owner 的缓存命中次数 | 未配 UsedLeaf 原子落在区间内 | 永久学习结论含区间内未配原子 |
| --- | ---: | ---: | ---: |
| fib_updates_8 | 636 | 143 | 0 |
| circular-buffer | 33,505 | 11,015 | 10 |
| airline_reservations_6 | 4,100 | 8,571 | 41,522 |
| fib-snapshot-11 | 13,469 | 1,884 | 295 |

## 6. 成本边界与原型决策

按 E 的每个病例、每一轮计算 `reuse P1 墙钟 − stock P1 墙钟 − 本轮准备子进程墙钟`，然后对三轮取中位数。两版周期同样在配对后减一次准备。这个反事实把整段 worker 成本设为零，固定了当时的候选、搜索和其他成本。四个 P1 残差均为正。[逐对原始运算](evidence/si1a/zero-worker-pairs.tsv) · [中位数](evidence/si1a/zero-worker-medians.json)

| 病例 | 已付准备中位数 s | 准备免费后 P1 仍多耗 s | 准备免费后两版周期仍多耗 s |
| --- | ---: | ---: | ---: |
| fib_updates_8 | 0.273 | 0.245 | 0.273 |
| circular-buffer | 3.505 | 1.711 | 2.104 |
| airline_reservations_6 | 2.240 | 1.768 | 3.890 |
| fib-snapshot-11 | 4.296 | 5.885 | 15.318 |

circular-buffer 的冷／复用纯搜索配对节省中位数为 0.362 s，复用 P1 比 stock 多耗 5.216 s。准备中“变量语义及静态模型”2.017 s 包括读取、对象构造、锚点和匹配；单独结构细化为 31.56 ms。身份继承、双端登记及必要内容检查都将占用上表的一部分预算。正式计时起点须早于源继承，计入 P0/P1 建模、封存／读回、完整候选域、全部 P1 B 成员索引、实际连接、导入及根层传播。历史质量统计沿用 E 的分开口径。[E 配对数据](evidence/d43e/pairs.tsv) · [E 分段耗时](evidence/d43e/runs.tsv)

以实测端口／原生行数估算一份 typed 目录。情景中每个端口角色 32 B（六个 32 位键字段、值种类／符号、本地负载）；角色数取具名 A、G、额外 helper／free 物理结果以及 RF/Guard 绑定行，包含常量和不同角色的别名。每个 Site/Context/Event 取 24 B、V 取 16 B；B 索引头每条 12 B、文字 4 B，T 声明描述符 24 B。P0 只计实际 UsedLeaf 内容，P1 计完整永久 B 库和八类静态 T 描述符。再按表内实际生成的辅助位每条模板索引 12 B、每次缓存命中一条 8 B 关联估算。下列为序列化情景的小计。可变长度 token／key、字段和对象布局、候选全集的成员、复绑定展开、哈希桶、临时缓冲、原有 dense 库、文件头与校验、内存分配器和峰值 RSS 均需另计。[各侧条目、字节及组成](evidence/si1a/wire-size-scenarios.tsv)

| 病例 | P0／P1 端口角色行 | P0／P1 小计 MiB | P1 完整永久 B occurrence |
| --- | ---: | ---: | ---: |
| fib_updates_8 | 19,310／18,814 | 1.02／1.78 | 45,757 |
| circular-buffer | 268,843／270,194 | 11.95／37.80 | 1,161,265 |
| airline_reservations_6 | 225,715／89,317 | 9.83／9.06 | 243,406 |
| fib-snapshot-11 | 218,314／218,395 | 12.30／32.36 | 1,001,473 |

**建议进入 B 的条件。** 先对本阶段实际出现的比较、加法、数组 fresh、互斥锁 union 布局、指针来源、别名与 RF/Guard 建立可审计身份。保留关闭、影子及独立审计模式。影子阶段逐模型对照全部输入／作用域、理论图、原生变量顺序、性质／展开及确定性搜索计数；补充恒等及已知有符号置换、两次相同源码拷贝、相似调用删除、线程出生和 PHI、常量／取反、重复门、缓存首次 owner 互换、负输出 XOR、批量分配、字段／端序变化、RF 端点或极性互换、候选域变化及截断归档负例。逐项核对可导出 UsedLeaf 及结论覆盖。缺少来源的生成器应先列出对实际证明的影响。只有形成完整独立的 typed 准备路径后，才有依据测量取代双文本 Model 和旧匹配器的成本；付费前移、单纯提高覆盖或附着数都不能推出加速。

## 7. 复现

在本分支的 WSL 工作树内执行。已有冻结归档时可直接设置 `D` 为含 `matrix/` 和 `exact/` 的 D 归档根，`B` 为含 `accepted/` 的 B 归档根。若需恢复，使用 `d43b_archive.py restore dependency-reuse/reports/evidence/d43d/raw <全新D目录>` 和相同命令的 `d43b/raw` 版本。离线统计只读旧归档和已发布的压缩来源流。

```bash
S=dependency-reuse/scripts
E=dependency-reuse/reports/evidence/si1a
T=$(mktemp -d)
mkdir "$T/summary"
cp -r "$E/probe" "$T/summary/"
python3 "$S/si1a_census.py" "$D" "$T/summary"
python3 "$S/si1a_review.py" "$D" "$B" "$T/summary" "$T/reader"
cmp "$E/cohorts.tsv" "$T/summary/cohorts.tsv"
cmp "$E/proof-dispositions.tsv" "$T/summary/proof-dispositions.tsv"
cmp "$E/zero-worker-pairs.tsv" "$T/summary/zero-worker-pairs.tsv"
```

重建诊断观测时，`NATIVE` 指向冻结 D 的已编译源码树，`T` 使用全新目录。脚本检查原生 ELF、每个被观测翻译单元和所有冻结输入，再私有链接。原始来源流中的缓存地址在发布前改为本次运行内的条目序号。追溯外部身份时不使用这些序号。

```bash
S=dependency-reuse/scripts
T=$(mktemp -d)
python3 "$S/si1a_probe.py" build "$NATIVE" "$T/build"
python3 "$S/si1a_probe.py" model "$T/build/si1a-deagle" "$T/models" "$T/evidence/probe"
python3 "$S/si1a_census.py" "$D" "$T/evidence" --observed-models "$T/models"
python3 "$S/si1a_review.py" "$D" "$B" "$T/evidence" "$T/reader" --observer-build "$T/build/build.json"
python3 "$S/si1a_probe.py" off-control "$T/build/si1a-deagle" "$NATIVE/src/cbmc/deagle_exe" "$T/smoke" "$T/evidence/off-control.json"
```

在全新目录只用已封存的来源流及 D/B 归档再执行上述离线流程，17 个统计和祖先处置文件逐字节一致。[复算回执](evidence/si1a/reproduction-check.json)

本阶段提交至独立分支，等待 SI-1A 审查。
