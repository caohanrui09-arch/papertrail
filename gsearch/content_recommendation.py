"""Content/user-profile adaptation built from original sklearn and SAR components."""
from datetime import datetime, timezone
import importlib.metadata as metadata
import inspect
from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd
import psutil

from .data import write_json
from .identifiers import sha256
from .paper_recommendation import PaperRecommender


ROOT = Path("reports/stage11")
DATA = Path("data/stage11-content")
ORIGINAL = Path("data/stage9-recommendation")
PARAMS = {"ngram_range": [1, 2], "min_df": 2, "max_features": 30000,
          "stop_words": "english", "sublinear_tf": True, "norm": "l2"}
ALPHAS = (0.0, 0.25, 0.5, 0.75, 1.0)


def read(path: Path) -> dict | list:
    import json
    return json.loads(path.read_text(encoding="utf-8"))


def parse_time(value: str) -> datetime:
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)


def sklearn_runtime() -> dict:
    target = (Path(".cache/stage11/deps")).resolve()
    if str(target) not in sys.path:
        sys.path.insert(0, str(target))
    import sklearn.feature_extraction.text as text
    import sklearn.preprocessing._label as label
    import sklearn.preprocessing._data as preprocessing
    import sklearn.metrics.pairwise as pairwise
    if not Path(inspect.getfile(text)).resolve().is_relative_to(target):
        raise ValueError("Expected the isolated pinned content runtime")
    return {"packages": {n:metadata.version(n) for n in ("scikit-learn", "joblib", "threadpoolctl", "cloudpickle", "narwhals", "numpy", "scipy", "pandas", "psutil")},
            "source_hashes": {m.__name__:sha256(Path(inspect.getfile(m))) for m in (text,label,preprocessing,pairwise)}}


def prepare() -> None:
    if DATA.exists():
        raise ValueError("Refusing to overwrite content experiment data")
    cutoff_text = read(ORIGINAL/"audit.json")["cutoffs"]["train_exclusive"]
    cutoff = parse_time(cutoff_text)
    rows = read(Path("data/stage10-catalog/metadata.json"))
    eligible, excluded = [], []
    for row in rows:
        try:
            past = parse_time(row["updated_at"]) < cutoff and parse_time(row["published_at"]) < cutoff
        except (ValueError, TypeError, KeyError):
            past = False
        if past and row["coverage"]["has_title"] and row["coverage"]["has_abstract"]:
            eligible.append({k:row[k] for k in ("doc_id", "title", "abstract", "published_at", "updated_at")})
        else:
            excluded.append({"doc_id":row["doc_id"], "published_at":row.get("published_at"), "updated_at":row.get("updated_at"),
                             "reason":"latest version not strictly pre-cutoff, unknown dates, or missing text"})
    eligible.sort(key=lambda r:r["doc_id"])
    if len(eligible) != 1781 or len(excluded) != 267:
        raise ValueError("Time-screened cohort differs from the inspected fixed data")
    write_json(DATA/"documents.json",eligible)
    write_json(DATA/"catalog.json",[r["doc_id"] for r in eligible])
    write_json(DATA/"excluded.json",excluded)
    write_json(DATA/"audit.json", {"original_candidates":len(rows),"eligible":len(eligible),"excluded":len(excluded),
        "cutoff":cutoff_text,"source_metadata_sha256":sha256(Path("data/stage10-catalog/metadata.json")),
        "availability_assumption":"Snapshot latest-version date and first submission are before cutoff; no exact archived historical text proof",
        "denominator":"All future explicit likes remain, including excluded267 and all other out-of-catalog papers",
        "history":"Only original train-period feedback; all known positive/negative seen items masked equally",
        "dev":"Previously used public/logged holdout; descriptive pilot only"})


