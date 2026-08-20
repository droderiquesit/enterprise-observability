"""Control-M: catching an abnormal job WHILE IT IS STILL RUNNING.

The claim this phase makes is narrow and testable: a job that historically
takes five minutes and is twenty minutes in must be alerting *now*, not
tomorrow morning when its completion record finally exists.

These tests evaluate the COMMITTED catalog query — the operator, the threshold
and the in-flight gate are all read out of
`platform/policy/archetypes/controlm.yaml`, never restated here. Editing the
query to something that can no longer see a running job fails these tests
rather than quietly passing them.
"""
import re
from pathlib import Path

import correlate_events as ce
import generate_runbooks
import obs_common as oc
from runbook_content import RESOURCE_FAMILY

POLICY = oc.load_policy()
ARCH = {aid: a for aid, a in POLICY["archetypes"].items() if aid.startswith("controlm-")}
INFLIGHT = POLICY["archetypes"]["controlm-job-inflight-overrun"]

TELEMETRY_DOC = (Path(__file__).resolve().parent.parent
                 / "docs" / "telemetry-gaps.md").read_text()

_TAIL = re.compile(r"(>=|<=|>|<)\s*(-?[0-9.]+)\s*$")


def _condition(query: str) -> tuple[str, float]:
    """(operator, threshold) as committed in the catalog query."""
    m = _TAIL.search(query.strip())
    assert m, f"no comparison found in {query!r}"
    return m.group(1), float(m.group(2))


def _evaluate(query: str, sample: dict) -> tuple[bool, float]:
    """Evaluate a catalog query against one poll's worth of metric values.

    Only the arithmetic the Control-M archetypes actually use is implemented —
    a product of metric terms, or a single term. That is enough to prove the
    behaviour that matters: what the monitor computes and whether it crosses
    the number written in the catalog.
    """
    value = 1.0
    for metric in generate_runbooks.metrics_in(query):
        assert metric in sample, f"query reads {metric}, sample does not supply it"
        value *= sample[metric]
    op, threshold = _condition(query)
    fired = {">": value > threshold, ">=": value >= threshold,
             "<": value < threshold, "<=": value <= threshold}[op]
    return fired, value


def _poll(expected_duration: float, elapsed: float, running: int) -> dict:
    """One exporter poll, exactly as docs/telemetry-gaps.md §9 defines it."""
    return {
        "controlm.job.expected_duration": expected_duration,
        "controlm.job.elapsed_seconds": elapsed,
        "controlm.job.duration_ratio": elapsed / expected_duration,
        "controlm.job.running": running,
    }


# --- the headline capability -------------------------------------------------

def test_a_job_at_four_times_its_expected_duration_fires_while_still_running():
    """The requirement, stated as a test: a 5-minute job, 20 minutes in, has
    not finished — and the monitor is already alerting."""
    sample = _poll(expected_duration=300, elapsed=1200, running=1)
    fired, value = _evaluate(INFLIGHT["query"], sample)
    assert sample["controlm.job.running"] == 1, "the job has NOT ended"
    assert value == 4.0
    assert fired, "a job at 4x its baseline must alert before it completes"


def test_the_alert_arrives_long_before_the_job_ends():
    """Walk the run minute by minute and find the first poll that alerts. An
    alert that arrives at minute 19 of a 20-minute overrun is a completion
    alert with extra steps; this one has to leave usable time on the clock."""
    expected, actual_end = 300, 1200
    first_alert = next(
        elapsed for elapsed in range(60, actual_end + 1, 60)
        if _evaluate(INFLIGHT["query"], _poll(expected, elapsed, running=1))[0])
    assert first_alert <= 660, first_alert          # ~11 minutes: ratio 2.0 + one poll
    assert actual_end - first_alert >= 540, (
        "at least nine minutes of warning before the run would have ended")


def test_the_monitor_cannot_fire_on_a_job_that_has_already_finished():
    """`controlm.job.running` is a GATE, not decoration. Once Control-M reports
    an end state the evaluated value collapses to zero, so the in-flight monitor
    resolves itself instead of restating what the failure archetypes already
    said."""
    finished = _poll(expected_duration=300, elapsed=1200, running=0)
    fired, value = _evaluate(INFLIGHT["query"], finished)
    assert value == 0.0
    assert not fired


