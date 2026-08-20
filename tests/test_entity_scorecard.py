"""Entity-aware scorecards (§41).

The property under protection is that the three kinds are graded DIFFERENTLY,
and differently in the specific ways the platform argued for — not merely that
three labels exist. A "kind" that scores identically to the others is a column
in a report, not a rule set, and would be worth deleting.

The second property is that the deploy gate did not change. The fleet score
gates production at ≥ 85; re-weighting it in place would have changed what that
gate means without anybody deciding to.
"""
import monitor_scorecard as ms
import obs_common as oc

POLICY = oc.load_policy()
KINDS = POLICY["scorecards"]["entity_kinds"]
REPORT = ms.build(POLICY)


# --- the classification is total and explicit --------------------------------

def test_every_archetype_resolves_to_exactly_one_entity_kind():
    for aid, a in POLICY["archetypes"].items():
        assert oc.entity_kind(POLICY, a["resource_type"]) in KINDS, aid


def test_an_unclassified_resource_type_raises_rather_than_defaulting():
    """A silent default is how a new datastore technology gets graded as a
    request path and is never asked for a backup check."""
    try:
        oc.entity_kind(POLICY, "some_new_thing_nobody_classified")
    except KeyError as exc:
        assert "scorecards.yaml" in str(exc)
    else:
        raise AssertionError("an unclassified resource_type must not resolve")


def test_the_service_archetype_view_agrees_with_the_resource_type_view():
    """Reports classify RESOURCES by service_archetype and monitors by
    resource_type. If the two views disagreed, a report could claim a datastore
    was covered by a monitor the scorecard grades as a service."""
    assert oc.entity_kind_of_service_archetype(POLICY, "datastore") == "datastore"
    assert oc.entity_kind_of_service_archetype(POLICY, "infrastructure_resource") \
        == "infrastructure"
    assert oc.entity_kind_of_service_archetype(POLICY, "api") == "service"


# --- the three kinds are genuinely graded differently ------------------------

def test_each_kind_weights_total_one_hundred():
    for kind, spec in KINDS.items():
        assert sum(spec["weights"].values()) == 100, kind


def test_the_kinds_do_not_share_a_weighting():
    """Three identical weight blocks would be three labels, not three rule sets."""
    blocks = [tuple(sorted(spec["weights"].items())) for spec in KINDS.values()]
    assert len(set(blocks)) == len(blocks)


def test_a_service_is_judged_harder_on_its_objective_than_a_datastore():
    """The core §41 argument: a datastore is covered by the SLOs of the services
    it backs, so grading it on a per-datastore objective punishes the correct
    design."""
    assert KINDS["service"]["weights"]["slo_linkage"] > \
        KINDS["datastore"]["weights"]["slo_linkage"]
    assert KINDS["service"]["weights"]["slo_linkage"] > \
        KINDS["infrastructure"]["weights"]["slo_linkage"]


def test_infrastructure_is_judged_hardest_on_grouping():
    """One infrastructure monitor covers thousands of identical things, so
    grouping is not hygiene — it is the whole difference between a usable alert
    and a notification storm."""
    card = KINDS["infrastructure"]["weights"]["cardinality"]
    assert card > KINDS["service"]["weights"]["cardinality"]
    assert card > KINDS["datastore"]["weights"]["cardinality"]


def test_only_datastores_carry_the_durability_dimension():
    assert "durability" in KINDS["datastore"]["weights"]
    assert "durability" not in KINDS["service"]["weights"]
    assert "durability" not in KINDS["infrastructure"]["weights"]


def test_the_same_monitor_scores_differently_under_a_different_kind():
    """The end-to-end proof that the kind, not just the label, changes the score."""
    inst = next(i for i in oc.expand_instances(POLICY)
                if oc.entity_kind(POLICY, POLICY["archetypes"][i["archetype"]]
                                  ["resource_type"]) == "service")
    arch = POLICY["archetypes"][inst["archetype"]]
    base = ms.score_instance(POLICY, inst, arch)

    as_service = ms.score_entity(POLICY, base, inst, arch, set())
    # Same monitor, reclassified as a datastore with no durability horizon.
    as_datastore = ms.score_entity(
        POLICY, base, inst, dict(arch, resource_type="db_instance"), set())
    assert as_service["entity_kind"] == "service"
    assert as_datastore["entity_kind"] == "datastore"
    assert as_service["entity_score"] != as_datastore["entity_score"]


