from pathlib import Path
import joblib
import numpy as np
from scipy import sparse
from sklearn.metrics.pairwise import linear_kernel

class TypeRetriever:
    """Load and query a TF-IDF type index for plausible type predictions."""

    def __init__(self, index_dir: str):
        self.index_dir = Path(index_dir)
        self._load_index()

    def _load_index(self):
        """Load TF-IDF vectorizer and matrices from disk."""
        self.vectorizer = joblib.load(self.index_dir / "vectorizer.pkl")
        self.X = sparse.load_npz(self.index_dir / "tfidf_matrix.npz")
        self.type_labels = np.load(self.index_dir / "type_labels.npy", allow_pickle=True)
        self.slot_ids = np.load(self.index_dir / "slot_ids.npy", allow_pickle=True)

    def query(self, text: str, topn: int = 5):
        """
        Retrieve plausible type predictions for a given context text.

        Returns:
            List[(type_label, similarity_score, slot_id)]
        """
        q = self.vectorizer.transform([text])
        sims = linear_kernel(q, self.X).ravel()
        idxs = np.argsort(-sims, kind="mergesort")

        seen = set()
        results = []
        for i in idxs:
            typ = self.type_labels[i]
            if typ not in seen:
                seen.add(typ)
                results.append((typ, float(sims[i]), self.slot_ids[i]))
                if len(results) >= topn:
                    break
        return results

    def batch_query(self, texts: list[str], topn: int = 5):
        """Vectorized batch retrieval for multiple queries."""
        qmat = self.vectorizer.transform(texts)
        sims = linear_kernel(qmat, self.X)
        results = []
        for i, row in enumerate(sims):
            idxs = np.argsort(-row, kind="mergesort")
            seen, cur = set(), []
            for j in idxs:
                t = self.type_labels[j]
                if t not in seen:
                    seen.add(t)
                    cur.append((t, float(row[j]), self.slot_ids[j]))
                    if len(cur) >= topn:
                        break
            results.append(cur)
        return results
