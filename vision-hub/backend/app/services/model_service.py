"""Model library: registry specs combined with weight status and measured speed."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.schemas import ModelConfigOut, ModelDetailOut, ModelOut, WeightOut
from app.services.analysis_service import measured_seconds_per_frame
from app.vision import data_types as dt
from app.vision import weights
from app.vision.base_model import ModelSpec
from app.vision.model_registry import registry


def _spec(model_id: str) -> ModelSpec:
    try:
        return registry.get_spec(model_id)
    except KeyError:
        raise NotFoundError(f"Model '{model_id}' is not registered.") from None


def _to_out(spec: ModelSpec, measured: dict[str, float], cls=ModelOut):
    status, detail = registry.status_of(spec)
    public = spec.public_dict()
    extra = {}
    if cls is ModelDetailOut:
        extra = {"config_schema": public["config_schema"], "default_config": public["default_config"]}
    return cls(
        model_id=spec.model_id, name=spec.name, category=spec.category, version=spec.version,
        description=spec.description, license=spec.license, kind=spec.kind, requires=spec.requires,
        produces=spec.produces, input_types=spec.input_types,
        output_descriptions={t: dt.DESCRIPTIONS.get(t, t) for t in spec.produces},
        weights=[WeightOut(name=w.name, source=w.source, kind=w.kind, size_mb=w.size_mb, license=w.license,
                           present=weights.is_present(w),
                           sha256=weights.sha256_of(w) if weights.is_present(w) else None)
                 for w in spec.weights],
        status=status, status_detail=detail, neural=spec.neural, cost_hint=spec.cost_hint,
        labels=spec.labels, method=spec.method, limitations=spec.limitations,
        seconds_per_frame=measured.get(spec.model_id, spec.default_seconds_per_frame),
        seconds_per_frame_measured=spec.model_id in measured,
        providers={t: [p.model_id for p in registry.providers_of(t)] for t in spec.requires},
        **extra,
    )


def list_models(db: Session, category: str | None = None) -> list[ModelOut]:
    measured = measured_seconds_per_frame(db)
    return [_to_out(s, measured) for s in registry.specs() if not category or s.category == category]


def get_model(db: Session, model_id: str) -> ModelDetailOut:
    return _to_out(_spec(model_id), measured_seconds_per_frame(db), ModelDetailOut)


def get_configuration(model_id: str) -> ModelConfigOut:
    public = _spec(model_id).public_dict()
    return ModelConfigOut(model_id=model_id, config_schema=public["config_schema"],
                          default_config=public["default_config"])
