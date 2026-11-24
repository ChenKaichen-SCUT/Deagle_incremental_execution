# 阶段 11A · Deagle Closure 并发理论图的跨版本复用

状态 **READY_FOR_REVIEW**。独立分支 `stage-11a-closure-theory` 以 SV-COMP 修复预实验 `ff434538e5eaa78cf8c5e93eb3e41a7ccf06a5ff` 为直接父提交，阶段 10 基线为 `dca9eb78250426fe5b2aab22aea5ef91025dd24d`。本次交付是理论研究、独立检查器和固定原生库实验。正式 ClosureSolver、MiniSAT、建模流程与既有验证性质保持阶段 10 的实现。[前置实验](svcomp26-repair-pilot.md) · [原生基线](stage-10.md)

**可安全迁移的是有可重放证明的条件推理。** 如果旧推理的端点、绑定、规则、块关系、静态前提和本轮使能条件在 P1 都能核实，可以在 P1 重新得到同一结论。旧运行期图缺少足够信息来安全删除任意前提；当前最保守的生产设计仍是新建运行期图、根层状态和输出容器，只逐条重放通过审核的证明。读写锁实例给出了相同布尔输入、两处 PO→APO、原断言结论相反的可复现例子。[定义与 A–I 证明](evidence/stage-11a/formal.md) · [逐条源码和文献对照](evidence/stage-11a/source-map.md)

## 真实实例 · read_write_lock-2 的 P1→P2

固定输入为 `pthread-atomic/read_write_lock-2`、ILP32、unreach-call、展开界限 4。读取预实验归档 `pairs/read_write_lock-2/P1-P2/1/F` 的两份完整模型，以及 `S/old/answer.txt` 的真实 SAT 赋值。所用分块、文件和原始索引均校验 SHA-256。F 与 S 的候选／原始输入相互核对。两份冻结的原生结果对同一性质 reach_error.assertion.1 分别记录 FAILURE、SUCCESS，命令均带 --unwinding-assertions。两版 `s8-input.bin` **逐字节相同**，SHA-256 均为 `1c72c2fb6613d75f15542426200c38e898cc1786bf7e27c64855442ef3879b4a`。[确切输入指纹及差分](evidence/stage-11a/real-delta.json) · [冻结源码和补丁](../cases/svcomp26/versions/read_write_lock-2)

| 按动态操作对齐的声明 | P1 | P2 |
|---|---:|---:|
| 事件（42 写、35 读、4 出生） | 81 | 81 |
| 候选 RF / 写 guard | 131 / 42 | 131 / 42 |
| PO / APO | 97 / 15 | 95 / 17 |
| 有事件的显式 SSA 原子区 | 8 | 10 |

两位读者各自释放读锁时，对 `r` 的读和写从普通先后改为同一原子区内的有向先后。四个原生 APO 单点分量变为两个双成员分量。其余语义边、事件 guard 表达式、类型、地址分区、RF/guard 的变量、相对极性与别名组相同。原始表示仍有 6 个端点改名、6 条 guard 记录改变诊断行号；调用帧及 GOTO 位点也有变化。完整附件保留每个对应项，包括这四个搬入新函数的释放事件。[两版完整声明](evidence/stage-11a/real-declarations.json.gz)

**直接从同一份布尔赋值取证。** 从 P1 SAT 模型中解码出三个已使能的计数写和两条选中 RF。令 `S` 为 R1 获取读锁时的写，`Dread,Dwrite` 为 R1 的释放读／写，`Aread,Awrite` 为 R2 的获取读／写。两次读都选择 `S`；R2 的获取始终是原子的。独立枚举器对五个事件的所有排列检查实际先后、RF 和块连续性。P1 只剩

```text
S  Dread  Aread  Awrite  Dwrite
```

P2 把 `Dread,Dwrite` 也放进一个连续块。两个读改写块无论谁先执行，后一个读都会看到前一块的写，无法仍读 `S`，合法顺序为零。该投影保留了两条 RF 的来源，任何满足全图的执行投影后都必须满足它，故可用来排除**该赋值**。它不能单独排除 P2 的所有其他赋值。用同一原生库提交这两张投影图，分别得到 SAT 和 UNSAT。[投影、唯一顺序与九步矛盾证明](evidence/stage-11a/real-delta.json) · [原生对照](evidence/stage-11a/native-verdicts.json)

**独立检查整个源码查询。** 另外将冻结源码中的两个写者、两个读者、获取／释放函数和原断言逐项翻译为 SC 状态机。入口校验完整源码指纹与关键函数正文。共享访问按操作交错，命名原子函数整体执行。静态零初始化；失败的 `assume_abort_if_not` 终止该前缀，将这类边视为无法继续。允许 main 先按原顺序创建全部线程、最后 join，覆盖源程序每个可达的工作线程交错；反过来，任何此类交错都可以在四次创建后调度。对已完成线程和无后续共享影响的局部值做状态合并。[状态机与源码检查](../scripts/stage11a/lock.py)

