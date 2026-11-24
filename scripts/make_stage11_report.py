"""Rescore every local output; publish aggregate-only evidence and limitations."""
from pathlib import Path
import json
import re

import numpy as np
import pandas as pd

from gsearch.benchmark_content import FUSIONS, SINGLES, check_plan, model_signature, pick_metric
from gsearch.content_recommendation import DATA, ORIGINAL, ROOT, load, parse_time, read, sklearn_runtime
from gsearch.data import write_json
from gsearch.evaluate import metrics
from gsearch.identifiers import sha256
from scripts.make_stage9_report import paired


def main() -> None:
    plan=check_plan()
    lock=read(ROOT/"locked-before-dev.json")
    tuning_names=(*SINGLES,*FUSIONS)
    if (lock["plan_sha256"]!=sha256(ROOT/"plan.json") or
            lock["tuning_hashes"]!={m:sha256(ROOT/f"{m}-tuning.json") for m in tuning_names} or
            lock["model_signature_sha256"]!=sha256(DATA/"model-signature.json")):
        raise ValueError("Selection or model lock changed")
    sklearn_runtime()
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=1):
        engine=load()
        if model_signature(engine)!=read(DATA/"model-signature.json"):
            raise ValueError("Frozen train-only fit does not reproduce")
        catalog=set(engine.catalog)
        source={r["doc_id"]:r for r in read(Path("data/stage10-catalog/metadata.json"))}
        for row in read(DATA/"documents.json"):
            if any(row[k]!=source[row["doc_id"]][k] for k in row):
                raise ValueError("Content differs from original snapshot")
            if not all(parse_time(row[k])<parse_time(plan["temporal_assumption"]["cutoff"]) for k in ("updated_at","published_at")):
                raise ValueError("Text eligibility boundary changed")
        results,predictions,validated={},{},{}
        for split in ("tuning","dev"):
            frame=pd.read_csv(ORIGINAL/(split+".csv"),dtype={"user_id":str,"arxiv_id":str})
            positives=frame[frame.rating==1].groupby("user_id").arxiv_id.agg(set).to_dict()
            negatives=frame[frame.rating==-1].groupby("user_id").arxiv_id.agg(set).to_dict()
            names=tuning_names if split=="tuning" else (*SINGLES,"hybrid")
            for method in names:
                result=read(ROOT/f"{method}-{split}.json")
                path=DATA/f"{method}-{split}-predictions.json"
                if (result["predictions_sha256"]!=sha256(path) or result["plan_sha256"]!=sha256(ROOT/"plan.json") or
                        result["model_signature_sha256"]!=lock["model_signature_sha256"]):
                    raise ValueError("Raw prediction/model integrity mismatch")
                rows=read(path)["users"]
                if [r["user_id"] for r in rows]!=sorted(positives):
                    raise ValueError("Users omitted/reordered")
                for i,row in enumerate(rows):
                    user=row["user_id"]
                    ids=[h["doc_id"] for h in row["recommendations"]]
                    if (len(ids)!=10 or len(set(ids))!=10 or not set(ids)<=catalog or
                            set(ids)&engine.sar.seen.get(user,set()) or set(row["relevant"])!=positives[user] or
                            row["warm"]!=(user in engine.user2row) or
                            row["catalog_positive_count"]!=len(positives[user]&catalog) or
                            row["observed_future_dislikes_returned"]!=len(set(ids)&negatives.get(user,set()))):
                        raise ValueError("Ground truth, common mask, user group or catalog mismatch")
                    for key,value in metrics(ids,positives[user],10).items():
                        if abs(value-row[key])>1e-12:
                            raise ValueError("Raw scoring mismatch")
                    # Replay a deterministic sample, not all expensive component computations.
                    if i%500==0:
                        mode="hybrid" if method in FUSIONS or method=="hybrid" else method
                        alpha=FUSIONS.get(method,lock["selected_sar_weight"])
                        if ids!=[h["doc_id"] for h in engine.recommend(user,mode,10,alpha)]:
                            raise ValueError("Ranking replay differs")
                for key in ("recall","hit","mrr","ndcg"):
                    if abs(np.mean([r[key] for r in rows])-result["summary"][key+"@10"])>1e-12:
                        raise ValueError("Aggregate score mismatch")
                coverage=len({h["doc_id"] for r in rows for h in r["recommendations"]})/len(catalog)
                if abs(coverage-result["summary"]["catalog_coverage"])>1e-12:
                    raise ValueError("Catalog coverage mismatch")
                for warm,name in ((True,"warm"),(False,"cold")):
                    group=[r for r in rows if r["warm"]==warm]
                    if len(group)!=result["groups"][name]["users"]:
                        raise ValueError("User cohort mismatch")
                    for key in ("recall","ndcg","mrr"):
                        if abs(np.mean([r[key] for r in group])-result["groups"][name][key])>1e-12:
                            raise ValueError("Cohort metrics mismatch")
                results[split,method]=result
                predictions[split,method]=rows
                validated[f"{method}-{split}"]=len(rows)
            for method in names:
                for row,pop in zip(predictions[split,method],predictions[split,"popular"]):
                    if not row["warm"] and row["recommendations"]!=pop["recommendations"]:
                        raise ValueError("Cold fallback differs between methods")
        for endpoint,single in (("hybrid_a000","content"),("hybrid_a100","sar")):
            if any(a["recommendations"]!=b["recommendations"] for a,b in zip(predictions["tuning",endpoint],predictions["tuning",single])):
                raise ValueError("Fusion endpoint differs from single branch")
        selected=max(FUSIONS,key=lambda m:(*pick_metric(m,results["tuning",m]),FUSIONS[m] in (0,1),-FUSIONS[m]))
        best=max(SINGLES,key=lambda m:(*pick_metric(m,results["tuning",m]),-SINGLES.index(m)))
        if selected!=lock["selected_fusion"] or best!=lock["best_single_on_tuning"]:
            raise ValueError("Tuning selection differs from protocol")
    comparison={}
    for split in ("tuning","dev"):
        hybrid=selected if split=="tuning" else "hybrid"
        comparison[split]={"hybrid_minus_tuning_best_single":paired(predictions[split,hybrid],predictions[split,best]),
                           "content_minus_sar":paired(predictions[split,"content"],predictions[split,"sar"])}
    write_json(ROOT/"paired-aggregate.json",comparison)
    from scripts.make_stage8_report import verify_history
    from gsearch.benchmark_target_alignment import check_plan as check8
    from gsearch.benchmark_recommendation import check_plan as check9
    verify_history()
    check8()
    check9()
    for stage in (8,9):
        receipt=read(Path(f"reports/stage{stage}/final-validation.json"))
        for name,digest in receipt["outputs"].items():
            if sha256(Path(f"reports/stage{stage}")/name)!=digest:
                raise ValueError("Historical results changed")
    old=read(Path("reports/stage10/final-validation.json"))
    for base,key in ((Path("data/stage10-catalog"),"data_assets"),(Path("."),"code_assets")):
        for name,digest in old[key].items():
            if sha256(base/name)!=digest:
                raise ValueError("Frozen stage10 code/data changed")
    tested=re.search(r"Ran (\d+) tests in [^\n]+\n\s*\nOK",(ROOT/"tests-final.log").read_text(encoding="utf-8-sig"))
    if not tested:
        raise ValueError("Missing passing full tests")
    table,groups,grid=[],[],[]
    for split in ("tuning","dev"):
        hybrid=selected if split=="tuning" else "hybrid"
        for method in (*SINGLES,hybrid):
            result=results[split,method]
            s=result["summary"]
            table.append(f"| {split} | {method} | {s['recall@10']:.6f} | {s['ndcg@10']:.6f} | {s['mrr@10']:.6f} | {s['catalog_coverage']:.2%} | {1000*s['mean_seconds']:.3f} / {1000*s['p95_seconds']:.3f} |")
            for name,g in result["groups"].items():
                latency=[r["seconds"] for r in predictions[split,method] if r["warm"]==(name=="warm")]
                groups.append(f"| {split} | {method} | {name} | {g['users']} | {g['recall']:.6f} | {g['ndcg']:.6f} | {1000*np.mean(latency):.3f} / {1000*np.quantile(latency,.95):.3f} |")
    for method,alpha in FUSIONS.items():
        s=results["tuning",method]["summary"]
        grid.append(f"| {alpha:g} | {s['recall@10']:.6f} | {s['ndcg@10']:.6f} | {s['mrr@10']:.6f} |")
    delta=comparison["dev"]["hybrid_minus_tuning_best_single"]
    deltas=[]
    for metric,value in delta.items():
        lo,hi=value["bootstrap_95_percentile_interval"]
        deltas.append(f"| {metric} | {value['mean_delta']:+.6f} | [{lo:+.6f}, {hi:+.6f}] | {value['wins']}/{value['losses']}/{value['ties']} |")
    fit=results["tuning","content"]["fit"]
    dev=results["dev","content"]["summary"]
    endpoint=lock["selected_sar_weight"] in (0,1)
    dislikes="、".join(f"{m}={results['dev',m]['summary']['observed_future_dislikes_returned']}" for m in (*SINGLES,"hybrid"))
    conclusion=("tuning选择融合端点，实际退化为单方法，因此没有混合收益证据。" if endpoint else
                "后段混合NDCG点估计最高，但相对最佳单方法的主指标差异区间跨0，尚无稳定整体质量改善证据。Recall的描述性配对区间为正，不能替代主指标或独立测试。")
    doc=f'''# 第十一阶段：内容推荐与协同推荐严格对照

四组方法在同一1781篇目录和相同训练历史下完成评价。tuning选SAR权重{lock['selected_sar_weight']:g}，最佳单方法为{best}；冻结后只运行四组dev。{conclusion} 本轮为词法内容推荐试验，不代表神经语义推荐、生成式推荐或Agent决策已经改善。

## 固定范围及时间假设

原2048篇候选均由原train点赞频次确定，不引入新论文。仅保留首次提交和快照最新更新均严格早于{plan['temporal_assumption']['cutoff']}且原标题/摘要完整的1781篇，267篇排除。源文字来自阶段10固定CC0元数据快照；**源日期筛选是一项保守假设，没有历史逐版本文字证明，不声称完全消除时间泄漏。** 日期为arXiv提交/更新日期，不是期刊发表日期。

四方法使用完全相同的原train反馈；用户兴趣仅含目录内train点赞，train正负反馈均作为已读过滤。tuning/dev全部有未来点赞用户3571/3587人均保留。目录外、267篇及其他未来新论文点赞继续计入Recall分母，没有候选内过滤用户或抽负例。dev未来点赞只有{dev['future_positive_catalog_coverage']:.2%}位于当前目录，限制召回；该比率按点赞数计，不等同于宏平均Recall的数值上限。不与阶段9不同2048篇范围的分数直接比较。

## 开源复用和模型

比较维护活跃的[scikit-learn](https://github.com/scikit-learn/scikit-learn/tree/1.9.1)（BSD3）、[sentence-transformers](https://github.com/huggingface/sentence-transformers/tree/33f9bd81610560e48ff5eac80e910496b49ae193)（Apache2）和[旧TFIDF例程](https://github.com/ariflaksito/tfidf-cb-recsys/tree/aa68ddf4f61e237ebc4525df443e33d11455fa18)（无声明许可、不复制）。阅读sklearn核心变换、实际1.9.1 fit_transform、MultiLabelBinarizer和许可；神经备选只看文档/许可与目录，未审编码器核心。先使用无新预训练权重的词法基线，避免引入模型截断/许可/预训练时间暴露假设。维护、源码blob和依赖风险见[来源审计](stage11/upstream-audit.json)。

实际调用sklearn TfidfVectorizer、MultiLabelBinarizer、normalize、linear_kernel，SAR沿用固定MIT上游源码，无自写TFIDF/余弦/协同算法。内容输入为标题＋换行＋原摘要，一二元词、min_df2、max_features30000、英文停词、sublinearTF和L2。目录1781篇拟合词表与IDF，用户向量为其train点赞文档向量求和再L2归一化，按余弦排序。共{fit['vocabulary']}词、{fit['warm_users']}名有目录内点赞历史用户，零内容向量{fit['zero_profile_users']}。

SAR用同一1781篇重新拟合原Jaccard组件，二值正反馈、无时间衰减。新用户或没有目录内点赞的用户为cold，四方法统一回退train流行度；cold不意味着完全没有任何站内行为。所有候选均至少有一条train点赞，本轮没有评价新论文物品冷启动；无历史冷用户也无法直接从点赞生成内容画像。零文本向量单独标记并回退内容流行度。所有相等分数按论文ID固定排序。

混合为过滤已读后的全候选排名带权RRF：alpha/(60+SAR_rank)+(1-alpha)/(60+content_rank)。alpha为SAR权重，0/1直接返回原内容/SAR分支。tuning只在下列五点按NDCG→Recall→MRR选择，相等优先端点再小权重；最佳单方法也仅用tuning选择。独立锁文件、模型矩阵签名和代码/数据hash先于dev固定，dev没有扫描参数。

| SAR权重 | tuning Recall@10 | tuning NDCG@10 | tuning MRR@10 |
|---:|---:|---:|---:|
{chr(10).join(grid)}

## 四组质量、覆盖与成本

以下Recall/NDCG是每用户宏平均，目录外gold保留。覆盖为至少被推荐一次的目录论文比例，耗时列为每请求均值/P95毫秒。

| 划分 | 方法 | Recall@10 | NDCG@10 | MRR@10 | 推荐目录覆盖 | 均值 / P95 ms |
|---|---|---:|---:|---:|---:|---:|
{chr(10).join(table)}

| 划分 | 方法 | 用户组 | 人数 | Recall@10 | NDCG@10 | 均值 / P95 ms |
|---|---|---|---:|---:|---:|---:|
{chr(10).join(groups)}

dev推荐命中未来已观测点踩的次数：{dislikes}。仅统计真实已标注反馈；未观测论文不当负例，未来点踩没有用于过滤或训练。

主比较是冻结混合相对tuning最佳单方法{best}的dev配对差。用户bootstrap10000次、固定seed，区间仅描述用户抽样变动，**不覆盖训练随机性、目录选择/时间假设或反复使用dev的选型偏差**。

| 指标 | 平均差 | bootstrap95%区间 | 胜/负/平 |
|---|---:|---|---|
{chr(10).join(deltas)}

内容减SAR的次要对照和tuning配对统计保存在[聚合比较](stage11/paired-aggregate.json)，不按dev结果回头修改权重。

成本测量为CPU单数值线程、batch1、每用户轮换方法顺序；每方法首用户预热一次并排除该次计时，不能保证所有冷热分支均已预热。混合计入两个组件计算和融合，不复用其他方法本次请求结果。单次本地测量受进程/系统负载影响，不能视为服务SLA。tuning拟合SAR {fit['sar_seconds']:.3f}s、TFIDF {fit['tfidf_seconds']:.3f}s、画像 {fit['profiles_seconds']:.3f}s；矩阵存储{fit['sparse_storage_mib']:.2f}MiB，进程RSS前/SAR后/全部后={fit['rss_before_mib']:.1f}/{fit['rss_after_sar_mib']:.1f}/{fit['rss_after_all_mib']:.1f}MiB，是快照而非峰值或独立服务内存。每次重拟合签名一致后才读取该段标签。

## 验证、复现与结论边界

{int(tested.group(1))}项测试通过；12份完整输出逐用户重计分、用户集合/全部gold/已读过滤/目录/冷热指标核对，冷用户四方法完全一致，融合两个端点与原单方法完全一致，固定抽样排名复演，train模型签名重现，阶段3—10冻结资产核对不变。见[完整性收据](stage11/final-validation.json)。逐用户派生数据与预测只在被Git忽略的data/stage11-content，遵守Scholar Inbox非商业及禁止分享衍生材料限制；本报告仅聚合数据。

安装：`.cache/stage6-env/Scripts/python.exe scripts/setup_content_runtime.py`。固定官方二进制轮子和SHA256仅写项目.cache/stage11/deps，共享CUDA环境不改。数据准备函数`gsearch.content_recommendation.prepare()`拒绝覆盖已有目录。评价按顺序运行`python -m gsearch.benchmark_content --phase plan`、`tuning`、`lock`、`dev`（均使用上述解释器，已有结果拒绝覆盖）；报告用`python -m scripts.make_stage11_report`重检并生成。已有锁/输出应保留，独立复现实验需新目录及新协议，不能覆盖历史。

本轮未接管现有Agent默认推荐、未训练新T5/神经编码器，也未证明Agent质量收益。当前内容匹配是词法近似；大量未来点赞不在目录、源文本时间只是假设、单次测量及dev重复使用均限制结论。后续扩目录或神经内容方法必须重新审计可用时间与冻结评价，不用这轮dev继续调参。
'''
    Path("reports/阶段11_内容与协同推荐对照.md").write_text(doc,encoding="utf-8")
    write_json(ROOT/"final-validation.json",{"tests":int(tested.group(1)),"raw_outputs_rescored":validated,
        "model_signature_reproduced":True,"cold_outputs_identical":True,"fusion_endpoints_identical":True,
        "fixed_ranking_replay":"every500th user per method/split","historical_stages3_10":"unchanged",
        "selected_sar_weight":lock["selected_sar_weight"],"best_single_on_tuning":best,"dev_descriptive_only":True,
        "source_text":"exact snapshot fields; historical availability remains an assumption",
        "outputs":{p.name:sha256(p) for p in ROOT.glob("*.json") if p.name!="final-validation.json"},
        "code_assets":{str(p):sha256(p) for p in (Path("gsearch/content_recommendation.py"),Path("gsearch/benchmark_content.py"),Path("scripts/setup_content_runtime.py"),Path("scripts/make_stage11_report.py"),Path("tests/test_content_recommendation.py"))}})
    print(json.dumps({"tests":int(tested.group(1)),"selected_sar_weight":lock["selected_sar_weight"],
        "best_single":best,"dev_primary":delta,"report":"reports/阶段11_内容与协同推荐对照.md"}),flush=True)


if __name__=="__main__":
    main()
