# PI-0　持续 MiniSAT 与可切换 Closure 的接口预检

**DESIGN_FEASIBLE · READY_FOR_REVIEW**

固定上游的 ClosureSolver 可以在同一 Boolean 公式的一次 assumptions 查询返回 UNSAT 后，继续对下一次查询返回 SAT。跨版复用需要在根层简化前保护输入，把理论初始化和搜索理由纳入作用域，并单独管理 Closure 工作图的生命周期。原版构建、三个 stock 检查和四例规模统计均已完成。当前分支的会话代码是通过 C++11 编译检查的接口声明。持久会话、跨版命中和性能闸门均留待审查后的阶段。[机器状态](PI-0-status.json) · [设计、生命周期图和源码入口](../docs/design.md)

## 基线与现场

本次消息点名 PI-0。所列附件 `deagle_SI_1_stable_identity_guide.md` 规定的是 SI-1 阶段。实际依据为同一下载目录的 `deagle_PI_persistent_minisat_closure_guide.md` 第 7 节 PI-0，文件 SHA-256 为 `b3db574dd0d7eea2888c7ad8edfd8c9f7d1fc10ad364472763b7a760ead93f7d`。

| 项目 | 本轮固定值 |
|---|---|
| 官方上游 | `thufv/Deagle@d8c79eaba5df03b1a013dc6ffbb3a1e249485c1e`，树 `ee983048136026478a6af5774ab20077b273db2f`。官方提交与本地对象一致 |
| 开发 | `D:/Deagle_persistent_solver`，新分支 `codex/persistent-minisat-closure` 从上游直接分出。源码骨架、配置与原始证据提交 `245aaefa1019ea2bcc37bdb38454fc69f46fb39c` |
| 冻结输入和独立检查 | 通过 Git 对象读取研究提交 `d764b47976574a9302dd82bb9442b0e62c7466fa`。另存既有工作树和分支头，SI 路线冻结提交为 `86bbdfa88574d09cfa13637294b039c57cd7fd89` |
| 构建 | WSL2 `Deagle-Jammy` 的新 detached 工作树 `/home/deagle/pi0-stock`，初始 `git status --porcelain` 为空。Ubuntu 22.04.5、G++ 11.4.0、GNU Make 4.3、C++11、`-O2`，执行 `make -C src -j12 cbmc.dir` |
| 结果 | 构建 80.16 秒。新 ELF 共 16,108,880 字节，SHA-256 `f8c08f379f3777f7ef36e197346e6fdcef3fa57aa71c35f40d7ef587010ed7ab`，与独立 D0 stock 的摘要一致。构建回执记录了 ClosureSolver、Closure、ClosureTypes、Solver 和 SAT 适配器的目标文件与链接结果 |
| 主机 | Windows 11 build 26200，i7-13700F。WSL 可见 16 个逻辑 CPU、30,802,092 KiB RAM、32 GiB swap。检查进程绑定 CPU 0。预检时 ext4 可用约 843 GiB，D 盘约 253 GiB，E 盘约 25 GiB |

