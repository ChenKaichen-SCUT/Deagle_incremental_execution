# Deagle 并发程序增量验证

本项目研究并发 C 程序经过一次修复后，增量构建事件顺序模型、复用有效理论约束，与独立全量 Deagle 验证同一程序和性质的结果。实施范围和每一阶段的验收条件见[执行指南](EXECUTION_GUIDE.md)。

阶段 5 已完成，状态为 `READY_FOR_REVIEW`。`batch_total` 修改乘数后，新求解器实际导入了一条旧排序冲突子句，候选有界通过。在同一旧程序的另一个候选上，导入后仍检出 62 步反例。条件或同步修改使理论图发生变化，三个候选共拒绝 14 条旧子句。五个候选的目标性质结论均与独立全量 Deagle 一致。阶段 6 等待确认。[阶段 5 报告与复现命令](reports/stage-05.md) · [原生导入回执](reports/evidence/stage-05/batch_total/candidate-import.json) · [五个候选的验收记录](reports/evidence/stage-05/acceptance.json) · [项目状态](project_state.json)

运行 `python -B scripts/stage5/check_evidence.py` 可离线核对阶段 5 的原始冲突、带符号映射、原生导入回执、两路性质结果和独立顺序枚举。`python -B scripts/stage4/check_evidence.py` 可重放已有的模型构建证据，`python -B scripts/stage2/freeze.py` 可核对三个冻结版本对。[阶段 4 模型增量构建](reports/stage-04.md) · [阶段 3 全量对照](reports/stage-03.md) · [阶段 2 病例与反例](reports/stage-02.md) · [阶段 1 工具报告](reports/stage-01.md) · [阶段 0 环境报告](reports/stage-00.md)

## 复查环境

在目标 Ubuntu 服务器的项目根目录执行以下命令。第一条重建 Git 不保存的空目录，并仅检查密钥文件的元数据及打开权限。第二条将新的采样保存在 `runs/`，便于和[阶段 0 快照](reports/environment.json)对照。

```bash
python3 -B scripts/init_workspace.py
python3 -B scripts/probe_environment.py \
  --apt-inrelease http://repo.huaweicloud.com/ubuntu/dists/jammy/InRelease \
  > runs/environment-recheck.json
```

探测脚本使用 Python 3.10 标准库，按这台服务器的 cgroup v2 层级计算有效资源。四个上游提交、Deagle 兼容补丁、二进制哈希和 Python 依赖均已锁定。[资源配置](configs/project.yaml) · [工具锁](configs/toolchain.lock.json) · [Python 依赖锁](configs/mini-requirements.lock)

控制端项目根目录保存 `apikey.txt`。Git 忽略密钥、第三方检出、虚拟环境和运行目录。仓库中的执行指南副本保留了[原始文件](deagle_incremental_execution_guide.md)的字节内容。
