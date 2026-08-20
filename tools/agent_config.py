#!/usr/bin/env python3
"""DATADOG AGENT CONFIGURATION RENDERER — layers in, one config out.

The thing this prevents is ten thousand hand-written datadog.yaml files. A node
declares a handful of facts; the configuration is COMPOSED from layers that are
each reviewed once and reused everywhere:

    base -> os -> profile(s) -> environment -> criticality -> node -> exception

Every layer may add keys and may override a key a lower layer set. Nothing
reaches back down. That ordering is the whole design: it means "what does prod
change?" is answerable by reading one file, and "why does this host have that
setting?" is answerable by rendering it with --explain.

WHY A RENDERER AND NOT TEMPLATES PER HOST. A template per host is a file per
host, which is the sprawl this exists to avoid. Composition means adding the
next server changes no file at all — it declares facts and inherits config.

THE OUTPUT IS DETERMINISTIC AND HASHED. Same inputs produce byte-identical
output, so `config_version` is a sha256 of the rendered bytes and drift
detection is a string comparison rather than a semantic diff. Non-determinism
here (dict ordering, a timestamp, a random default) would make every node
permanently non-compliant, so the hash is computed over sorted, canonical YAML.

WHAT THIS DOES NOT DO. It does not decide WHICH profile a node gets — that is
platform/policy/agent_profiles.yaml, which already resolves profiles from host
facts and is the catalog the whole platform shares. Duplicating that decision
here would create two answers to one question.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import obs_common as oc                                   # noqa: E402

CM_DIR = oc.REPO_ROOT / "configuration-management" / "datadog-agent"
CONFIG_DIR = CM_DIR / "config"
POLICY_DIR = CM_DIR / "policies"
NODES_DIR = CM_DIR / "nodes"

# `windows-standard` / `linux-standard` are the names the operator-facing
# interface uses, but the OS layer is chosen by the node's `os` fact so a
# Windows node cannot declare the Linux baseline. Accepting the alias and
# checking it agrees is friendlier than rejecting the word people will type.
OS_ALIASES = {"windows-standard": "windows", "linux-standard": "linux"}

# A rendered config is committed, diffed and pasted into tickets, so it must
# never contain key material. These are the shapes that mean "someone inlined a
# secret"; ENC[...] handles are the supported form and are explicitly allowed.
SECRET_PATTERNS = [
    (re.compile(r"\b[a-f0-9]{32}\b"), "32-hex string (Datadog API key shape)"),
    (re.compile(r"\b[a-f0-9]{40}\b"), "40-hex string (Datadog app key shape)"),
    (re.compile(r"(?i)(password|passwd|secret|api_?key|app_?key)\s*:\s*(?!ENC\[)['\"]?[^\s'\"{}]{8,}"),
     "inline credential"),
]


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


# -----------------------------------------------------------------------------
# merge
# -----------------------------------------------------------------------------
def deep_merge(base: dict, overlay: dict, *, path: str = "",
               provenance: dict | None = None, layer: str = "") -> dict:
    """Overlay wins on scalars; lists CONCATENATE; dicts recurse.

    Lists concatenate rather than replace, and that is a deliberate asymmetry
    worth stating. A profile adding a `windows_service` instance must not erase
    the one the OS layer added, or composing two profiles would silently drop
    whichever was applied first — the single most likely way for this system to
    lose a check without anyone noticing. Scalars replace because "prod uses
    warn instead of info" is exactly the override the layering is for.
    """
    out = copy.deepcopy(base)
    for key, value in overlay.items():
        here = f"{path}.{key}" if path else key
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = deep_merge(out[key], value, path=here,
                                  provenance=provenance, layer=layer)
        elif key in out and isinstance(out[key], list) and isinstance(value, list):
            merged = out[key] + [v for v in value if v not in out[key]]
            out[key] = merged
            if provenance is not None:
                provenance.setdefault(here, []).append(f"{layer} (appended)")
        else:
            out[key] = copy.deepcopy(value)
            if provenance is not None:
                provenance.setdefault(here, []).append(layer)
    return out


def substitute(obj, facts: dict):
    """Replace {{ fact }} placeholders from the node's declared facts.

    An unresolved placeholder is an ERROR, not a blank. A config containing a
    literal `{{ sqlserver_host }}` starts an Agent that connects to a host of
    that name, fails, and reports a connection error that sends someone hunting
    for a DNS problem that does not exist.
    """
    if isinstance(obj, dict):
        return {k: substitute(v, facts) for k, v in obj.items()}
    if isinstance(obj, list):
        return [substitute(v, facts) for v in obj]
    if isinstance(obj, str):
        m = re.fullmatch(r"\{\{\s*(\w+)\s*\}\}", obj)
        if m:                                  # whole-value: keep the real type
            if m.group(1) not in facts:
                raise KeyError(f"unresolved placeholder {{{{ {m.group(1)} }}}}")
            return facts[m.group(1)]

        def one(mo):
            if mo.group(1) not in facts:
                raise KeyError(f"unresolved placeholder {{{{ {mo.group(1)} }}}}")
            return str(facts[mo.group(1)])
        return re.sub(r"\{\{\s*(\w+)\s*\}\}", one, obj)
    return obj


# -----------------------------------------------------------------------------
# layers
# -----------------------------------------------------------------------------
def load_layers() -> dict:
    return {
        "base": _yaml(CONFIG_DIR / "base.yaml"),
        "os": {p.stem: _yaml(p) for p in sorted((CONFIG_DIR / "os").glob("*.yaml"))},
        "profiles": {p.stem: _yaml(p)
                     for p in sorted((CONFIG_DIR / "profiles").glob("*.yaml"))},
        "environments": _yaml(POLICY_DIR / "environments.yaml")["environments"],
        "criticality": _yaml(POLICY_DIR / "criticality.yaml")["criticality"],
        "rings": _yaml(POLICY_DIR / "rollout-rings.yaml"),
        "secrets": _yaml(POLICY_DIR / "secrets.yaml"),
    }


def resolve_profiles(node: dict) -> tuple[str, list[str]]:
    """(os_layer, workload_profiles) from the node's declaration."""
    os_name = node["os"]
    workloads = []
    for p in node.get("profiles", []):
        if p in OS_ALIASES:
            if OS_ALIASES[p] != os_name:
                raise ValueError(
                    f"node {node['name']}: declares profile {p!r} but os is "
                    f"{os_name!r} — the baseline follows the operating system, "
                    f"so these can never disagree")
            continue                                   # the OS layer covers it
        workloads.append(p)
    return os_name, workloads


