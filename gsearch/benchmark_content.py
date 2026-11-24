"""Frozen four-family content/collaborative comparison with tuning-only fusion selection."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd

from .content_recommendation import ALPHAS, DATA, ORIGINAL, PARAMS, ROOT, load, read, sklearn_runtime
from .data import write_json
from .evaluate import metrics
from .identifiers import sha256


SINGLES = ("popular","sar","content")
FUSIONS = {f"hybrid_a{round(a*100):03d}":a for a in ALPHAS}


def state() -> dict:
    return {"runtime":sklearn_runtime(),"runtime_lock_sha256":sha256(ROOT/"runtime-lock.json"),
        "data":{p.name:sha256(p) for p in DATA.glob("*.json") if p.name in ("documents.json","catalog.json","excluded.json","audit.json")},
        "feedback":{s:sha256(ORIGINAL/(s+".csv")) for s in ("train","tuning","dev")},
        "code":{p:sha256(Path("gsearch")/p) for p in ("content_recommendation.py","benchmark_content.py","paper_recommendation.py","evaluate.py")},
        "upstream_audit":sha256(ROOT/"upstream-audit.json")}


def check_plan() -> dict:
    plan = read(ROOT/"plan.json")
    if plan["state"]!=state() or plan["params"]!=PARAMS or plan["alphas"]!=list(ALPHAS):
        raise ValueError("Content comparison protocol drift")
    return plan


def sparse_digest(matrix: object) -> str:
    h=hashlib.sha256()
    h.update(str(matrix.shape).encode())
    for array in (matrix.data,matrix.indices,matrix.indptr):
        h.update(array.tobytes())
    return h.hexdigest()


def model_signature(engine: object) -> dict:
    return {"catalog":engine.catalog,"users_sha256":hashlib.sha256("\n".join(engine.users).encode()).hexdigest(),
        "vocabulary_sha256":hashlib.sha256(json.dumps({w:int(i) for w,i in engine.vectorizer.vocabulary_.items()},sort_keys=True).encode()).hexdigest(),
        "idf_sha256":hashlib.sha256(engine.vectorizer.idf_.tobytes()).hexdigest(),
        "documents_sha256":sparse_digest(engine.documents),"profiles_sha256":sparse_digest(engine.profiles),
        "histories_sha256":sparse_digest(engine.history_matrix),
        "sar_similarity_sha256":hashlib.sha256(np.asarray(engine.sar.model.item_similarity).tobytes()).hexdigest()}


def pick_metric(method: str, result: dict) -> tuple:
    s=result["summary"]
    return (s["ndcg@10"],s["recall@10"],s["mrr@10"])


def run_evaluation(split: str) -> None:
    sklearn_runtime()
    from threadpoolctl import threadpool_limits
    if split=="tuning":
        methods={m:(m,None) for m in SINGLES}
        methods.update({m:("hybrid",a) for m,a in FUSIONS.items()})
    else:
        lock=read(ROOT/"locked-before-dev.json")
        methods={m:(m,None) for m in SINGLES}
        methods["hybrid"]=("hybrid",lock["selected_sar_weight"])
    if any((ROOT/f"{m}-{split}.json").exists() for m in methods):
        raise ValueError("Refusing to overwrite evaluation")
    with threadpool_limits(limits=1):
        engine=load()
        signature=model_signature(engine)
        signature_path=DATA/"model-signature.json"
        if signature_path.exists():
            if read(signature_path)!=signature:
                raise ValueError("Model/data fit changed across tuning/dev")
        else:
            if split!="tuning":
                raise ValueError("Train model must be frozen before dev")
            write_json(signature_path,signature)
        frame=pd.read_csv(ORIGINAL/(split+".csv"),dtype={"user_id":str,"arxiv_id":str})
        positives=frame[frame.rating==1].groupby("user_id").arxiv_id.agg(set).to_dict()
        negatives=frame[frame.rating==-1].groupby("user_id").arxiv_id.agg(set).to_dict()
        users=sorted(positives)
        method_names=list(methods)
        rows={m:[] for m in methods}
        for m,(mode,a) in methods.items():
            engine.recommend(users[0],mode,10,0.5 if a is None else a)  # excluded warmup
        for position,user in enumerate(users):
            rotate=position%len(method_names)
            order=method_names[rotate:]+method_names[:rotate]
            for method in order:
                mode,a=methods[method]
                started=time.perf_counter()
                hits=engine.recommend(user,mode,10,0.5 if a is None else a)
                elapsed=time.perf_counter()-started
                ids=[h["doc_id"] for h in hits]
                if set(ids)&engine.sar.seen.get(user,set()) or len(ids)!=len(set(ids)):
                    raise ValueError("Known ratings or duplicates entered output")
                relevant=positives[user]
                inside=relevant&set(engine.catalog)
                rows[method].append({"user_id":user,"relevant":sorted(relevant),"recommendations":hits,
                    **metrics(ids,relevant,10),"seconds":elapsed,"warm":user in engine.user2row,
                    "text_profile_zero":user in engine.zero_profile_users,
                    "catalog_positive_count":len(inside),
                    "catalog_recall":len(set(ids)&inside)/len(inside) if inside else None,
                    "observed_future_dislikes_returned":len(set(ids)&negatives.get(user,set()))})
            if (position+1)%1000==0:
                print(json.dumps({"split":split,"users_done":position+1,"total":len(users)}),flush=True)
        for method in methods:
            records=rows[method]
            seconds=np.array([r["seconds"] for r in records])
            summary={k+"@10":sum(r[k] for r in records)/len(records) for k in ("recall","hit","mrr","ndcg")}
            summary.update({"users":len(records),"warm_users":sum(r["warm"] for r in records),
                "cold_users":sum(not r["warm"] for r in records),"catalog_items":len(engine.catalog),
                "catalog_coverage":len({h["doc_id"] for r in records for h in r["recommendations"]})/len(engine.catalog),
                "future_positive_catalog_coverage":sum(r["catalog_positive_count"] for r in records)/sum(len(r["relevant"]) for r in records),
                "observed_future_dislikes_returned":sum(r["observed_future_dislikes_returned"] for r in records),
                "mean_seconds":float(seconds.mean()),"median_seconds":float(np.median(seconds)),
                "p95_seconds":float(np.quantile(seconds,.95))})
            groups={}
            for warm in (True,False):
                group=[r for r in records if r["warm"]==warm]
                groups["warm" if warm else "cold"]={"users":len(group),**{
                    k:sum(r[k] for r in group)/len(group) if group else None for k in ("recall","mrr","ndcg")}}
            destination=DATA/f"{method}-{split}-predictions.json"
            write_json(destination,{"method":method,"split":split,"users":records})
            result={"method":method,"split":split,"k":10,"sar_weight":methods[method][1],
                "summary":summary,"groups":groups,"fit":engine.fit,"model_signature_sha256":sha256(signature_path),
                "predictions_sha256":sha256(destination),"plan_sha256":sha256(ROOT/"plan.json"),
                "cost_note":"CPU single numerical thread, batch1, rotated method order per user, excluded warmup; component calculations included per request; fit costs separate",
                "scope":"All future likes counted; snapshot temporal screening is an assumption; reused dev; lexical content baseline"}
            write_json(ROOT/f"{method}-{split}.json",result)
            print(json.dumps({"method":method,"split":split,"summary":summary}),flush=True)


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--phase",choices=("plan","tuning","lock","dev"),required=True)
    args=parser.parse_args()
    if args.phase=="plan":
        if (ROOT/"plan.json").exists():
            raise ValueError("Protocol must precede tuning")
        write_json(ROOT/"plan.json",{"frozen_before_tuning":True,"state":state(),"params":PARAMS,"alphas":list(ALPHAS),
            "families":list(SINGLES)+["hybrid"],"k":10,"fusion":"alpha/(60+SAR_rank)+(1-alpha)/(60+content_rank), ranks computed after common seen mask; alpha0/1 use exact single branch",
            "selection":"tuning NDCG, Recall, MRR; fusion ties prefer endpoint then smaller alpha; best single ties prefer popular then SAR then content",
            "profile":"L2 normalize sum of liked eligible document TF-IDF vectors; same positive history as SAR; no heldout text/feedback fitting",
            "cold":"no eligible train likes -> identical popularity fallback for all methods; zero text profile -> explicit content popularity fallback",
            "mask":"all train-period positive and negative ratings; no future dislikes used as mask",
            "temporal_assumption":read(DATA/"audit.json"),"threads":1,
            "primary_comparison":"selected hybrid versus best single selected on tuning; four dev methods only, no dev grid search"})
        return
    check_plan()
    if args.phase=="lock":
        if (ROOT/"locked-before-dev.json").exists():
            raise ValueError("Refusing to overwrite selection")
        results={m:read(ROOT/f"{m}-tuning.json") for m in (*SINGLES,*FUSIONS)}
        fusion=max(FUSIONS,key=lambda m:(*pick_metric(m,results[m]),FUSIONS[m] in (0,1),-FUSIONS[m]))
        single=max(SINGLES,key=lambda m:(*pick_metric(m,results[m]),-SINGLES.index(m)))
        write_json(ROOT/"locked-before-dev.json",{"frozen_before_dev":True,"selected_fusion":fusion,
            "selected_sar_weight":FUSIONS[fusion],"best_single_on_tuning":single,"plan_sha256":sha256(ROOT/"plan.json"),
            "tuning_hashes":{m:sha256(ROOT/f"{m}-tuning.json") for m in results},
            "model_signature_sha256":sha256(DATA/"model-signature.json")})
        print(json.dumps({"selected_fusion":fusion,"best_single":single}),flush=True)
        return
    if args.phase=="dev":
        lock=read(ROOT/"locked-before-dev.json")
        if (lock["plan_sha256"]!=sha256(ROOT/"plan.json") or
            lock["tuning_hashes"]!={m:sha256(ROOT/f"{m}-tuning.json") for m in (*SINGLES,*FUSIONS)} or
            lock["model_signature_sha256"]!=sha256(DATA/"model-signature.json")):
            raise ValueError("Frozen fusion/single/model changed")
    run_evaluation(args.phase)


if __name__=="__main__":
    main()
