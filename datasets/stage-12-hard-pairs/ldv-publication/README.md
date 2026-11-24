# ldv-publication

发布设备状态与检查属于同一原子操作，仍允许工作线程更新设备且保留退出时的 join。

原性质由 YAML 的 unreach-call.prp 指定。两端均按 ILP32、SC 和展开 4 从头建模，执行全部原生性质及展开检查。

| 版本 | 结论 | 服务器纯搜索秒 | CDCL 冲突 | 理论冲突 |
|---|---|---:|---:|---:|
| P0 | SAT | 0.000693 | 4 | 0 |
| P1 | UNSAT | 0.000460 | 3 | 0 |

P0 产生 4 条 CDCL 第一 UIP 学习记录。已确认 0 个有符号变量对应和 0 条保留原始子句（按重数）。原始宿主上的时间见 baseline.json，原始公式、图和轨迹见阶段证据索引。模型差分仅确认通过签名和语义身份核对的部分；未映射项单独计数。

Windows 工作区运行 `.\deagle-local.cmd hard-pair ldv-publication`。
