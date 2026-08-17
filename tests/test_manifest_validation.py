"""Self-service manifest validation: compliant passes, violations rejected."""
from pathlib import Path

import yaml

import obs_common as oc
import validate_manifests as vm

POLICY = oc.load_policy()
GOOD = oc.REPO_ROOT / "platform" / "requests" / "payments-checkout-latency.yaml"


def _mutate(tmp_path: Path, **overrides) -> Path:
    doc = yaml.safe_load(GOOD.read_text())
    doc.update(overrides)
    for k, v in list(overrides.items()):
        if v is None:
            doc.pop(k, None)
    p = tmp_path / "req.yaml"
    p.write_text(yaml.safe_dump(doc))
    return p


def test_reference_manifest_is_compliant():
    assert vm.validate_manifest(GOOD, POLICY) == []


def test_missing_slo_rejected(tmp_path):
    errs = vm.validate_manifest(_mutate(tmp_path, slo_id="slo-does-not-exist"), POLICY)
    assert any("not in platform SLO catalog" in e for e in errs)


def test_unknown_team_rejected(tmp_path):
    errs = vm.validate_manifest(_mutate(tmp_path, team="rogue-team"), POLICY)
    assert any("not a registered team" in e for e in errs)


def test_unknown_workflow_rejected(tmp_path):
    errs = vm.validate_manifest(_mutate(tmp_path, workflow="auto-nonexistent"), POLICY)
    assert any("workflow" in e for e in errs)


def test_high_cardinality_group_rejected(tmp_path):
    errs = vm.validate_manifest(
        _mutate(tmp_path, group_by=["service", "host", "container_id", "path"]), POLICY)
    assert any("forbidden high-cardinality" in e for e in errs)
    assert any("exceeds max" in e for e in errs)


def test_unscoped_query_rejected(tmp_path):
    errs = vm.validate_manifest(
        _mutate(tmp_path, query="avg(last_10m):avg:trace.http.request.duration{*} > 2.5"), POLICY)
    assert any("scoped to the declared env" in e for e in errs)


def test_fixed_threshold_without_justification_rejected(tmp_path):
    errs = vm.validate_manifest(_mutate(tmp_path, justification=None), POLICY)
    assert any("requires a `justification`" in e for e in errs)


def test_missing_runbook_field_rejected(tmp_path):
    errs = vm.validate_manifest(_mutate(tmp_path, runbook=None), POLICY)
    assert any("missing required field: runbook" in e for e in errs)
