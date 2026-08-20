"""GIT-YAML PLANE — the ONLY way a change leaves this server.

    MCP → YAML → branch → commit → push → pull request → CI → Terraform → Datadog

Every step after "pull request" already exists and is not weakened here: the
same ci.yml gate, the same offline plan, the same credentialed monitor
validation, the same promotion through qa → stage → production behind the
`datadog-production` approval environment. What this module adds is only the
first three arrows.

FOUR CONSTRAINTS, each of which came from a specific way this could go wrong:

  1. NEVER TOUCH THE CALLER'S WORKING TREE. All work happens in a dedicated
     `git worktree` under generated/ (gitignored). An agent that leaves
     uncommitted edits in somebody's checkout has broken their day.
  2. DRY RUN IS THE DEFAULT. `apply=False` computes the branch name, the file
     set and the diff and writes nothing. A dry run is not a promise that the
     real run will succeed — it is the thing you read before allowing one.
  3. NEVER PUSH TO A PROTECTED BRANCH. The base branch is read, never written;
     the target branch name is generated and refused if it resolves to the
     default branch.
  4. THE WRITE FENCE IS RE-CHECKED HERE. obs_act.assert_writable already ran at
     generation time; it runs again at write time, because the file set can be
     assembled by a caller that never called the generator.
"""
from __future__ import annotations

import datetime as dt
import re
import shutil
import subprocess
from pathlib import Path

import obs_act
from obs_state import REPO_ROOT

BRANCH_PREFIX = "mcp/"
DEFAULT_WORKTREE_ROOT = REPO_ROOT / "generated" / "mcp" / "worktrees"
PROTECTED_BRANCHES = {"main", "master", "tfstate"}


class GitOpsError(Exception):
    pass


def _git(args: list[str], cwd: Path, check: bool = True) -> str:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise GitOpsError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", str(text).lower()).strip("-")
    return (slug or "change")[:48]


def branch_name(subject: str, principal_id: str, when: dt.datetime | None = None) -> str:
    """Deterministic, greppable, and namespaced so it is obvious who opened it."""
    when = when or dt.datetime.now(dt.timezone.utc)
    return f"{BRANCH_PREFIX}{when:%Y%m%d}-{slugify(subject)}-{slugify(principal_id)}"


def insert_yaml_block(text: str, parent_key: str, block: str) -> str:
    """Append `block` at the END of a top-level YAML section, in place.

    Used for platform/policy/slos.yaml, where the new objective must land
    inside `slos:` and NOT after `tier0_slo_template:` further down the file.
    Purely textual on purpose: round-tripping the file through PyYAML would
    delete every comment in it, and the comments in that file are the design
    rationale a reviewer needs.
    """
    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines)
                  if ln.startswith(f"{parent_key}:")), None)
    if start is None:
        raise GitOpsError(f"no top-level `{parent_key}:` key to insert under")
    end = len(lines)
    for i in range(start + 1, len(lines)):
        ln = lines[i]
        if ln.strip() and not ln[0].isspace() and not ln.lstrip().startswith("#"):
            end = i
            break
    # Comment/blank lines immediately above the next section introduce THAT
    # section, so the insert goes above them.
    while end - 1 > start and (not lines[end - 1].strip()
                               or lines[end - 1].lstrip().startswith("#")):
        end -= 1
    if not block.endswith("\n"):
        block += "\n"
    return "".join(lines[:end]) + block + "".join(lines[end:])


def _apply_files(tree: Path, files: dict[str, str]) -> list[dict]:
    """Write the change set into a worktree. Returns per-file operations."""
    ops = []
    for rel, content in sorted(files.items()):
        obs_act.assert_writable(rel)                # fence, re-checked at write time
        target = tree / rel
        if rel in obs_act.ALLOWED_INSERT_TARGETS:
            key = obs_act.ALLOWED_INSERT_TARGETS[rel]
            existing = target.read_text()
            target.write_text(insert_yaml_block(existing, key, content))
            ops.append({"path": rel, "operation": "insert", "under": key,
                        "bytes_added": len(content)})
            continue
        existed = target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        ops.append({"path": rel, "operation": "modify" if existed else "create",
                    "bytes": len(content)})
    return ops