[官方提交](https://github.com/thufv/Deagle/commit/d8c79eaba5df03b1a013dc6ffbb3a1e249485c1e) · [构建回执与实际 flags](evidence/pi0/stock/build.json) · [原始 make 日志](evidence/pi0/stock/build.log.gz) · [Windows 与工作树](evidence/pi0/environment-windows.json) · [WSL](evidence/pi0/environment-wsl.txt)

## stock 性质、展开与见证

保持原命令、输入哈希和配额，每次使用新建模型和本轮构建的 stock。每个进程各有一条原生性质和一次完成的 Closure 查询。核对完整性质对象时只忽略临时工作目录的绝对路径，完整原文保存在压缩 stdout 中。退出码、目标、展开迭代、展开告警、反例步数及确定性搜索计数与 D0 一致。

| 输入 | 原生性质与结果 | 退出码 | 冲突 / 决策 / Boolean 传播 | 理论传播 / 环 | 墙钟秒 / 峰值 KiB |
|---|---|---:|---:|---:|---:|
| worker_violation | `worker.assertion.1` FAILURE，SAT，66 步见证中先写入 `flag=1` | 10 | 0 / 140 / 624 | 3 / 0 | 0.058 / 15,488 |
| fib_updates_8 P0 | `main.assertion.1` FAILURE，SAT，187 步见证 | 10 | 1,442 / 7,652 / 1,103,863 | 3,708 / 25 | 0.119 / 19,584 |
| fib_updates_8 P1 | `main.assertion.1` SUCCESS，有界 UNSAT | 0 | 22,702 / 60,369 / 28,170,688 | 7,979 / 23 | 2.010 / 29,056 |

两端均启用展开断言，两条工作线程循环各记录第 1 至 8 次迭代，未报告展开不足。独立重放 P0 的 16 次原子更新得到 `left=2815, right=1723`。对两个线程的 12,870 种交错独立枚举，P0 最大分量为 4,180，P1 为 2,584，恰好达到原断言上界。三个 stock 控制串行执行，空图诊断探针的编译与该组检查并行发起。单次 stock 墙钟只用于运行核对。[检查及见证投影](evidence/pi0/stock/checks.json) · [P0 完整性质与展开](evidence/pi0/stock/fib_updates_8/P0/result.json) · [P1 完整性质与展开](evidence/pi0/stock/fib_updates_8/P1/result.json) · [小例原文](evidence/pi0/stock/smoke/worker_violation/smoke/stdout.gz)

同一固定公式 `x ∨ y` 的原生探针在 `¬x,¬y` 下获得两个文字的失败核心，`okay()==true`。随即仅假设 `¬x`，得到模型 `x=false,y=true`。随后加入真正的永久空子句才出现 `okay()==false`。探针链接未修改的 `solvers.a`，全程使用同一个空理论图。另一个只检验设计语义的两事件枚举捕获了删除静态 PO 后误留无条件旧理由的反例。[原生探针](evidence/pi0/stock-probe.txt) · [有限枚举](evidence/pi0/contract-examples.json)

## 每条规范 CNF 一个 selector 的规模

计数来自四例两端共八份已封存的首查询模型。先按 B/Q 分开，比较完整排序后的带符号文字，保留原始 occurrence 数、去重数、空句、单位句和目标。归档覆盖了进入原生输入观察点的 CNF。前端更早消去的真式不需要安装。四例各端都是一个实际查询边界，原始 MiniSAT assumptions 均为空。历史对照的这一边界含目标及三项展开性质，继续标为 `INCOMPLETE_UNWINDING`。[逐模型计数、完整路径和摘要](evidence/pi0/scale.json) · [计数脚本](../scripts/selector-census.py)

| 病例 | P0 唯一 B / Q | P1 唯一 B / Q | P0 / P1 原生图边 | P0 assumptions 估计 | P1 仅当前图与输入 | P1 联合库估计 |
|---|---:|---:|---:|---:|---:|---:|
| fib_updates_8 | 47,493 / 2,560 | 45,757 / 2,560 | 386 / 386 | 50,055 | 48,319 | 63,140 |
| circular-buffer | 1,160,134 / 1,833 | 1,161,265 / 1,833 | 3,129 / 3,129 | 1,161,969 | 1,163,100 | 2,324,675 |
| airline_reservations_6 | 866,692 / 44,021 | 243,406 / 44,021 | 931 / 481 | 910,715 | 287,429 | 1,195,185 |
| fib-snapshot-11，历史 | 1,001,471 / 714 | 1,001,473 / 714 | 6,454 / 6,454 | 1,002,187 | 1,002,189 | 1,944,096 |

**实测与估计的边界。** 两端各观测到一个静态图上下文。四对本地有序图流的摘要均不同，语义相等仍须在统一命名空间内认证。EPOCH 估计按每版一个 epoch 和一个查询控制量，加上每条唯一 B/Q 的 selector。联合库包含启用和停用两种符号的 assumptions。本估计保守地为新版查询和图各分配新控制量，Q 内容只在本版查询内去重。按已封存 SI-1B 直接 μ，对旧 B 逐文字翻译并比较 P1 完整子句，四例可共享 B 分别为 35,234、394、2,959、60,280 条。历史查询专用重编号经隔离检查，未参与 B 共享。上述 μ 只用于离线估算。[估计口径](../scripts/selector-census.py) · [两版约束契约](../docs/design.md)

| 病例 | P0 结构小计 MiB | P1 联合库结构小计 MiB | 普通原子全用 fresh 时 P1 assumptions / MiB |
|---|---:|---:|---:|
| fib_updates_8 | 7.4 | 9.3 | 98,374 / 14.5 |
| circular-buffer | 171.5 | 343.1 | 2,325,069 / 343.1 |
| airline_reservations_6 | 134.6 | 176.7 | 1,198,144 / 177.2 |
| fib-snapshot-11，历史 | 147.9 | 286.9 | 2,004,376 / 295.8 |

布局由 stock 编译器实测，Lit、CRef、Clause 头各 4 字节，Watcher 和 VarData 各 8 字节，watch vector 头 16 字节。结构小计按根简化前的 guarded Clause、两个 watcher 与一个原始 CRef、每个 selector 的原生数组、一个 assumptions 向量、全部安装时的六个层边界数组，以及拟用的每条 registry 16 字节索引和一份文字载荷计算。Q 子句另含查询控制文字。以 circular-buffer 联合库为例，六个层边界数组就约 53.2 MiB。普通程序变量、额外容器容量、哈希表、学习数据库、活动理论图及前端内存均在小计之外。根简化、提前冲突和实际分配策略会改变占用。持久会话峰值 RSS 和 assumptions 墙钟尚待实测。[原生布局](evidence/pi0/stock-probe.txt) · [按结构列出的字节数](evidence/pi0/scale.json)

## 冻结的接口与实验边界

最先需要接通 `satcheck_minisat2_baset::lcnf/add_variables/do_prop_solve` 的事务收集、`ClosureSolver::set_graph/search/propagate/apply_literal_assignment` 的受保护出口、`addMissingCoClauses` 的统一分配，以及 `cancelUntil/newDecisionLevel` 与工作图代次的同步。尤其要覆盖 `set_graph` 两个直接写 `ok=false` 的入口和 `use_available_info` 在 assumptions 之前的提前返回。首次封存应晚于 `finish_eager_conversion`。详细文档逐项给出理论局部前提、EPOCH 后备、GC、失败回滚和结果所有权。[设计与源码清单](../docs/design.md) · [逐行原生审计](evidence/pi0/native-sites.json) · [最小代码骨架](../include/session_contract.h)

后续三轮配对的四臂为 Stock、Reset-active、Reset-union、Persistent。病例与每轮执行顺序已逐行封存。三例真实修复分别保留 64/32/64 位、展开 10/8/8，历史对照保留 32 位、展开 25。每臂支付本轮 P0，新增 P1 模型只在 P0 完成后可见。固定 CPU 0 串行执行，原生失败、超时、UNKNOWN 与冷建单列。P1 包含完整前端、身份/差分、安装切换、假设与理论重放、搜索、结果与见证。双版本周期再计入 P0、启动和关闭。冻结模型和 μ 的后端诊断单列成本，详细审计不得与生产配对计时并行。[逐文件 SHA、命令、资源限额、轮序与计时边界](../configs/frozen-pairs.json)

工程门槛要求至少一个真实修复相对 Reset-active 的同边界 P1 配对中位数同时节省 5% 和 0.2 秒，三轮至少两轮改善，并且相对可比 stock 后端仍有正预算。生产完整 P1 与两版周期相对独立 stock 按同一门槛分别判断。L1 正确性、L2 原生驻留及实际使用、L3 跨图局部混合命中各自审查。现阶段 resident、active、hit 和持久化性能字段均未实测。[预注册门槛](../configs/frozen-pairs.json) · [当前阶段状态](PI-0-status.json)

**停止点。** 接口有具体实现路径，值得首先验证受保护的输入、初始化理由与切图后的联合传播。百万级 assumptions 能否承受、动态 CO 能否完整恢复、旧混合学习能否跨变更图起作用仍待验证。已预注册的 PI-1 assumptions 边界微测只做激活、传播、回退，单列层数、图重放和 RSS。本次没有启动该阶段。

## 复核与复算

以下命令在 WSL 的固定工具链执行。`pi` 指本交付目录，`repo` 指持有两个固定 SHA 的研究 Git 对象库。第一组使用已封存输入做离线复核，最后一组单独复建 stock 并重放三个预检进程。原始 argv、环境、输入摘要、退出码、stdout/stderr 哈希、完整性质和搜索累计数随各次回执保存。[原始证据与 SHA-256 索引](evidence/pi0/files.json)

```bash
export LC_ALL=C PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1
pi=/mnt/d/Deagle_persistent_solver/persistent-solver
repo=/mnt/e/Deagle_incremental_execution
out=$(mktemp -d)
python3 "$pi/scripts/verify-evidence.py" "$repo"
python3 "$pi/scripts/selector-census.py" "$repo" "$pi/reports/evidence/pi0/stock-probe.txt" "$out/scale.json"
cmp "$out/scale.json" "$pi/reports/evidence/pi0/scale.json"
python3 "$pi/scripts/source-audit.py" "$repo" "$out/native-sites.json"
cmp "$out/native-sites.json" "$pi/reports/evidence/pi0/native-sites.json"
python3 "$pi/scripts/contract-examples.py"
g++ -std=c++11 -Wall -Wextra -Werror -pedantic -x c++ -fsyntax-only "$pi/include/session_contract.h"

bash "$pi/scripts/build-stock.sh" /home/deagle/dependency-reuse/upstream "$out/stock" "$out/build"
python3 "$pi/scripts/stock-check.py" "$repo" "$out/stock" "$out/build" "$out/controls"
g++ -std=c++11 -O2 -I "$out/stock/src" -I "$out/stock/minisat-2.2.1" "$pi/scripts/stock-probe.cpp" "$out/stock/src/solvers/solvers.a" -o "$out/probe"
"$out/probe"
```

预检配置 SHA-256 为 `dd126402f522354967550e43ae95586ec39d2bfe838b1bd81a64fb43d10f494e`，原始证据索引 SHA-256 为 `44b1609683edbd35b6e8dc19f646580e6fe767955fcedc84b4ce8818e19903e7`。审查提交是本报告与状态回执的共同提交，父提交固定本报告引用的实现与数据。
