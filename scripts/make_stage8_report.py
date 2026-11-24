"""Validate matched training receipts and report the frozen tuning decision."""
import hashlib
import json
from pathlib import Path
import re

from gsearch.benchmark_target_alignment import check_plan, gate, group_summary, weights
from gsearch.data import write_json
from gsearch.evaluate import metrics
from gsearch.identifiers import sha256
from gsearch.train_target_alignment import AlignedDataset, DATA, ROOT, RUNS, TARGETS, TRAINING, read
from scripts.make_stage4_report import paired


def verify_training() -> dict:
    plan = check_plan()
    common = read(TARGETS / "common.json")
    receipts = {}
    for mode, path in RUNS.items():
        run = read(path / "run.json")
        if (run["training"] != TRAINING or run["plan_sha256"] != sha256(ROOT / "plan.json") or
                run["initial_assets"] != plan["state"]["base_assets"] or run["engine"] != plan["state"]["engine"] or
                run["observed_steps"] != 4000 or run["observed_samples"] != 32000 or run["observed_batches"] != 4000 or
                run["common_sha256"] != sha256(TARGETS / "common.json") or
                run["target_sha256"] != sha256(TARGETS / f"{mode}.json")):
            raise ValueError("Wrong training budget or provenance")
        dataset = AlignedDataset(common, read(TARGETS / f"{mode}.json")["aliases"])
        digest = hashlib.sha256()
        usage = {k: 0 for k in ("input_tokens", "padded_input_tokens", "label_tokens", "padded_label_tokens")}
        for start in range(0, len(dataset), 8):
            batch = [dataset[i] for i in range(start, start+8)]
            for row in batch:
                row.pop("_position")
                digest.update((json.dumps(row, sort_keys=True, separators=(",", ":"))+"\n").encode())
            usage["input_tokens"] += sum(sum(r["attention_mask"]) for r in batch)
            usage["padded_input_tokens"] += max(len(r["input_ids"]) for r in batch)*8
            usage["label_tokens"] += sum(len(r["labels"]) for r in batch)
            usage["padded_label_tokens"] += max(len(r["labels"]) for r in batch)*8
        if run["usage"] != usage or run["observed_token_batch_sha256"] != digest.hexdigest():
            raise ValueError("Actual collated batches differ from frozen data")
        receipts[mode] = run
    a, b = receipts.values()
    for key in ("initial_assets", "task_position_schedule_sha256", "common_sha256", "engine", "training", "trainable_parameters"):
        if a[key] != b[key]:
            raise ValueError(f"Training groups differ in {key}")
    if any(a["usage"][k] != b["usage"][k] for k in ("input_tokens", "padded_input_tokens")):
        raise ValueError("Training inputs were not paired")
    return receipts


def verify_history() -> None:
    from gsearch.benchmark_bundles import code_hashes
    from gsearch.benchmark_identifiers import state, training_state
    from gsearch.benchmark_query_aug import check_state as check5, trained_models
    from gsearch.benchmark_prefix import check_state as check7
    from gsearch.retrieval import Corpus
    from gsearch.verification import validate_frozen_assets
    p3 = read(Path("reports/stage3-locked-protocol.json"))
    if p3["code_hashes"] != code_hashes():
        raise ValueError("Stage3 code changed")
    if (p3["tasks_audit_sha256"] != sha256(Path("data/stage3-bundles/audit.json")) or
            p3["verifier_config_sha256"] != sha256(Path("reports/stage2-locked-config.json"))):
        raise ValueError("Stage3 tasks/verifier config changed")
    validate_frozen_assets(Corpus(Path("data/prepared/documents.json")), read(Path("reports/stage2-locked-config.json")))
    if (read(Path("reports/stage4/plan.json"))["state"] != state() or
            read(Path("reports/stage4/locked-before-dev.json"))["weights"] != training_state()):
        raise ValueError("Stage4 assets changed")
    p5 = read(Path("reports/stage5/plan.json"))
    check5(p5)
    if read(Path("reports/stage5/locked-before-dev.json"))["models"] != trained_models(p5):
        raise ValueError("Stage5 assets changed")
    check7(read(Path("reports/stage7/plan.json")))
    for stage in (6, 7):
        receipt = read(Path(f"reports/stage{stage}/final-validation.json"))
        if any(sha256(Path(f"reports/stage{stage}") / name) != value for name, value in receipt["outputs"].items()):
            raise ValueError(f"Stage{stage} recorded outputs changed")
    if "stage3-7 unchanged" not in (ROOT / "historical-validation-corrected.log").read_text(encoding="utf-8-sig"):
        raise ValueError("Missing stage6 original isolated-runtime validation")