def _default_branch(repo: Path) -> str:
    head = _git(["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
                repo, check=False).strip()
    if head:
        return head.split("/", 1)[-1]
    return "main"


def propose(*, files: dict[str, str], subject: str, body: str, principal_id: str,
            repo_root: Path | None = None, base: str | None = None,
            apply: bool = False, push: bool = False,
            worktree_root: Path | None = None,
            approval: dict | None = None) -> dict:
    """Create the branch, commit the change set, and (optionally) open the PR.

    `apply=False` (the default) is a genuine dry run: it resolves the branch
    name, re-checks the fence on every path, renders the commit message and the
    PR body, and returns them WITHOUT creating a branch, a worktree, a commit
    or a remote reference. Nothing on disk changes.
    """
    repo = Path(repo_root or REPO_ROOT)
    if not files:
        raise GitOpsError("no files in the change set")
    for rel in files:
        obs_act.assert_writable(rel)

    base = base or _default_branch(repo)
    branch = branch_name(subject, principal_id)
    if branch in PROTECTED_BRANCHES or branch == base:
        raise GitOpsError(f"refusing to write to protected branch {branch!r}")

    commit_message = (
        f"{subject}\n\n{body.strip()}\n\n"
        f"Proposed through the observability MCP server by principal `{principal_id}`.\n"
        f"Files are constrained to the Act-mode write fence (mcp/obs_act.py).\n"
        + (f"Approved for production by `{approval.get('approver')}` "
           f"(change record {approval.get('ticket')}).\n" if approval and approval.get("required")
           else ""))

    pr_body = _pr_body(files, body, principal_id, approval)
    result = {
        "dry_run": not apply,
        "branch": branch, "base": base,
        "files": sorted(files),
        "commit_message": commit_message,
        "pull_request_body": pr_body,
        "pushed": False, "pull_request_url": None,
    }
    if not apply:
        result["note"] = ("DRY RUN — no branch, worktree, commit or remote reference was "
                          "created. Re-run with dry_run=false to open the pull request.")
        return result

    root = Path(worktree_root or DEFAULT_WORKTREE_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    tree = root / branch.replace("/", "__")
    if tree.exists():
        shutil.rmtree(tree)
    _git(["worktree", "add", "-b", branch, str(tree), base], repo)
    try:
        result["operations"] = _apply_files(tree, files)
        _git(["add", "--", *sorted(files)], tree)
        status = _git(["status", "--porcelain"], tree).strip()
        if not status:
            result["note"] = "the change set is identical to the base branch; nothing to commit"
            return result
        _git(["-c", "user.name=observability-mcp",
              "-c", "user.email=o11y@acme.example",
              "commit", "-m", commit_message], tree)
        result["commit"] = _git(["rev-parse", "HEAD"], tree).strip()
        result["diffstat"] = _git(["show", "--stat", "--oneline", "HEAD"], tree)
        if push:
            _git(["push", "-u", "origin", branch], tree)
            result["pushed"] = True
            result.update(_open_pull_request(tree, branch, base, subject, pr_body))
        else:
            result["note"] = (
                "committed on a local branch; push=false. To finish: "
                f"`git push -u origin {branch}` then "
                f"`gh pr create --base {base} --head {branch} --title {subject!r}`")
    finally:
        # The worktree is scratch space, not state. Leaving it behind would let
        # a second call collide with a stale checkout of the same branch.
        _git(["worktree", "remove", "--force", str(tree)], repo, check=False)
    return result


def _open_pull_request(tree: Path, branch: str, base: str, title: str, body: str) -> dict:
    """Open the PR with `gh` when it exists; otherwise hand back the command.

    Deliberately not an API call with a token this server holds: the pull
    request should be attributable to the operator's own GitHub identity, and
    `gh` already carries it.
    """
    if not shutil.which("gh"):
        return {"pull_request_url": None,
                "pull_request_command": (
                    f"gh pr create --base {base} --head {branch} "
                    f"--title {title!r} --body-file -")}
    proc = subprocess.run(
        ["gh", "pr", "create", "--base", base, "--head", branch,
         "--title", title, "--body", body],
        cwd=str(tree), capture_output=True, text=True)
    if proc.returncode != 0:
        return {"pull_request_url": None,
                "pull_request_error": proc.stderr.strip()[:500]}
    return {"pull_request_url": proc.stdout.strip().splitlines()[-1]}


def _pr_body(files: dict[str, str], rationale: str, principal_id: str,
             approval: dict | None) -> str:
    lines = [
        "## What this changes",
        "",
        rationale.strip(),
        "",
        "## Files",
        "",
    ]
    for rel in sorted(files):
        op = "insert into" if rel in obs_act.ALLOWED_INSERT_TARGETS else "write"
        lines.append(f"- `{rel}` ({op})")
    lines += [
        "",
        "## How this was produced",
        "",
        f"Opened by the observability MCP server on behalf of `{principal_id}`.",
        "",
        "- Act mode cannot write to Datadog. This pull request is the only exit path.",
        "- The file set was checked against the Act-mode write fence "
        "(`mcp/obs_act.py`): `platform/entities/`, `platform/monitors/`, "
        "`platform/runbooks/` and an anchored insert into `platform/policy/slos.yaml`.",
        "- A plan was run before this was proposed; `obs.propose_change` refuses a "
        "change set whose content hash does not match a plan from this session.",
        "",
        "## What still has to happen",
        "",
        "`ci.yml` runs the full gate (YAML/schema, pytest, terraform fmt/validate, the "
        "offline plan with every precondition and budget check, plan determinism, Trivy "
        "and gitleaks, and a credentialed plan whose monitors Datadog itself validates). "
        "Merging promotes to qa then stage automatically; production remains an explicit "
        "`deploy.yml` dispatch behind the `datadog-production` approval environment.",
    ]
    if approval and approval.get("required"):
        lines += ["", "## Production approval", "",
                  f"Approved by `{approval.get('approver')}` "
                  f"({approval.get('approver_role')}), change record "
                  f"`{approval.get('ticket')}`."]
    return "\n".join(lines) + "\n"
