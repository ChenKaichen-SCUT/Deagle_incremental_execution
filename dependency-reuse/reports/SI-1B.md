# SI-1B 原生稳定身份影子原型

**READY_FOR_REVIEW · PARTIAL_IDENTITY_COVERAGE**

基线 `be3064304254e516ed37a27944d7a208a7971453`，分支 `codex/stable-model-identity`。预注册提交 `8eaf081461c3e1c9f5d513916be99188fae8f46b`，源码及审计工具固定于 `8fdad1cd27da7201db52755da78135e4f39366c1`。发布 ELF 的 SHA-256 为 `418d5e656c4f26c4cf46c07a8501561f0c1af1801fa9060fe1e956b6fbe83f1a`。[预注册](../configs/si1b-plan.json) · [构建收据](evidence/si1b/build.json) · [审查状态](SI-1B-status.json)

四例 P0 的 657,084 个原子中，影子目录直接建立了 **42,149 个带符号单射对应**。独立读回逐条找到了两侧的实际绑定。SI-1A 标出的 58,464 个 UsedLeaf 缺口补回 **3,679 个（6.29%）**，其中辅助编码 3,646 个、SSA 位 33 个、指针／聚合 0 个。三个真实修复病例共补回 403 个，另有 3,276 个来自历史对照。旧 μ 在 UsedLeaf 上另有 97,674 个对应未被直接身份恢复。本阶段得到的是来源可审计的局部能力，覆盖结果支持保留 SI-1B 的部分覆盖标记。[总表](evidence/si1b/summary.json) · [按域分解](evidence/si1b/scope-summary.tsv)

## 实现和边界

源处理先重放真实补丁，认证未变 token 区间、父作用域和派生角色。P1 新节点使用独立编号空间。编译器的声明、GOTO 降低／复制、函数指针分派目标、线程出生、调用和循环实际发生进入本地侧表。PHI、隐藏赋值、初始静态写、读与写具有不同角色。同一实例下重复而无法区分的生产者被拒绝。旧版数据和本次实际输入各自有摘要。[源继承](../scripts/si1b_sources.py) · [GOTO 与执行实例](../../src/goto-symex/dependency_context.cpp) · [身份格式和完整复现命令](../stable-identity/SI-1B-format.md)

在实际 Bool/BV 返回、等式传播、已有 symbol、批量分配、比较、加法、选择、数组下标和原生门路径登记正负文字或常量。外层结果端口取自定义／读的执行实例；内层额外要求有类型的操作数、编码分支、位宽、位号和具体角色。缓存首次 lowering 保存一次实际返回、直接内部角色和子模板引用。命中登记 owner，随后按双方可认证的根和子引用惰性连接。地址只标识本进程当前缓存生命期。保留原生常量折叠、等式别名和缓存行为。[原生登记](../../src/util/stable_identity.cpp) · [算术内部角色](../../src/solvers/flattening/bv_utils.cpp) · [目录解释](../scripts/si1b_catalog.py)

写／读和 Guard 来源必须落到原生事件。RF 创建符号、安装的有向端点和实际选择文字三方交叉核对。带符号连接要求原子承担的全部理论角色一致。连接器比较完整键，按两侧文字符号异或构造正变量的像，整分量拒绝不一致的提案。源码、二进制收据以及生产连接入口中均可核查其输入。D4.3 的 μ、历史 UsedLeaf 和永久学习记录只在直接映射生成后进入独立诊断。约束保持性、Dirty、候选准入和原生导入均留待阶段审查。[连接器](../scripts/si1b_join.py) · [独立见证读回](../scripts/si1b_witness.py) · [历史统计入口](../scripts/si1b_audit.py)

## 八个模型的原生一致性

三种运行方式分别为关闭身份、正常影子登记、独立审计。前两种完整求解且不导入。完整归档审计将原生模型与 SI-1A 冻结模型核对到第一个查询根。另以相同探针分别编译冻结原生源码与本版源码，在**默认无 manifest 的实际编码配置**下比较冻结原生、当前 off、当前 shadow 三路。探针在首次根边界结束，每个侧表及生产成本均有独立收据。[独立探针源码](../scripts/si1b_passive.py) · [冻结观察器构建](evidence/si1b/passive-build-stock.json) · [本版观察器构建](evidence/si1b/passive-build-si.json)

