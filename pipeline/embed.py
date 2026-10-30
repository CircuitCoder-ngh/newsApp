"""Sentence embeddings for headlines, with an on-disk cache.

The cache is purely an optimisation (it lives in actions/cache on CI); a cold
run just re-embeds the EMBED_WINDOW of articles.
"""

import hashlib
from pathlib import Path

import numpy as np

from . import config


def _key(text: str) -> str:
    return hashlib.sha1(f"{config.EMBED_MODEL}\n{text}".encode()).hexdigest()[:20]


def normalize_rows(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.where(norms == 0, 1, norms)


class Embedder:
    def __init__(self, cache_dir: Path):
        self.cache_path = cache_dir / "embeddings.npz"
        self.model_dir = cache_dir / "fastembed"
        self._model = None

    def _load_model(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=config.EMBED_MODEL, cache_dir=str(self.model_dir))
        return self._model

    def _load_cache(self) -> dict[str, np.ndarray]:
        if not self.cache_path.exists():
            return {}
        with np.load(self.cache_path) as data:
            return dict(zip(data["keys"].tolist(), data["vectors"]))

    def _save_cache(self, cache: dict[str, np.ndarray]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        keys = list(cache)
        vectors = np.stack([cache[k] for k in keys]) if keys else np.zeros((0, 0), np.float32)
        tmp = self.cache_path.with_name("embeddings.tmp.npz")
        np.savez(tmp, keys=np.array(keys), vectors=vectors)
        tmp.replace(self.cache_path)

    def embed(self, texts: list[str]) -> np.ndarray:
        """Return one L2-normalized row per text. The cache keeps only these texts."""
        cache = self._load_cache()
        keys = [_key(t) for t in texts]
        todo = {k: t for k, t in zip(keys, texts) if k not in cache}
        if todo:
            vectors = self._load_model().embed(list(todo.values()), batch_size=64)
            for k, v in zip(todo, vectors):
                cache[k] = np.asarray(v, dtype=np.float32)
        kept = {k: cache[k] for k in keys}
        if todo or len(kept) != len(cache):
            self._save_cache(kept)
        if not texts:
            return np.zeros((0, 384), np.float32)
        return normalize_rows(np.stack([kept[k] for k in keys]))
