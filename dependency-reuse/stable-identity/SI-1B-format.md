# SI-1B 身份目录与复算

## 生命周期

每对输入先由 `si1b_sources.py` 在原生编码前保存 `source-catalog.json` 与两个 `P*.tokens`。逻辑文件名属于冻结的暂存清单。文件字节摘要用于校验。首次编号取自 P0 的独立命名空间，P1 新增节点使用分离的命名空间。仅在补丁重放认证的 token 区间、词法父作用域和降低角色都能延续时继承。相邻不可区分副本、宏及行号重定向保守处置。已预处理的 `.i` 直接使用冻结字节，含预处理指令的 `.c` 按 ABI 收集 GCC 定义过的宏名。源目录中保存了命令和宏集合摘要。

原生进程使用 `DEAGLE_SI1B_CATALOG` 和本侧的 `DEAGLE_SI1B_TOKENS`。GOTO 指令携带独立来源字段。注册表、表达式语法和模板均置于原生表达式之外。执行上下文通过父线程出生、调用位置、所在线程中的循环发生和当前站点描述。局部 SAT 编号、缓存地址、模板编号和 SSA 展示名只用于本次实际绑定。出生、重复位置及其父实例不能唯一确认时，依赖它们的端口失去认证。

原生适配器在第一次查询的根边界写出目录。登记随即关闭，原生求解继续。原生缓存可以比模板活得短，销毁或重建会解除本地句柄绑定。为支持稍后的连接，影子目录保留已冻结的旧模板、值和已发生的 owner 关联。当前实现将这部分内存保留至进程退出。审计模式可额外保存访问顺序，并在根边界退出。

## 原生二进制 SI1BIN01

头部为八字节 magic、32 位字节序标记 `0x01020304`、字符串个数。每个 UTF-8 串前存放 32 位字节数，0 号串为空。然后写入总 word 数和类型化记录，尾部为 `SI1END01`。本版在固定 Linux 小端 ABI 下使用 32 位无符号 word。每行由一个 ASCII 类型、负载 word 个数和负载组成。C++ 编写器与 Python 解码器分别检查实际输出及目录边界。[原生写入器](../../src/util/stable_identity.cpp) · [读取器与认证规则](../scripts/si1b_catalog.py)

| 记录 | 实际内容 |
|---|---|
| D / O / I | 类型检查声明及其词法位置、降低来源与父角色、最终 GOTO 站点 |
| X / b / V | 当前站点及其线程、调用、循环上下文，SSA 出生，实际定义和事件来源 |
| J / W / E | 带类型的结构、语义属性、操作数与本地表达式。源调试位置从类型结构中剔除 |
| K / M / Q / q | 位宽、成员偏移和宽度、填充及引用类型，本次实际地址对象和保留编号 |
| U / T / A / C | 转换 owner、转换模板、owner 到模板的引用、带操作数位置和转换域的直接子模板引用 |
| L / P / R / h | 模板实际返回值、内部 lowering 路径、角色到本地值、命中模板的次数 |
| B / F / H / G | 原生已命名 Boolean 或 BV 返回值、RF 创建方向和名称、安装时的 RF 端点及核验标记、安装的事件 Guard |
| N / Z / Y | 连续原子分配及所属转换、封存时的上界及 ABI、审计专用命中／未命中访问 |

普通变量的有符号值为 `2*v+sign`，0 号变量保留。常量按原生 32 位读为 `-1` 或 `-2`。模板成员缺失、有歧义或没有认证路径可单独报告。缓存命中共用先前实际返回值和内部角色表。对于数组下标的自由输出，证书还要求数组来源、类型、下标表达式和相应 owner。无法识别的直接子模板关系保留本地诊断。根目录的 SHA-256、字节数、ELF、配置、输入及 token 校验值均在 `seal.json`。本格式是 SI-1B 影子研究格式。

## 带符号直接连接

两版的完整 typed tuple 进入同一个 interner。外层为执行实例、定义／读取角色、对象、布局和具体位。内层还需表达式、操作数、宽度、符号及真实编码分支。两个原生模板必须能从同源 owner 到达。配对模板惰性访问并去重，按实际返回位或内部角色发出提案。跨版本实际文字对 `(x,y)` 对正变量的提案为 `(x//2, y XOR (x&1))`。