八组原子的连续分配、全部有序 B/Q/U 子句及符号、门、理论图与绑定、查询均通过严格核对。实际出现的 U 行数为 0。**244,714 条**根边界实名 Boolean/BV 端口与独立安装快照逐项一致。可见反例、性质、展开义务、各次查询的决策、冲突、Boolean 与理论传播、理论环冲突、动态 CO 和重启计数均通过。在此基础上，42,149 个接受的对应均找到了单值的原生端口见证，错误 0。每例证据保留原始 stdout、stderr、配置、审计模型、生产目录和独立访问流。[Fibonacci](evidence/si1b/fib_updates_8/audit/model-audit.json) · [circular-buffer](evidence/si1b/circular-buffer/audit/model-audit.json) · [airline](evidence/si1b/airline_reservations_6/audit/model-audit.json) · [历史对照](evidence/si1b/fib-snapshot-11/audit/model-audit.json)

原生 `oc_guard_map` 以 SSA 步地址排列。观测分配会改变这组事件的访问顺序。独立探针在每个具名 Guard 进入和退出处包围访问，验证事件集合、每个事件的完整缓存句柄／命中／操作符／原子上界，以及区段外的完整有序流。八组的区段内均未发生 miss 或分配，安装图与所有输入仍逐行相等。三路各自的真实顺序单独保留，离线回放能还原各自整个访问流摘要。[Guard 遍历数据示例](evidence/si1b/circular-buffer/passive/P0/receipt.json) · [发布证据复算](evidence/si1b/replay.json)

开发时观察到两次需要修复的失败。第一次影子运行在未打开旧 manifest 时写入了空的 D1 输出流，现将旧输出与身份记录分开。历史 P0 第一次完整搜索中，影子较 off 少 56 次 Boolean 传播和 1 次理论传播。原因为提前创建原生循环标识改变了查询构造中的驻留顺序。默认影子路径改为在已经存在的循环实例中按名字读数。最终 off 与 shadow 同为 108,789 次冲突、341,809 次决策、131,660,246 次 Boolean 传播和 285,458 次理论传播。历史 D4.3 manifest 的 74 个变位只涉及查询；已独立核对，受影响编号在两份 μ 上均未映射，也不在 UsedLeaf 或永久结论中。[首次失败](evidence/si1b/development/early-shadow-crash/run.json) · [修正前日志](evidence/si1b/development/pre-fix-shadow/stdout.gz) · [历史同配置结果](evidence/si1b/fib-snapshot-11/audit/model-audit.json)

三个修复病例保持 P0 `VIOLATION`、P1 `BOUNDED_PASS`。历史 fib-snapshot-11 两侧继续按 `INCOMPLETE_UNWINDING` 报告，原生返回的 `fib.unwind.0`、`t1.unwind.0`、`t2.unwind.0` 和触及展开界的口径均已核对。

## 覆盖范围

下表按旧版原子去重。“相同”要求新变量及其符号均相同。“失去”表示旧 μ 有像、直接身份缺少可认证的像。“分歧”是两种映射都有像但变量或符号不同。全部 P1 原子和所有原生理论接口也有独立反向统计。UsedLeaf 和永久结论的分母来自 P0 的真实记录。[完整八类来源交叉表](evidence/si1b/coverage.tsv)

| P0 域 | 全部 | D4.3 μ | 直接身份 | 相同 | 新增 | 失去 | 分歧 | 两者均无 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 全部原子 | 657,084 | 254,243 | 42,149 | 36,455 | 5,694 | 217,788 | 0 | 397,147 |
| UsedLeaf | 182,327 | 123,863 | 29,868 | 26,189 | 3,679 | 97,674 | 0 | 54,785 |
| 永久学习结论 | 25,969 | 14,171 | 7,053 | 5,714 | 1,339 | 8,457 | 0 | 10,459 |
| 理论接口 | 8,999 | 8,322 | 5,848 | 5,848 | 0 | 2,474 | 0 | 677 |

