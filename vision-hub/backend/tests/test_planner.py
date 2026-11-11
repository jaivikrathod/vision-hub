"""Pipeline planner: auto-adding providers, ordering and validation."""

import pytest
from pydantic import BaseModel

from app.core.exceptions import PipelineError
from app.vision.base_model import BaseVisionModel, ModelSpec
from app.vision.model_registry import ModelRegistry
from app.vision.pipeline_planner import plan_pipeline


class _Cfg(BaseModel):
    threshold: float = 0.5


def _model(model_id, kind="frame", requires=(), produces=()):
    spec = ModelSpec(model_id=model_id, name=model_id.title(), category="t", version="1", description="",
                     license="MIT", kind=kind, requires=list(requires), produces=list(produces),
                     config_schema=_Cfg, neural=False)
    return type(model_id, (BaseVisionModel,), {"spec": spec})


@pytest.fixture
def reg():
    r = ModelRegistry()
    r._discovered = True  # isolated registry, no plugin discovery
    for cls in (
        _model("pose", produces=["dets", "kps"]),
        _model("track", requires=["dets"], produces=["tracks", "track_summaries"]),
        _model("act", kind="post", requires=["tracks", "kps"], produces=["activity_segments"]),
        _model("clipact", kind="clip", requires=["dets", "tracks"], produces=["activity_segments"]),
    ):
        r.register(cls)
    return r


def test_auto_adds_providers_in_dependency_order(reg):
    p = plan_pipeline(["act"], reg=reg)
    assert p.model_ids == ["pose", "track", "act"]
    assert [s.auto_added for s in p.steps] == [True, True, False]
    assert p.step("act").depends_on == ["track", "pose"]  # no duplicates


def test_selected_models_are_not_auto_added(reg):
    p = plan_pipeline(["track", "pose"], reg=reg)
    assert p.model_ids == ["pose", "track"]
    assert not any(s.auto_added for s in p.steps)


def test_two_models_producing_the_same_unrequired_output_is_fine(reg):
    p = plan_pipeline(["act", "clipact"], reg=reg)
    assert p.model_ids.index("clipact") < p.model_ids.index("act")  # clip before post


def test_missing_provider(reg):
    reg.register(_model("needy", requires=["depth"]))
    with pytest.raises(PipelineError, match="no installed model provides"):
        plan_pipeline(["needy"], reg=reg)


def test_frame_model_cannot_depend_on_post_output(reg):
    reg.register(_model("late", kind="frame", requires=["activity_segments"]))
    with pytest.raises(PipelineError, match="only exists"):
        plan_pipeline(["late", "act"], reg=reg)


def test_ambiguous_provider(reg):
    reg.register(_model("pose2", produces=["dets"]))
    with pytest.raises(PipelineError, match="several selected models"):
        plan_pipeline(["pose", "pose2", "track"], reg=reg)


def test_cycle(reg):
    reg.register(_model("a", kind="post", requires=["b_out"], produces=["a_out"]))
    reg.register(_model("b", kind="post", requires=["a_out"], produces=["b_out"]))
    with pytest.raises(PipelineError, match="Circular"):
        plan_pipeline(["a", "b"], reg=reg)


def test_config_validation(reg):
    p = plan_pipeline(["pose"], {"pose": {"threshold": 0.7}}, reg=reg)
    assert p.step("pose").config.threshold == 0.7
    with pytest.raises(PipelineError, match="Invalid configuration"):
        plan_pipeline(["pose"], {"pose": {"threshold": "high"}}, reg=reg)


def test_unknown_and_duplicate_models(reg):
    with pytest.raises(PipelineError, match="Unknown model"):
        plan_pipeline(["nope"], reg=reg)
    with pytest.raises(PipelineError, match="only once"):
        plan_pipeline(["pose", "pose"], reg=reg)
    with pytest.raises(PipelineError, match="at least one"):
        plan_pipeline([], reg=reg)


def test_real_plugins_are_registered():
    from app.vision.model_registry import registry

    ids = set(registry.ids())
    assert {"human_pose", "human_tracking", "activity_pose_temporal", "activity_xclip"} <= ids
    p = plan_pipeline(["activity_pose_temporal"])
    assert p.model_ids[-1] == "activity_pose_temporal"
    assert "human_tracking" in p.model_ids
    # Every real config schema has working defaults and exports JSON Schema for the UI.
    for spec in registry.specs():
        public = spec.public_dict()
        assert public["config_schema"]["type"] == "object"
        assert isinstance(public["default_config"], dict)


def test_pose_model_advises_higher_resolution_for_small_videos():
    from app.vision.plugins.human_pose import HumanPoseConfig, HumanPoseModel

    small = {"width": 768, "height": 576}
    assert "1280" in HumanPoseModel.advice(HumanPoseConfig(), small)[0]
    assert HumanPoseModel.advice(HumanPoseConfig(image_size=1280), small) == []
    assert HumanPoseModel.advice(HumanPoseConfig(), {"width": 1920, "height": 1080}) == []