同键多值、拆分、合并、相反极性、常量与变量转换、理论绑定不一致会污染整个连接分量。理论原子必须保有全部同名同向 RF 与带符号 Guard 绑定。指针编码的对象位要求整个本版编号目录具有可认证且一致的解释，offset 位仍需认证存储来源和 ABI。struct 避开填充，union 只认证所有重叠视图均能解释的数值位。[直接连接](../scripts/si1b_join.py) · [独立端口读回](../scripts/si1b_witness.py)

每例 `join/direct-map.tsv.gz` 包含旧变量、正文字的新带符号像及见证键。`typed-keys.json.gz` 的下标为这一对模型内部的完整键引用。`P0-ir.json.gz` 和 `P1-ir.json.gz` 连接原生站点、事件及上下文。`P*-atoms.tsv.gz` 覆盖包括拒绝项在内的全部本地变量。`audit/coverage.tsv` 逐类给出五种互斥对照处置。旧 μ 和 UsedLeaf 仅由独立比较脚本读取。

## 复算

在 Linux / WSL 的工作树中可直接从 Git 证据复算。命令会校验文件、重建四份带符号映射、逐项解析所有见证，并按每个探针实际记录的 Guard 遍历顺序还原检查流。无需运行原生求解器。

```sh
python3 dependency-reuse/scripts/si1b_replay.py dependency-reuse/reports/evidence/si1b
```

完整原生复现沿用 SI-1A 的冻结 D4.3-D 构建及还原目录。以下为 Bash 命令。令 `D` 指向含 `native` 和 `restored` 的 D 阶段目录，`Z` 为本次新建的空目录。构建驱动会校验冻结 ELF，在独立副本中编译。正式影子体只消费新目录和冻结输入，最后的历史对照单独读取 `restored`。

```sh
S="$PWD/dependency-reuse/scripts"
mkdir -p "$Z"
python3 "$S/build_si1b.py" "$D/native" "$Z/native"
ELF="$Z/native/src/cbmc/deagle_exe"
python3 "$S/si1b_native.py" control "$ELF" "$Z/accepted-controls"
d="$Z/native/src"
g++ -O2 -std=c++17 -I"$d" dependency-reuse/tests/si1b/cache_owners.cpp \
  -Wl,--start-group "$d/solvers/solvers.a" "$d/util/util.a" "$d/big-int/big-int.a" \
  -Wl,--end-group -o "$Z/cache-control-final"
python3 "$S/si1b_controls.py" "$Z/accepted-controls" "$Z/cache-control-final" "$Z/extended-controls.json"
python3 "$S/si1b_native.py" cohort "$ELF" "$Z/release"
python3 "$S/si1b_passive.py" build "$D/native" "$Z/tap-stock"
python3 "$S/si1b_passive.py" build "$Z/native" "$Z/tap-si"
python3 "$S/si1b_passive.py" check "$Z/passive" "$Z/release" "$Z/tap-stock/deagle" "$Z/tap-si/deagle"
for c in fib_updates_8 circular-buffer airline_reservations_6 fib-snapshot-11; do
  p="$Z/release/$c"
  taskset -c 0 python3 "$S/si1b_join.py" "$p/shadow/P0" "$p/shadow/P1" "$p/source" "$Z/dr/$c"
  python3 "$S/si1b_audit.py" "$c" "$Z/release" "$Z/dr" "$D/restored" "$Z/passive" "$Z/verified/$c"
done
python3 "$S/si1b_publish.py" "$Z" "$Z/evidence"
python3 "$S/si1b_replay.py" "$Z/evidence"
```

证据的 CPU、内存和超时设置在逐进程 `run.json` 中。影子成本使用完整原生运行的 CPU 0 数据，根边界观察和读回属审计。增加 `--development` 可在具备初次失败运行目录时同时封存其回执。重新编译时工作目录或工具链可能影响 ELF 摘要，比较的两侧必须来自同一次构建。
