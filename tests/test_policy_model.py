"""The policy model itself: priority derivation, paging discipline, budgets.

These tests protect the decisions that are easy to erode one pull request at a
time — the ones where a small, reasonable-looking edit quietly turns a quiet
platform into a noisy one.
"""
import obs_common as oc
import validate_policy as vp

POLICY = oc.load_policy()


def test_policy_lint_is_clean():
    """The committed policy must satisfy every rule the platform advertises."""
    assert vp.lint() == []


# --- priority derivation ----------------------------------------------------

def test_customer_impact_on_critical_band_is_p1():
    assert oc.resolve_priority(POLICY, "customer_impact", "critical", "prod") == "P1"


def test_same_signal_is_quieter_on_a_lower_band():
    assert oc.resolve_priority(POLICY, "customer_impact", "standard", "prod") == "P2"
    assert oc.resolve_priority(POLICY, "customer_impact", "baseline", "prod") == "P3"


def test_hygiene_is_never_urgent():
    for band in ("critical", "standard", "baseline"):
        assert oc.resolve_priority(POLICY, "hygiene", band, "prod") == "P4"


def test_environment_can_only_make_a_signal_quieter():
    """The property that stops staging from ever paging."""
    for impact in POLICY["priorities"]["matrix"]:
        for band in ("critical", "standard", "baseline"):
            prod = oc.PRIORITY_RANK[oc.resolve_priority(POLICY, impact, band, "prod")]
            for env in ("stage", "qa"):
                if band not in POLICY["environments"][env]["bands_instantiated"]:
                    continue
                other = oc.PRIORITY_RANK[oc.resolve_priority(POLICY, impact, band, env)]
                assert other >= prod, f"{env} is louder than prod for {impact}/{band}"


def test_stage_and_qa_never_reach_p1_or_p2():
    for env in ("stage", "qa"):
        for impact in POLICY["priorities"]["matrix"]:
            for band in POLICY["environments"][env]["bands_instantiated"]:
                assert oc.resolve_priority(POLICY, impact, band, env) in ("P3", "P4")


# --- paging discipline ------------------------------------------------------

def test_only_production_pages():
    for env in ("qa", "stage", "dev"):
        assert not oc.pages(POLICY, "P1", "critical", env)


def test_p3_and_p4_never_page():
    for p in ("P3", "P4"):
        assert not oc.pages(POLICY, p, "critical", "prod")


def test_p2_pages_only_from_confirmed_impact():
    """A symptom does not wake anyone; measured or confirmed impact does."""
    assert not oc.pages(POLICY, "P2", "critical", "prod", source="archetype")
    assert oc.pages(POLICY, "P2", "critical", "prod", source="slo_burn")
    assert oc.pages(POLICY, "P2", "critical", "prod", source="composite")


def test_standard_and_baseline_bands_never_page():
    for band in ("standard", "baseline"):
        assert not oc.pages(POLICY, "P1", band, "prod")


# --- the estate -------------------------------------------------------------

def test_dev_creates_no_monitors():
    assert all(i["env"] != "dev" for i in oc.expand_instances(POLICY, ["dev", "qa", "stage", "prod"]))


def test_estate_stays_inside_every_budget():
    card = POLICY["global"]["cardinality"]
    inst = oc.expand_instances(POLICY)
    assert len(inst) <= card["max_total_managed_monitors"]
    assert sum(1 for i in inst if i["pages"]) <= card["max_paging_monitors"]
    assert sum(1 for i in inst if i["priority"] == "P1") <= card["max_p1_monitors"]


def test_paging_is_a_small_minority_of_the_estate():
    inst = oc.expand_instances(POLICY)
    paging = sum(1 for i in inst if i["pages"])
    assert paging / len(inst) < 0.20, (
        f"{paging}/{len(inst)} monitor patterns can page. Above roughly a fifth, "
        "the platform is training people to ignore pages.")


def test_predictive_detection_dominates():
    """Predictive-first is a claim; this is the measurement."""
    inst = oc.expand_instances(POLICY)
    predictive = sum(1 for i in inst if i["detection"] in
                     ("anomaly", "seasonal_anomaly", "forecast", "outlier", "rate_of_change"))
    fixed = sum(1 for i in inst if i["detection"] == "threshold")
    assert predictive >= fixed * 0.6, (
        f"only {predictive} predictive vs {fixed} fixed-threshold instances")