def test_the_gate_is_arithmetic_in_the_query_not_only_a_tag_filter():
    """A tag filter can be silently dropped by an emitter that forgets to send
    `job_state`. Multiplying by `running` makes firing on a finished run
    arithmetically impossible."""
    q = INFLIGHT["query"]
    assert "controlm.job.running" in q
    assert "*" in q.split("controlm.job.duration_ratio", 1)[1]
    assert "job_state:running" in q


def test_a_normal_run_is_silent_and_a_drifting_one_warns_first():
    ok, _ = _evaluate(INFLIGHT["query"], _poll(300, 330, running=1))     # ratio 1.1
    assert not ok
    warn = INFLIGHT["thresholds"]["warning"]
    crit = INFLIGHT["thresholds"]["critical"]
    assert warn < crit, "the warning must arrive while there is still recovery time"
    _, value = _evaluate(INFLIGHT["query"], _poll(300, 480, running=1))  # ratio 1.6
    assert warn <= value < crit, "1.6x should warn, not page a critical"


def test_the_threshold_is_a_multiple_of_the_jobs_own_baseline():
    """One monitor, thousands of jobs: the same catalog number must be correct
    for a 40-second file poll and a six-hour ledger close, which is only true
    because the metric is a ratio."""
    for baseline in (40, 300, 21600):
        fired, value = _evaluate(INFLIGHT["query"], _poll(baseline, baseline * 4, running=1))
        assert fired and value == 4.0


# --- the rest of the catalog behaves as declared ------------------------------

def test_every_controlm_archetype_is_registered_end_to_end():
    assert len(ARCH) == 9, sorted(ARCH)
    for aid, a in ARCH.items():
        assert a["domain"] == "integration"
        assert a["runbook"] in POLICY["runbooks"], aid
        assert a["slo_id"] in POLICY["slos"], aid
        assert a["workflow"] in POLICY["workflows"], aid
        assert a["resource_type"] in RESOURCE_FAMILY, (
            f"{aid}: resource_type {a['resource_type']} has no runbook content family")
        assert (generate_runbooks.RUNBOOK_DIR / f"{a['runbook']}.md").exists(), aid


def test_the_catalog_covers_every_control_m_failure_mode_asked_for():
    """Named individually so deleting one is a visible test failure, not a
    silently thinner catalog."""
    for aid in ("controlm-job-inflight-overrun",      # in-flight duration ratio
                "controlm-job-runtime-drift",         # run-over-run baseline growth
                "controlm-job-late-start",            # missed / late start
                "controlm-job-not-executed",          # missing execution
                "controlm-job-abnormally-short",      # abnormally short run
                "controlm-job-failure",               # job failure
                "controlm-dependency-failure",        # dependency failure
                "controlm-job-last-success-stale",    # job-level freshness
                "controlm-exporter-telemetry-loss"):  # the poller itself
        assert aid in ARCH


def test_every_metric_the_catalog_reads_has_an_emission_contract():
    """No archetype may query a metric nobody has agreed to emit."""
    for aid, a in ARCH.items():
        for metric in generate_runbooks.metrics_in(a["query"]):
            assert metric.startswith("controlm.job."), (aid, metric)
            assert f"`{metric}`" in TELEMETRY_DOC, (
                f"{aid} reads {metric}, which docs/telemetry-gaps.md does not define")


def test_the_six_contract_metrics_are_all_documented():
    for metric in ("controlm.job.running", "controlm.job.elapsed_seconds",
                   "controlm.job.expected_duration", "controlm.job.duration_ratio",
                   "controlm.job.status", "controlm.job.last_success"):
        assert f"`{metric}`" in TELEMETRY_DOC


def test_an_abnormally_short_run_is_caught_from_the_other_side():
    """The success that isn't: Control-M ends the job OK in 8 seconds because
    the input file was empty."""
    a = ARCH["controlm-job-abnormally-short"]
    fired, value = _evaluate(a["query"], _poll(300, 8, running=0))
    assert fired and value < 0.1
    assert not _evaluate(a["query"], _poll(300, 290, running=0))[0]


