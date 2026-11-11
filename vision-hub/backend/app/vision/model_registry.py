"""Model registry: discovers plugins and keeps the ``vision_models`` table in sync.

A plugin is a sub-package of ``app.vision.plugins`` that exposes a ``PLUGIN``
attribute (a :class:`BaseVisionModel` subclass). Adding a model therefore means
adding one package; nothing else in the application changes.

Plugin modules must import heavy libraries (torch, ultralytics, transformers)
lazily inside ``load()`` so the API process stays light.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.vision import weights
from app.vision.base_model import BaseVisionModel, ModelSpec

logger = logging.getLogger(__name__)

PLUGIN_PACKAGE = "app.vision.plugins"


class ModelRegistry:
    def __init__(self) -> None:
        self._classes: dict[str, type[BaseVisionModel]] = {}
        self._lock = threading.Lock()
        self._discovered = False

    # ------------------------------------------------------------ discovery
    def register(self, cls: type[BaseVisionModel]) -> type[BaseVisionModel]:
        spec = getattr(cls, "spec", None)
        if not isinstance(spec, ModelSpec):
            raise TypeError(f"{cls.__name__} has no ModelSpec")
        with self._lock:
            existing = self._classes.get(spec.model_id)
            if existing is not None and existing is not cls:
                raise ValueError(f"Duplicate model_id '{spec.model_id}'")
            self._classes[spec.model_id] = cls
        return cls

    def unregister(self, model_id: str) -> None:
        with self._lock:
            self._classes.pop(model_id, None)

    def discover(self) -> None:
        if self._discovered:
            return
        package = importlib.import_module(PLUGIN_PACKAGE)
        for info in pkgutil.iter_modules(package.__path__):
            if not info.ispkg:
                continue
            name = f"{PLUGIN_PACKAGE}.{info.name}"
            try:
                module = importlib.import_module(name)
                plugin = getattr(module, "PLUGIN", None)
                if plugin is None:
                    logger.warning("Plugin package %s has no PLUGIN attribute; skipped", name)
                    continue
                self.register(plugin)
            except Exception:
                logger.exception("Failed to import model plugin %s", name)
        self._discovered = True
        logger.info("Registered models: %s", ", ".join(sorted(self._classes)))

    # --------------------------------------------------------------- access
    def ids(self) -> list[str]:
        self.discover()
        return sorted(self._classes)

    def get_class(self, model_id: str) -> type[BaseVisionModel]:
        self.discover()
        try:
            return self._classes[model_id]
        except KeyError:
            raise KeyError(model_id) from None

    def get_spec(self, model_id: str) -> ModelSpec:
        return self.get_class(model_id).spec

    def specs(self) -> list[ModelSpec]:
        self.discover()
        return [self._classes[k].spec for k in sorted(self._classes)]

    def providers_of(self, data_type: str) -> list[ModelSpec]:
        return [s for s in self.specs() if data_type in s.produces]

    # --------------------------------------------------------------- status
    @staticmethod
    def status_of(spec: ModelSpec) -> tuple[str, str | None]:
        from app.db import ModelStatus

        missing = [w for w in spec.weights if not weights.is_present(w)]
        if not missing:
            return ModelStatus.AVAILABLE.value, None
        names = ", ".join(w.name for w in missing)
        size = sum(w.size_mb or 0 for w in missing)
        size_txt = f" (~{size:.0f} MB)" if size else ""
        if settings.allow_model_download:
            return ModelStatus.NOT_DOWNLOADED.value, f"{names}{size_txt} will be downloaded on first use."
        return ModelStatus.WEIGHTS_MISSING.value, f"Missing weights: {names}. Downloads are disabled."

    def sync_to_db(self, db: Session) -> None:
        """Upsert every registered model; mark rows of removed plugins as disabled."""
        from app.db import ModelStatus, VisionModel

        rows = {r.model_id: r for r in db.scalars(select(VisionModel)).all()}
        for spec in self.specs():
            status, detail = self.status_of(spec)
            public = spec.public_dict()
            row = rows.pop(spec.model_id, None) or VisionModel(model_id=spec.model_id)
            row.name = spec.name
            row.category = spec.category
            row.version = spec.version
            row.description = spec.description
            row.license = spec.license
            row.kind = spec.kind
            row.weights_info = public["weights"]
            row.config_schema = public["config_schema"]
            row.default_config = public["default_config"]
            row.requires = spec.requires
            row.produces = spec.produces
            row.status = status
            row.status_detail = detail
            row.is_active = True
            db.add(row)
        for row in rows.values():
            row.is_active = False
            row.status = ModelStatus.DISABLED.value
            row.status_detail = "Plugin is no longer installed."
        db.commit()


registry = ModelRegistry()
