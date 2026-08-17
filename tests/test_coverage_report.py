"""Coverage report: the planned monitor estate passes the governance gates;
seeded violations are detected by the right check."""
import copy
import json
from pathlib import Path

import build_inventory
import coverage_report as cr
import obs_common as oc
import profile_engine

FIXTURES = Path(__file__).parent / "fixtures"
POLICY = oc.load_policy()
MONITORS = json.loads((FIXTURES / "monitors_planned.json").read_text())
SLOS = json.loads((FIXTURES / "slos.json").read_text())


def _small_estate():
    inv = {"resources": build_inventory.synthesize(1200), "resource_count": 1200}
    assignments = profile_engine.assign(inv, POLICY)
    return inv, assignments


def _run(monitors, slos):
    inv, assignments = _small_estate()
    return cr.run_checks(inv, assignments, monitors, slos, POLICY)


def test_planned_estate_monitor_contract_clean():
    report = _run(MONITORS, SLOS)
    c = report["summary"]["check_counts"]
    # Contract checks against the Terraform-planned monitors must be clean.
    assert c["C5"] == 0, report["checks"]["C5"]  # runbooks
    assert c["C6"] == 0, report["checks"]["C6"]  # workflows
    assert c["C7"] == 0, report["checks"]["C7"]  # routing
    assert c["C8"] == 0, report["checks"]["C8"]  # duplicates
    assert c["C9"] == 0, report["checks"]["C9"]  # unmanaged
    assert c["C11"] == 0                          # cardinality
    assert c["C12"] == 0                          # expired exceptions


def test_full_coverage_of_alertable_estate():
    report = _run(MONITORS, SLOS)
    s = report["summary"]
    assert s["coverage_pct"] == 100.0, report["checks"]["C1"][:5]
    assert s["resources_observe_only"] > 0  # dev/sandbox/tier4 policy working
    assert s["check_counts"]["C4"] == 0     # every service maps to an SLO


def test_clickops_monitor_detected():
    rogue = {"id": 1, "name": "click-ops special", "type": "metric alert",
             "query": "avg(last_5m):avg:system.cpu.user{*} > 90", "tags": []}
    report = _run(MONITORS + [rogue], SLOS)
    assert report["summary"]["check_counts"]["C9"] == 1


def test_duplicate_monitor_detected():
    dupe = copy.deepcopy(MONITORS[0])
    dupe["id"] = 99999
    dupe["name"] = "duplicate of first"
    report = _run(MONITORS + [dupe], SLOS)
    assert report["summary"]["check_counts"]["C8"] >= 1


def test_missing_runbook_and_workflow_detected():
    broken = copy.deepcopy(MONITORS[0])
    broken["id"] = 88888
    broken["query"] = "unique-query-for-this-test"
    broken["tags"] = [t for t in broken["tags"]
                      if not t.startswith(("runbook:", "automation_ref:", "dedup_key:"))]
    report = _run(MONITORS + [broken], SLOS)
    assert report["summary"]["check_counts"]["C5"] == 1
    assert report["summary"]["check_counts"]["C6"] == 1


def test_broken_slos_surface_in_c13():
    report = _run(MONITORS, SLOS)
    problems = json.dumps(report["checks"]["C13"])
    assert "no valid monitors found" in problems or "monitor not found" in problems
    assert "telemetry dependency" in problems


def test_uncovered_kind_detected():
    # Remove all host archetype monitors → prod/staging hosts become C1 gaps.
    no_hosts = [m for m in MONITORS if not any(t.startswith("archetype:host-") or t == "archetype:memory-pressure" or t == "archetype:disk-capacity-forecast" for t in m["tags"])]
    report = _run(no_hosts, SLOS)
    assert report["summary"]["check_counts"]["C1"] > 0
    assert report["summary"]["coverage_pct"] < 100.0


def test_markdown_render():
    report = _run(MONITORS, SLOS)
    md = cr.to_markdown(report)
    assert "# Coverage & Compliance Report" in md
    assert "C9 Unmanaged (click-ops) monitors" in md