def test_control_m_never_pages_for_a_symptom_and_only_prod_pages():
    """Adding a scheduler catalog must not quietly enlarge the paging estate."""
    inst = [i for i in oc.expand_instances(POLICY) if i["archetype"].startswith("controlm-")]
    assert inst
    assert all(i["env"] == "prod" for i in inst if i["pages"])
    assert all(i["priority"] == "P1" for i in inst if i["pages"])
    assert all(POLICY["archetypes"][i["archetype"]]["impact_class"] == "customer_impact"
               for i in inst if i["pages"])


# --- correlation: one incident, rooted at the job -----------------------------

def _event(ts, ck, dk, archetype, domain, signal, priority, title):
    return {"ts": ts, "correlation_key": ck, "dedup_key": dk, "archetype": archetype,
            "domain": domain, "signal": signal, "priority": priority, "env": "prod",
            "region": "eastus2", "kind": "alert", "title": title, "service": ck.split(".")[-1]}


def test_a_long_running_job_adopts_the_pipeline_and_the_stale_data_it_caused():
    """The §26 correlation example: three alerts, three domains, one incident —
    and the parent is the job, not the freshness alert that shouted loudest.

    The timestamps are the real ones: the job overruns, the pipeline that waits
    on it misses its window twelve minutes later, the data product reads stale
    twenty-five minutes after that. A five-minute correlation window would have
    produced three incidents.
    """
    events = [
        _event(0, "batch-platform.prod.batch-platform",
               "batch-platform.prod.controlm-job-inflight-overrun",
               "controlm-job-inflight-overrun", "integration", "latency", "P2",
               "gl-close job running 4x its baseline"),
        _event(720, "data-pipelines.prod.data-platform",
               "data-platform.prod.schedule-missed-run",
               "schedule-missed-run", "data", "schedule_miss", "P2",
               "downstream load never started"),
        _event(2220, "data-pipelines.prod.finance-mart",
               "finance-mart.prod.pipeline-output-stale",
               "pipeline-output-stale", "data", "freshness", "P1",
               "finance mart is stale"),
    ]
    groups = ce.correlate(events)

    assert len(groups) == 1, [g["parent"]["title"] for g in groups]
    g = groups[0]
    assert g["parent"]["archetype"] == "controlm-job-inflight-overrun", (
        "the job is the cause; freshness outranks latency in the generic ranking, "
        "which is exactly what the scheduler rule exists to override")
    assert g["suppressed"] == 2
    assert sum(x["pages"] for x in groups) == 1, "three alerts, one page"
    assert g["creates_incident"]


def test_adopting_a_p1_child_does_not_downgrade_the_incident():
    """Suppression must never lose severity: the group keeps the worst priority
    among its members while keeping the job as the root cause."""
    events = [
        _event(0, "batch-platform.prod.batch-platform",
               "batch-platform.prod.controlm-job-failure",
               "controlm-job-failure", "integration", "job_failure", "P2",
               "nightly extract ended not ok"),
        _event(1800, "data-pipelines.prod.finance-mart",
               "finance-mart.prod.pipeline-output-stale",
               "pipeline-output-stale", "data", "freshness", "P1",
               "finance mart is stale"),
    ]
    g = ce.correlate(events)[0]
    assert g["parent"]["archetype"] == "controlm-job-failure"
    assert g["priority"] == "P1"
    assert g["creates_incident"]


def test_an_unrelated_data_alert_is_not_adopted_by_a_control_m_job():
    """The rule joins on env. A stale data product in stage is not evidence
    about a job running in prod."""
    events = [
        _event(0, "batch-platform.prod.batch-platform",
               "batch-platform.prod.controlm-job-inflight-overrun",
               "controlm-job-inflight-overrun", "integration", "latency", "P2",
               "job overrunning in prod"),
        dict(_event(600, "data-pipelines.stage.finance-mart",
                    "finance-mart.stage.pipeline-output-stale",
                    "pipeline-output-stale", "data", "freshness", "P3",
                    "stage mart is stale"), env="stage"),
    ]
    assert len(ce.correlate(events)) == 2
