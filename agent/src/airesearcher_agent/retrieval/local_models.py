import gc
import logging
from threading import Lock
from typing import Any, cast

import numpy as np
import torch
from sentence_transformers import SentenceTransformer
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from airesearcher_agent.config import Settings

logger = logging.getLogger(__name__)


def _selected_device(configured: str) -> str:
    normalized = configured.strip().lower()
    if normalized == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if normalized == "cuda" and not torch.cuda.is_available():
        logger.warning("CUDA was requested but is unavailable; using CPU")
        return "cpu"
    if normalized not in {"cpu", "cuda"}:
        raise ValueError("AIRESEARCHER_MODEL_DEVICE must be auto, cpu, or cuda")
    return normalized


def _is_cuda_oom(error: BaseException) -> bool:
    return isinstance(error, torch.cuda.OutOfMemoryError) or (
        isinstance(error, RuntimeError) and "out of memory" in str(error).lower()
    )


def _clear_cuda() -> None:
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


class BgeM3EmbeddingProvider:
    def __init__(self, settings: Settings) -> None:
        self._model_name = settings.embedding_model
        self._cache_dir = str(settings.model_cache_dir)
        self._batch_size = settings.embedding_batch_size
        self._dimension = settings.vector_size
        self._device = _selected_device(settings.model_device)
        self._model: SentenceTransformer | None = None
        self._lock = Lock()

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def device(self) -> str:
        return self._device

    def _load(self) -> SentenceTransformer:
        if self._model is None:
            logger.info("Loading embedding model %s on %s", self._model_name, self._device)
            self._model = SentenceTransformer(
                self._model_name,
                device=self._device,
                cache_folder=self._cache_dir,
                trust_remote_code=False,
            )
            dimension = self._model.get_sentence_embedding_dimension()
            if dimension != self._dimension:
                raise RuntimeError(
                    f"embedding dimension {dimension} does not match configured {self._dimension}"
                )
        return self._model

    def _encode_once(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        raw = model.encode(
            texts,
            batch_size=self._batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        array = np.asarray(raw, dtype=np.float32)
        if array.ndim == 1:
            array = array.reshape(1, -1)
        if array.shape != (len(texts), self._dimension):
            raise RuntimeError(f"unexpected embedding shape {array.shape}")
        return cast(list[list[float]], array.tolist())

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with self._lock:
            try:
                return self._encode_once(texts)
            except BaseException as error:
                if self._device != "cuda" or not _is_cuda_oom(error):
                    raise
                logger.warning("Embedding model exhausted CUDA memory; retrying once on CPU")
                self._model = None
                self._device = "cpu"
                _clear_cuda()
                return self._encode_once(texts)


class BgeReranker:
    def __init__(self, settings: Settings) -> None:
        self._model_name = settings.reranker_model
        self._cache_dir = str(settings.model_cache_dir)
        self._batch_size = settings.reranker_batch_size
        self._device = _selected_device(settings.model_device)
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self._lock = Lock()

    @property
    def device(self) -> str:
        return self._device

    def _load(self) -> tuple[Any, Any]:
        if self._tokenizer is None or self._model is None:
            logger.info("Loading reranker model %s on %s", self._model_name, self._device)
            self._tokenizer = AutoTokenizer.from_pretrained(
                self._model_name,
                cache_dir=self._cache_dir,
                trust_remote_code=False,
            )
            model = AutoModelForSequenceClassification.from_pretrained(
                self._model_name,
                cache_dir=self._cache_dir,
                trust_remote_code=False,
            )
            model.eval()
            model.to(self._device)
            if self._device == "cuda":
                model.half()
            self._model = model
        return self._tokenizer, self._model

    def _score_once(self, query: str, passages: list[str]) -> list[float]:
        tokenizer, model = self._load()
        scores: list[float] = []
        for start in range(0, len(passages), self._batch_size):
            batch = passages[start : start + self._batch_size]
            pairs = [[query, passage] for passage in batch]
            inputs = tokenizer(
                pairs,
                padding=True,
                truncation=True,
                return_tensors="pt",
                max_length=512,
            )
            device_inputs = {name: value.to(self._device) for name, value in inputs.items()}
            with torch.no_grad():
                logits = model(**device_inputs, return_dict=True).logits.view(-1).float().cpu()
            scores.extend(float(value) for value in logits.tolist())
        return scores

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        with self._lock:
            try:
                return self._score_once(query, passages)
            except BaseException as error:
                if self._device != "cuda" or not _is_cuda_oom(error):
                    raise
                logger.warning("Reranker exhausted CUDA memory; retrying once on CPU")
                self._tokenizer = None
                self._model = None
                self._device = "cpu"
                _clear_cuda()
                return self._score_once(query, passages)
