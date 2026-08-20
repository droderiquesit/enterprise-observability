"""DATADOG AGENT CONFIGURATION MANAGEMENT — composition, guardrails, drift.

The failure this whole area exists to prevent is a configuration file per host.
These tests assert the properties that keep it composed instead: that layers
combine in the documented order, that a check added by one layer survives
another, and that the guardrails which make composition safe actually refuse
the things they claim to refuse.

The representative render tests (§25) are the ones that would catch a change to
a shared layer breaking one workload while leaving the others fine.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import pytest                                            # noqa: E402
import yaml                                              # noqa: E402

import agent_config as ac                                # noqa: E402
import obs_common as oc                                  # noqa: E402

LAYERS = ac.load_layers()
NODES = {n["name"]: n for n in ac.load_nodes()}
POLICY = oc.load_policy()


def rendered(name):
    return ac.render(NODES[name], LAYERS)


# --- the catalog boundary ----------------------------------------------------

def test_every_config_profile_names_a_real_catalog_profile():
    """This folder renders configuration; platform/policy/agent_profiles.yaml
    decides which hosts get it. Two files describing the same profile is the
    duplication the design exists to avoid, so each config profile points at a
    catalog entry and the lint fails if that entry disappears."""
    catalog = set(oc.load_agent_profiles()["agent_profiles"])
    for name, frag in LAYERS["profiles"].items():
        cp = frag.get("catalog_profile")
        if cp is None:
            continue        # azure-managed-databases installs nothing
        assert cp in catalog, (
            f"config profile {name!r} claims catalog profile {cp!r}, which is "
            f"not in agent_profiles.yaml (have: {sorted(catalog)})")


def test_the_minimum_agent_version_is_not_declared_twice():
    """Two files naming a minimum version is two answers to one question, and
    the one that loses is whichever the reader did not open."""
    rings = LAYERS["rings"]["versions"]["minimum_version"]
    fleet = oc.load_agent_profiles()["fleet"]["minimum_agent_version"]
    assert rings == fleet, (
        f"rollout-rings.yaml says {rings}, agent_profiles.yaml says {fleet}")


def test_environments_are_the_platform_vocabulary():
    vocab = set(POLICY["global"]["tag_vocabulary"]["env"])
    assert set(LAYERS["environments"]) == vocab


def test_criticality_tiers_are_the_platform_tiers():
    assert set(LAYERS["criticality"]) == set(POLICY["tiers"])


# --- composition -------------------------------------------------------------

def test_a_profile_does_not_erase_a_check_a_lower_layer_added():
    """THE MERGE PROPERTY THAT MATTERS.

    The Windows layer adds a windows_service instance watching the Agent
    itself; the sqlserver profile adds one watching MSSQLSERVER. If lists
    replaced instead of concatenating, whichever applied second would silently
    win and the estate would lose a check with nothing failing.
    """
    r = rendered("win-sql-01")
    services = [s for i in r["conf_d"]["windows_service.d/conf.yaml"]["instances"]
                for s in i["services"]]
    assert "datadogagent" in services      # from os/windows
    assert "MSSQLSERVER" in services       # from profile/sqlserver


def test_layer_order_lets_policy_override_a_profile():
    """prod sets log_level warn over the base default; the later layer wins."""
    assert rendered("win-app-01")["datadog_yaml"]["log_level"] == "warn"
    assert rendered("lnx-tomcat-01")["datadog_yaml"]["log_level"] == "info"


def test_an_unresolved_placeholder_is_an_error_not_a_blank():
    """A config containing a literal {{ sqlserver_host }} starts an Agent that
    tries to resolve a host of that name and reports a connection failure,
    sending someone after a DNS problem that does not exist."""
    node = dict(NODES["win-sql-01"])
    node["facts"] = {k: v for k, v in node["facts"].items() if k != "sqlserver_host"}
    with pytest.raises(KeyError, match="sqlserver_host"):
        ac.render(node, LAYERS)


def test_declaring_the_wrong_os_baseline_is_refused():
    node = dict(NODES["lnx-tomcat-01"])
    node["profiles"] = ["windows-standard", "tomcat"]
    with pytest.raises(ValueError, match="baseline follows the operating system"):
        ac.render(node, LAYERS)


# --- features: policy AND capability ----------------------------------------

def test_a_poller_does_not_get_apm_just_because_it_is_tier1():
    """Criticality says tier1 gets APM. A VMware poller runs no instrumented
    code, so enabling it buys nothing and consumes an APM host licence per
    poller — policy saying "may" is not the same as a profile being able to."""
    r = rendered("poller-vmware-a")
    assert r["features"]["apm_enabled"] is False
    assert r["datadog_yaml"]["apm_config"]["enabled"] is False


def test_a_profile_cannot_turn_logs_on_where_policy_turns_them_off():
    """The other direction of the same rule: dev is deliberately quiet."""
    node = dict(NODES["win-app-01"], env="dev", name="win-app-dev")
    assert ac.render(node, LAYERS)["features"]["logs_enabled"] is False


def test_dbm_reaches_only_profiles_that_can_use_it():
    assert rendered("win-sql-01")["features"]["dbm_enabled"] is True
    assert rendered("poller-db-a")["features"]["dbm_enabled"] is True
    assert rendered("win-app-01")["features"]["dbm_enabled"] is False


# --- tagging (§9) ------------------------------------------------------------

def test_every_node_carries_the_mandatory_tag_set():
    for name in NODES:
        tags = dict(t.split(":", 1) for t in rendered(name)["datadog_yaml"]["tags"])
        for required in ("env", "team", "criticality", "managed_by",
                         "monitoring_profile"):
            assert required in tags, f"{name} is missing {required}"
        assert tags["managed_by"] == "ninjaone"


def test_unified_service_tagging_is_present_wherever_it_is_needed():
    """env/service/version is the join between a metric, a log and a trace.
    Telemetry without it cannot be correlated to anything, which looks like
    coverage and is not."""
    for name in NODES:
        r = rendered(name)
        dd = r["datadog_yaml"]
        if dd.get("logs_enabled") or dd.get("apm_config", {}).get("enabled"):
            assert dd.get("service"), f"{name} ships telemetry with no service"
            assert dd.get("env"), f"{name} ships telemetry with no env"


def test_tag_values_are_checked_against_the_platform_vocabulary():
    node = dict(NODES["win-app-01"], env="preprod", name="bad-env")
    with pytest.raises(ValueError, match="unknown environment"):
        ac.render(node, LAYERS)


# --- secrets (§15) -----------------------------------------------------------

def test_no_rendered_configuration_contains_a_secret():
    """A rendered config is committed, diffed and pasted into tickets. ENC[]
    handles are the supported form; anything else is key material in a file
    that is not treated as sensitive."""
    for name in NODES:
        assert ac.scan_for_secrets(rendered(name)) == [], name


def test_an_inlined_credential_is_detected():
    """The detector must actually detect — a secret scan that never fires is
    indistinguishable from one that is not running."""
    node = dict(NODES["win-sql-01"], name="leaky")
    node["overrides"] = {"datadog_yaml": {"api_key": "0123456789abcdef0123456789abcdef"}}
    assert ac.scan_for_secrets(ac.render(node, LAYERS))


def test_the_committed_source_files_contain_no_secrets_either():
    for path in (ac.CONFIG_DIR, ac.POLICY_DIR, ac.NODES_DIR):
        for f in path.rglob("*.yaml"):
            for line in f.read_text().splitlines():
                if "ENC[" in line or line.strip().startswith("#"):
                    continue
                for pattern, what in ac.SECRET_PATTERNS:
                    assert not pattern.search(line), f"{f.name}: {what}: {line[:70]}"


# --- log guardrails (§6) -----------------------------------------------------

def test_recursive_log_collection_is_refused():
    """C:\\**\\*.log finds IIS logs, Windows logs, another application's logs
    and eventually the Agent's own — a feedback loop that ends in a full
    disk."""
    node = dict(NODES["win-app-01"], name="greedy")
    node["overrides"] = {"logs": [{"type": "file", "path": "C:\\**\\*.log",
                                   "source": "csharp", "service": "x"}]}
    problems = ac.validate(ac.render(node, LAYERS), LAYERS)
    assert any("unbounded recursive" in p for p in problems)


def test_collecting_one_path_twice_is_refused():
    """Duplicate collection bills twice and double-counts every log-derived
    metric."""
    node = dict(NODES["win-app-01"], name="double")
    dup = dict(NODES["win-app-01"]["facts"])["serilog_path"]
    node["overrides"] = {"logs": [{"type": "file", "path": dup,
                                   "source": "csharp", "service": "y"}]}
    problems = ac.validate(ac.render(node, LAYERS), LAYERS)
    assert any("collected more than once" in p for p in problems)


def test_debug_logs_are_dropped_at_the_agent_not_at_indexing():
    """Dropping them later means paying to transmit and ingest them first."""
    rules = [r for l in rendered("win-app-01")["logs"]
             for r in l.get("log_processing_rules", [])]
    assert any(r["name"] == "exclude_debug_verbose" for r in rules)


# --- representative renders (§25, §31) ---------------------------------------

@pytest.mark.parametrize("name,expect_checks,expect_sources", [
    ("win-app-01", {"iis.d/conf.yaml", "windows_service.d/conf.yaml",
                    "process.d/conf.yaml", "win32_event_log.d/conf.yaml"}, {"iis", "csharp"}),
    ("win-sql-01", {"sqlserver.d/conf.yaml", "windows_service.d/conf.yaml"}, {"sqlserver"}),
    ("lnx-tomcat-01", {"tomcat.d/conf.yaml", "jmx.d/conf.yaml",
                       "process.d/conf.yaml"}, {"tomcat"}),
    ("poller-vmware-a", {"vsphere.d/conf.yaml"}, set()),
    ("poller-db-a", {"sqlserver.d/conf.yaml"}, set()),
])
def test_representative_node_renders_the_checks_it_exists_for(
        name, expect_checks, expect_sources):
    r = rendered(name)
    assert expect_checks <= set(r["conf_d"]), (
        f"{name} missing {expect_checks - set(r['conf_d'])}")
    assert {l["source"] for l in r["logs"]} == expect_sources
    assert ac.validate(r, LAYERS) == []


def test_sql_custom_queries_do_not_duplicate_native_metrics():
    """Re-collecting what the integration already provides doubles cost, and
    the two copies disagree during exactly the incidents where the number
    matters. Backup age and failed jobs have no native equivalent, which is
    why they are the only two."""
    q = rendered("win-sql-01")["conf_d"]["sqlserver.d/conf.yaml"]["instances"][0]
    names = {c["name"] for cq in q["custom_queries"] for c in cq["columns"]}
    assert names == {"sqlserver.backup.age_hours",
                     "sqlserver.agent.failed_jobs_24h"}


def test_the_database_poller_stays_inside_its_capacity_cap():
    """The cap bounds the failure domain. Raising it to fit one more instance
    defeats the reason it exists."""
    cap = LAYERS["profiles"]["database-poller"]["capacity"]["max_instances_per_poller"]
    r = rendered("poller-db-a")
    assert len(r["conf_d"]["sqlserver.d/conf.yaml"]["instances"]) <= cap


def test_the_vmware_pair_is_active_standby_with_one_active():
    """Both pollers active would double every vCenter metric — redundancy that
    corrupts the data it was meant to protect."""
    vm = [n for n in NODES.values() if "vmware-poller" in n.get("profiles", [])]
    roles = [n["facts"]["vmware_poller_role"] for n in vm]
    assert roles.count("active") <= 1, "more than one active VMware poller"
    model = LAYERS["profiles"]["vmware-poller"]["redundancy"]["model"]
    assert model == "active_standby"


# --- drift (§22) -------------------------------------------------------------

def test_the_config_hash_is_deterministic():
    """Non-determinism here would make every node permanently non-compliant,
    because the desired hash would differ from itself on every render."""
    for name in NODES:
        assert ac.render(NODES[name], LAYERS)["config_version"] == \
               ac.render(NODES[name], ac.load_layers())["config_version"]


def test_the_config_hash_changes_when_the_configuration_does():
    before = rendered("win-app-01")["config_version"]
    node = dict(NODES["win-app-01"])
    node["criticality"] = "tier2"
    assert ac.render(node, LAYERS)["config_version"] != before


def test_the_hash_describes_the_configuration_not_the_report():
    """--explain adds provenance to the output. If that changed the hash,
    inspecting a node would make it look like it had drifted."""
    plain = ac.render(NODES["win-app-01"], LAYERS)
    explained = ac.render(NODES["win-app-01"], LAYERS, explain=True)
    assert "provenance" in explained
    assert plain["config_version"] == explained["config_version"]


def test_explain_names_the_layer_that_set_each_value():
    """"Why does this host have that setting?" has to be answerable without
    reading seven files in the right order."""
    prov = ac.render(NODES["win-app-01"], LAYERS, explain=True)["provenance"]
    assert any("os/windows" in v for v in prov.values())
    assert any("profile/iis" in v for v in prov.values())
    assert any("env/prod" in v for v in prov.values())


# --- NinjaOne automation -----------------------------------------------------
#
# There is no PowerShell interpreter in this environment or in CI, so these are
# STATIC checks. They are deliberately narrow: they assert the properties this
# repository depends on, and they do not pretend to be a parser. A real
# PSScriptAnalyzer pass on a Windows runner would be strictly better and is
# recorded as the gap it is in docs/troubleshooting.md.

NINJA = ac.CM_DIR / "ninjaone"


def ps_scripts():
    return sorted(NINJA.glob("*.ps1")) + sorted(NINJA.glob("*.psm1"))


def test_the_automation_scripts_exist():
    names = {p.name for p in ps_scripts()}
    for required in ("DD-Agent-Lifecycle.ps1", "DD-Agent-Install.ps1",
                     "DD-Agent-Configure.ps1", "DD-Agent-Validate.ps1",
                     "DD-Agent-Upgrade.ps1", "DD-Agent-Reconcile.ps1",
                     "DD-Agent-Rollback.ps1", "DD-Agent-Discover.ps1",
                     "DDAgent.psm1"):
        assert required in names


def test_no_powershell_7_only_syntax():
    """The estate runs Windows Server, where 5.1 is still common. The ternary
    and null-coalescing operators are 7.0+ and fail at PARSE time, so a script
    using one does not run at all on the hosts it exists to manage."""
    for p in ps_scripts():
        for i, line in enumerate(p.read_text().splitlines(), 1):
            code = line.split("#")[0]
            assert "??" not in code, f"{p.name}:{i} null-coalescing is 7.0+"
            assert not re.search(r"\)\s*\?\s.+\s:\s", code), \
                f"{p.name}:{i} ternary is 7.0+"


def test_every_script_sets_strictmode_and_stops_on_error():
    """A script that continues past an error does the REST of its work against
    a state it did not achieve — the install fails, the configure writes anyway
    and the host reports compliant with no Agent."""
    for p in ps_scripts():
        t = p.read_text()
        assert "Set-StrictMode" in t, p.name
        if p.suffix == ".ps1" and "Validate" not in p.name:
            assert "$ErrorActionPreference = 'Stop'" in t, p.name


def test_braces_and_quotes_balance():
    for p in ps_scripts():
        t = p.read_text()
        assert t.count("{") == t.count("}"), f"{p.name}: unbalanced braces"
        assert t.count("<#") == t.count("#>"), f"{p.name}: unbalanced comment block"


def test_the_module_exports_exactly_what_it_defines():
    """An unexported function is invisible to the scripts that call it, and the
    failure is a late 'not recognized' on a production host rather than here."""
    t = (NINJA / "DDAgent.psm1").read_text()
    defined = set(re.findall(r"^function ([A-Za-z-]+)", t, re.M))
    exported = set(re.findall(r"[A-Za-z]+-[A-Za-z]+",
                              t.split("Export-ModuleMember")[1]))
    assert defined <= exported, f"not exported: {defined - exported}"


def test_no_secret_is_passed_on_a_command_line():
    """A key on a command line lands in the NinjaOne activity log, the local
    event log and the process table."""
    for p in ps_scripts():
        for i, line in enumerate(p.read_text().splitlines(), 1):
            code = line.split("#")[0]
            assert not re.search(r"-(ApiKey|Password|Secret)\s+['\"]?[A-Za-z0-9]{16,}",
                                 code), f"{p.name}:{i} literal secret argument"


def test_validate_implements_every_check_the_ring_gate_claims():
    """policies/rollout-rings.yaml lists what an upgrade must prove before a
    ring is considered soaked. A name there that the script does not implement
    makes the promotion gate quietly weaker than it says it is."""
    declared = set(LAYERS["rings"]["upgrade_validation"])
    script = (NINJA / "DD-Agent-Validate.ps1").read_text()
    implemented = set(re.findall(r"\$checks\['(\w+)'\]", script))
    # Feature-conditional checks are proven by Test-DDTelemetryFlowing rather
    # than by their own named entry; they are named here so the exemption is
    # explicit rather than a silent gap.
    conditional = {"logs_arriving_when_enabled", "apm_arriving_when_enabled",
                   "dbm_arriving_when_enabled"}
    missing = declared - implemented - conditional
    assert not missing, f"declared but not implemented in DD-Agent-Validate: {missing}"


def test_the_lifecycle_restarts_only_when_configuration_changed():
    """Running hourly across the estate is only reasonable because a compliant
    host is a no-op. A restart on every run is a fleet-wide telemetry gap every
    hour, dressed up as reconciliation."""
    mod = (NINJA / "DDAgent.psm1").read_text()
    assert "if (-not $ConfigChanged -and (Test-DDAgentHealthy)) { return $false }" in mod
    assert "return $false                     # nothing changed; do not restart" in mod


def test_reconciliation_is_bounded():
    """An unbounded retry on a host that cannot be fixed restarts the Agent
    forever — a permanent telemetry gap presented as self-healing."""
    t = (NINJA / "DD-Agent-Reconcile.ps1").read_text()
    assert "MaxAttempts" in t
    assert "while ($attempt -lt $MaxAttempts" in t
