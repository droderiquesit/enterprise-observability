"""Agent profiles, fleet compliance, and the deployment-metadata contract.

Three things are protected here, and they are the three that were previously
claimed in documentation and implemented nowhere:

  1. the profiles are INTERNALLY CONSISTENT — every archetype a profile claims
     to enable exists, and every tag it matches on is in the vocabulary;
  2. the compliance calculation actually detects each of the eight §39
     conditions, proved against a fixture where each one is true exactly once;
  3. the deployment marker cannot be emitted without a version, which is the
     defect it exists to fix.

The fixture is small on purpose. A big one hides which host is failing which
check, and this file's whole value is that it can say.
"""
import json
from pathlib import Path

import emit_deployment_event as ede
import fleet_compliance as fc
import obs_common as oc
import pytest

POLICY = oc.load_policy()
AGENT_PROFILES = oc.load_agent_profiles()
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def report():
    inventory = json.loads((FIXTURES / "fleet_inventory.json").read_text())
    hosts = json.loads((FIXTURES / "fleet_hosts.json").read_text())
    return fc.evaluate(inventory, hosts, POLICY, AGENT_PROFILES,
                       float(inventory["fixture_now_ts"]))


def findings_for(report, host):
    return next(h["findings"] for h in report["hosts"] if h["host"] == host)


# --- the profile catalog ----------------------------------------------------

def test_the_five_standard_profiles_exist():
    """§37 names five. A sixth would be profile sprawl; a fifth missing would
    leave part of the estate with no defined agent configuration at all."""
    assert set(AGENT_PROFILES["agent_profiles"]) == {
        "base-infrastructure", "windows-server", "linux-server",
        "application", "sqlserver"}


def test_exactly_one_base_and_one_os_profile_per_family():
    kinds = [p["kind"] for p in AGENT_PROFILES["agent_profiles"].values()]
    assert kinds.count("base") == 1
    os_matches = [tuple(p["match"]["os_family"])
                  for p in AGENT_PROFILES["agent_profiles"].values()
                  if p["kind"] == "os"]
    assert sorted(os_matches) == [("linux",), ("windows",)]


def test_every_enabled_archetype_actually_exists():
    """The claim that makes the profiles worth reading: if a profile says it
    enables an archetype, that archetype must be a real one. A typo here is a
    monitor everybody believes is covered and nothing collects for."""
    for pid, prof in AGENT_PROFILES["agent_profiles"].items():
        for aid in prof.get("enables_archetypes", []):
            assert aid in POLICY["archetypes"], f"{pid} enables unknown archetype {aid}"


def test_profile_match_values_are_in_the_tag_vocabulary():
    vocab = POLICY["global"]["tag_vocabulary"]
    for pid, prof in AGENT_PROFILES["agent_profiles"].items():
        for key, allowed in (prof.get("match") or {}).items():
            if key not in vocab:
                continue          # os_family and db_engine are fleet facts
            for value in allowed:
                assert value in vocab[key], f"{pid} matches {key}:{value}, not in vocabulary"


def test_required_host_tags_are_the_tier_1_tags():
    """The base profile's required tags ARE docs/tagging-standard.md Tier 1.
    If they drift apart, agents are configured to send tags the monitors do
    not select on, which is indistinguishable from sending nothing."""
    required = AGENT_PROFILES["agent_profiles"]["base-infrastructure"] \
        ["agent_config"]["required_host_tags"]
    assert set(required) == {"env", "service", "team", "tier",
                             "service_archetype", "alert_band"}


def test_no_kubernetes_profile_is_instantiated():
    """The estate has no Kubernetes. A cluster-agent profile would create a
    fleet in the documentation that does not exist in the datacentre — and a
    compliance denominator of zero, which reports as 100%."""
    assert "kubernetes-node" not in AGENT_PROFILES["agent_profiles"]
    conditional = AGENT_PROFILES["conditional_profiles"]["kubernetes-node"]
    assert conditional["enabled"] is False
    assert conditional["reason"].strip()
    assert conditional["enable_when"].strip()


def test_every_compliance_check_is_claimed_by_some_profile():
    declared = set(AGENT_PROFILES["compliance"]["checks"])
    used = {c for p in AGENT_PROFILES["agent_profiles"].values()
            for c in p.get("compliance_checks", [])}
    assert used == declared, f"declared but unused: {declared - used}; unknown: {used - declared}"


