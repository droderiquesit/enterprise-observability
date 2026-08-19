"""Governance checks, run against the REAL planned estate.

`tests/fixtures/monitors_planned.json` is generated from the actual
`terraform plan` output of stacks/coverage, so these tests grade the monitors
this repository would really deploy — not a hand-written approximation that
agrees with itself.
"""
import copy
import json
from pathlib import Path

import build_inventory
import coverage_report as cr
import obs_common as oc
import profile_engine

FIXTURES = Path(__file__).parent / "fixtures"
POLICY = oc.load_policy()
SERVICES = oc.load_services()
MONITORS = json.loads((FIXTURES / "monitors_planned.json").read_text())
SLOS = json.loads((FIXTURES / "slos.json").read_text())


def _estate(n=2000):
    inv = {"resources": build_inventory.synthesize(n), "resource_count": n}
    return inv, profile_engine.assign(inv, POLICY, SERVICES)


def _run(monitors=None, slos=None):
    inv, assignments = _estate()
    return cr.run_checks(inv, assignments, monitors or MONITORS, slos or SLOS, POLICY)


# --- the contract holds on the real estate ----------------------------------

def test_every_planned_monitor_satisfies_the_contract():
    c = _run()["summary"]["check_counts"]
    assert c["C5"] == 0, "monitors without a runbook"
    assert c["C6"] == 0, "monitors without automation"
    assert c["C7"] == 0, "monitors without routing"
    assert c["C8"] == 0, "duplicate monitors"
    assert c["C9"] == 0, "unmanaged monitors"
    assert c["C11"] == 0, "cardinality violations"
    assert c["C12"] == 0, "expired exceptions"
    assert c["C14"] == 0, "paging discipline violations"
    assert c["C15"] == 0, "monitors with no actionable response"
    assert c["C17"] == 0, "monitors with no auto-resolve condition"


def test_full_coverage_of_the_alertable_estate():
    s = _run()["summary"]
    assert s["coverage_pct"] == 100.0
    assert s["resources_observe_only"] > 0, "dev/tier3 policy should exclude some estate"
    assert s["check_counts"]["C4"] == 0, "every service maps to an SLO"


def test_paging_estate_is_small_and_production_only():
    s = _run()["summary"]
    assert 0 < s["monitors_paging"] < s["monitors_managed"] * 0.2


# --- seeded defects are each caught by the right check ----------------------

def test_clickops_monitor_is_detected():
    rogue = {"id": 999001, "name": "temporary CPU check", "type": "metric alert",
             "query": "avg(last_5m):avg:system.cpu.user{*} > 90", "tags": [], "message": ""}
    assert _run(MONITORS + [rogue])["summary"]["check_counts"]["C9"] == 1


def test_duplicate_monitor_is_detected():
    dupe = copy.deepcopy(MONITORS[0])
    dupe["id"] = 999002
    dupe["name"] = "a copy somebody made"
    assert _run(MONITORS + [dupe])["summary"]["check_counts"]["C8"] >= 1


def test_missing_runbook_and_automation_are_detected():
    broken = copy.deepcopy(MONITORS[0])
    broken.update(id=999003, query="unique-query-for-this-test",
                  tags=[t for t in broken["tags"]
                        if not t.startswith(("runbook:", "automation_ref:", "dedup_key:"))])
    c = _run(MONITORS + [broken])["summary"]["check_counts"]
    assert c["C5"] == 1 and c["C6"] == 1


def test_monitor_that_pages_outside_production_is_detected():
    bad = copy.deepcopy(MONITORS[0])
    bad.update(id=999004, name="staging pager", query="unique-staging-query")
    bad["tags"] = [t for t in bad["tags"] if not t.startswith(("env:", "pages:", "dedup_key:"))]
    bad["tags"] += ["env:stage", "pages:true"]
    assert _run(MONITORS + [bad])["summary"]["check_counts"]["C14"] == 1


def test_p3_monitor_that_pages_is_detected():
    bad = copy.deepcopy(MONITORS[0])
    bad.update(id=999005, name="p3 pager", query="unique-p3-query")
    bad["tags"] = [t for t in bad["tags"]
                   if not t.startswith(("priority:", "pages:", "dedup_key:"))]
    bad["tags"] += ["priority:P3", "pages:true"]
    assert _run(MONITORS + [bad])["summary"]["check_counts"]["C14"] == 1


