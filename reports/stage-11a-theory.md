# 阶段 11A-T · Deagle Closure 并发理论图跨版本更新的理论研究

**READY_FOR_REVIEW**　审查分支 *stage-11a-theory-deepening*

本阶段得到一个允许删除和替换的闭包等价定理。研究对象是有限、有类型的正向 Ordering Consistency 规则子集 $R$。在事件及文字语义匹配可靠、声明和动态前提差分完整、能够查全受影响的规则实例时，对旧闭包做过删除、从边界重推，再传播新增事实，恰好得到在 P1 对同一 $R$ 从头推理的全部结论：

$$
U_R(C_0,\Delta^-,\Delta^+,\Gamma_0,\Gamma_1)
  =\operatorname{Cl}_R(D_1,\Gamma_1).
$$

该等式比较语义事实集合。允许一次修改同时改变 PO/APO、RF、guard、CO 或原子块，前提是相应的成员资格、解释和规则域变化完整进入差分。**固定原生 ClosureSolver 全部过程的闭包等价及严格 SC 正确性尚未证明。** 现有源码足以确定若干推理的方向，也显示了独立的预防传播、根层处理、按需 CO 和模式相关的终局判断；从这些过程到本规则集没有一般的双向精化证明。[完整语义和源码对照](evidence/stage-11a-theory/formal-semantics.md) · [T1–T8 证明](evidence/stage-11a-theory/theorems-and-proofs.md)

