"""Aggregate-only recommendation report; keep all adapted user records local."""
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd

from gsearch.benchmark_recommendation import DATA, METHODS, ROOT, check_plan, read
from gsearch.data import write_json
from gsearch.evaluate import metrics
from gsearch.identifiers import sha256
from gsearch.paper_recommendation import load_recommender


def paired(first: list[dict], second: list[dict]) -> dict:
    if [(r["user_id"], r["relevant"]) for r in first] != [(r["user_id"], r["relevant"]) for r in second]:
        raise ValueError("User comparisons are not paired")
    rng, result = np.random.default_rng(20261025), {}
    for metric in ("recall", "ndcg", "mrr"):
        delta = np.array([a[metric]-b[metric] for a, b in zip(first, second)])
        samples = np.concatenate([rng.choice(delta, size=(100, len(delta)), replace=True).mean(axis=1) for _ in range(100)])
        result[metric] = {"mean_delta": float(delta.mean()), "bootstrap_95_percentile_interval": np.quantile(samples, [0.025, 0.975]).tolist(),
                         "wins": int((delta > 1e-12).sum()), "losses": int((delta < -1e-12).sum()),
                         "ties": int((abs(delta) <= 1e-12).sum())}
    return result


def main() -> None:
    check_plan()
    lock, audit = read(ROOT / "locked-before-dev.json"), read(DATA / "audit.json")
    if (lock["plan_sha256"] != sha256(ROOT / "plan.json") or
            lock["tuning"] != {m: sha256(ROOT / f"{m}-tuning.json") for m in METHODS}):
        raise ValueError("Selection drift")
    engine = load_recommender()
    training = pd.read_csv(DATA / "train.csv", dtype={"user_id": str, "arxiv_id": str})
    future_frames = {s: pd.read_csv(DATA / f"{s}.csv", dtype={"user_id": str, "arxiv_id": str}) for s in ("tuning", "dev")}
    periods = [pd.to_datetime(f.time, format="mixed", utc=True) for f in (training, *future_frames.values())]
    if not periods[0].max() < periods[1].min() <= periods[1].max() < periods[2].min():
        raise ValueError("Temporal leakage or boundary overlap")
    counts = training[training.rating == 1].arxiv_id.value_counts().to_dict()
    if engine.catalog != sorted(sorted(counts, key=lambda d: (-counts[d], d))[:2048]):
        raise ValueError("Catalog selection did not use training-only popularity")
    results, predictions, validation = {}, {}, {}
    for split in ("tuning", "dev"):
        f = future_frames[split]
        positives = f[f.rating == 1].groupby("user_id").arxiv_id.agg(set).to_dict()
        for method in METHODS:
            result = read(ROOT / f"{method}-{split}.json")
            path = DATA / f"{method}-{split}-predictions.json"
            if result["predictions_sha256"] != sha256(path) or result["plan_sha256"] != sha256(ROOT / "plan.json"):
                raise ValueError("Raw prediction integrity mismatch")
            rows = read(path)["users"]
            if [r["user_id"] for r in rows] != sorted(positives):
                raise ValueError("Evaluation omitted users with future likes")
            for row in rows:
                ids = [h["doc_id"] for h in row["recommendations"]]
                if (set(row["relevant"]) != positives[row["user_id"]] or len(set(ids)) != len(ids) or
                        set(ids)&engine.seen.get(row["user_id"], set()) or not set(ids).issubset(engine.catalog)):
                    raise ValueError("Incorrect ground truth, duplicates, historical ratings or namespace")
                for metric, value in metrics(ids, set(row["relevant"]), 10).items():
                    if abs(row[metric]-value) > 1e-12:
                        raise ValueError("Raw metrics differ")
            for metric in ("recall", "hit", "mrr", "ndcg"):
                if abs(sum(r[metric] for r in rows)/len(rows)-result["summary"][metric+"@10"]) > 1e-12:
                    raise ValueError("Aggregate metrics differ")
            results[split, method], predictions[split, method] = result, rows
            validation[f"{method}-{split}"] = len(rows)
    selected = max(METHODS, key=lambda m: (results["tuning", m]["summary"]["ndcg@10"],
            results["tuning", m]["summary"]["recall@10"], results["tuning", m]["summary"]["mrr@10"], m == "popular"))
    if selected != lock["selected"]:
        raise ValueError("Selection differs from predeclared rule")
    comparisons = {s: paired(predictions[s, "sar"], predictions[s, "popular"]) for s in ("tuning", "dev")}
    write_json(ROOT / "paired-aggregate.json", comparisons)
    from scripts.make_stage8_report import verify_history
    from gsearch.benchmark_target_alignment import check_plan as check8
    verify_history()
    check8()
    old = read(Path("reports/stage8/final-validation.json"))
    if any(sha256(Path("reports/stage8")/name) != value for name, value in old["outputs"].items()):
        raise ValueError("Stage8 original results changed")
    log = (ROOT / "tests-final.log").read_text(encoding="utf-8-sig")
    tested = re.search(r"Ran (\d+) tests in [^\n]+\n\s*\nOK", log)
    if not tested:
        raise ValueError("Final tests did not pass")
    demo = read(Path("data/stage9-demo/agent-final.json"))
    generic = read(Path("data/stage9-demo/agent.json"))
    demo_summary = {"final_source_checked_selection": demo["source_checked_selection"],
        "tools": [r["tool"] for r in demo["trace"]], "seconds": demo["seconds"],
        "errors": sum("error" in r["result"] for r in demo["trace"]),
        "final_selected_count": len(demo["answer"].get("paper_ids", [])) if isinstance(demo["answer"], dict) else 0,
        "semantic_stance_verified": False, "generic_prompt_prior_tools": [r["tool"] for r in generic["trace"]],
        "case_selection": "first training-only user with a positive rating on an available original abstract",
        "scope": "single integration example; no recommendation or Agent quality benchmark conclusion"}
    write_json(ROOT / "agent-smoke-aggregate.json", demo_summary)
    table, groups, deltas = [], [], []
    for (split, method), result in results.items():
        s = result["summary"]
        table.append(f"| {split} | {method} | {s['evaluated_users_with_future_likes']} | {s['recall@10']:.6f} | {s['ndcg@10']:.6f} | {s['mrr@10']:.6f} | {s['catalog_coverage']:.2%} | {s['observed_future_dislikes_returned']} |")
        for group, g in result["groups"].items():
            groups.append(f"| {split} | {method} | {group} | {g['users']} | {g['recall']:.6f} | {g['ndcg']:.6f} |")
    for split, comp in comparisons.items():
        for metric, d in comp.items():
            lo, hi = d["bootstrap_95_percentile_interval"]
            deltas.append(f"| {split} | {metric} | {d['mean_delta']:+.6f} | [{lo:+.6f}, {hi:+.6f}] | {d['wins']}/{d['losses']}/{d['ties']} |")
    doc = f'''# 第九阶段：推荐算法与科研发现 Agent 融合

首个真实个性化推荐模块已经落地。复用原版Recommenders SAR，依据真实用户论文点赞构建协同偏好，接入查询无关推荐、个性化论文搜索和原文读取工具。tuning按预定规则选择 **{selected}**，随后冻结并评价后段数据。当前目录覆盖与绝对效果很低，因此不能包装成成熟推荐系统。

## 实际融合位置

```mermaid
flowchart TD
    U[用户历史点赞/已知点踩] --> R[原版SAR协同过滤]
    Q[当前研究查询] --> B[原版SQLite BM25]
    R --> P[无需查询的个性化推荐]
    R --> F[词法候选内BM25/SAR等权RRF]
    B --> F
    P --> A[smolagents科研发现工具]
    F --> A
    A --> E[读取已返回论文的原摘要]
    E --> S[原文来源检查后的论文选择]
```

同一user、arxiv命名空间、历史过滤和调用预算贯穿三工具。推荐解释来自训练点赞论文对候选的Jaccard贡献，不是凭空编写的语义相似度。点踩不作为正例，已知正负历史都排除；冷用户明确回退训练流行度。搜索在词法候选内融合偏好，不把全部流行论文混进查询结果。

**边界**：新入口尚未使用旧SciFact T5生成权重或NLI核验模型；它们属于不同目录和任务，保持原样。当前完成的是“协同推荐＋词法搜索＋原文读取＋Agent工具”的首版融合，生成式个性化推荐和新目录的证据分类还未训练。新数据没有查询相关性gold，个性化搜索仅通过接口/来源测试，不宣称排序收益已验证。

## 开源与数据选型

比较[Recommenders](https://github.com/recommenders-team/recommenders/tree/ba49f480a3a6604b09c8cde903958f9d9dca8a9d)（MIT）、Cornac（Apache2）和RecBole（MIT）。选SAR是因为其原版仅用当前已有numpy/pandas/scipy，避免编译或迁移整套训练栈；8份原始源码/许可Git blob逐项核验，未重写协同过滤。详见[来源审计](stage9/upstream-audit.json)、[许可证记录](../THIRD_PARTY_NOTICES.md)。

[Scholar Inbox原始数据](https://github.com/avg-dev/scholar_inbox_datasets/tree/92b0fac32110b1243081476f69607cf51aa71ad4)来自真实论文点赞/点踩，原文献[ACL2025论文](https://arxiv.org/abs/2504.08385)。实际{audit['source_rows']}条评分、{audit['users']}用户、{audit['papers']}篇，正负评分452434/321658。CiteULike镜像许可不明，未下载。

数据许可CC BY-NC-ND4.0，仅作本地非商业研究。原CSV/全文许可保持原样；处理后的逐用户划分、预测和Agent轨迹仅在忽略的data/保存，不分发改编数据。本报告及审计文件只含聚合统计和hash，不代表商业使用许可。

## 划分与实验预算

排除{audit['missing_or_invalid_time_rows_excluded']}条缺少/无效时间记录。全局时间80%/90%边界为{audit['cutoffs']['train_exclusive']}、{audit['cutoffs']['tuning_exclusive']}；源时区未声明，UTC仅统一排序。train/tuning/dev事件数612247/76531/76531，训练只用时间边界前的点赞。固定Jaccard、threshold1、binary affinity，无时间衰减或调参网格。tuning比较MostPop/SAR，以NDCG、Recall、MRR选型，平局优先流行度；dev不重选、不重新训练。

为控制SAR的item×item矩阵，候选仅取训练点赞频次最高2048篇，约32MiB float64相似度矩阵。**完整未来点赞均留在Recall分母**，目录外论文仍计漏召回；不采样容易的负例。候选只覆盖tuning未来点赞6.86%、dev5.21%，目录外与新论文是主要结构性限制。该结果是历史评分补全实验，存在原平台曝光选择偏差，不能解释为在线CTR或全站推荐效果。

## 结果

| split | 方法 | 有未来点赞的用户 | Recall@10 | NDCG@10 | MRR@10 | 推荐覆盖目录比例 | 返回的未来已知点踩数 |
|---|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(table)}

最后一列只统计未来明确点踩，未观察到的反馈不是确定负例。SAR虽有较大推荐目录覆盖，绝对命中率依然很低；没有将小幅相对变化当作高质量推荐。

warm指至少在2048目录内有一条训练点赞；cold包含真正新用户，以及只有目录外/负历史而未进入SAR用户矩阵的人。

| split | 方法 | 用户组 | 人数 | Recall@10 | NDCG@10 |
|---|---|---|---:|---:|---:|
{chr(10).join(groups)}

## 同用户差异 SAR−MostPop

| split | 指标 | 均值差 | 95%配对bootstrap区间 | 提高/下降/相同 |
|---|---|---:|---|---:|
{chr(10).join(deltas)}

10000次用户重采样，seed20261025，单数据时序划分，区间仅为描述性估计。不能把推荐模块结果转称为T5生成式检索或Agent收益。

## 真实Agent接入与验证

通用提示的首次Qwen1.5B运行出现工具格式解析失败，仅完成部分流程，原始失败保留在本地。随后单独新增领域提示适配，未改推荐实验的冻结代码/模型/结果。真实smolagents执行“推荐→读取原摘要→最终论文选择”，最终来源检查 **{demo_summary['final_source_checked_selection']}**，选中{demo_summary['final_selected_count']}篇；约{demo_summary['seconds']:.2f}秒，工具序列为{demo_summary['tools']}。最终检查拒绝未读取的论文ID，合成契约测试验证了该拒绝路径。

这只是一例集成检查，不是Agent相对固定流程的效果证明。推荐不构成科学论断的支持证据，原文来源可核对不等于语义事实已验证。

当前候选只含41篇已发布原摘要，可读推荐/搜索限制在此子集中；其他候选只返回真实arxiv ID和链接，缺原文时明确拒绝读取。原文件有709个有效arxiv ID，另有一个缺ID的唯一记录，准备审计的all_original_abstracts=710包含该记录；它没有进入目录或任何模型。没有虚构题名，显示标题仅为arxiv标识。

{tested.group(1)}项测试通过；四份原始预测全部重计分，训练时序/候选选择/历史正负过滤/逐用户分母核对通过，阶段3—8冻结资产不变。复现入口见[README](../README.md)，汇总收据见[final-validation.json](stage9/final-validation.json)。

## 后续融合路线

1. 优先补齐合法论文元数据和新论文入库，扩大候选覆盖；先解决当前5%左右的未来正例覆盖上限。
2. 复用成熟内容推荐/向量检索组件，为新论文和冷用户提供召回，按相同时序协议对照协同、内容及混合方案。
3. 在新文献目录上训练“用户历史＋当前研究任务→论文ID”的生成式推荐，保留协同/内容强基线；旧SciFact权重不直接迁移目录。
4. 最后评价Agent的偏好追问、探索与停止决策，固定检索推荐组件、同预算比较固定流程/规则/LLM，并另评证据任务。
'''
    Path("reports/阶段9_推荐与搜索融合.md").write_text(doc, encoding="utf-8")
    write_json(ROOT / "final-validation.json", {"frozen_protocol": "match", "raw_user_rescoring": validation,
        "training_only_catalog": True, "global_time_boundaries_disjoint": True, "all_future_positives_in_denominator": True,
        "historical_positive_and_negative_filter": "valid", "upstream_git_blobs": "8 original files match",
        "selected_recomputed": selected, "tests": int(tested.group(1)), "historical_stages3_4_5_6_7_8": "unchanged",
        "agent_smoke": demo_summary, "integration_post_benchmark": True,
        "integration_assets": {str(p): sha256(p) for p in (Path("gsearch/recommendation_agent.py"), Path("gsearch/prompts/discovery.txt"))},
        "outputs": {p.name: sha256(p) for p in ROOT.glob("*.json") if p.name != "final-validation.json"}})
    print(json.dumps({"selected": selected, "raw_rescoring": validation, "tests": int(tested.group(1)), "agent": demo_summary}), flush=True)


if __name__ == "__main__":
    main()