def verify_output(result: dict, split: str, mode: str) -> None:
    claims = [c for c in read(DATA / f"{split}.json") if c["evidence"]]
    if [r["claim_id"] for r in result["queries"]] != [c["id"] for c in claims]:
        raise ValueError("Missing, reordered or duplicate judged queries")
    aliases = {tuple(r["token_ids"]): r["doc_id"] for r in read(TARGETS / f"{mode}.json")["aliases"]} if mode in RUNS else {}
    if mode in RUNS and len(result["decode_work"]) != len(claims):
        raise ValueError("Extra or missing work receipts")
    for i, (row, claim) in enumerate(zip(result["queries"], claims)):
        if row["query"] != claim["claim"] or row["relevant"] != sorted(claim["evidence"]):
            raise ValueError("Query/label mismatch")
        for k, v in metrics([r["doc_id"] for r in row["predictions"]], set(row["relevant"]), 10).items():
            if abs(row[k]-v) > 1e-12:
                raise ValueError("Raw prediction rescoring differs")
        if mode in RUNS:
            work = result["decode_work"][i]
            if (work["query_sha256"] != hashlib.sha256(row["query"].encode()).hexdigest() or
                    len(row["predictions"]) != 10 or len({r["doc_id"] for r in row["predictions"]}) != 10 or
                    work["returned_alias_tokens_including_eos"] != [len(r["generated_token_ids"]) for r in row["predictions"]]):
                raise ValueError("Decode work misaligned")
            if any(aliases[tuple(r["generated_token_ids"])] != r["doc_id"] for r in row["predictions"]):
                raise ValueError("Raw token lookup differs from original document identity")
    if result["groups"] != group_summary(result):
        raise ValueError("Supervision groups differ")
    for k in ("recall", "hit", "mrr", "ndcg"):
        if abs(sum(r[k] for r in result["queries"])/len(claims)-result["summary"][k+"@10"]) > 1e-12:
            raise ValueError("Summary rescoring differs")
    if abs(sum(r["seconds"] for r in result["queries"])/len(claims)-result["summary"]["mean_seconds"]) > 1e-12:
        raise ValueError("Summary timings differ from raw query timings")
    if mode in RUNS:
        expected_cost = {"mean_returned_tokens": sum(sum(r["returned_alias_tokens_including_eos"]) for r in result["decode_work"])/(len(claims)*10),
                         "mean_generation_steps": sum(r["generation_steps"] for r in result["decode_work"])/len(claims)}
        if expected_cost != result["cost"]:
            raise ValueError("Reported cost differs from raw generation receipts")