# --- the kind-specific rules actually fire -----------------------------------

def test_a_datastore_technology_with_no_durability_horizon_loses_those_points():
    inst = next(i for i in oc.expand_instances(POLICY)
                if oc.entity_kind(POLICY, POLICY["archetypes"][i["archetype"]]
                                  ["resource_type"]) == "datastore")
    arch = POLICY["archetypes"][inst["archetype"]]
    base = ms.score_instance(POLICY, inst, arch)

    covered = ms.score_entity(POLICY, base, inst, arch, {arch["resource_type"]})
    bare = ms.score_entity(POLICY, base, inst, arch, set())
    assert covered["entity_dimensions"]["durability"] == \
        KINDS["datastore"]["weights"]["durability"]
    assert bare["entity_dimensions"]["durability"] == 0
    assert any("durability horizon" in f for f in bare["entity_findings"])


def test_durability_is_judged_per_technology_not_per_monitor():
    """A single monitor cannot be blamed for a missing sibling: coverage is a
    property of the archetype set for a resource_type."""
    covered = oc.durability_covered_types(POLICY)
    assert "azure_sql" in covered      # has a storage-exhaustion forecast
    assert "backup_job" in covered     # IS the backup check
    # And the gap the platform admits to in scorecards.yaml is real.
    assert "azure_storage" not in covered


def test_an_infrastructure_monitor_without_a_collapse_key_is_flagged():
    inst = next(i for i in oc.expand_instances(POLICY)
                if oc.entity_kind(POLICY, POLICY["archetypes"][i["archetype"]]
                                  ["resource_type"]) == "infrastructure")
    arch = dict(POLICY["archetypes"][inst["archetype"]],
                group_by=["site", "device"], notify_by=[])
    _, findings = ms.entity_rules(POLICY, "infrastructure", inst, arch, set())
    assert any("collapse key" in f for f in findings)


def test_a_datastore_capacity_signal_that_pages_is_flagged():
    inst = next(i for i in oc.expand_instances(POLICY))
    arch = dict(POLICY["archetypes"][inst["archetype"]], signal="capacity")
    _, findings = ms.entity_rules(POLICY, "datastore", dict(inst, pages=True),
                                  arch, {arch["resource_type"]})
    assert any("lead time" in f for f in findings)


def test_a_customer_impact_service_with_no_objective_is_flagged():
    inst = next(i for i in oc.expand_instances(POLICY))
    arch = dict(POLICY["archetypes"][inst["archetype"]],
                impact_class="customer_impact")
    _, findings = ms.entity_rules(POLICY, "service",
                                  dict(inst, slo_id="slo-does-not-exist"), arch, set())
    assert any("no resolvable SLO" in f for f in findings)


# --- the committed estate holds up under the entity model --------------------

def test_every_entity_kind_is_present_and_meets_its_minimum():
    for kind, v in REPORT["by_entity_kind"].items():
        assert v["monitors"] > 0, f"{kind} grades nothing — the classification is wrong"
        assert v["meets_minimum"], (
            f"{kind} averages {v['average']} against a minimum of {v['min_score']}")


def test_the_only_open_entity_findings_are_the_declared_durability_backlog():
    """scorecards.yaml records what each rule found when it was written. If a
    NEW kind of finding appears, that note is now a lie."""
    for finding in REPORT["entity_findings"]:
        assert "durability horizon" in finding, finding


# --- the deploy gate did not change ------------------------------------------

def test_the_fleet_gate_still_passes_at_its_committed_thresholds():
    """The deploy pipeline runs `--min-fleet-score 85 --max-failing 0`."""
    s = REPORT["summary"]
    assert s["fleet_average"] >= 85.0
    assert s["failing"] == 0


def test_the_entity_layer_did_not_reweight_the_fleet_model():
    """The fleet dimensions must still total the original 100-point model — the
    entity layer READS them and never writes them."""
    assert sum(ms.WEIGHTS.values()) == 100
    row = REPORT["monitors"][0]
    assert set(row["dimensions"]) == set(ms.WEIGHTS)
    assert round(sum(row["dimensions"].values()), 1) == row["score"]