def test_the_application_profile_carries_the_deployment_metadata_contract():
    """§8: DD_VERSION is grouped on by two archetypes and emitted by nothing.
    The profile is where that requirement becomes machine-readable."""
    env_vars = {e["name"]: e for e in
                AGENT_PROFILES["agent_profiles"]["application"]["required_runtime_env"]}
    for name in ("DD_ENV", "DD_SERVICE", "DD_VERSION",
                 "DD_GIT_COMMIT_SHA", "DD_GIT_REPOSITORY_URL"):
        assert env_vars[name]["required"] is True


# --- profile assignment -----------------------------------------------------

def test_assignment_composes_base_os_and_role():
    profiles = fc.assign_profiles(
        {"os_family": "windows", "service_archetype": "api",
         "db_engine": None, "env": "prod"}, AGENT_PROFILES)
    assert profiles == ["application", "base-infrastructure", "windows-server"]


def test_a_datastore_without_db_engine_gets_no_database_profile():
    """Guessing would produce a SQL Server rollout onto hosts that were never
    SQL Server. The missing tag is reported instead, by tags_missing."""
    profiles = fc.assign_profiles(
        {"os_family": "windows", "service_archetype": "datastore",
         "db_engine": None, "env": "prod"}, AGENT_PROFILES)
    assert "sqlserver" not in profiles


def test_a_host_with_no_os_fact_still_gets_the_base_profile():
    """An agent that never reported has no platform metadata. It must still be
    in the fleet — that is the whole point of agent_missing."""
    assert fc.assign_profiles({}, AGENT_PROFILES) == ["base-infrastructure"]


# --- version comparison -----------------------------------------------------

def test_an_unparseable_agent_version_is_treated_as_ancient():
    """Safe direction: it puts the host on the remediation list rather than
    silently exempting it from the version check."""
    assert fc.parse_version("not-a-version") < fc.parse_version("7.55.0")
    assert fc.parse_version("7.55.0") == (7, 55, 0)
    assert fc.parse_version("7.58.1-rc.2") > fc.parse_version("7.55.0")


# --- each of the eight §39 conditions ---------------------------------------

def test_agent_missing_is_detected_from_the_inventory_not_the_host_list(report):
    """The check that only works because the denominator is the inventory:
    vm-legacy-04 has no Datadog host record at all, so a measurement taken
    from the host list could not see it."""
    assert "agent_missing" in findings_for(report, "vm-legacy-04")
    assert "vm-legacy-04" not in {h["name"] for h in
                                  [fc.normalize_host(r) for r in
                                   json.loads((FIXTURES / "fleet_hosts.json").read_text())]}


def test_agent_offline_is_distinct_from_agent_missing(report):
    f = findings_for(report, "batch-lin-05")
    assert "agent_offline" in f and "agent_missing" not in f


def test_agent_out_of_date(report):
    assert "agent_out_of_date" in findings_for(report, "app-lin-03")


def test_integration_missing_names_the_profile_and_the_check(report):
    """A healthy agent with one required check never enabled — the commonest
    real fleet defect, and invisible to any metric that counts agents."""
    items = report["findings"]["integration_missing"]
    assert {"host": "file-win-08", "profile": "windows-server",
            "integration": "wmi_check"} in items


def test_dbm_missing_is_reported_separately_from_the_integration(report):
    f = findings_for(report, "sql-win-02")
    assert "dbm_missing" in f and "integration_missing" not in f


def test_apm_missing_on_an_application_host(report):
    assert "apm_missing" in findings_for(report, "app-lin-03")


def test_tags_missing_catches_both_absent_and_invalid_values(report):
    by_host = {f["host"]: f["violations"] for f in report["findings"]["tags_missing"]}
    assert "invalid_env:production" in by_host["file-win-08"]
    assert "missing_tag:alert_band" in by_host["vm-legacy-04"]


def test_ownership_missing(report):
    assert "ownership_missing" in findings_for(report, "vm-legacy-04")


# --- the ratio itself -------------------------------------------------------

def test_a_fully_instrumented_host_has_no_findings(report):
    """Without this the suite would only prove the checks can fail, not that
    they can pass — a report that flags everything is as useless as one that
    flags nothing."""
    for host in ("app-win-01", "app-lin-07"):
        assert findings_for(report, host) == []


def test_exempt_hosts_leave_the_denominator_entirely(report):
    assert report["exempt_hosts"] == ["appliance-06"]
    assert "appliance-06" not in {h["host"] for h in report["hosts"]}
    assert report["summary"]["hosts_exempt"] == 1


