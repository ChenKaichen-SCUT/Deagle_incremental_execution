# 构建、重跑与离线核验

在 Linux 上使用项目固定阶段 10 的原生源码和已编译归档。上游工作树 HEAD 为 a2ba2f01fcc8dc83261f614039141017fb846178，阶段 10 的观测补丁与冻结二进制共同构成基底。阶段 11B 的构建脚本检查前端二进制 SHA-256，将变更后的 Closure.cc、ClosureSolver.cc 和工作进程放进独立编译目录，链接同树的 solvers.a 与 util.a。正式构建不改变 Closure 类成员布局。源码补丁给出相对阶段 10 的实际改动，新头文件在 scripts/stage11b 中；instrument.py 按唯一上下文生成同一组翻译单元。完整的编译器版本、原生对象输入与生成文件的哈希在 build.json 与 raw 的 build/build.log 中。核对原始基底可使用阶段 10 的构建记录。[阶段 10 构建](../../../scripts/stage10/build.sh) · [原生构建](../../../scripts/stage11b/build.sh)

从仓库根目录运行以下命令。NATIVE 指已恢复的阶段 10 原生工作树。SOURCES 指阶段 7 已恢复的 sources 目录，其下含 fib_updates_8/fib_updates_8 与 batch_retained/batch_total。PILOT 指含 cases/svcomp26 的仓库根目录。OUT 是新的实验目录。试验启动前应确保没有其他性能作业在同机运行。

~~~bash
bash scripts/stage11b/reproduce.sh "$NATIVE" "$SOURCES" "$PILOT" "$OUT"
~~~

从 Zenodo 下载指定版本的 paper168-artifact.zip 后可独立恢复选择过程。artifact.py 读取已发布容器的历史层，不执行容器内容。panel.py 核验每个 YAML 与作者成绩表的映射并只为 13 道困难题和 3 道控制题打包。工件提取需要约 9 GB 暂存。versions.py 从这些冻结源码中恢复尝试修补的长栈任务和 ticket 规模对。

~~~bash
python scripts/stage11b/artifact.py paper168-artifact.zip "$TEMP_ARTIFACT"
python scripts/stage11b/panel.py "$TEMP_ARTIFACT" "$TEMP_PANEL"
python scripts/stage11b/versions.py "$TEMP_ARTIFACT/files/workspace" "$TEMP_VERSIONS"
python scripts/stage11b/weak_controls.py "$TEMP_PANEL" "$TEMP_RESULT/weak-sc.json"
~~~

原始证据采用内容寻址。raw/files.json 的键是独立运行的逻辑路径，其值是原始字节的 SHA-256。ZIP 中同名条目含该文件的原始字节，Git 中按 parts.json 记录的顺序存储，读取器自动校验并拼接。重复的原始求解输入、反例和搜索流共用内容对象。formal 路径为正式构建，initial 路径为第一版，pilot 保存读写锁最初的表示差异拒绝记录。公开脚本可校验每个对象并从逐次记录重建汇总。

~~~bash
python scripts/stage11b/summarize.py reports/evidence/stage-11b
python scripts/stage11b/verify_evidence.py
python scripts/stage11b/raw_store.py read reports/evidence/stage-11b/raw formal/lock12/1/GS/new/worker/closure-stats.tsv
~~~

完整重跑会在独立目录构建带求解后导出的审计二进制。audit_proofs.py 将每个实际使用的块对与同版正式 GS 的输入、闭包、搜索流和完整返回文件核对，再分别在两个版本的直接 PO 基底上找出有根路径。proofs.json.gz 存放语义块名称、直接边与两条路径。proof-replay.json 列出实际命中的正式轮次，并保留同排名内事件次序的差异。离线核验同时检验 200 个原生搜索流、120 次 SAT 的证书处置，并用修改过的配置检查全量回退的匹配条件。

ticket 的人工审查可从 initial/ticket56/1/GS 的 old、new 两侧恢复以下文件，保持原文件名并分别放在 old/、new/ 目录，生成 tar.gz 后运行 ticket_review.py。所需文件为 full_model.json、goto.json、visits.json、native-bindings.json、s8-graph.tsv、s8-input.bin 和 receipt.json。相同来源的正式全模型也可用于重做审查。规范化后的摘要应与 versions/ticket-review.json 相同。审查读写锁的数据直接来自阶段 11A 的 real-declarations 与已经核验的预实验原始块，bindings.reviewed_records 可重新生成其固定注册表。
