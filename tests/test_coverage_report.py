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