def test_a_reporting_host_outside_the_inventory_is_not_in_the_denominator(report):
    """orphan-lin-99 has an agent and no inventory entry. Fleet compliance
    measures the estate the platform knows it must cover; an unknown host is
    coverage_report.py's C2/C9 finding, not a fleet-compliance numerator."""
    assert "orphan-lin-99" not in {h["host"] for h in report["hosts"]}


def test_a_host_counts_once_regardless_of_how_many_findings_it_has(report):
    """Per-finding weighting would let the fleet's score improve without a
    single host becoming correct."""
    assert len(findings_for(report, "vm-legacy-04")) == 3
    s = report["summary"]
    assert s["hosts_required"] == 7
    assert s["hosts_compliant"] == 2
    assert s["compliance_pct"] == 28.6


def test_an_empty_denominator_is_not_reported_as_compliant():
    """The false-green this platform exists to prevent: 0/0 is 'nothing is
    known', never '100% compliant'."""
    empty = fc.evaluate({"resources": []}, [], POLICY, AGENT_PROFILES, 0.0)
    assert empty["measured"] is False
    assert empty["summary"]["compliance_pct"] == 0.0
    assert "Not measured" in fc.to_markdown(empty, AGENT_PROFILES)


def test_esxi_hosts_are_not_counted_as_missing_agents():
    """ESXi runs no third-party agent; it is collected through vCenter.
    Counting it would manufacture a permanent, unfixable gap."""
    inv = {"resources": [{"id": "esxi_host:esx-01", "kind": "esxi_host",
                          "name": "esx-01", "tags": {}}]}
    assert fc.evaluate(inv, [], POLICY, AGENT_PROFILES, 0.0)["summary"]["hosts_required"] == 0


def test_the_percentage_is_compliant_over_required(report):
    s = report["summary"]
    assert s["compliance_pct"] == round(
        s["hosts_compliant"] / s["hosts_required"] * 100, 1)


def test_the_gate_is_off_and_says_so():
    """Report-only is a decision with a recorded trigger, not an oversight."""
    targets = AGENT_PROFILES["compliance"]["ratio"]["report_targets"]
    assert targets["gate"] is False
    assert targets["gate_when"].strip()
    assert targets["target_pct"] == 95


# --- deployment metadata ----------------------------------------------------

def test_a_deployment_marker_cannot_be_emitted_without_a_version():
    """Emitting a versionless marker would reproduce the exact defect this
    tool exists to fix."""
    with pytest.raises(SystemExit):
        ede.build_payload({"DD_SERVICE": "observability-platform", "DD_ENV": "prod"})


def test_the_marker_carries_unified_service_tags():
    payload = ede.build_payload({
        "DD_SERVICE": "observability-platform", "DD_ENV": "prod",
        "DD_VERSION": "412-abc123", "DD_GIT_COMMIT_SHA": "abc123",
        "DD_GIT_REPOSITORY_URL": "https://github.com/acme/enterprise-observability",
    })
    assert "service:observability-platform" in payload["tags"]
    assert "env:prod" in payload["tags"]
    assert "version:412-abc123" in payload["tags"]
    assert payload["aggregation_key"] == "deployment:observability-platform:prod"


def test_the_deploy_workflow_sets_all_three_deployment_variables():
    """§8's MISSING row was 'no pipeline sets DD_VERSION / DD_GIT_COMMIT_SHA'.
    This is the assertion that keeps it closed."""
    wf = (Path(__file__).parent.parent / ".github/workflows/deploy.yml").read_text()
    for var in ("DD_VERSION:", "DD_GIT_COMMIT_SHA:", "DD_GIT_REPOSITORY_URL:"):
        assert var in wf
    assert "emit_deployment_event.py" in wf


def test_the_tagging_standard_documents_the_per_runtime_requirement():
    doc = (Path(__file__).parent.parent / "docs/tagging-standard.md").read_text()
    assert "## Deployment metadata" in doc
    for runtime in ("IIS", "Java", "Node.js", "Python", "systemd", "Azure App Service"):
        assert runtime in doc


def test_the_fleet_standard_documents_all_three_delivery_paths():
    doc = (Path(__file__).parent.parent / "docs/fleet-management.md").read_text()
    for mechanism in ("Azure Policy", "deployIfNotExists", "golden image",
                      "configuration management", "Azure Arc"):
        assert mechanism in doc
    # Manual installation must be documented as the exception, not as a path.
    assert "Manual installation — the exception, not a path" in doc