def test_high_cardinality_monitor_is_detected():
    bad = copy.deepcopy(MONITORS[0])
    bad.update(id=999006, name="per-container monitor",
               query="avg(last_5m):avg:x{env:prod} by {container_id,host,service,pod_name} > 1")
    bad["tags"] = [t for t in bad["tags"] if not t.startswith("dedup_key:")]
    assert _run(MONITORS + [bad])["summary"]["check_counts"]["C11"] >= 1


def test_unactionable_monitor_is_detected():
    bad = copy.deepcopy(MONITORS[0])
    bad.update(id=999007, name="mystery alert", query="unique-mystery-query", message="it broke")
    bad["tags"] = [t for t in bad["tags"] if not t.startswith("dedup_key:")]
    assert _run(MONITORS + [bad])["summary"]["check_counts"]["C15"] == 1


def test_monitor_without_auto_resolve_is_detected():
    """`timeout_h: 0` is Datadog's default and means the monitor stays
    triggered until a human clears it — during which it will not alert again
    for the same group. It must fail, and it must stop a deploy."""
    bad = copy.deepcopy(MONITORS[0])
    bad.update(id=999010, name="never resolves", query="unique-never-resolves-query",
               options={"timeout_h": 0})
    bad["tags"] = [t for t in bad["tags"] if not t.startswith("dedup_key:")]
    s = _run(MONITORS + [bad])["summary"]
    assert s["check_counts"]["C17"] == 1
    assert s["deploy_blocking_counts"]["C17"] == 1
    assert s["deploy_pass"] is False


def test_monitor_with_no_options_at_all_is_detected():
    """A monitor created outside the factory has no options block; absent is
    the same failure as zero, not a reason to skip the check."""
    bad = copy.deepcopy(MONITORS[0])
    bad.update(id=999011, name="no options", query="unique-no-options-query")
    bad.pop("options", None)
    bad["tags"] = [t for t in bad["tags"] if not t.startswith("dedup_key:")]
    assert _run(MONITORS + [bad])["summary"]["check_counts"]["C17"] == 1


def test_auto_resolve_window_outside_the_policy_range_is_detected():
    """A 30-day auto-resolve is 'never' with extra steps."""
    bad = copy.deepcopy(MONITORS[0])
    bad.update(id=999012, name="resolves next month", query="unique-long-window-query",
               options={"timeout_h": 720})
    bad["tags"] = [t for t in bad["tags"] if not t.startswith("dedup_key:")]
    assert _run(MONITORS + [bad])["summary"]["check_counts"]["C17"] == 1


def test_planned_auto_resolve_windows_match_the_policy_maps():
    """The fixture is plan-derived, so this grades what Terraform really
    renders: every window is one of the values policy can produce."""
    ar = POLICY["global"]["monitor_defaults"]["auto_resolve"]
    allowed = set(ar["by_priority"].values()) | set(ar["by_signal"].values()) \
        | set(ar["by_detection"].values())
    windows = {(m.get("options") or {}).get("timeout_h") for m in MONITORS}
    assert windows <= allowed, windows - allowed
    assert None not in windows and 0 not in windows


def test_removing_a_pack_creates_a_coverage_gap():
    """Coverage is measured, not assumed: delete the API pack, coverage drops."""
    api_pack = set(POLICY["packs"]["api-core"]["archetypes"])
    reduced = [m for m in MONITORS
               if not any(t.startswith("archetype:") and t.split(":", 1)[1] in api_pack
                          for t in m["tags"])]
    r = _run(reduced)
    assert r["summary"]["check_counts"]["C1"] > 0
    assert r["summary"]["coverage_pct"] < 100.0


def test_expired_exception_is_detected():
    policy = oc.load_policy()
    policy["exceptions"] = copy.deepcopy(policy["exceptions"])
    policy["exceptions"][0]["expires"] = "2020-01-01"
    inv, assignments = _estate()
    r = cr.run_checks(inv, assignments, MONITORS, SLOS, policy)
    assert r["summary"]["check_counts"]["C12"] == 1


def test_markdown_renders():
    md = cr.to_markdown(_run())
    assert "# Coverage & Compliance Report" in md
    assert "C9 Unmanaged (click-ops) monitors" in md


