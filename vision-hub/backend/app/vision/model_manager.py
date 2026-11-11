"""Model manager: lazy loading, reuse and an LRU limit on loaded neural models.

Lives in the worker process. One instance per model id is kept; weights are
loaded once and reused across jobs. When more than ``MAX_LOADED_MODELS``
neural models would be loaded, the least recently used one is unloaded first
(rule-based models never count). Models used by the running job are pinned.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

from app.config import settings
from app.core.exceptions import AppError, ModelLoadError
from app.vision.base_model import BaseVisionModel
from app.vision.model_registry import ModelRegistry, registry

logger = logging.getLogger(__name__)


@dataclass
class ModelState:
    status: str = "unloaded"        # unloaded | loading | loaded | error
    error: str | None = None
    load_seconds: float | None = None
    last_used: float = 0.0


class ModelManager:
    def __init__(self, reg: ModelRegistry | None = None, max_loaded: int | None = None) -> None:
        self.registry = reg or registry
        self.max_loaded = max(1, max_loaded or settings.max_loaded_models)
        self._instances: OrderedDict[str, BaseVisionModel] = OrderedDict()
        self._states: dict[str, ModelState] = {}
        self._lock = threading.RLock()

    def state(self, model_id: str) -> ModelState:
        return self._states.setdefault(model_id, ModelState())

    def loaded_ids(self) -> list[str]:
        with self._lock:
            return [k for k, m in self._instances.items() if m.is_loaded]

    def get(self, model_id: str, device: str, pinned: set[str] | None = None) -> BaseVisionModel:
        """Return a loaded instance, loading it (and evicting others) if needed."""
        with self._lock:
            inst = self._instances.get(model_id)
            if inst is not None and inst.is_loaded and inst.device == device:
                self._instances.move_to_end(model_id)
                self.state(model_id).last_used = time.monotonic()
                return inst
            cls = self.registry.get_class(model_id)
            if inst is None:
                inst = cls()
                self._instances[model_id] = inst
            elif inst.is_loaded:  # loaded on a different device
                inst.unload()
            if cls.spec.neural:
                self._evict_for(model_id, pinned or set())
            st = self.state(model_id)
            st.status, st.error = "loading", None
            started = time.monotonic()
            try:
                inst.load(device)
            except AppError as exc:
                st.status, st.error = "error", exc.message
                raise
            except Exception as exc:
                st.status, st.error = "error", str(exc)
                logger.exception("Loading model %s failed", model_id)
                raise ModelLoadError(f"Failed to load model '{model_id}': {exc}") from exc
            st.status, st.load_seconds = "loaded", time.monotonic() - started
            st.last_used = time.monotonic()
            self._instances.move_to_end(model_id)
            logger.info("Loaded model %s on %s in %.1fs", model_id, device, st.load_seconds)
            return inst

    def _evict_for(self, model_id: str, pinned: set[str]) -> None:
        def neural_loaded() -> list[str]:
            return [k for k, m in self._instances.items()
                    if k != model_id and m.is_loaded and m.spec.neural]

        loaded = neural_loaded()
        while len(loaded) >= self.max_loaded:
            victim = next((k for k in loaded if k not in pinned), None)  # OrderedDict -> LRU first
            if victim is None:
                logger.warning("All %d loaded models are in use; loading %s above the limit",
                               len(loaded), model_id)
                return
            self.unload(victim)
            loaded = neural_loaded()

    def unload(self, model_id: str) -> None:
        with self._lock:
            inst = self._instances.get(model_id)
            if inst is not None and inst.is_loaded:
                try:
                    inst.unload()
                finally:
                    self.state(model_id).status = "unloaded"
                    logger.info("Unloaded model %s", model_id)
            try:
                import gc

                gc.collect()
            except Exception:  # pragma: no cover
                pass

    def unload_all(self) -> None:
        for model_id in list(self._instances):
            self.unload(model_id)