固定前置成果为阶段 10 的 [dca9eb7](https://github.com/ChenKaichen-SCUT/Deagle_incremental_execution/commit/dca9eb78250426fe5b2aab22aea5ef91025dd24d)、SV-COMP 预实验的 [ff43453](https://github.com/ChenKaichen-SCUT/Deagle_incremental_execution/commit/ff434538e5eaa78cf8c5e93eb3e41a7ccf06a5ff) 和本分支直接父提交、阶段 11A 的 [1099958](https://github.com/ChenKaichen-SCUT/Deagle_incremental_execution/commit/1099958b12ff0b0c4ca7b2e6334ef82700d337b4)。本次提交只包含理论文稿，未开展实验或工程实现。

## 删除后如何保证完整

将有效基础记为 $A_i$，具名的规则实例记为 $H_i$。同一结论可能有多份证明。$F_0$ 包含旧闭包中**所有体均已满足的实例**，因此也包含当时没有带来新结论的替代实例。删去的叶或已触发的旧实例会使其旧结论及后代进入过删除区 $O$。余下的 $K=C_0\setminus O$ 直接供本轮使用。沿旧证明的严格下降秩归纳可知，每个保留项仍有一份 P1 的有限证明；互相支持但没有基础的环无法通过该归纳。

随后补回新增基础以及仍有效却被过删除的基础，检查新增实例和所有能生产脏结论的 P1 实例。再由每个首次加入的事实触发其 P1 消费者。证明完整性的关键是穷尽任一终态可用的规则：若它有新抵达的父项，最后一个这样的父项会触发它；若父项全在 $K$，它要么属于初始边界，要么是头已经在 $K$ 的旧实例。因此终集包含基础且对 P1 全部规则封闭。另一方面，每次加入均有 P1 有限证明。用最小闭包的两向包含得到 T4。这一步补足了仅凭旧证明重放无法得到的“不会漏掉任何 P1 推导”。[增量演算、边界及连续更新](evidence/stage-11a-theory/incremental-calculus.md)

**真正利用旧派生事实的一个修改。** 在一条任意长的活动线程链上，只给出相邻结构边。首尾是同址写 $W_x,V_x$，中间事件访问不同单元。旧推理已经得到 $W_x<V_x$。线程外另有读 $r_x$，P0 中不活动。P1 使它活动并选 $W_x$ 为来源。同时，在不相连的另一组中，把一个读的旧来源替换成另一个同址写。基础语义及规则取正文的 $R$，各块是单点。第二组撤销旧 RF，必要时撤销其派生先后；旧图中没有从这些失效前提到第一条链的已触发规则，且旧 $r_x$ 没有选源。第一条链的派生先后遂留在 $K$。新 $\mathrm{RF}(W_x,r_x)$ 和已保留的 $W_x<V_x$ 立刻启用 FR，推出 $r_x<V_x$。这条新结论实际使用了稳定区中的旧推导，恢复不必重新遍历整条链。若完整地面化或语义比对本身要扫描全图，不能从这个推导例子推出端到端加速。[复杂度条件与最坏情况](evidence/stage-11a-theory/limits-and-counterexamples.md)

## 理论证明审查表

| 验收项目 | 审查结论 | 依据 |
|---|---|---|
| 语义定义 | 分别定义严格 SC 模型、各文献公理、选定 $R$、固定原生程序行为；区分六层声明、条件与状态 | [形式语义 §1–4、6](evidence/stage-11a-theory/formal-semantics.md) |
| 增量规则 | 给出具名实例、完整域前提、旧已触发依赖、撤销集和 P1 恢复边界；稳定的内部实例无需重放 | [演算 §1–3](evidence/stage-11a-theory/incremental-calculus.md) |
| 正确性 | 语义匹配有逐项义务，任意深度的旧有根证明均可按条件运输 | [T1、T2](evidence/stage-11a-theory/theorems-and-proofs.md) |
| 删除与替换 | 覆盖删除、替代支持、共享子证明、无根循环；未知身份可按旧删新加，依赖无法穷尽则拒绝 | [T3](evidence/stage-11a-theory/theorems-and-proofs.md) · [反例 §1–2](evidence/stage-11a-theory/limits-and-counterexamples.md) |
| 等价性 | 可靠性给出终集包含于 P1 冷闭包，边界触发与封闭性给出相反包含 | [T4](evidence/stage-11a-theory/theorems-and-proofs.md) |
| 原子块变化 | 并拆及改型须重核相交块、内部方向、异块前提和所有远端影响。无法确认隔离时，整图冷建 | [T5](evidence/stage-11a-theory/theorems-and-proofs.md) · [拆块构造](evidence/stage-11a-theory/limits-and-counterexamples.md) |
| 理论冲突 | 若能证明 $B_1\land T(D_1)\land\neg L$ 矛盾，则可无条件保留 $L$；额外假设必须解除或保留在前件 | [T6](evidence/stage-11a-theory/theorems-and-proofs.md) |
| CDCL 学习 | 对每个理论、布尔及根层前提，解析及最小化步骤审证；证明区分条件和无条件结论。相同 CNF 有明确反模型 | [T7](evidence/stage-11a-theory/theorems-and-proofs.md) · [混合子句反例](evidence/stage-11a-theory/limits-and-counterexamples.md) |
| 求解结果 | T4 只保证传播闭包相等。T8 对有限、完整 RF 和总 WS 选择给出严格 SC 构造证明；程序性质另需编码双向正确 | [T8](evidence/stage-11a-theory/theorems-and-proofs.md) |
| 复杂度 | 明计身份匹配、规则域变化、受影响关联和显式输出。给出局部常量对冷建线性的条件族、二次方失效和指数替代支持族 | [理论成本 §6](evidence/stage-11a-theory/limits-and-counterexamples.md) |
| 原生适用范围 | 已识别规则可用于核实对应数学推论。未授权沿用原生根、动态 CO、未经证明的学习子句、trail 或排名 | [适用域与精化义务](evidence/stage-11a-theory/scope-and-completeness.md) |

## 停止条件

S1 将原生承诺截在可识别的局部规则。S2、S4 要求显式给出全部语义前提、被删支持和恢复边界。S3 由 T4 在已声明片段内满足。S5 由 T6、T7 的逻辑蕴含和条件作用域约束。S6 所要求的非平凡、可删改、局部且闭包等价的受限子类已经建立。该结论的证明不使用阶段 11A 的枚举统计。

五份独立文稿分别给出[形式语义](evidence/stage-11a-theory/formal-semantics.md)、[增量演算](evidence/stage-11a-theory/incremental-calculus.md)、[定理与证明](evidence/stage-11a-theory/theorems-and-proofs.md)、[极限与反例](evidence/stage-11a-theory/limits-and-counterexamples.md)以及[完整性与未证命题](evidence/stage-11a-theory/scope-and-completeness.md)。按 S7 到此停止，等待审查。阶段 11B 尚未启动。
