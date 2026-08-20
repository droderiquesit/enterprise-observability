"""The single-YAML developer experience.

Two properties are being protected here:
  1. A compliant manifest passes with no ceremony.
  2. Every way a team could accidentally create a bad monitor is rejected with
     an explanation, before Terraform runs.
"""
from pathlib import Path

import yaml

import obs_common as oc
import validate_monitors as vm

POLICY = oc.load_policy()
SERVICES = oc.load_services()
# The reference manifest is a FIXTURE, not a deployed file: platform/monitors/
# is applied, so an example living there would be an artificial monitor in
# production. See platform/monitors/README.md.
GOOD = Path(__file__).parent / "fixtures" / "self_service_example.yaml"


def _mutate(tmp_path: Path, name: str = "self-service-example", **overrides) -> Path:
    doc = yaml.safe_load(GOOD.read_text())
    m = doc["monitor"]
    for k, v in overrides.items():
        if v is None:
            m.pop(k, None)
        else:
            m[k] = v
    m["name"] = name
    p = tmp_path / f"{name}.yaml"
    p.write_text(yaml.safe_dump(doc))
    return p


def test_every_committed_manifest_is_compliant():
    for p in sorted((oc.PLATFORM_DIR / "monitors").glob("*.yaml")):
        assert vm.validate(p, POLICY, SERVICES) == [], p.name


def _errs(tmp_path, **kw):
    return vm.validate(_mutate(tmp_path, **kw), POLICY, SERVICES)


def test_unknown_slo_is_rejected(tmp_path):
    assert any("SLO catalog" in e for e in _errs(tmp_path, slo="slo-imaginary"))


def test_unregistered_team_is_rejected(tmp_path):
    assert any("not registered" in e for e in _errs(tmp_path, team="rogue-team"))


def test_unknown_workflow_is_rejected(tmp_path):
    assert any("workflow registry" in e for e in _errs(tmp_path, workflow="auto-nope"))


def test_unknown_runbook_is_rejected(tmp_path):
    assert any("runbook registry" in e for e in _errs(tmp_path, runbook="nope"))


def test_unregistered_service_is_rejected(tmp_path):
    """Without a registration the platform cannot resolve tier, so it refuses."""
    assert any("not registered in platform/services" in e
               for e in _errs(tmp_path, service="mystery-service"))


def test_team_that_does_not_own_the_service_is_rejected(tmp_path):
    assert any("does not own service" in e for e in _errs(tmp_path, team="data-engineering"))


def test_high_cardinality_grouping_is_rejected(tmp_path):
    errs = _errs(tmp_path, group_by=["service", "host", "container_id", "trace_id"])
    assert any("banned identity keys" in e for e in errs)
    assert any("maximum is" in e for e in errs)


def test_dev_environment_is_accepted_but_can_only_be_informational(tmp_path):
    """dev alerts now. A team may request a dev monitor and it will be created
    — at P4, on the team's dev Teams channel, with no ServiceNow record and no
    way to page. The environment ceiling does that, not the request."""
    assert _errs(tmp_path, env=["dev"]) == []
    envp = oc.load_policy()["environments"]["dev"]
    assert envp["priority_ceiling"] == "P4"
    assert envp["paging_allowed"] is False


def test_p1_on_a_low_tier_service_is_rejected(tmp_path):
    """A team cannot obtain a pager by editing a YAML file."""
    errs = _errs(tmp_path, service="reporting-portal", team="application-development",
                 priority="P1")
    assert any("requires a tier0/tier1 service" in e for e in errs)


def test_duplicate_of_a_platform_pack_needs_a_justification(tmp_path):
    assert any("ALREADY covers" in e for e in _errs(tmp_path, justification=None))


def test_custom_archetype_requires_a_full_definition(tmp_path):
    errs = _errs(tmp_path, archetype="custom", query=None, monitor_type=None,
                 detection=None, impact_class=None, domain=None)
    for field in ("query", "monitor_type", "detection", "impact_class", "domain"):
        assert any(f"`{field}`" in e for e in errs), field


def test_unscoped_custom_query_is_rejected(tmp_path):
    errs = _errs(tmp_path, archetype="custom",
                 query="avg(last_10m):avg:trace.http.request.duration{*} > 2.5",
                 monitor_type="query alert", detection="threshold",
                 impact_class="degradation", domain="api")
    assert any("scoped to env" in e for e in errs)
    assert any("org-wide wildcard" in e for e in errs)


def test_backwards_warning_threshold_is_rejected(tmp_path):
    errs = _errs(tmp_path, archetype="custom",
                 query="avg(last_10m):p99:trace.http.request.duration{env:prod,service:checkout-api} > 2.5",
                 monitor_type="query alert", detection="threshold",
                 impact_class="degradation", domain="api",
                 thresholds={"critical": 2.5, "warning": 3.0})
    assert any("warning must be BELOW critical" in e for e in errs)


def test_auto_threshold_without_a_catalog_source_is_rejected(tmp_path):
    errs = _errs(tmp_path, archetype="custom",
                 query="avg(last_10m):p99:x{env:prod,service:checkout-api} > 1",
                 monitor_type="query alert", detection="threshold",
                 impact_class="degradation", domain="api",
                 thresholds={"critical": "auto"})
    assert any("needs a catalog archetype" in e for e in errs)


def test_name_must_match_the_filename(tmp_path):
    doc = yaml.safe_load(GOOD.read_text())
    doc["monitor"]["name"] = "some-other-name"
    p = tmp_path / "self-service-example.yaml"
    p.write_text(yaml.safe_dump(doc))
    assert any("must match the filename" in e for e in vm.validate(p, POLICY, SERVICES))


def test_predictive_flag_must_match_the_resolved_detection(tmp_path):
    errs = _errs(tmp_path, archetype="api-availability",
                 predictive={"anomaly": True, "forecast": False})
    assert any("declares no anomaly variant" in e for e in errs)