def main() -> None:
    plan = check_plan()
    decision = read(ROOT / "tuning-decision.json")
    if (decision["weights"] != weights() or decision["plan_sha256"] != sha256(ROOT / "plan.json") or
            decision["tuning_hashes"] != {m: sha256(ROOT / f"{m}-tuning.json") for m in (*RUNS, "bm25")}):
        raise ValueError("Decision inputs changed")
    computed = gate(read(ROOT / "full-tuning.json"), read(ROOT / "short-tuning.json"))
    if any(decision[k] != v for k, v in computed.items()):
        raise ValueError("Gate decision does not follow frozen rule")
    if not decision["passed"] and (list(ROOT.glob("*-dev.json")) or (ROOT / "locked-before-dev.json").exists()):
        raise ValueError("Dev evaluated despite failed tuning gate")
    if decision["passed"] and read(ROOT / "locked-before-dev.json") != decision:
        raise ValueError("Missing pre-dev freeze")
    runs = verify_training()
    verify_history()
    test_log = (ROOT / "tests-final.log").read_text(encoding="utf-8-sig")
    test_match = re.search(r"Ran (\d+) tests in [^\n]+\n\s*\nOK", test_log)
    if not test_match:
        raise ValueError("Missing successful final test run")
    splits = ("tuning", "dev") if decision["passed"] else ("tuning",)
    data = {s: {m: read(ROOT / f"{m}-{s}.json") for m in (*RUNS, "bm25")} for s in splits}
    comparisons, table, groups, costs, raw = {}, [], [], [], {}
    for split, methods in data.items():
        comparisons[split] = paired(methods["short"], methods["full"])
        for mode, result in methods.items():
            verify_output(result, split, mode)
            raw[f"{mode}-{split}"] = len(result["queries"])
            s = result["summary"]
            table.append(f"| {split} | {mode} | {s['judged_queries']} | {s['recall@10']:.6f} | {s['mrr@10']:.6f} | {s['ndcg@10']:.6f} | {s['mean_seconds']*1000:.2f} |")
            for label, group in result["groups"].items():
                groups.append(f"| {split} | {mode} | {label} | {group['queries']} | {group['recall']:.6f} | {group['ndcg']:.6f} |")
            if mode in RUNS:
                c = result["cost"]
                costs.append(f"| {split} | {mode} | {c['mean_returned_tokens']:.3f} | {c['mean_generation_steps']:.3f} | {s['mean_seconds']*1000:.2f} |")
    budgets = []
    for mode, run in runs.items():
        u = run["usage"]
        budgets.append(f"| {mode} | {u['input_tokens']} / {u['padded_input_tokens']} | {u['label_tokens']} / {u['padded_label_tokens']} | {run['seconds']:.2f} | {run['peak_allocated_mib']:.1f} |")
    pair_rows = []
    for split, comparison in comparisons.items():
        for metric in ("recall", "mrr", "ndcg"):
            p = comparison[metric]
            lo, hi = p["bootstrap_95_percentile_interval"]
            pair_rows.append(f"| {split} | {metric} | {p['mean_delta']:+.6f} | [{lo:+.6f}, {hi:+.6f}] | {p['wins']}/{p['losses']}/{p['ties']} |")
    write_json(ROOT / "paired.json", comparisons)
    outcome = "通过预定 tuning 门槛，冻结后评价两组 dev。" if decision["passed"] else "未通过预定 tuning 门槛，停止本轮短 ID 方案；没有跑 dev。"
    text = f'''# 第八阶段：完整/压缩 ID 匹配训练

{outcome} 这是同一基础T5、同一抽样序列、同一步数、不同原始token目标的配对实验。旧模型、Agent及历史冻结协议未改动。完整原始预测、训练日志、模型/代码/数据hash和调参前协议保存在[阶段目录](stage8/)。

## 开源复用与对照

实际调用 [Transformers v4.57.1 Seq2SeqTrainer](https://github.com/huggingface/transformers/tree/8cb5963cc22174954e7dca2c0a3320b7dc2f4edc) 和 DataCollatorForSeq2Seq，Apache2.0；官方翻译例程用于核对接口，不执行例程或下载它的数据。训练薄子类仅以Torch SequentialSampler替换随机sampler；使用原torch AdamW全部参数decay、恒定学习率、原生T5平均token交叉熵。未重写训练循环。

沿用[已核验ZeroGR原树](../third_party/zerogr_prefix/)，不运行其8×A800训练或含shell调用的入口。Tevatron的对比学习encoder训练与本轮生成目标不同，未迁移。[来源与适配成本](stage8/upstream-audit.json)；各许可证及复用边界见[第三方记录](../THIRD_PARTY_NOTICES.md)。本轮无依赖安装、远程代码或新训练框架。

两组从相同google-t5/t5-small基础权重开始，60506624个可训练参数，train727、静态5183文档，seed42/batch8/4000步，query fraction0.5，max_input160，lr5e-4，AdamW wd0.01/beta0.9,0.999/eps1e-8，clip1，BF16，tf32关闭，零warmup/无梯度累积/不选中间checkpoint。实际15991次index、16009次query，schedule hash与历史一致。两组输入及顺序完全相同，raw token IDs+EOS目标分别来自完整/短树；197个文本重分词不稳定别名经过回归检查。不同目标长度改变token权重和计算量，因此不声称相同FLOPs。

| 组 | 输入/含padding token | 标签/含padding token | 训练秒 | 峰值MiB |
|---|---:|---:|---:|---:|
{chr(10).join(budgets)}

训练GPU成本是分开顺序运行的设备观测，不能独立归因于目标长度；不与历史阶段耗时直接比较。短组标签减少也没有在本次训练耗时中体现加速。Trainer日志的total_flos是框架估算，本报告不据此声称实际FLOPs相等。

## 训练前写定的验收规则

质量路线：短−全NDCG>=0.01、Recall下降<=0.01、至少一篇gold文档缺少train查询监督组的Recall下降<=0.02。或成本路线：同样Recall保护、NDCG下降<=0.01，同时平均返回token<=完整组75%、实测平均延迟<=85%。任一路线通过才冻结并进入dev；这些是pilot工程门槛，不是统计非劣性证明。[原协议](stage8/plan.json)、[决定与原始输入hash](stage8/tuning-decision.json)。

决定详情：`{json.dumps(computed, ensure_ascii=False)}`

## 检索质量与成本

| split | 方法 | 有效查询 | Recall@10 | MRR@10 | NDCG@10 | 平均ms |
|---|---|---:|---:|---:|---:|---:|
{chr(10).join(table)}

有效查询指存在公开相关文档标注的查询；tuning80中46条有效、34条无证据排除。其余未标注文献不能统一视为不相关。BM25仅作强参照。

| split | 组 | 平均每返回ID token（含EOS） | 平均生成步数 | 平均ms |
|---|---|---:|---:|---:|
{chr(10).join(costs)}

batch1，两模型预先同时驻留，逐查询交替full/short先后顺序，各1次warmup不计时；分词+HF原生beam10+ZeroGR回调+原doc_id查表都计时。固定length_penalty1、不采样、不重归一化。token节约、beam×生成步数是工作代理，不是FLOPs；功耗/时钟仍会影响设备延迟，不是独立随机重复性能试验。

## 原始查询监督覆盖组

all_gold_supervised指所有gold文档曾有train查询监督；some_gold_not_supervised指至少一篇没有。两组均可通过静态文档索引任务见到这些文档，不能称为未见文档。组仅用于评价，不参与样本构造或标签优化。

| split | 方法 | 覆盖组 | 查询数 | Recall@10 | NDCG@10 |
|---|---|---|---:|---:|---:|
{chr(10).join(groups)}

## 同查询差异（短−全）

| split | 指标 | 均值差 | 95% bootstrap区间 | 提高/下降/相同 |
|---|---|---:|---|---:|
{chr(10).join(pair_rows)}

10000次配对查询重采样，seed20261025，单次训练种子，区间为描述性分析；tuning门槛不用区间作进一步筛选。公开dev已多轮使用，若本轮评价也不能声称独立测试或多种子结论。本轮没有验证Agent/事实核验的收益，也不自动切换默认检索器。

复现顺序见[README](../README.md)；训练原始token batch收据逐项重算，全部预测重计分与工作记录对齐。{test_match.group(1)}项测试通过，包括真实Trainer更新与197个不稳定别名的raw标签回归；阶段3—7冻结资产核对不变。验证摘要见[final-validation.json](stage8/final-validation.json)。
'''
    Path("reports/阶段8_完整与短ID匹配训练.md").write_text(text, encoding="utf-8")
    write_json(ROOT / "final-validation.json", {"plan_state": "match", "training_batch_receipts": "recomputed_match",
        "same_initial_weights_inputs_order_steps": True, "raw_token_target_lookup": "match",
        "historical_stages3_4_5_6_7": "unchanged; stage6 verified in original isolated runtime",
        "tests": int(test_match.group(1)), "tests_log_sha256": sha256(ROOT / "tests-final.log"),
        "gate_recomputed": computed, "raw_rescoring": raw, "outputs": {p.name: sha256(p) for p in ROOT.glob("*.json")
                                                                                       if p.name != "final-validation.json"}})
    print(json.dumps({"gate": computed, "raw_rescoring": raw}), flush=True)


if __name__ == "__main__":
    main()
