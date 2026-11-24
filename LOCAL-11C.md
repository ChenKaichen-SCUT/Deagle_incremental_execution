# Deagle 阶段 11C 原生源码

这份源码快照对应项目提交 7d2d08ecbf6e643d3537131489ab6ba23c327c52。根目录保留 Deagle 原始许可证、C 前端及验证器的完整固定源码。minisat-2.2.1 是前端直接链接的 MiniSAT/Closure 核心。worker-11c 保存阶段 11C 正式实验实际编译的翻译单元、证明导出、审核后的导入和三个辅助程序。两个位置各自服务于冻结实验中的一条执行路径。

在 Ubuntu 22.04 安装 GCC/G++、GNU Make、flex、bison、zlib1g-dev 和 libc6-dev-i386 后，从本目录执行以下命令。

~~~bash
make -C src -j4 cbmc.dir
bash worker-11c/build.sh
src/cbmc/deagle_exe --version
~~~

阶段实验使用带固定哈希的前端。运行五模式实验、读写锁示例或离线审核，可以使用迁移分支的启动脚本。该分支也携带构建所需的冻结对象和输入的 SHA-256。[运行入口与说明](https://github.com/ChenKaichen-SCUT/Deagle_incremental_execution/blob/local-runtime-11c/docs/local-runtime.md)
