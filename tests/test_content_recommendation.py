"""Content history, endpoint fusion, common masks and cold-user contracts."""
import importlib.util
from pathlib import Path
import unittest

if (importlib.util.find_spec("pandas") is None or importlib.util.find_spec("scipy") is None or
        not Path(".cache/stage11/deps/sklearn").exists()):
    raise unittest.SkipTest("Use stage6 runtime plus the isolated pinned stage11 dependencies")

import pandas as pd

from gsearch.content_recommendation import ContentComparison, parse_time, read, DATA
from gsearch.benchmark_content import model_signature


class ContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        train = pd.DataFrame([
            ("alice", "1", 1), ("alice", "5", -1),
            ("bob", "3", 1), ("bob", "4", 1),
            ("carol", "1", 1), ("carol", "2", 1),
            ("dave", "4", 1), ("dave", "5", 1),
            ("negative_only", "2", -1)], columns=["user_id", "arxiv_id", "rating"])
        text = {"1":"quantum photon optical", "2":"quantum photon optical experiment",
                "3":"biology cell protein", "4":"biology cell protein assay", "5":"unrelated volcano geology"}
        docs = [{"doc_id":d,"title":t,"abstract":t} for d,t in text.items()]
        cls.engine = ContentComparison(train, docs, params={"ngram_range":[1,2],"min_df":1,"norm":"l2"})

    def ids(self, user: str, mode: str, alpha: float=0.5) -> list[str]:
        return [x["doc_id"] for x in self.engine.recommend(user,mode,10,alpha)]

    def test_content_personalizes_and_masks_all_known_ratings(self) -> None:
        self.assertEqual(self.ids("alice","content")[0], "2")
        self.assertEqual(self.ids("bob","content")[0], "1")  # remaining disjoint texts tie by ID
        for method in ("popular","sar","content","hybrid"):
            self.assertFalse(set(self.ids("alice",method)) & {"1","5"})
        self.assertEqual(self.engine.history_matrix[self.engine.user2row["alice"]].nnz,1)

    def test_endpoints_are_exact_single_branches(self) -> None:
        for user in ("alice","bob","new"):
            self.assertEqual(self.engine.recommend(user,"hybrid",10,0),self.engine.recommend(user,"content",10))
            self.assertEqual(self.engine.recommend(user,"hybrid",10,1),self.engine.recommend(user,"sar",10))

    def test_cold_users_share_popularity_but_keep_negative_mask(self) -> None:
        for user in ("new","negative_only"):
            for method in ("sar","content","hybrid"):
                self.assertEqual(self.ids(user,method),self.ids(user,"popular"))
        self.assertNotIn("2",self.ids("negative_only","content"))

    def test_signature_and_profiles_do_not_change_on_inference(self) -> None:
        before=model_signature(self.engine)
        for method in ("popular","sar","content","hybrid"):
            self.ids("alice",method)
        self.assertEqual(before,model_signature(self.engine))

    def test_real_temporal_scope_is_strict_and_catalog_is_shared(self) -> None:
        if not (DATA/"audit.json").exists():
            self.skipTest("Prepared local research metadata absent")
        audit=read(DATA/"audit.json")
        docs=read(DATA/"documents.json")
        self.assertEqual(len(docs),1781)
        self.assertEqual(len(read(DATA/"excluded.json")),267)
        self.assertEqual([d["doc_id"] for d in docs],read(DATA/"catalog.json"))
        for d in docs:
            self.assertLess(parse_time(d["updated_at"]),parse_time(audit["cutoff"]))
            self.assertLess(parse_time(d["published_at"]),parse_time(audit["cutoff"]))


if __name__=="__main__":
    unittest.main()