def render(node: dict, layers: dict | None = None, *, explain: bool = False) -> dict:
    layers = layers or load_layers()
    os_name, workloads = resolve_profiles(node)
    prov: dict = {} if explain else None

    env = node["env"]
    tier = node["criticality"]
    if env not in layers["environments"]:
        raise ValueError(f"node {node['name']}: unknown environment {env!r}")
    if tier not in layers["criticality"]:
        raise ValueError(f"node {node['name']}: unknown criticality {tier!r}")

    acc = {"datadog_yaml": {}, "conf_d": {}, "logs": []}

    def apply(fragment: dict, layer: str):
        nonlocal acc
        for key in ("datadog_yaml", "conf_d", "logs"):
            if key in fragment:
                acc = deep_merge(acc, {key: fragment[key]},
                                 provenance=prov, layer=layer)

    apply(layers["base"], "base")
    if os_name not in layers["os"]:
        raise ValueError(f"node {node['name']}: no OS layer for {os_name!r}")
    apply(layers["os"][os_name], f"os/{os_name}")

    for p in workloads:
        if p not in layers["profiles"]:
            raise ValueError(f"node {node['name']}: unknown profile {p!r} "
                             f"(have: {', '.join(sorted(layers['profiles']))})")
        apply(layers["profiles"][p], f"profile/{p}")

    env_layer = layers["environments"][env]
    apply(env_layer, f"env/{env}")
    tier_layer = layers["criticality"][tier]
    apply(tier_layer, f"criticality/{tier}")

    # FEATURE SWITCHES resolve last, from TWO independent sources that must
    # both agree:
    #
    #   policy  (environment, criticality) — is this feature ALLOWED here?
    #   profile (`supports:`)              — can anything here USE it?
    #
    # Policy alone is not enough. Criticality says tier1 gets APM, which is
    # right for an application server and wrong for a VMware poller: the poller
    # runs no instrumented code, so enabling APM buys nothing and consumes an
    # APM host licence per poller. Requiring a profile to claim the feature is
    # what stops a policy default from spending money on hosts that cannot use
    # it.
    #
    # A profile saying "logs on" is still not sufficient on its own either —
    # that would turn logs on in dev, where the environment layer deliberately
    # turns them off.
    usable = set()
    for frag in [layers["os"][os_name]] + [layers["profiles"][p] for p in workloads]:
        usable |= set(frag.get("supports") or [])

    feature = {}
    for key, short, dd_key in (("logs_enabled", "logs", "logs_enabled"),
                               ("apm_enabled", "apm", None),
                               ("dbm_enabled", "dbm", None)):
        allowed = tier_layer.get(key, env_layer.get(key))
        if allowed is None:
            continue
        val = bool(allowed) and short in usable
        feature[key] = val
        if dd_key:
            acc["datadog_yaml"][dd_key] = val
    if "apm_enabled" in feature:
        acc["datadog_yaml"].setdefault("apm_config", {})["enabled"] = feature["apm_enabled"]

    apply(node.get("overrides", {}), "node")

    facts = dict(node.get("facts", {}))
    facts.update({
        "service": node.get("service", node["name"]),
        "env": env,
        "node_tags": "",                       # replaced by the tag block below
        "dbm_enabled": feature.get("dbm_enabled", False),
    })
    acc = substitute(acc, facts)

    acc["datadog_yaml"]["tags"] = build_tags(node)
    acc["datadog_yaml"]["hostname"] = node["name"]
    if node.get("service"):
        acc["datadog_yaml"]["env"] = env
        acc["datadog_yaml"]["service"] = node["service"]
    if node.get("version"):
        acc["datadog_yaml"]["version"] = node["version"]

    rendered = {
        "node": node["name"],
        "os": os_name,
        "profiles": workloads,
        "datadog_yaml": acc["datadog_yaml"],
        "conf_d": acc["conf_d"],
        "logs": acc["logs"],
        "features": feature,
    }
    rendered["config_version"] = config_hash(rendered)
    if explain:
        rendered["provenance"] = {k: v for k, v in sorted(prov.items())}
    return rendered