| 独立状态遍历 | P1 | P2 |
|---|---:|---:|
| 可达状态 | 853 | 321 |
| 可执行转移，含断言失败边 | 1,506 | 532 |
| 可到达原断言失败的转移 | 18 | 0 |
| 锁计数／互斥不变量失效的状态 | 400 | 0 |

P1 的最短失败轨迹有 16 步。R1 先在读者计数为 1 时算出待写回的 0；R2 此时成功获取读锁；R1 才把 0 写回。写者由此进入，在 R2 两次取值之间把 `x` 改成 3，断言观察到不同的值。计数是状态图上的边数，同一边可能有多条前缀。P2 的原子递减保持 `r = 活动读者数`，`w` 跟踪活动写者，读写互斥。每段重叠读临界区内 `x` 保持不变，写 `y` 的读者都写该值，每个读者在自身读 `y` 前已写过它，故原断言成立。这项结论限于这份冻结程序、固定线程数及这里的 SC／原子函数解释。P2 在 GCC 严格处理隐式函数声明时的已知诊断仍见预实验。[所有状态计数与最短轨迹](evidence/stage-11a/read-write-lock.json) · [预实验的性质与编译记录](svcomp26-repair-pilot.md)

## 有限图、文献反例与原生复现

| 实验 | 方法及结果 |
|---|---|
| 672 张小图，6,432 次有向修改 | 4 个固定事件，遍历 16 种静态边子集、7 种非空 RF 来源域、3 种 guard、2 种 APO。分别比较 2,688 次顺序、1,728 次 RF、1,344 次 guard、672 次原子修改。候选程序带入旧证明，参考程序从头排列活动事件并逆向查最近同址写。逐项比较结果中的 guard、RF 和完整顺序。模型集合分歧 0；更新后闭包与冷建规则闭包的事实集合分歧也为 0。[生成域与计数](evidence/stage-11a/finite-suite.json) |
| 13 个定向修改 | 覆盖加删边、替换 RF、反转 guard、PO/APO 改型、拆并块、增删／改名／重排事件、关闭路径中点及改变类型。每例存两张完整图、精确差分、失效工作量及区别两版的见证（若存在）。含删错旧证明后找回替代路径。语义拒绝项和有符号绑定实验另存。[修改与证明](evidence/stage-11a/edit-cases.json) · [无法准入的图](evidence/stage-11a/refusals.json) · [绑定与负例](evidence/stage-11a/literal-bindings.json) |
| TACAS 图 1 | 独立枚举得到 4 个严格序，全部要求 `rx3 < wx2`。重新饱和可给出该边的证明。固定库接受原图，额外指定相反方向后拒绝。这个结果检验论文图 1 的必要后继关系。[模型与推理链](evidence/stage-11a/literature-histories.json) · [原生逆序日志](evidence/stage-11a/native/tacas-reverse.stdout) |
| FM 图 3(b) | 18 个事件、6 个线程、8 条指定 RF。只跑正向传递、FR、WS 规则有 60 个有序对且无环。独立的按线程前缀搜索穷尽 1,179 个不同状态，无合法严格 SC 顺序；两个可选 `z` 写序均存有成环证明。固定原生库在一次补全中加入 5 条 CO 子句，发生 2 次冲突，返回 UNSAT。不能把论文中缺少总写序的规则集直接视为固定版全部算法，也不能由单图推出固定版对严格 SC 全域正确。[独立证据](evidence/stage-11a/literature-histories.json) · [固定原生日志](evidence/stage-11a/native/fm.stdout) |
| 连续 solve 排名污染 | 使用阶段 10 原二进制新跑 `--same-graph`。同一 `batch_total` 输入交替 assumptions 的 7 轮与 fresh 的 SAT/UNSAT 全部一致，第 1、4、6 轮（从 0 计）UNSAT 后调用方仍持有上一轮的 23 个键。另一组同一非空图连续两次 SAT，返回向量由 `obj#1,obj#2` 翻为 `obj#2,obj#1`，外部表对这两个键的值却两次都是 `0,1`。复现的是输出状态污染，没有观测到这 7 轮的真假判定分歧。[原始 TSV](evidence/stage-11a/native/rank/unchanged.tsv) · [双 SAT 对照](evidence/stage-11a/native/rank/rf-direction.tsv) · [逐轮原始边界与跟踪](evidence/stage-11a/native/rank/details.zip) |

参考枚举器只依赖 Python 标准库，不导入原生传播或候选推理。它按定义枚举排列并确定实际 RF；候选程序按 RF 分支逐步重放旧证明、重新饱和，然后以合法前缀扩展。完整的严格序检查保留在两条独立路径上。18 事件的参考搜索使用记忆化，线程 PC 与每址最后写完整决定剩余转移。本阶段没有以运行秒数或操作计数申报加速。[参考枚举](../scripts/stage11a/reference.py) · [候选规则](../scripts/stage11a/candidate.py) · [文献图与独立前缀检查](../scripts/stage11a/literature.py)

