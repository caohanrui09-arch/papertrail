# 同机独立运行时与迁移回放

这是2026-10-28实际完成的**同一Windows机器上的干净运行时/新路径复现**。使用uv0.13.6官方校验二进制、独立下载的CPython3.12.3及CPU Torch2.6.0+cpu；没有继承旧父目录site-packages、启用用户site、修改注册表或全局PATH。真实第二台机器及跨操作系统尚未测试。

## 新资产布局

| 路径 | 内容 |
|---|---|
| .cache/stage17/bootstrap | 固定官方uv二进制与归档SHA收据 |
| .cache/stage17/python | 独立Python发行版，非旧Miniconda标准库 |
| .cache/stage17/runtime | 干净虚拟环境；阶段17基础45包哈希锁，阶段18按保留原版本的锁添加API依赖 |
| .cache/stage17/replica | 新绝对路径的最小私有副本，481项原字节资产、万篇文档、409份官方原响应 |
| reports/stage17 | uv审计、包哈希锁、运行时/迁移验收收据 |

原始元数据中的绝对raw_path没有在文件里重写：新加载器校验原文件hash后，只在内存里把路径映射到副本的`.cache/stage13/raw/{sha}.body`。训练CSV、文本、版本、原始响应及旧阶段源码字节保持一致；原模型构造、TFIDF/SAR和工具循环直接复用。

## 已验证的结果

- 新CPU环境全部拟合签名与旧实验精确一致，包括词表、IDF、文档/用户稀疏矩阵和SAR矩阵。
- 三路推荐、工具轨迹及原v1读取与阶段16真实演示逐项一致。
- 所有已导入文件模块与sys.path均位于新运行时、独立Python或迁移副本。
- 回放启用Python审计钩子，拒绝旧工作区/旧基础Python文件读取及socket连接；实际旧根读取尝试0、网络连接尝试0。这不是操作系统容器或对恶意原生扩展的安全隔离证明。
- 首次失败定位到Transformers提前从venv加载sklearn；新启动器在任何旧模块导入前加入本副本的依赖目标路径，保留原sklearn来源检查。原版本/实现没有放宽。

## 当前电脑上的启动步骤

已有本机资产不需要重新安装。查看`.cache/stage17/replica/data/relocated-run.json`和`isolated-io-proof.json`；重复回放入口拒绝覆盖这次结果。后续若要重跑，应使用新的私有输出副本并保留原收据。

可用下面流程理解重建依赖；bootstrap可由可用Python执行，不需要先装CUDA：

```powershell
# 从项目根目录，先用现有Python执行一次官方uv归档校验
py -3.12 -m scripts.bootstrap_stage17_runtime
py -3.12 -m scripts.manage_stage17_env --phase python
py -3.12 -m scripts.manage_stage17_env --phase venv
# 已发布requirements哈希锁，不需要重做依赖选型
py -3.12 -m scripts.manage_stage17_env --phase install
py -3.12 -m scripts.prepare_stage17_bundle
py -3.12 -m scripts.manage_stage17_env --phase target
py -3.12 -m scripts.run_stage17_replay
```

这些命令对已完成环境/副本有拒绝覆盖保护；不是让你在当前工作区反复执行。准备副本依赖合法取得的本地反馈、官方响应及阶段16演示，Git源码本身不包含这些私有资产。从空机器下载原数据、完整重训早期T5实验仍是另一项工作，未在当前阶段冒充完成。

依赖只使用官方PyPI轮子及官方PyTorch CPU索引公布的直接URL和SHA，禁止源码构建，全部带哈希；uv/venv的固定来源与许可见阶段17审计和第三方通知。直连下载首次失败后沿用已有代理成功，没有关闭TLS或改系统代理。

当前可继续使用[本地服务](LOCAL_SERVICE.md)。这消除了“只有原CUDA环境能运行”的依赖，尚不替代真实其他硬件/系统的验收。
