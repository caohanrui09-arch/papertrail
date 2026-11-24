# 阶段45最终验收修正

**最终收据以 `reports/stage45/final-validation-v2.json` 为准。** 核验入口：

```powershell
Set-Location '<repo>'
& .cache/stage17/runtime/Scripts/python.exe -E -s -m scripts.validate_sft_delivery_v2
```

初版封装辅助脚本从.cache路径执行，没有把项目目录加入Python导入路径，造成 `scoring-equivalence-tests.log` 的导入失败；初版资产核验器只检查哈希、模型、数据和数值，没有拦截这份失败日志。模块形式的同一10项测试此前已通过。

修正后再次在项目根导入测试，生成独立的 `scoring-equivalence-tests-v2.log`，10项全部通过。最终v2验收额外要求18项SID边界测试、20项冻结评价测试、10项计分等价测试共48项的成功日志，并保留九组各512条真实事件的逐字段等价证明。

初版298个文件、失败日志和收据全部保留且哈希不变；v2只追加测试证明、修正说明和验收入口。训练锁、九组质量数值、模型、预测、SID映射及源数据均未修改。没有追加训练或根据分数改预算。

算法和分步复跑说明仍见 [SID_SFT_V45.md](SID_SFT_V45.md)，结果见 [阶段45报告](../reports/阶段45_SID与受控SFT试验.md)。本轮最终结论：内容SID在三个训练种子中相对打乱SID两次略高、一次略低，未超过内容基线；保留网站默认方案，不进入RL。基线使用完整反馈、SFT仅1024条监督，不能推断完整训练上限。