def build_tags(node: dict) -> list[str]:
    """The standard tag set (§9), from the node and from nothing else.

    Tag KEYS are not invented here: they come from platform/policy/global.yaml,
    which is the same vocabulary the monitors, SLOs and Service Catalog use. A
    key list maintained in two places is how `resource_type` on a monitor stops
    matching `resource_type` on a host.
    """
    tags = {
        "env": node["env"],
        "team": node["team"],
        "criticality": node["criticality"],
        "managed_by": "ninjaone",
        "monitoring_profile": ",".join(node.get("profiles", [])) or "base",
    }
    for optional in ("service", "version", "platform", "resource_type",
                     "resource_class", "application", "business_unit", "region",
                     "location", "subscription", "resource_group", "cost_center",
                     "data_classification", "support_model", "owner"):
        if node.get(optional):
            tags[optional] = node[optional]
    return [f"{k}:{v}" for k, v in sorted(tags.items())]


def config_hash(rendered: dict) -> str:
    """sha256 over the canonical form — the drift primitive (§22).

    Deliberately excludes `config_version` itself and any provenance, so the
    hash describes the CONFIGURATION and not the report about it.
    """
    payload = {k: v for k, v in rendered.items()
               if k not in ("config_version", "provenance")}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


# -----------------------------------------------------------------------------
# validation
# -----------------------------------------------------------------------------
def scan_for_secrets(rendered: dict) -> list[str]:
    text = yaml.safe_dump(rendered, sort_keys=True)
    found = []
    for line in text.splitlines():
        if "ENC[" in line:
            continue                    # the supported form, by design
        for pattern, what in SECRET_PATTERNS:
            if pattern.search(line):
                found.append(f"{what}: {line.strip()[:80]}")
    return found