## 八项审查结论

1. **复用判据已建立。** 可以共享经语义对齐的静态声明，并在 P1 重放所有叶子均成立的条件证明。全新布尔输入的等同性不足以认证理论上下文。
2. **有证明的部分**包括有限严格 SC 的总序刻画、正向规则可靠性、按证明 DAG 迁移、支持失效后重新饱和，以及带已认证前提的 resolution。理论冲突子句在 P1 的充分条件是对其反面假设重新证明矛盾。
3. **有限验证的部分**包括候选代码的组合行为、实际固定库在五份理论输入上的行为、循环传播与动态 CO 在特定图上的作用。原生所有控制路径、严格 SC 的全域等价以及任意源码的事件匹配均未获证明。
4. **整图重建条件**包括未知事件／存储别名、含义未证的 guard／RF／CO、未知 APO 来源或拆分且没有完整依赖索引、根层和队列来源不全。已有阶段 10 的生产基线仍按原生能力重建运行期图。理论上具备依赖索引时，已知边增删及局部块变化可局部重算，但所有远端受影响结论均须失效。
5. **可以只保留部分推理。** 只把条件证书带入新世代，在新对象内核验、重绑定，再决定本轮是否可传播。旧根、旧冲突标志、输出和内部引用随原世代终止。阶段 5 的真实证书已做有效、删前提失效、只改诊断元数据三项复核。[冻结证书复核](evidence/stage-11a/stage5-replay.json)
6. **与 MiniSAT 的连接**需要有符号稳定身份、版本 activation literals 和逐轮 assumptions 同时覆盖 Boolean 与理论解释；含理论原因的 CDCL 子句需要完整解析／最小化证据或 P1 重新证明。相同 CNF 下可构造旧纯 Boolean 文字结论在 P1 失效的实例。[真值表和反例顺序](evidence/stage-11a/mixed-cdcl.json)
7. **严格 SC 结论的假设**包括活动读的唯一最新同址写、写序全序、地址粒度、正确的 guard 与原子区连续性、正确的初始化和线程事件。固定源码还会从数组更新、同指针和同源行建立 APO；race 专用路径跳过写序补全。这些假设改变须重新验证，本文未改变项目语义。
8. **预计节省的工作**是重复路径、FR/WS 推导和已有理论矛盾证明。6,432 次定向比较累计保留 58,160 次事实，其中 15,344 次含派生父项；15,584 次旧事实失效。数字跨试验累计，不能外推墙钟收益。11B 需实测审核、失效和补传播的总成本。[拟议接口、复杂度及回退策略](evidence/stage-11a/design-11b.md)

## 复现与交付

干净检出本分支后，从项目根运行下列命令。Python 3.10 或更新版本即可。脚本从已提交的预实验压缩归档按哈希取实际采集的声明及赋值，重新跑枚举、源码搜索、证书、差分，校验 11 份结构化证据。`--compare` 会比较JSON 的完整内容、压缩 JSON 解压后的内容和提交清单中的 SHA-256，原生结果由已提交的原始日志核对。[离线重放入口](../scripts/stage11a/run.py) · [证据与源码散列清单](evidence/stage-11a/manifest.json)

```bash
python -B scripts/stage11a/run.py runs/stage-11a-replay --compare
```

需重新执行原生实验时，使用阶段 10 的 Linux 工作树、固定静态库和 `final`（含 `build/solver-session`、`formal/batch_total/01/F/old`）。脚本先校验阶段 10 工作进程指纹，再运行交替 assumptions，编译隔离的研究驱动并运行五份声明。输出写入新目录；下面第二条使用新产生的 TSV 和 stdout 再核对正式结果。时钟和进程级观测的原始字节可随运行改变。[原生复现脚本](../scripts/stage11a/reproduce_native.sh) · [实际库与二进制指纹](evidence/stage-11a/native/control.sha256) · [阶段 10 环境复原](stage-10.md)

```bash
bash scripts/stage11a/reproduce_native.sh "$NATIVE10" "$STAGE10_FINAL" "$PWD/runs/stage-11a-native"
python -B scripts/stage11a/run.py runs/stage-11a-native-review --native runs/stage-11a-native --compare
```

[完整数学定义与 A–I](evidence/stage-11a/formal.md) · [四篇文献、源码与证书映射](evidence/stage-11a/source-map.md) · [11B 设计草案](evidence/stage-11a/design-11b.md) · [全部原始证据](evidence/stage-11a)

阶段 11A 到此停止，提交审查。下一阶段的算法实现、性能实验及合并均待进一步批准。
