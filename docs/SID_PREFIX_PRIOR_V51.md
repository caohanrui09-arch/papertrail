# 阶段51：SID前缀条件频率基线

工作目录：`<repo>`。
报告：`reports/阶段51_SID前缀先验与诊断收尾.md`；简历/面试补充：`docs/SID_EXPERIMENT_CLOSURE_V51.md`。

## 验收现有交付

```powershell
Set-Location '<repo>'
& '.\.cache\stage17\runtime\Scripts\python.exe' -E -s -m scripts.verify_sid_prefix_prior
```

只验收哈希、测试日志与结论，不重训/推理/计分。旧阶段45–50的收据链一起验证；新收据 `reports/stage51/final-validation.json`。

## 概率契约

只用每种SID冻结排列前4096条原始标签；每个位置使用前面的真实SID token作上下文，排除当前和未来token。`(count(prefix,next)+1)/(count(prefix)+K)`，Laplace α=1，K采用与保存模型位置条件NLL相同的完整位置码本64/64/64/11/1。未见prefix为均匀分布，不回退边际，也不使用目录树子节点集。第一位置等于边际；EOS K1始终NLL0。

新代码用stdlib Counter准备上下文统计，Laplace NLL直接调用阶段50已验证函数。没有实现训练器/decoder、没有安装框架。两种SID映射各自统计；同一映射内128/512共用两项4096先验。

原32严格训练前缀不重选，归档模型NLL不变。16查询事件在4096训练数据中，仍计入基线训练计数，无leave-one-out；其他16未选事件也可能有目标论文在其他标签出现。按事件/目标论文曝光/历史长度分别报告。主要判据只平均三个语义位置，身份和EOS单列，不将后缀简单任务混入结论。

前缀先验看到与teacher forcing相同的前序真实SID，但没有encoder用户历史。它是损失参照，未做目录排序、未生成Top10，不是新的推荐质量基线。128模型仅训练1024，而先验/512用4096，128作为旧参考不宣称等数据预算。这里是训练源健康检查，不是独立测试或个性化证明。

## 文件

- `four-method-comparison.csv`：288行，六跑×全部/事件曝光/论文曝光/历史长度×语义平均及五位置。各行含四方法NLL、样本数、token数和未见上下文数。
- `comparison.json`、`decision.json`、`closure-evidence.json`：数值、事前判断规则及收尾材料索引。
- ignored `data/stage51-prefix-prior`：两映射计数、320个唯一先验查询、六份共960条位置宽表，引用1920个旧模型位置损失；不当作960个独立样本。

事前规则：若六个512跑都没有在32前缀的三语义平均NLL上低于匹配前缀先验超过1e-12，就关闭当前预算加量路线；否则只记录混合证据、继续暂停训练。1e-12是数值判断容差，不是统计检验。

## 新本地研究副本复跑

仅在阶段50完整封存输入存在、尚无stage51输出的独立副本执行。不要删除现有封存或覆盖结果。

```powershell
$cpuPrefix = '.\.cache\stage17\runtime\Scripts\python.exe'
& $cpuPrefix -E -s -m unittest discover -s tests -p test_sid_prefix_prior.py -v
& $cpuPrefix -E -s -u -m scripts.compare_sid_prefix_prior
& $cpuPrefix -E -s -m unittest discover -s tests -p test_sid_prefix_prior.py -v 2>&1 | Out-File -Encoding utf8 reports/stage51/tests.log
& $cpuPrefix -E -s -m scripts.validate_sid_prefix_prior
& $cpuPrefix -E -s -m scripts.report_sid_prefix_prior
& $cpuPrefix -E -s -m scripts.verify_sid_prefix_prior
```

逐条核对退出码，失败即停并保存输出；脚本拒绝覆盖。首轮测试在协议前进行，再运行仅用于ROOT建立后的日志保存，不计20个不同测试。只需要已有CPU57包环境，未导入torch/transformers，旧权重可因收据验证而读取字节哈希，但不加载模型。此说明不是第二台机器实测。

无训练、生成、RL/dev、网站或依赖更改。当前路线关闭不等于整个网站/项目关闭，内容推荐默认保持。旧简历/面试文件不覆盖，新补充明确数字分母、复用关系及结论边界。逐用户衍生仍仅本地，按Scholar Inbox原CC BY-NC-ND4.0及元数据条款使用，不随简历/公共仓库分发；见本阶段THIRD_PARTY_NOTICES。
