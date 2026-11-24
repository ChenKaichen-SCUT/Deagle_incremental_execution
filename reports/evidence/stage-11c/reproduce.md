# 构建、重跑和离线审核

Linux 实验使用项目阶段 10 的补丁树和编译归档。上游源码为 a2ba2f01fcc8dc83261f614039141017fb846178。前端 SHA-256 为 b84a95d9d02e9fc48217373bf71564db1cb8ce4029644936a893aaaaef0a529e。阶段 11B 父提交为 8de2a0625649254357cd60ede7626204665b5458。11C 的三个正式可执行文件分别是原生工作进程、独立布尔证明生成器、零决策原生契约检查器。它们以及输入归档、生成的翻译单元都有 SHA-256。编译器使用 C++11 和 -O2，审核进程使用 Python 标准库和系统 sha256sum。[阶段 10 构建](../../../scripts/stage10/build.sh) · [11C 构建指纹](build.sha256)

准备阶段 10 的已构建原生树 NATIVE，恢复阶段 7 归档的 sources/ 为 SOURCES，PILOT 为本仓库中包含 cases/svcomp26 的目录。OUT 应为一个新的实验目录。脚本依次执行正式矩阵、负向控制、独立计数构建与回放、两种 batch 回归、算术多查询以及证书归档。每个正式模式均在独立控制进程中运行，同一版本对使用一个原生工作进程。每版重新启动完整 Deagle 前端。计数和机制诊断在全部正式计时之后执行。七轮统计按预定次序交替，最初五轮后给每例追加两轮，以检查时间波动。[阶段 7 归档索引](../stage-07/archive.json) · [冻结的源码及性质](../stage-11b/versions/README.md)

~~~bash
bash scripts/stage11c/reproduce.sh "$NATIVE" "$SOURCES" "$PILOT" "$OUT"
~~~

原版的应用耗时另用阶段 1 固定的 Deagle F0 二进制直接重跑七轮。其提交 a159f9923722646185ba8028610b2eef2618fa72 保留上游求解算法和项目 JSON 输出兼容补丁。脚本默认从 third_party/deagle-baseline/src/cbmc/deagle_exe 读取，也可用环境变量 F0 指定该二进制。直接运行只启用 JSON 结果出口，完整墙钟包含正常输出。为取得可比较的模型、CNF 和搜索数据，正式矩阵中的 stock 另使用阶段 10 固定二进制直接运行并采集观测。F0 与 stock 的完整命令、性质和源文件哈希均可独立核对。[F0 锁定记录](../../../configs/stage05.lock.json) · [原版逐次数据](original.json)

在已发布的仓库中可以只核验原始字节、所有签名证明、真实提交和独立严格 SC 调度。raw/files.json 将逻辑路径映射到 SHA-256。raw/parts.json 固定对象 ZIP 的拼接顺序和分块哈希。相同的输入、日志和搜索流共用内容对象。以下命令提取一个代表性的原生搜索使用记录。

~~~bash
python -B scripts/stage11c/check_evidence.py reports/evidence/stage-11c
python -B scripts/stage11c/seal.py
python -B scripts/stage11b/raw_store.py read reports/evidence/stage-11c/raw formal/fib_updates_8/1/TC/new/worker/use.tsv
~~~

每组的 old/worker/proof.log 是采集时的记录。old/library.json.gz 给出带来源的旧理论结论、混合学习 DAG 和逐个拒绝处置。new/audit.json.gz 包含各候选在 P1 的审核结果、实际使用的当前原始子句及理论叶、逐步消解、最终批准清单和对应哈希。new/worker/use.tsv 分别记录附着和第一次搜索开始后的实际用途。查看某条 P0 学习子句时，先从旧库的 mixed 项取 root，再沿 dag 的父索引查找到原始 CNF 与 theory 叶。P1 的 proofs 用同一条旧学习记录 ID。对旧库未收录的学习记录也可从 mixed_decisions 和原生 L 行恢复拒绝原因和带符号内容。

正式样本的原版独立运行在 formal 下每个病例的 0/stock。原始源文件、harness、当前模型、搜索流、进程时间及审核证据均在 raw 中。controls/negative 下的输入是明确标记的求解器接口变体，仅用于失效与回退验证。mechanism 包含单轮 batch 回归。pilot 中保留了早期构建的试跑记录，正式计时只取 formal 路径。[逐次测量](trials.json) · [全部原始路径](raw/files.json)

逐条处置清单可以用 Python 标准库 gzip 和 json 打开。清单的 learnt 按每个 P0 的原生 1-UIP 序号索引，含原始带符号结论、analyze 父来源、两版处置及在 C、TC 中的实际使用。T 单独编号环冲突，另列 T_theory。admitted-mixed.json 只展开实际导入的六条混合证明，便于人工复核。输入等价性检查逐组比较 T 与 TC 的有序理论子句，以及 C 与 TC 的有序混合子句。[逐条清单](clause-inventory.json.gz) · [实际导入的推导](admitted-mixed.json) · [离线审核结果](verification.json)

若要单独核对源码补丁，以下命令在临时目录生成 11B 源文件，应用 native.patch，补上同版 trace.hpp、sealed.hpp，再与实测构建清单逐一比对。阶段 10 的准备路径可以与正式服务器不同。源文件按 Linux LF 字节核验。

~~~bash
python -B scripts/stage11c/verify_sources.py "$NATIVE" reports/evidence/stage-11c
~~~
