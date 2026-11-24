"""Audit enrichment coverage, exact source text, identity joins, and real Agent source reads."""
import hashlib
import json
from pathlib import Path
import re

from gsearch.data import write_json
from gsearch.enrich_catalog import OUTPUT, source_valid
from gsearch.identifiers import sha256
from gsearch.metadata_fetch import CATALOG, ROOT as CACHE, read
from gsearch.paper_identity import canonical_id
from gsearch.retrieval import BM25, Corpus


ROOT = Path("reports/stage10")


def main() -> None:
    audit, metadata = read(OUTPUT/"audit.json"), read(OUTPUT/"metadata.json")
    original = read(CATALOG)
    corpus = Corpus(OUTPUT/"documents.json")
    if ([r["doc_id"] for r in metadata] != [canonical_id(x) for x in original] or
            len(metadata) != 2048 or audit["original_catalog_sha256"] != sha256(CATALOG)):
        raise ValueError("Catalog identity/coverage denominator changed")
    source_cache, checked = {}, 0
    for record in metadata:
        if record.get("fetch_status") != "acquired":
            continue
        if not source_valid(record):
            raise ValueError("Source hash/identity mismatch")
        path = record["provenance"]["raw_path"]
        if path not in source_cache:
            payload = json.loads(Path(path).read_bytes())
            source_cache[path] = {canonical_id(r["paper_id"]): r for r in payload}
        source = source_cache[path][record["doc_id"]]
        if (source.get("title") != record["title"] or source.get("abstract") != record["abstract"] or
                source.get("first_version_date") != record["published_at"]):
            raise ValueError("Enriched title/abstract/date differ from exact source metadata")
        checked += 1
    lexical = BM25(corpus)
    indexed = {r[0] for r in lexical.db.execute("SELECT doc_id FROM docs")}
    if indexed != set(corpus.by_id) or len(indexed) != audit["coverage_counts"]["searchable"]:
        raise ValueError("Search index omitted or introduced identities")
    sample_results = []
    for doc in corpus.documents[:10]:
        hits = lexical.search(doc["title"], 10)
        sample_results.append({"returned": len(hits), "all_ids_valid": all(h["doc_id"] in indexed for h in hits)})
    lexical.db.close()
    demo = read(Path("data/stage10-demo/agent.json"))
    result = demo["result"]
    reads = [r["result"] for r in demo["trace"] if r["tool"] == "read_paper" and "error" not in r["result"]]
    if not result["source_checked_selection"] or not reads or not all(r["source_verified"] for r in reads):
        raise ValueError("Real Agent did not complete a source-checked original abstract read")
    demo_summary = {"tools": [r["tool"] for r in demo["trace"]], "source_checked_selection": result["source_checked_selection"],
                    "source_reads": len(reads), "seconds": result["seconds"], "semantic_stance_verified": False,
                    "scope": "single integration smoke; not relevance, recommendation, or factual correctness evaluation"}
    write_json(ROOT/"agent-smoke-aggregate.json", demo_summary)
    from gsearch.benchmark_recommendation import check_plan as check9
    from scripts.make_stage8_report import verify_history
    from gsearch.benchmark_target_alignment import check_plan as check8
    check9()
    check8()
    verify_history()
    old = read(Path("reports/stage9/final-validation.json"))
    if any(sha256(Path("reports/stage9")/n) != v for n, v in old["outputs"].items()):
        raise ValueError("Stage9 frozen outputs changed")
    log = (ROOT/"tests-final.log").read_text(encoding="utf-8-sig")
    match = re.search(r"Ran (\d+) tests in [^\n]+\n\s*\nOK", log)
    if not match:
        raise ValueError("Final tests not successful")
    previous = read(Path("data/stage9-recommendation/documents.json"))
    by_id = {r["doc_id"]: r for r in metadata}
    comparison = {"old_abstract_count": len(previous),
        "exact_same": sum(d["sentences"][0] == by_id[d["doc_id"]].get("abstract") for d in previous),
        "whitespace_normalized_same": sum(" ".join(d["sentences"][0].split()) == " ".join((by_id[d["doc_id"]].get("abstract") or "").split()) for d in previous)}
    write_json(ROOT/"old-abstract-comparison.json", comparison)
    counts = audit["coverage_counts"]
    rows = [f"| {label} | {counts[key]} / 2048 | {counts[key]/2048:.2%} |" for key, label in (
        ("has_title", "真实标题"), ("has_abstract", "原摘要"), ("has_published_date", "arXiv首次提交日期"),
        ("has_source", "来源与响应校验"), ("searchable", "可搜索（已入FTS）"), ("citable", "可引用原摘要"))]
    mappings = [f"| {split} | {v['all_rows']} | {v['candidate_rows']} | {v['candidate_unmapped_rows']} | {v['outside_catalog_rows']} |"
                for split, v in audit["identity"]["interactions"].items()]
    doc = f'''# 第十阶段：2048篇候选元数据补齐与论文身份统一

完成固定目录的源元数据补齐、身份映射及原文读取验证。候选仍为阶段9同一2048篇，没有新增候选、重训或重新调参。独立目录为data/stage10-catalog，旧实验和交互文件保留原样。

## 获取组件、条款与实际来源

对比[arxiv.py](https://github.com/lukasschwab/arxiv.py/tree/09d1b8bc3c85c6334d480fa94c310c3b729b1d01)和arxivpy，选择维护较新的MIT arxiv.py，原样保留5份源码/许可及Git blob。检查了官方请求分页、重试/限速、Result与lxml解析；适配层只加超时、请求记录、全局冷却、缓存和断点，不执行PDF下载。[官方条款](https://github.com/arXiv/arxiv-docs/blob/dfa98b066152b89bd6f0195c88e3c751d210900a/source/help/api/tou.md)规定描述性元数据CC0、legacy API单连接且至少3秒间隔；这不授权复制全文。

实际访问中官方API两次429，第一次后冷却五分钟再试，随后停止，原始响应/时间与失败批次保留；没有换arxiv地址绕过限流。Hugging Face过滤服务返回500，另一元数据镜像查询遇到TLS中断。最终只读取[公开arXiv OAI元数据快照](https://huggingface.co/datasets/secemp9/arxiv-complete/tree/cee894837962fede5612cccf2a4c7cacf49b4c3a/metadata)，固定commit cee894837962fede5612cccf2a4c7cacf49b4c3a，发布者声明收集日期2026-08-30；不是官方实时API结果，也不是逐篇实时网页复核。

复用PyArrow26.0.0（Apache2.0）与已有HfFileSystem0.36.2，对固定metadata Parquet按列/分组读取，按ID选出原始记录；不下载PDF、LaTeX或fulltext配置。先用小读取缓存，发现往返开销大后保留断点、改用有界分块缓存；公开镜像最多4个读取器，与停止的arxiv legacy API请求分开。PyArrow仅装到项目.cache/stage10/deps，没有升级共享环境。文件LFS SHA、读取位置、原始选中行、标题/摘要精确字节hash与来源许可均保留。详见[选型审计](stage10/upstream-audit.json)。

## 覆盖审计

| 项目 | 数量 | 比例 |
|---|---:|---:|
{chr(10).join(rows)}

失败或缺字段共{audit['failure_items']}篇，逐篇原因保存在data/stage10-catalog/failures.json。缺字段不生成补写。可搜索表示真实标题＋摘要已入FTS并可查询，不意味着任意查询都能排进Top10；可引用仅指来源可追溯的原摘要，不代表完整论文可用或科学论断被证实。

原目录只有41篇摘要，题名是ID占位；新目录显示真实源标题。与旧41篇逐字/空白归一比较为{comparison['exact_same']}/{comparison['whitespace_normalized_same']}篇相同，版本或格式差异不覆盖旧文本。日期字段是源记录中的首次arxiv提交时间，**不是期刊正式出版日期**。快照文字可能晚于历史推荐划分，不将当前富化文本回填为过去已知信息来重新宣称推荐改善。

## 统一身份与交互映射

基本ID标识论文，paper_key统一为arxiv:ID，版本独立记录。网址、arXiv:前缀和版本别名可解析为相同论文身份，恶意域名/非法ID拒绝。快照只给版本数量时不猜最新版本号；请求未取得的具体vN版本会明确拒绝，不用当前摘要替代。

| split | 全部交互 | 本候选目录交互 | 本目录未映射 | 目录外交互（保留） |
|---|---:|---:|---:|---:|
{chr(10).join(mappings)}

原始交互、原推荐候选与SAR输入不变；新candidate-interactions.csv只是本目录的映射视图，逐用户数据仍本地保存，不分发。目录外事件没有被删除或假装映射成功。推荐、搜索、原文读取返回同一doc_id及paper_key。

## Agent原文读取与验证

新入口gsearch.catalog_discovery调用既有SAR、BM25、smolagents和领域提示Qwen。真实例子工具序列{demo_summary['tools']}，完成{demo_summary['source_reads']}次来源校验读取，最终选择检查{demo_summary['source_checked_selection']}，约{demo_summary['seconds']:.2f}秒。原摘要返回时再次核对缓存响应hash及标题/摘要逐字一致；拒绝未检索论文、未获取版本、篡改文本或缺来源的引用。这是一例集成验证，不证明Agent优于固定流程，也没有迁移旧SciFact NLI。

{match.group(1)}项测试通过，包括ID/URL/版本边界、原版Atom解析、快照版本数量不冒充版本号、来源篡改拒绝和原有推荐/证据预算。四个推荐原始输出等历史阶段3—9资产核对不变。本轮没有重新训练或评价推荐质量。

**目录仍为2048篇，因此本次不会直接改变阶段9的5.21%未来点赞候选覆盖率。** 下一步才是新论文入库和内容召回，需单独设计时间可用性与推荐对照。

复现与入口见[README](../README.md)。覆盖JSON：[coverage.json](stage10/coverage.json)；完整性收据：[final-validation.json](stage10/final-validation.json)。原始源响应和缓存仅在.cache/stage10，富化字段、映射与逐篇失败在data/stage10-catalog，逐用户Agent轨迹在data/stage10-demo。
'''
    Path("reports/阶段10_目录补齐与身份统一.md").write_text(doc, encoding="utf-8")
    write_json(ROOT/"final-validation.json", {"catalog_items":2048,"exact_source_rows_checked":checked,
        "coverage_counts":counts,"identity_mapping":audit["identity"],"ftS_index_identities":"match",
        "title_query_smokes":sample_results,"real_agent":demo_summary,"tests":int(match.group(1)),
        "historical_stages3_4_5_6_7_8_9":"unchanged","old_abstract_comparison":comparison,
        "data_assets":{p.name:sha256(p) for p in OUTPUT.iterdir() if p.is_file()},
        "code_assets":{str(p):sha256(p) for p in (Path('gsearch/paper_identity.py'),Path('gsearch/metadata_fetch.py'),
            Path('gsearch/enrich_catalog.py'),Path('gsearch/catalog_discovery.py'),Path('scripts/read_metadata_parquet.py'))}})
    print(json.dumps({"coverage":counts,"source_rows_checked":checked,"tests":int(match.group(1)),"agent":demo_summary}),flush=True)


if __name__ == "__main__":
    main()
