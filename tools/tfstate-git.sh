#!/usr/bin/env bash
# =============================================================================
# GIT-BACKED TERRAFORM STATE (ADR-016)
#
# State lives on the orphan branch `tfstate` of THIS repository, one file per
# stack × environment:
#
#   foundation/prod.tfstate
#   coverage/qa.tfstate  coverage/stage.tfstate  coverage/prod.tfstate
#
# Terraform itself always runs with the default LOCAL backend; this script
# moves state between the branch and the stack directory around each run,
# using git plumbing only — nothing is ever checked out, so it cannot
# interact with the working tree or .gitignore. The guarantees a remote
# backend provides map to:
#
#   LOCKING      GitHub Actions `concurrency: tfstate` serialises every
#                workflow that touches state (deploy + governance). Persist
#                pushes fast-forward only and rebuilds on the new parent
#                before retrying, so a lost race can never overwrite another
#                run's commit.
#   VERSIONING   every apply is one commit on `tfstate` — full history,
#                point-in-time recovery with `git show <sha>:<file>`.
#   ENCRYPTION   GitHub encrypts repository content at rest; the repository
#                is private. State must still never contain secrets — the
#                Datadog provider keeps credentials in env vars, not state.
#   SEPARATION   one state file per environment; promotion never rewrites
#                another environment's state.
#
# Usage:
#   tfstate-git.sh restore <stack> <env>   # branch → stacks/<stack>/terraform.tfstate
#   tfstate-git.sh persist <stack> <env>   # stacks/<stack>/terraform.tfstate → branch
# =============================================================================
set -euo pipefail

CMD="${1:?restore|persist}" STACK="${2:?stack}" ENVNAME="${3:?env}"
REPO_ROOT="$(git rev-parse --show-toplevel)"
BRANCH="tfstate"
REMOTE_REF="refs/remotes/origin/$BRANCH"
STATE_PATH="$STACK/$ENVNAME.tfstate"
STATE_LOCAL="$REPO_ROOT/stacks/$STACK/terraform.tfstate"
export GIT_DIR="$REPO_ROOT/.git"

fetch_branch() {
  git fetch origin "+refs/heads/$BRANCH:$REMOTE_REF" 2>/dev/null || return 1
}

case "$CMD" in
  restore)
    if fetch_branch && git cat-file -e "$REMOTE_REF:$STATE_PATH" 2>/dev/null; then
      git cat-file blob "$REMOTE_REF:$STATE_PATH" > "$STATE_LOCAL"
      echo "restored $STATE_PATH ($(wc -c < "$STATE_LOCAL") bytes)"
    else
      rm -f "$STATE_LOCAL"
      echo "no state yet for $STATE_PATH — first apply will create it"
    fi
    ;;
  persist)
    [ -f "$STATE_LOCAL" ] || { echo "nothing to persist: $STATE_LOCAL missing" >&2; exit 1; }
    blob=$(git hash-object -w "$STATE_LOCAL")
    for delay in 0 2 4 8 16; do
      sleep "$delay"
      parent=""
      if fetch_branch; then
        parent=$(git rev-parse "$REMOTE_REF")
        if [ "$(git rev-parse --quiet --verify "$REMOTE_REF:$STATE_PATH" || true)" = "$blob" ]; then
          echo "state unchanged for $STATE_PATH — nothing to push"
          exit 0
        fi
      fi
      # Build the new tree on top of the current branch tip (or empty).
      export GIT_INDEX_FILE="$REPO_ROOT/.git/tfstate-index.$$"
      rm -f "$GIT_INDEX_FILE"
      [ -n "$parent" ] && git read-tree "$parent"
      git update-index --add --cacheinfo "100644,$blob,$STATE_PATH"
      tree=$(git write-tree)
      rm -f "$GIT_INDEX_FILE"; unset GIT_INDEX_FILE
      commit=$(git commit-tree "$tree" ${parent:+-p "$parent"} \
        -m "tfstate: $STACK/$ENVNAME @ $(git rev-parse --short HEAD)")
      # Fast-forward-only push: a concurrent writer loses nothing — we
      # re-fetch and rebuild on the new parent, then try again.
      if git push origin "$commit:refs/heads/$BRANCH" 2>/dev/null; then
        echo "persisted $STATE_PATH ($commit)"
        exit 0
      fi
      echo "push raced — rebuilding on new tip" >&2
    done
    echo "ERROR: could not push state for $STATE_PATH" >&2
    exit 1
    ;;
  *) echo "unknown command: $CMD" >&2; exit 2 ;;
esac
