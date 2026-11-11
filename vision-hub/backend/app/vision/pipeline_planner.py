"""Pipeline planner: turns the user's model selection into an ordered pipeline.

* Resolves ``requires`` / ``produces`` into a dependency graph.
* Auto-adds providers for data no selected model produces (marked ``auto_added``).
* Rejects circular dependencies, ambiguous providers, and impossible orderings
  (a per-frame model cannot depend on data that only exists after the pass).
* Validates each model's configuration against its schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core.exceptions import PipelineError
from app.vision import data_types as dt
from app.vision.base_model import ModelSpec
from app.vision.model_registry import ModelRegistry, registry

_KIND_ORDER = {"frame": 0, "clip": 1, "post": 2}


@dataclass
class PipelineStep:
    spec: ModelSpec
    config: BaseModel
    auto_added: bool
    depends_on: list[str] = field(default_factory=list)

    @property
    def model_id(self) -> str:
        return self.spec.model_id


@dataclass
class Pipeline:
    steps: list[PipelineStep]

    @property
    def model_ids(self) -> list[str]:
        return [s.model_id for s in self.steps]

    def step(self, model_id: str) -> PipelineStep:
        return next(s for s in self.steps if s.model_id == model_id)

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "model_id": s.model_id, "name": s.spec.name, "kind": s.spec.kind,
                "auto_added": s.auto_added, "depends_on": s.depends_on,
                "configuration": s.config.model_dump(mode="json"),
            }
            for s in self.steps
        ]


def _validate_config(spec: ModelSpec, raw: dict | None) -> BaseModel:
    try:
        return spec.config_schema(**(raw or {}))
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'config'}: {e['msg']}" for e in exc.errors()
        )
        raise PipelineError(f"Invalid configuration for '{spec.name}': {problems}",
                            extra={"model_id": spec.model_id}) from exc


def plan_pipeline(
    selected: list[str],
    configs: dict[str, dict] | None = None,
    reg: ModelRegistry | None = None,
) -> Pipeline:
    reg = reg or registry
    configs = configs or {}
    if not selected:
        raise PipelineError("Select at least one model.")
    if len(set(selected)) != len(selected):
        raise PipelineError("Each model can be selected only once.")

    specs: dict[str, ModelSpec] = {}
    for model_id in selected:
        try:
            specs[model_id] = reg.get_spec(model_id)
        except KeyError:
            raise PipelineError(f"Unknown model '{model_id}'.", extra={"model_id": model_id}) from None
    auto: set[str] = set()

    # ---- auto-add providers until every requirement is satisfied
    changed = True
    while changed:
        changed = False
        produced = {t for s in specs.values() for t in s.produces}
        for spec in list(specs.values()):
            for need in spec.requires:
                if need in produced:
                    continue
                candidates = sorted(
                    (p for p in reg.providers_of(need) if p.model_id not in specs),
                    key=lambda p: (-p.priority, len(p.requires), _KIND_ORDER[p.kind], p.model_id),
                )
                if not candidates:
                    raise PipelineError(
                        f"'{spec.name}' needs {dt.DESCRIPTIONS.get(need, need)} ('{need}'), "
                        "but no installed model provides it.",
                        extra={"model_id": spec.model_id},
                    )
                provider = candidates[0]
                specs[provider.model_id] = provider
                auto.add(provider.model_id)
                produced |= set(provider.produces)
                changed = True

    # ---- dependency edges
    deps: dict[str, list[str]] = {m: [] for m in specs}
    for model_id, spec in specs.items():
        for need in spec.requires:
            providers = [p for p, ps in specs.items() if need in ps.produces and p != model_id]
            if len(providers) > 1:
                names = ", ".join(specs[p].name for p in providers)
                raise PipelineError(
                    f"'{spec.name}' needs '{need}', which several selected models provide ({names}). "
                    "Select only one of them."
                )
            if not providers:
                raise PipelineError(f"'{spec.name}' cannot produce its own input '{need}'.")
            provider = specs[providers[0]]
            if spec.kind in ("frame", "clip"):
                if provider.kind == "post" or need in dt.JOB_TYPES:
                    raise PipelineError(
                        f"'{spec.name}' runs on every frame but needs '{need}', which only exists "
                        "after the whole video has been processed."
                    )
            if providers[0] not in deps[model_id]:
                deps[model_id].append(providers[0])

    # ---- topological sort (Kahn), stable by kind then selection order
    order_hint = {m: i for i, m in enumerate(selected)}
    remaining = {m: set(d) for m, d in deps.items()}
    ordered: list[str] = []
    while remaining:
        ready = [m for m, d in remaining.items() if not d]
        if not ready:
            cycle = ", ".join(sorted(remaining))
            raise PipelineError(f"Circular dependency between models: {cycle}.")
        ready.sort(key=lambda m: (_KIND_ORDER[specs[m].kind], order_hint.get(m, -1), m))
        nxt = ready[0]
        ordered.append(nxt)
        del remaining[nxt]
        for d in remaining.values():
            d.discard(nxt)

    steps = [
        PipelineStep(
            spec=specs[m],
            config=_validate_config(specs[m], configs.get(m)),
            auto_added=m in auto,
            depends_on=deps[m],
        )
        for m in ordered
    ]
    return Pipeline(steps=steps)
