# Deagle 并发程序增量验证

本项目研究并发 C 程序经过一次修复后，增量构建事件顺序模型、复用有效理论约束，与独立全量 Deagle 验证同一程序和性质的结果。实施范围和每一阶段的验收条件见[执行指南](EXECUTION_GUIDE.md)。

阶段 6 已完成，状态为 `READY_FOR_REVIEW`。mini-SWE-agent 根据 `batch_total` 的真实反例通过 DeepSeek 官方 API 生成了单行修复。原生执行跳过 60 步、重算 13 步，向新求解器导入 1 条旧理论子句。增量与独立全量验证均有界通过。9 次双路运行覆盖 5 个不同版本对，其中两对修复后仍有错误，两路都检出。阶段 7 等待确认。[阶段 6 报告与复现命令](reports/stage-06.md) · [AI 补丁](reports/evidence/stage-06/ai/patch.diff) · [验收记录](reports/evidence/stage-06/acceptance.json) · [项目状态](project_state.json)

运行 `python -B scripts/stage6/check_evidence.py` 可用标准库和 Git 离线核对完整链路，包括从模型工具调用重建补丁、核对检查点与原生子句、重新解析两路性质结果。对于配置好工具的服务器，`python3 -B -m incdeagle.cli replay-pair --case cases/batch_total/task.yaml --check-model` 可从新会话重放与这次 AI 输出字节一致的冻结版本对，API 调用为零。[阶段 5 理论子句复用](reports/stage-05.md) · [阶段 4 模型增量构建](reports/stage-04.md) · [阶段 3 全量对照](reports/stage-03.md) · [阶段 2 病例与反例](reports/stage-02.md) · [阶段 1 工具报告](reports/stage-01.md) · [阶段 0 环境报告](reports/stage-00.md)

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
