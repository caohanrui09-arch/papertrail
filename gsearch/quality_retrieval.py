"""Native BM25 / frozen TFIDF query / explicit five-paper contextual vector."""
import numpy as np
from sklearn.metrics.pairwise import linear_kernel
from sklearn.preprocessing import normalize
from .unified_search import AsOfBM25

METHODS = ('bm25', 'query_tfidf', 'personalized_query_tfidf')


class QualityRetrieval:
    def __init__(self, model: object, profiles: dict):
        self.model = model
        self.searcher = AsOfBM25(model)
        self.contexts = {}
        for key, profile in profiles.items():
            positions = [model.position[d] for d in profile['history_doc_ids']]
            # Same five title+abstract documents shown to the human annotator.
            summed = model.documents[positions].sum(axis=0)
            self.contexts[key] = normalize(np.asarray(summed), norm='l2')

    def search(self, query: dict, profile: dict, method: str) -> dict:
        if method not in METHODS:
            raise ValueError('Unknown frozen method')
        user, at = profile['user_id'], query['at']
        if method == 'bm25':
            return self.searcher.search(user, at, query['request'], 10)
        vector = self.model.vectorizer.transform([query['request']])
        if vector.nnz == 0:
            return {'papers': [], 'method': method, 'no_query_signal': True}
        if method == 'personalized_query_tfidf':
            context = self.contexts[query['profile_id']]
            if np.any(context):
                vector = normalize(.7 * vector.toarray() + .3 * context, norm='l2')
        scores = linear_kernel(vector, self.model.documents).ravel()
        eligible = self.model.eligible(user, at)
        positive = eligible[scores[eligible] > 0]
        ranked = positive[np.argsort(-scores[positive], kind='stable')[:10]]
        papers = []
        for index in ranked:
            doc = self.model.catalog[int(index)]
            row = self.model.by_id[doc]
            papers.append({'doc_id': doc, 'score': float(scores[index]), 'version': row['version'],
                'title': row['title'], 'source_url': row['source_url']})
        return {'papers': papers, 'method': method, 'vocabulary_scope': 'frozen initial9000 vocabulary/IDF; no future refit'}
