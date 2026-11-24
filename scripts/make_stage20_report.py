"""Seal completed preparation only; human annotation/quality remain pending."""
import json
from pathlib import Path

from gsearch.quality_protocol import digest,save,coverage
from gsearch.human_quality import configuration,load_state
from scripts.freeze_quality_preparation import CODE

PROJECT=Path(__file__).resolve().parents[1]
ROOT=PROJECT/'data/stage20-quality'
REPORT=PROJECT/'reports/stage20'


def main() -> None:
    receipt=REPORT/'final-validation.json'
    if receipt.exists():raise ValueError('Never overwrite sealed preparation')
    configuration()
    verified=json.loads((REPORT/'preparation-validation.json').read_text())
    if verified['failures'] or verified['errors'] or not verified['actual_empty_human_score_cli_blocked'] or not verified['stages3_19_unchanged']:
        raise ValueError('Preparation verification incomplete')
    queries,mapping,runs,labels,confirmed=load_state()
    status=coverage(queries,mapping,runs,labels,confirmed)
    if labels or confirmed or status['quality_ready'] or (ROOT/'human-results').exists():
        raise ValueError('This receipt must not claim future human results')
    from gsearch.quality_protocol import read_csv
    if read_csv(ROOT/'work/real-query-intake.csv'):
        raise ValueError('Intake is no longer empty; record source and version first')
    costs=json.loads((REPORT/'retrieval-cost.json').read_text())
    audit=json.loads((REPORT/'agent-failure-audit.json').read_text())
    overlay=json.loads((PROJECT/'.cache/stage20/overlay.json').read_text())
    from scripts.manage_stage17_env import BASE
    if any(digest(PROJECT/p)!=v or digest(BASE/'replica'/p)!=v for p,v in overlay.items()):
        raise ValueError('Pool runtime overlay drift')
    rows=[]
    for name,value in costs['methods'].items():
        rows.append(f"| {name} | {value['requests']} | {value['mean_ms']:.2f} | {value['warm_mean_ms']:.2f} | {value['p95_ms_nearest_rank']:.2f} | 未计算 |")
    report=f'''# 第二十阶段：主题检索盲标注准备与Agent失败归因

按用户明确的“暂时无人标注，先完成准备工作”完成当前交付：**24条模型草拟需求、423个盲标注对、原生组件评分/导入门槛、成本记录及历史Agent失败分类**。真人原创需求0、人工确认需求0、人工相关性标签0，因此没有人工NDCG/MRR、语义选文准确率或真实用户收益结果。准备阶段完成，不将后续人工任务标记为完成。

## 草拟需求与共享评价范围

- 主题、带主题的个性化推荐、组合需求各8，共24。单条来源均assistant_draft；只参考用户给出的生成式搜广推+Agent方向，没有冒充从真实用户收集问题。保留真实需求空收集表。将来人工确认草稿也仍保留原始来源，不改称真人原创。
- 8个主题族按hash整体划分tuning9/evaluation15，用户上下文也不跨split；没有按检索结果或标签挑选需求。所有方法用同一万篇明确arXiv v1、相同2025-02-23时点、全部训练正负seen过滤；可用时间仍是提交日结束+24h代理，不能称已证明的历史入库。查询在本轮草拟，只在历史目录上模拟需求。
- 个性化上下文为hash选出的五篇真实训练点赞论文，标注者能读到相同五篇原摘要；不是匿名用户对该需求的真实自述，也不是沿用完整用户历史画像。显式主题优先，历史作上下文，后续相关性判断不等于真实用户满意度。

## 三方法与成本

原生SQLite FTS5 BM25、冻结词表/IDF的sklearn查询TFIDF、查询TFIDF+同五篇历史向量。组合先L2归一化历史向量之和，再以0.7查询/0.3历史混合并原生归一化；权重预先固定，没有人工标签选型。查询无内容信号不补零分伪相关结果，历史无支持退回查询。三个方法共享当前目录和seen，结果稳定按ID并列排序。

| 方法 | 请求数 | 平均ms（含首建） | 无首建平均ms | P95 ms | 人工质量 |
|---|---:|---:|---:|---:|---|
{chr(10).join(rows)}

24需求×3方法×3轮共216次计时，顺序轮换，无查询得分/排名缓存。BM25首次快照构建约{costs['bm25_snapshot_builds'][0]['snapshot_seconds']:.3f}秒，模型和适配装载拟合{costs['one_time_model_and_adapter_fit_seconds']:.2f}秒单列。查询稀疏向量和组合稠密向量使用不同原生kernel路径，不能把当前耗时差异单独归为算法复杂度，也不代表生产QPS或质量优势。没有按延迟改变公式或挑选候选。

## 盲池与人工门槛

每需求汇总三方法Top10并去重，共423个需求—论文对。标注方只获得blind/和work/，无方法、排名、得分、split、真实用户ID或预填相关性标签；需求分组及组内候选hash排序，不依方法次序。文件分离是实验盲法约定，不是对电脑所有者的访问控制。

CSV、Label Studio原生data-only JSON和Choices配置已准备；无predictions/预标注。Label Studio未安装、启动或验收前端，当前只校验格式并用测试fixture验证导入解析。BEIR原版custom_metrics.py、LICENSE、NOTICE及CONTRIBUTORS完整保留；sklearn ndcg_score文件LF Git blob与固定源码一致。比较的ir_measures未安装，错误猜测的仓库/文件路径如实记录，不宣称已读未取得的实现。无新包安装或共享CUDA修改。

人工等级0/1/2，必须填写真人来源声明、化名、带时区时间及简短依据；缺失不等于0，模型来源被拒绝。需求须先人工确认，文本/来源改变需要新池版本。取消、多次冲突及不完整Label Studio注释被拒绝，需人工复核，不自动用模型裁判。human声明不等于身份认证。实际空标注score命令非零退出，未写出质量结果；status的NDCG/MRR保持null。

未来仅在目标split全量池内人工标完后调用原生指标：sklearn NDCG@10增益2^grade-1、理想排序基于完整已标池；未返回槽位以零增益表示。MRR@10用未修改的BEIR mrr、grade>=1相关、上游保留5位小数。报告池覆盖、返回结果标注覆盖和Top10槽位；池外相关论文未知，完整目录Recall不计算。tuning评分后再冻结才允许evaluation，不能改权重或覆盖结果。单元测试的合成等级只用于软件检查，没有写进真实工作表。

## Agent失败分类

只读分析阶段19全部12个正式LLM任务，5完成/7失败：重复检索循环3、非法参数阻止有效检索3、读取/路由后未最终提交1。共31次重复工具尝试、6次非法参数拒绝、26次预算拒绝；事件类别可重叠，不能相加作为任务数。7次无被接受的最终答案不全是最终答案内容错误，要结合前序步骤理解。

遗漏k的合法请求经原生工具得到默认3；模型显式null/布尔值不作为默认值悄悄修复。重复检索/读取按原预算计费。没有复现合法请求被后端错误拒绝，因此本轮不修改冻结接口、不重新跑LLM或继续调提示词。语义选文错误数量为未评估，需要人工相关性标签，不能从协议失败推断。

## 验收和交付

{verified['regression_tests']}项完整测试通过；245篇候选及上下文文献通过178份官方原始响应独立重解析；423盲行/Label Studio格式、216计时记录及全seen/as-of/历史正赞上下文复核通过。阶段3—19资产、481原迁移资产、独立CPU运行时57包不变。原有本地服务未改动，所有个人派生材料仍留忽略的data/.cache，无对外发布。

入口annotation-status.cmd；材料目录data/stage20-quality/，说明docs/QUALITY_ANNOTATION.md。work/（人工编辑）和human-results/（未来结果）刻意不纳入本准备收据的不可变清单。人工尚未开始，不能据该收据声称真实需求采集、人工相关性对照或Agent质量改善完成。
'''
    report_path=PROJECT/'reports/阶段20_主题检索盲标注准备与失败归因.md'
    report_path.write_text(report,encoding='utf-8')
    all_code=CODE+['gsearch/human_quality.py','scripts/verify_quality_preparation.py','scripts/make_stage20_report.py','annotation-status.cmd']
    vendor=[p for p in (PROJECT/'third_party/beir_metrics_upstream').iterdir() if p.is_file()]
    immutable=[p for directory in ('inputs','evaluator','runs','blind','templates') for p in (ROOT/directory).rglob('*') if p.is_file()]
    immutable+=[ROOT/'pool-manifest.json']
    immutable += [PROJECT/'.cache/stage20'/name for name in ('overlay.json','agent-failures-private.json','status-gate.log','score-gate.log','regression-tests.log')]
    outputs=[p for p in REPORT.glob('*.json') if p!=receipt]
    result={'status':'preparation_complete_awaiting_human','preparation_passed':True,
        'assistant_draft_queries':24,'human_authored_queries':0,'human_judgments':0,'blind_pairs':423,
        'human_quality_comparison_completed':False,'human_annotation_performed':False,
        'regression_tests':verified['regression_tests'],'stages3_19_unchanged':True,
        'mutable_work_and_future_human_results_excluded':True,
        'code':{str((PROJECT/p).relative_to(PROJECT)):digest(PROJECT/p) for p in all_code},
        'vendor':{str(p.relative_to(PROJECT)):digest(p) for p in vendor},
        'outputs':{str(p.relative_to(PROJECT)):digest(p) for p in outputs},
        'private_data':{str(p.relative_to(PROJECT)):digest(p) for p in immutable},
        'docs':{'docs/QUALITY_ANNOTATION.md':digest(PROJECT/'docs/QUALITY_ANNOTATION.md')},
        'report':{str(report_path.relative_to(PROJECT)):digest(report_path)}}
    save(receipt,result)
    print(json.dumps({'status':result['status'],'receipt_sha256':digest(receipt),'human_judgments':0,'blind_pairs':423}),flush=True)


if __name__=='__main__':main()
