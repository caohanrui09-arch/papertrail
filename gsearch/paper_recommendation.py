"""Thin adapter around the original MIT SAR implementation, not a new CF engine."""
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "third_party/recommenders_sar_upstream"


def upstream_sar() -> type:
    audit = json.loads((ROOT / "reports/stage9/upstream-audit.json").read_text(encoding="utf-8"))
    for name, expected in audit["git_blobs"].items():
        data = (VENDOR / name).read_bytes()
        digest = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if digest != expected:
            raise ValueError(f"Upstream SAR source changed: {name}")
    if str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))
    from recommenders.models.sar import SAR
    if not Path(sys.modules[SAR.__module__].__file__).resolve().is_relative_to(VENDOR):
        raise ValueError("Unexpected recommender package shadowing pinned source")
    return SAR


class PaperRecommender:
    def __init__(self, training: pd.DataFrame, catalog: list[str]):
        required = {"user_id", "arxiv_id", "rating"}
        if not required.issubset(training.columns) or not catalog or len(catalog) != len(set(catalog)):
            raise ValueError("Expected real user/item/rating data and unique catalog")
        if training.duplicated(["user_id", "arxiv_id"]).any():
            raise ValueError("Resolve duplicate user-paper ratings before fitting")
        self.catalog = sorted(catalog)
        self.seen = training.groupby("user_id")["arxiv_id"].agg(set).to_dict()
        self.likes = training[training.rating == 1].groupby("user_id")["arxiv_id"].agg(set).to_dict()
        positive = training[(training.rating == 1) & training.arxiv_id.isin(catalog)].copy()
        if set(positive.arxiv_id) != set(catalog):
            raise ValueError("Every catalog item needs a training-period positive interaction")
        self.popularity = positive.arxiv_id.value_counts().to_dict()
        self.model = upstream_sar()(col_user="user_id", col_item="arxiv_id", col_rating="rating",
                     similarity_type="jaccard", threshold=1, timedecay_formula=False, normalize=False)
        positive["rating"] = positive["rating"].astype(float)
        self.model.fit(positive[["user_id", "arxiv_id", "rating"]])

    def scores(self, user_id: str, method: str = "sar") -> dict[str, float]:
        if not isinstance(user_id, str) or not user_id or method not in ("sar", "popular"):
            raise ValueError("Expected user ID and sar/popular method")
        if method == "popular" or user_id not in self.model.user2index:
            return {d: float(self.popularity[d]) for d in self.catalog}
        # Call upstream scoring; mask all historical ratings in our boundary adapter.
        values = self.model.score(pd.DataFrame({"user_id": [user_id]}), remove_seen=False)[0]
        return {d: float(values[self.model.item2index[d]]) for d in self.catalog}

    def recommend(self, user_id: str, k: int = 10, method: str = "sar",
                  allowed: set[str] | None = None) -> list[dict]:
        if type(k) is not int or not 1 <= k <= 100:
            raise ValueError("Expected 1<=k<=100")
        scores = self.scores(user_id, method)
        seen = self.seen.get(user_id, set())
        candidates = [d for d in self.catalog if d not in seen and (allowed is None or d in allowed)]
        ranked = sorted(candidates, key=lambda d: (-scores[d], d))[:k]
        return [{"doc_id": d, "score": scores[d], "source": method,
                 "cold_user_fallback": method == "sar" and user_id not in self.model.user2index,
                 "url": "https://arxiv.org/abs/" + d} for d in ranked]

    def explanation(self, user_id: str, item: str, k: int = 3) -> dict:
        if item not in self.model.item2index:
            raise ValueError("Paper outside trained recommendation catalog")
        if user_id not in self.model.user2index:
            return {"kind": "training_popularity_fallback", "history_contributions": []}
        target = self.model.item2index[item]
        rows = []
        for seed in sorted(self.likes.get(user_id, set()) & set(self.catalog)):
            similarity = float(self.model.item_similarity[self.model.item2index[seed], target])
            if similarity > 0:
                rows.append({"arxiv_id": seed, "jaccard_contribution": similarity})
        rows.sort(key=lambda r: (-r["jaccard_contribution"], r["arxiv_id"]))
        return {"kind": "collaborative_co_liking_not_semantic_evidence", "history_contributions": rows[:k]}


def load_recommender(folder: Path = Path("data/stage9-recommendation")) -> PaperRecommender:
    training = pd.read_csv(folder / "train.csv", dtype={"user_id": str, "arxiv_id": str})
    return PaperRecommender(training, json.loads((folder / "catalog.json").read_text(encoding="utf-8")))