# --- gate split: estate hygiene is advisory for deploy, blocking for nightly -

def test_clickops_monitor_fails_governance_but_not_the_deploy_gate():
    rogue = {"id": 999008, "name": "temporary CPU check", "type": "metric alert",
             "query": "avg(last_5m):avg:system.cpu.user{*} > 91", "tags": [], "message": ""}
    s = _run(MONITORS + [rogue])["summary"]
    assert s["check_counts"]["C9"] == 1
    assert s["deploy_blocking_counts"]["C9"] == 0
    assert s["pass"] is False


def test_declared_telemetry_dependency_is_advisory_for_deploy():
    """slos.yaml really declares one (slo-infra-backup-success) — the producer
    is deployed outside this platform, so it must not block the deploy gate."""
    s = _run()["summary"]
    assert s["check_counts"]["C13"] >= 1
    assert s["deploy_blocking_counts"]["C13"] == 0


def test_live_slo_status_error_blocks_the_deploy_gate():
    broken = copy.deepcopy(SLOS[0]) if SLOS else {"name": "broken slo", "tags": []}
    broken["name"] = "slo with a broken query"
    broken["overall_status"] = [{"error": "metric not found"}]
    s = _run(slos=SLOS + [broken])["summary"]
    assert s["deploy_blocking_counts"]["C13"] >= 1
    assert s["deploy_pass"] is False


def test_managed_monitor_missing_required_tag_blocks_the_deploy_gate():
    bad = copy.deepcopy(MONITORS[0])
    bad.update(id=999009, name="undertagged managed monitor", query="unique-undertagged-query")
    bad["tags"] = [t for t in bad["tags"] if not t.startswith(("service:", "dedup_key:"))]
    s = _run(MONITORS + [bad])["summary"]
    assert s["deploy_blocking_counts"]["C3"] >= 1
    assert s["deploy_pass"] is False


def test_deploy_pass_is_consistent_with_blocking_counts():
    s = _run()["summary"]
    assert s["deploy_pass"] == all(v == 0 for v in s["deploy_blocking_counts"].values())
    for cid, n in s["deploy_blocking_counts"].items():
        assert 0 <= n <= s["check_counts"][cid]


# --- accepted findings: governance fails on NEW, not on KNOWN ----------------

def test_acceptances_are_owned_and_time_boxed():
    """An acceptance without an owner or an expiry is a silent waiver."""
    accs = [e for e in POLICY["exceptions"] if e.get("control") == "finding_acceptance"]
    assert accs, "expected at least one finding_acceptance entry"
    for e in accs:
        assert e["owner"] and e["approved_by"] and e["expires"], e["id"]
        assert "check" in e["scope"], e["id"]
        assert isinstance(e["value"], int), e["id"]


def test_expired_acceptance_stops_suppressing():
    import datetime as dt
    live = cr.acceptances(POLICY, today=dt.date(2026, 9, 1))
    assert live, "acceptances should be live before their expiry"
    dead = cr.acceptances(POLICY, today=dt.date(2099, 1, 1))
    assert dead == {}, "an expired acceptance must stop suppressing findings"


def test_a_finding_beyond_the_accepted_count_still_fails():
    """Accepting 27 untagged resources must not accept the 28th."""
    inv, assignments = _estate()
    r = cr.run_checks(inv, assignments, MONITORS, SLOS, POLICY)
    s = r["summary"]
    # The synthetic estate seeds far more tag violations than the live-calibrated
    # acceptance covers, so the surplus must remain unaccepted and fail the run.
    assert s["check_counts"]["C3"] > s["accepted_counts"]["C3"]
    assert s["unaccepted_counts"]["C3"] > 0
    assert s["pass"] is False


def test_declared_dependency_accepted_but_live_slo_error_is_not():
    broken = copy.deepcopy(SLOS[0]) if SLOS else {"name": "x", "tags": []}
    broken["name"] = "objective with a broken query"
    broken["overall_status"] = [{"error": "metric not found"}]
    s = _run(slos=SLOS + [broken])["summary"]
    # the declared dependency is accepted; the live error is a real failure
    assert s["accepted_counts"]["C13"] == 1
    assert s["unaccepted_counts"]["C13"] >= 1
    assert s["deploy_pass"] is False