class ContentComparison:
    def __init__(self, training: pd.DataFrame, documents: list[dict], params: dict | None = None):
        sklearn_runtime()
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.preprocessing import MultiLabelBinarizer, normalize
        self.catalog = sorted(r["doc_id"] for r in documents)
        if not self.catalog or len(self.catalog) != len(set(self.catalog)):
            raise ValueError("Expected a unique nonempty document catalog")
        rows = {r["doc_id"]:r for r in documents}
        started = time.perf_counter()
        memory = psutil.Process()
        rss_before = memory.memory_info().rss
        self.sar = PaperRecommender(training,self.catalog)
        sar_seconds = time.perf_counter()-started
        rss_sar = memory.memory_info().rss
        self.popularity = np.array([self.sar.popularity[d] for d in self.catalog],dtype=np.float64)
        self.position = {d:i for i,d in enumerate(self.catalog)}
        positive = training[(training.rating==1)&training.arxiv_id.isin(self.catalog)]
        histories = positive.groupby("user_id").arxiv_id.agg(lambda r:sorted(set(r))).sort_index()
        self.users = list(histories.index)
        self.user2row = {u:i for i,u in enumerate(self.users)}
        if set(self.users) != set(self.sar.model.user2index):
            raise ValueError("Content/SAR do not share training-positive user history")
        args = dict(PARAMS if params is None else params)
        args["ngram_range"] = tuple(args["ngram_range"])
        self.vectorizer = TfidfVectorizer(**args)
        started = time.perf_counter()
        self.documents = self.vectorizer.fit_transform([rows[d]["title"]+"\n"+rows[d]["abstract"] for d in self.catalog])
        text_seconds = time.perf_counter()-started
        started = time.perf_counter()
        self.history_matrix = MultiLabelBinarizer(classes=self.catalog,sparse_output=True).fit_transform(histories.tolist())
        # Normalize the sum of liked document vectors: identical to normalized mean, no holdout content.
        self.profiles = normalize(self.history_matrix@self.documents,norm="l2",copy=False)
        profile_seconds = time.perf_counter()-started
        self.zero_profile_users = {self.users[i] for i,n in enumerate(self.profiles.getnnz(axis=1)) if n==0}
        self.fit = {"sar_seconds":sar_seconds,"tfidf_seconds":text_seconds,"profiles_seconds":profile_seconds,
            "rss_before_mib":rss_before/2**20,"rss_after_sar_mib":rss_sar/2**20,"rss_after_all_mib":memory.memory_info().rss/2**20,
            "rss_note":"process snapshots, not peak RSS or standalone service memory",
            "catalog":len(self.catalog),"warm_users":len(self.users),"vocabulary":len(self.vectorizer.vocabulary_),
            "document_nnz":self.documents.nnz,"profile_nnz":self.profiles.nnz,"zero_profile_users":len(self.zero_profile_users),
            "sparse_storage_mib":sum(x.data.nbytes+x.indices.nbytes+x.indptr.nbytes for x in (self.documents,self.profiles,self.history_matrix))/2**20}

    def content_scores(self, user: str) -> np.ndarray:
        from sklearn.metrics.pairwise import linear_kernel
        if user not in self.user2row or user in self.zero_profile_users:
            return self.popularity.copy()
        return linear_kernel(self.profiles[self.user2row[user]],self.documents).ravel()

    def sar_scores(self,user: str) -> np.ndarray:
        values = self.sar.scores(user,"sar")
        return np.array([values[d] for d in self.catalog],dtype=np.float64)

    def eligible_indices(self,user: str) -> np.ndarray:
        seen = self.sar.seen.get(user,set())
        return np.array([i for i,d in enumerate(self.catalog) if d not in seen],dtype=np.int64)

    def recommend(self,user: str,method: str,k: int=10,alpha: float=0.5) -> list[dict]:
        if method not in ("popular","sar","content","hybrid") or type(k) is not int or not 1<=k<=100:
            raise ValueError("Unknown recommendation method or invalid K")
        if not isinstance(user,str) or not user or not 0<=alpha<=1:
            raise ValueError("Expected user and 0<=SAR weight<=1")
        candidates = self.eligible_indices(user)
        if method=="popular" or user not in self.user2row:
            scores = self.popularity[candidates]
        elif method=="sar" or (method=="hybrid" and alpha==1):
            scores = self.sar_scores(user)[candidates]
        elif method=="content" or (method=="hybrid" and alpha==0):
            scores = self.content_scores(user)[candidates]
        else:
            cf, content = self.sar_scores(user)[candidates],self.content_scores(user)[candidates]
            cf_order, text_order = np.argsort(-cf,kind="stable"),np.argsort(-content,kind="stable")
            cf_rank, text_rank = np.empty(len(candidates)),np.empty(len(candidates))
            cf_rank[cf_order],text_rank[text_order] = np.arange(1,len(candidates)+1),np.arange(1,len(candidates)+1)
            scores = alpha/(60+cf_rank)+(1-alpha)/(60+text_rank)
        if not np.isfinite(scores).all():
            raise ValueError("Nonfinite recommendation scores")
        order = np.argsort(-scores,kind="stable")[:k]
        return [{"doc_id":self.catalog[int(candidates[i])],"score":float(scores[i])} for i in order]


def load() -> ContentComparison:
    training = pd.read_csv(ORIGINAL/"train.csv",dtype={"user_id":str,"arxiv_id":str})
    return ContentComparison(training,read(DATA/"documents.json"))