def validate(rendered: dict, layers: dict | None = None) -> list[str]:
    layers = layers or load_layers()
    policy = oc.load_policy()
    problems: list[str] = []
    node = rendered["node"]

    for s in scan_for_secrets(rendered):
        problems.append(f"{node}: possible secret in rendered config — {s}")

    tags = dict(t.split(":", 1) for t in rendered["datadog_yaml"]["tags"] if ":" in t)
    vocab = policy["global"]["tag_vocabulary"]
    for key in ("env", "criticality"):
        vkey = "tier" if key == "criticality" else key
        if key in tags and vkey in vocab and tags[key] not in vocab[vkey]:
            problems.append(f"{node}: {key}={tags[key]!r} is not in the "
                            f"platform tag vocabulary {vocab[vkey]}")
    if tags.get("team") and tags["team"] not in policy["teams"]:
        problems.append(f"{node}: team {tags['team']!r} is not in teams.yaml")

    # Unified service tagging is the join between metrics, logs and traces. A
    # node that ships logs or traces without it produces telemetry that cannot
    # be correlated to anything, which looks like coverage and is not.
    dd = rendered["datadog_yaml"]
    if (dd.get("logs_enabled") or dd.get("apm_config", {}).get("enabled")) \
            and not dd.get("service"):
        problems.append(f"{node}: logs or APM enabled without `service` — the "
                        f"telemetry cannot be joined to anything")

    # Duplicate log paths bill twice and double-count every log-derived metric.
    paths = [l.get("path") for l in rendered["logs"] if l.get("path")]
    for p in {x for x in paths if paths.count(x) > 1}:
        problems.append(f"{node}: log path collected more than once: {p}")

    guard = layers["profiles"].get("serilog", {}).get("guardrails", {})
    for pattern in guard.get("forbid_path_patterns", []):
        for p in paths:
            if re.search(pattern, p):
                problems.append(f"{node}: log path {p!r} is an unbounded "
                                f"recursive pattern — it will eventually "
                                f"collect the Agent's own log")
    if guard.get("max_log_sources_per_node") and \
            len(rendered["logs"]) > guard["max_log_sources_per_node"]:
        problems.append(f"{node}: {len(rendered['logs'])} log sources exceeds "
                        f"the cap of {guard['max_log_sources_per_node']}")

    # Co-location rules for poller roles: a browser-test burst that starves a
    # vSphere collection produces a VMware outage that looks like vCenter's.
    spl = layers["profiles"].get("synthetic-private-location", {})
    forbid = set(spl.get("guardrails", {}).get("forbid_colocation_with", []))
    if "synthetic-private-location" in rendered["profiles"]:
        clash = forbid & set(rendered["profiles"])
        if clash:
            problems.append(f"{node}: private-location worker co-located with "
                            f"{sorted(clash)} — validate capacity first")

    for name, conf in rendered["conf_d"].items():
        if not isinstance(conf, dict) or "instances" not in conf:
            problems.append(f"{node}: {name} has no `instances` block")
    return problems


# -----------------------------------------------------------------------------
def load_nodes() -> list[dict]:
    return [_yaml(p)["node"] for p in sorted(NODES_DIR.glob("*.yaml"))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--node", help="render one node by name; default is all")
    ap.add_argument("--explain", action="store_true",
                    help="show which layer set each key")
    ap.add_argument("--out-dir", type=Path,
                    help="write rendered datadog.yaml + conf.d per node")
    ap.add_argument("--check", action="store_true",
                    help="validate only; non-zero exit on any problem")
    args = ap.parse_args()

    layers = load_layers()
    nodes = [n for n in load_nodes() if not args.node or n["name"] == args.node]
    if not nodes:
        print(f"no node matched {args.node!r}", file=sys.stderr)
        return 1

    problems, rendered_all = [], []
    for node in nodes:
        r = render(node, layers, explain=args.explain)
        rendered_all.append(r)
        problems += validate(r, layers)
        if args.out_dir:
            d = args.out_dir / node["name"]
            (d / "conf.d").mkdir(parents=True, exist_ok=True)
            (d / "datadog.yaml").write_text(
                yaml.safe_dump(r["datadog_yaml"], sort_keys=True))
            for name, conf in r["conf_d"].items():
                p = d / "conf.d" / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(yaml.safe_dump(conf, sort_keys=True))

    if not args.check:
        print(yaml.safe_dump(rendered_all, sort_keys=False, width=100))
    for p in problems:
        print(f"AGENT CONFIG: {p}", file=sys.stderr)
    print(f"rendered {len(rendered_all)} node(s), {len(problems)} problem(s)",
          file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
