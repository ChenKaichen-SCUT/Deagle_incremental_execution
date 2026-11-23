# Deagle 并发程序增量验证

本项目研究并发 C 程序经过一次修复后，增量构建事件顺序模型、复用有效理论约束，与独立全量 Deagle 验证同一程序和性质的结果。实施范围和每一阶段的验收条件见[执行指南](EXECUTION_GUIDE.md)。

阶段 7 已完成，状态为 `READY_FOR_REVIEW`。9 个冻结版本对各重复 3 次，全量与增量在 27 次配对中结论一致。7 个候选在给定界限内通过，2 个仍有错误，两路均检出。5 个版本对实际跳过原生符号执行前缀，4 个实际导入旧理论子句。27 次候选验证中增量路径均较慢，按版本对等权计算的全量时间与增量时间之比中位数为 0.247。[阶段 7 报告](reports/stage-07.md) · [逐次测量](reports/evidence/stage-07/measurements.json) · [项目状态](project_state.json)

运行 `python -B scripts/stage7/check_evidence.py` 可用 Python 标准库和 Git 从原生归档重算统计，核对模型、已导入子句和反例。在配置好工具的 Linux 服务器上，运行 `python3 -B scripts/stage7/experiment.py --out runs/stage-07/reproduction` 可在新目录重做实验。实验复用冻结补丁，API 调用为零。[构建与复现步骤](reports/stage-07.md) · [阶段 6 AI 补丁与单次修复链路](reports/stage-06.md) · [阶段 5 理论子句复用](reports/stage-05.md) · [阶段 4 模型增量构建](reports/stage-04.md) · [阶段 3 全量对照](reports/stage-03.md) · [阶段 2 病例与反例](reports/stage-02.md) · [阶段 1 工具报告](reports/stage-01.md) · [阶段 0 环境报告](reports/stage-00.md)

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