| 病例 | 全部原子旧→新映射 | UsedLeaf 旧→新映射 | 已补原缺口／原缺口 | 永久结论原子旧→新 | 理论接口旧→新 |
|---|---:|---:|---:|---:|---:|
| fib_updates_8 | 10,416 → 8,953 | 6,515 → 5,629 | 245 / 1,547 | 1,592 → 1,658 | 246 → 220 |
| circular-buffer | 37,067 → 473 | 8,860 → 172 | 0 / 27,607 | 1,180 → 10 | 2,243 → 4 |
| airline_reservations_6 | 15,310 → 3,319 | 8,140 → 1,707 | 158 / 23,718 | 435 → 44 | 255 → 48 |
| fib-snapshot-11（历史） | 191,450 → 29,404 | 100,348 → 22,360 | 3,276 / 5,592 | 10,964 → 5,341 | 5,578 → 5,576 |

旧缺口的辅助编码为 **3,646 / 34,754**，指针／聚合为 **0 / 22,732**，SSA 位为 **33 / 291**；RF 0 / 661、Guard 0 / 16、自由变量 0 / 8、未知来源 0 / 2，普通 Boolean 原缺口为 0。Fibonacci 的 P0 原子 2582 在两版 `harness.c` 第 26 行的 `right_worker` 更新中都是第 1 位加法进位，正文字映射到 P1 原子 2086。airline 的 P0 原子 8547 来自 `reserve_seat` 第 2 位比较前缀，正文字映射到 P1 原子 5975。两例见证均含双边原生位置、执行实例、模板、角色和分配位置。历史对照的新增记录可同样逐项查询。[Fibonacci 见证](evidence/si1b/fib_updates_8/source-witnesses.json) · [airline 见证](evidence/si1b/airline_reservations_6/source-witnesses.json) · [历史对照见证](evidence/si1b/fib-snapshot-11/source-witnesses.json)

circular-buffer 的未补辅助原子中，10,462 个来自等式编码的 XOR，3,724 个来自取模中的 AND，另有 493 个为取模路径的加法器分配。airline 有 10,978 个未补辅助原子来自等式编码的同一 XOR 分配点。认证这些算术角色还要求其聚合操作数及执行实例具有可靠来源。直接连接没有旧结构映射提供的补充提案。此处报告的生成器位置沿用 SI-1A 的原生源码行号。[circular-buffer 分配点](evidence/si1b/circular-buffer/audit/used-old-gaps.tsv) · [airline 分配点](evidence/si1b/airline_reservations_6/audit/used-old-gaps.tsv)

四例 UsedLeaf 中实际有 24,165 个按互斥优先级归入指针／聚合类的原子，直接身份全部拒绝。17,767 个携带布局不兼容原因，6,398 个缺来源、对端或可认证的模板路径。永久结论中的对应计数为 4,229 和 870。airline 全模型内可以认证 384 个此类原子，均处于这两个目标域之外。原型核对实际 struct 成员布局、union 全部相交视图、填充和对象／offset 解释；单凭互斥锁名字、相同字节位置或本地指针编号均不能认证。所有节点保留 bound、ambiguous 或 unsupported 处置，冲突原因可多选。[circular-buffer 布局与缓存限制](evidence/si1b/circular-buffer/audit/cache-layout-limits.tsv) · [airline 布局与缓存限制](evidence/si1b/airline_reservations_6/audit/cache-layout-limits.tsv)

## 身份控制

相同源码在不同工作目录中具有相同的 5,358 个可识别端口键，1,957 个共同可认证原子全部映回自身。独立检查器对本地编号施加隐藏带符号置换，连接器恢复全部 1,957 个像，其中 654 个翻转，错误为 0。插入无关代码并删除相似调用的真实模型中，1,895 个对应被接受，其中 1,791 个原生变量号实际变化。小夹具中第一次调用保留，第二次退役。airline 的第一次加锁在两侧均落在源锚点 2097157，删除的第二次加锁属于不同锚点 2097160。[控制结果](evidence/si1b/controls.json) · [airline 两次加锁的原生站点](evidence/si1b/airline_reservations_6/audit/deleted-lock.json)