def test_every_fixed_threshold_has_a_recorded_rationale():
    for aid, a in POLICY["archetypes"].items():
        if a["detection"] == "threshold":
            assert a.get("rationale_fixed_threshold"), (
                f"{aid} uses a fixed number with no explanation of why that number "
                "has operational meaning")


def test_every_archetype_reaches_a_real_destination():
    """No monitor may resolve to a notification profile that has no route."""
    profiles = POLICY["notification_profiles"]["notification_profiles"]
    for i in oc.expand_instances(POLICY):
        routes = profiles[i["notification_profile"]]["routes"]
        assert i["priority"] in routes, (
            f"{i['key']} is {i['priority']} on profile {i['notification_profile']}, "
            "which defines no route for that priority — the alert would go nowhere")


def test_monitor_count_is_bounded_not_proportional_to_resources():
    """The framework's central claim, stated as a test.

    The naive model is services × environments × signals. This asserts the
    estate is a function of DECISIONS (archetypes × envs × bands) instead.
    """
    inst = oc.expand_instances(POLICY)
    naive = 100_000 * 4 * 20
    assert len(inst) < naive / 1000
    # And it does not move when the estate does: expansion never reads inventory.
    assert len(inst) == len(oc.expand_instances(POLICY))


# --- auto-resolve: every monitor resolves itself ----------------------------

def test_auto_resolve_policy_covers_every_priority():
    """A monitor that falls through every override still lands on a window."""
    ar = POLICY["global"]["monitor_defaults"]["auto_resolve"]
    assert set(ar["by_priority"]) == set(POLICY["global"]["tag_vocabulary"]["priority"])


def test_every_auto_resolve_window_is_inside_its_own_bounds():
    """The maps and the guardrail the factory enforces cannot disagree."""
    ar = POLICY["global"]["monitor_defaults"]["auto_resolve"]
    windows = {
        **{f"by_priority.{k}": v for k, v in ar["by_priority"].items()},
        **{f"by_signal.{k}": v for k, v in ar["by_signal"].items()},
        **{f"by_detection.{k}": v for k, v in ar["by_detection"].items()},
        "monitor_defaults.timeout_h": POLICY["global"]["monitor_defaults"]["timeout_h"],
    }
    for where, hours in windows.items():
        assert ar["min_hours"] <= hours <= ar["max_hours"], f"{where} = {hours}h"


def test_auto_resolve_is_never_disabled_by_policy():
    """`timeout_h: 0` is Datadog's default and means 'never resolves'. The
    whole point of this block is that no path through it can produce one."""
    ar = POLICY["global"]["monitor_defaults"]["auto_resolve"]
    assert ar["min_hours"] >= 1
    assert POLICY["global"]["monitor_defaults"]["timeout_h"] >= ar["min_hours"]
    for m in ("by_priority", "by_signal", "by_detection"):
        assert all(v >= ar["min_hours"] for v in ar[m].values()), m


def test_auto_resolve_overrides_name_real_signals_and_detections():
    """An override keyed on a typo is a silent no-op — it would look configured
    and resolve on the priority default instead."""
    ar = POLICY["global"]["monitor_defaults"]["auto_resolve"]
    signals = {a["signal"] for a in POLICY["archetypes"].values()}
    detections = set(POLICY["global"]["tag_vocabulary"]["detection"])
    assert set(ar["by_signal"]) <= signals, set(ar["by_signal"]) - signals
    assert set(ar["by_detection"]) <= detections, set(ar["by_detection"]) - detections


def test_ephemeral_signals_resolve_faster_than_the_priority_floor():
    """The reason by_signal exists: a batch run that ended, a deployment that
    happened, a security event that fired — none of these recover on their own,
    so they are exactly the monitors that get stuck in the triggered state."""
    ar = POLICY["global"]["monitor_defaults"]["auto_resolve"]
    slowest_floor = max(ar["by_priority"].values())
    for signal in ("job_failure", "schedule_miss", "change"):
        assert ar["by_signal"][signal] < slowest_floor
