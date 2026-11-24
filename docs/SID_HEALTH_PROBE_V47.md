# 冻结 SID 模型探针：阶段47

工作目录：`<repo>`。
主报告：`reports/阶段47_冻结模型历史与损失探针.md`；聚合表为 `reports/stage47/history-summary.csv` 和 `position-loss-summary.csv`。

## 当前结果验收（不重新推理）

在 PowerShell 执行：

```powershell
Set-Location '<repo>'
& '.\.cache\stage17\runtime\Scripts\python.exe' -E -s -m scripts.verify_sid_health_probe
```

验收校验阶段45的303项、阶段46的38项资产，以及本阶段协议、续跑锁、测试、原始输出和交付文件。最终收据为 `reports/stage47/final-validation.json`。校验不导入 torch、不更新权重、不访问网络。

## 探针解释

六模型均为既有128步检查点。A在训练截止画像中固定抽取16个长度1、16个长度20的用户，同长度一对一交换历史；目录、接收者已读过滤和解码保持一致。384次请求仅说明输入敏感性，不是推荐质量测试。反事实历史可能和接收者的已读集合不一致，复制输入的影响另外记录。

B用32个严格时序训练前缀，pilot事件与池内未抽事件各16，分别覆盖两种历史长度。未抽事件不等于目标论文从未用于训练。输入不含目标，先前目标token由teacher forcing提供；位置码本归一化不等于目录树分支归一化。32前缀在六模型重复使用，960位置不能当成960个独立用户。

完整词表分析损失使用BF16前向logits的显式FP32交叉熵；原生AMP损失单独保存。均值验收在相同AMP口径内进行，阈值仍为1e-4。首轮跨精度口径比较失败保留于 `first-attempt.log`，没有将其覆盖为成功。原64次beam输出复用，只新增320次；正式teacher-forcing为192样本，诊断8样本，中断前向保守上界32样本，合计上界232。原中断批次未记录，不能声称精确总数。

原生HF生成、beam祖先和转移分数、原生PyTorch CE直接复用。观察器原样返回分数；只保存紧凑路径和转移值，没有保留完整词表logits。独立验收可重建样本、合法前缀、祖先路径、先验、均值和分解恒等式，不声称能从完整原始logits重算全部softmax。

## 在新的本地研究副本重新生成

以下仅适用于保留阶段46及其输入、但尚无阶段47输出的新副本。当前封存目录不要执行生成命令，也不要删除结果以强行重跑。无需先运行旧的 `scripts.run_sid_health_probe`；该入口保留用于解释原失败。

```powershell
$cpuProbe = '.\.cache\stage17\runtime\Scripts\python.exe'
$gpuProbe = '..\.venv\Scripts\python.exe'
& $cpuProbe -E -s -m scripts.verify_sid_failure_audit
& $cpuProbe -E -s -m scripts.prepare_sid_health_probe
& $cpuProbe -E -s -m unittest discover -s tests -p test_sid_health_data.py -v 2>&1 | Out-File -Encoding utf8 reports/stage47/data-tests.log
& $cpuProbe -E -s -m scripts.prepare_sid_health_continuation
& $gpuProbe -E -s -m scripts.continue_sid_health_probe
& $cpuProbe -E -s -m scripts.validate_sid_health_probe
& $cpuProbe -E -s -m scripts.report_sid_health_probe
& $cpuProbe -E -s -m scripts.verify_sid_health_probe
```

逐条检查退出码；失败立即停下。新副本直接使用修正入口时复用/诊断/中断计数为0，所有384请求正常生成，不必人为复现精度中断。路径按已有本地Windows布局解析，第三方源码哈希及模型必须与协议匹配；不是另一台机器复现证明。

CPU环境保留57包；GPU环境保留38包，torch 2.6.0+cu124、transformers 4.57.1，BF16支持为运行门槛。无需在GPU环境加装pandas/scipy，亦不修改26包网站环境。本机资源记录在execution.json；耗时不含全部初始化和原失败开销，不能作为生产吞吐。

## 训练决策与数据范围

decision.json建议下一轮只比较128→512步预算，尚未启动。需要另行冻结运行锁、资源门槛及检查点重现门槛；从相同基础模型出发，保留内容/打乱两臂和全部种子。原检查点没有优化器状态，不能声称精确续训。扩大前缀至4096条同时改变监督曝光，不能把收益单独归因步数；完整分母tuning保持原协议，已有dev仍仅描述性。暂不进入RL。

逐用户样本、输出与配对表仅存Git忽略的 `data/stage47-health`。Scholar Inbox交互来源CC BY-NC-ND 4.0的限制沿用既有审核；不随网站或公共仓库分发衍生画像/模型。本阶段未改网站、默认搜索或推荐。