实际执行覆盖两个不同线程出生，60 个含嵌套循环的实例，单义的用户 PHI 在上下文 46 取得生产者身份。另一个控制中的五个内部 PHI 均被保守拒绝。实际 BV converter 以 AB 和 BA 顺序访问相同嵌套加法，并销毁、重建 converter。前一代和后一代返回不同变量，两次访问同一代没有新增变量。两种顺序均核对了 32 条 sum 和 32 条 carry 角色。相同物理 144 个值条目对应 288 个逻辑 owner 条目。测试还验证了别名符号、常量变化、同键多值、拆分／合并、极性冲突、错误理论绑定、受损封存、宏展开与赋值外层 RHS 继承。改变聚合布局撤回 65 个原有对应，交换 RF 注册次序保留全部 18 个已认证 RF 原子，反转端点后全部拒绝。[缓存控制源码](../tests/si1b/cache_owners.cpp) · [执行控制及故障注入](../scripts/si1b_controls.py)

## 时间、内存与存储

下表为冻结输入、相同原生选项的一次探索性实测。每格两值依次为 P0、P1。到根用时含源码读取、建模与编码，终点位于封存之前。原生缓存仪表覆盖模板保存、命中、角色和 owner 关联。目录校验与端口连接另在一对模型专用的独立进程中计时。全量 off／shadow 求解墙钟、用户及内核 CPU、RSS 和独立审计开销均保留。本轮不以一次墙钟差推断性能收益。[逐版成本](evidence/si1b/cost.tsv) · [缓存物理／逻辑明细](evidence/si1b/cache.tsv)

| 病例 | 源继承 ms／对 | off 到根 ms | shadow 到根 ms | 原生缓存登记 ms | 原生目录 MiB | shadow 峰值 RSS KiB | 双版连接进程峰值 KiB |
|---|---:|---:|---:|---:|---:|---:|---:|
| fib_updates_8 | 16.1 | 54.1 / 54.3 | 70.2 / 69.5 | 8.6 / 8.5 | 1.10 / 1.08 | 27,716 / 34,176 | 64,124 |
| circular-buffer | 11.7 | 280.4 / 261.9 | 572.8 / 570.6 | 246.5 / 246.9 | 16.00 / 16.11 | 217,176 / 240,376 | 609,264 |
| airline_reservations_6 | 15.5 | 140.2 / 88.2 | 309.6 / 196.4 | 128.4 / 87.0 | 11.72 / 4.84 | 150,152 / 87,552 | 324,696 |
| fib-snapshot-11 | 10.8 | 262.8 / 499.4 | 728.9 / 869.4 | 358.3 / 430.6 | 20.63 / 20.63 | 330,520 / 342,872 | 953,068 |

八份原生目录共 **96,569,630 字节**。单份序列化 0.33–7.44 ms，SHA-256 封存 11.27–39.23 ms。四对模型的原生目录读取校验、源与 IR 完成处理、端口建索引、模板展开和冲突检查分别计费。四例直接连接／冲突检查分别为 73.3、493.5、186.7、1,628.6 ms；含读取、诊断、输出在内的整对准备分别为 0.276、3.057、1.388、4.833 s。原生注册计时器和缓存计时器采用互斥计费，根边界墙钟另包含回调参数构造等未单独拦截的成本。不同构建的 CPU 2 被动探针和独立回放均不计入这些数值。原始时间戳、分项和环境都可从收据重算。

以 circular-buffer P0 为例，24,899 个转换模板登记 243,687 个直接内部角色位置，实际 35,033 次缓存命中。逻辑值条目从单一 owner 的 320,160 增至所有绑定 owner 的 2,400,180；共享目录物理保存 327,910 个值条目，去除 204 次重复 owner／根请求。该病例 UsedLeaf 中，14,031 个未映射原子出现在实际复用模板及其子模板的值或分配中。另计的 13,386 个落入 SI-1A 的“不同 owner 后来命中”分配区间，两种集合存在重叠。仍有大批不具认证条件的模板，跨病例覆盖改善和当前维护成本不足以据此批准 SI-1C。[逐模型缓存规模](evidence/si1b/cache.tsv) · [逐域拒绝数](evidence/si1b/circular-buffer/audit/causes.tsv)

已从 Git 交付格式重新解压八份生产目录，重建直接映射、完整见证键、IR 目录及每个原子的处置，四例输出逐字节相同。独立检查器同时回放了三路原生观察。完整命令、文件 SHA-256、可独立复算的原始流及审查状态随本阶段提交。SI-1B 到此停止，等待审查。[复算命令与环境](../stable-identity/SI-1B-format.md) · [证据索引](evidence/si1b/files.json) · [复算收据](evidence/si1b/replay.json)
