TF ?= terraform
PY ?= python3
STACKS := stacks/coverage stacks/foundation
MODULES := $(wildcard modules/*)

.PHONY: setup fmt fmt-check validate test tf-validate matrix runbooks fixtures \
        inventory coverage reports reports-live plan-offline clean

# --- developer entry points --------------------------------------------------
setup:
	$(PY) -m venv .venv
	.venv/bin/pip install -r tools/requirements-dev.txt
	for d in $(MODULES) $(STACKS); do (cd $$d && $(TF) init -backend=false -input=false >/dev/null); done

## validate — the same offline gate CI runs (YAML/schema/pytest live inside
## the test suite; credentialed stages only run in CI).
validate: fmt-check test tf-validate

fmt:
	$(TF) fmt -recursive
fmt-check:
	$(TF) fmt -recursive -check

test:              ## policy lint, manifests, runbooks, generated docs, scorecard, scale
	$(PY) -m pytest tests/ -q

tf-validate:
	for d in $(MODULES) $(STACKS); do echo "== $$d"; (cd $$d && $(TF) validate) || exit 1; done

# --- regeneration ------------------------------------------------------------
matrix:            ## regenerate docs/monitor-coverage-matrix.md
	cd tools && $(PY) generate_matrix.py
runbooks:          ## regenerate runbook drafts from the archetype catalog
	cd tools && $(PY) generate_runbooks.py --report
fixtures:          ## regenerate tests/fixtures/monitors_planned.json from an offline plan
	cd stacks/coverage && DD_API_KEY=offline DD_APP_KEY=offline $(TF) plan -input=false \
		-var datadog_validate=false -out=plan.out && $(TF) show -json plan.out > plan.json
	cd tools && $(PY) refresh_fixtures.py ../stacks/coverage/plan.json

# --- terraform ---------------------------------------------------------------
## plan-offline — no credentials; exercises every precondition and budget check.
## Plans and applies against the live org happen ONLY in .github/workflows/
## deploy.yml, which restores/persists git-backed state (ADR-016) around each
## step — a local apply would run against empty state and duplicate the estate.
plan-offline:
	cd stacks/coverage && DD_API_KEY=offline DD_APP_KEY=offline $(TF) plan -input=false \
		-var datadog_validate=false
	cd stacks/foundation && DD_API_KEY=offline DD_APP_KEY=offline $(TF) plan -input=false \
		-var datadog_validate=false -var manage_rbac=false

# --- operations (credentialed; svc-observability keys, never personal) -------
inventory:         ## rebuild the inventory and reassign profiles
	cd tools && $(PY) build_inventory.py --live && $(PY) profile_engine.py
coverage:          ## coverage & compliance report against the live org
	cd tools && $(PY) coverage_report.py --live

# --- reports (offline by default; §34) ---------------------------------------
## reports — the five report families. Offline against tests/fixtures so it runs
## in a pull request with no credentials; `make reports-live` for the runtime
## half (never-triggered, noisy, flapping) that only the running estate answers.
reports:
	cd tools && $(PY) reports.py --fixtures ../tests/fixtures
reports-live:      ## report families against the live org (credentialed)
	cd tools && $(PY) reports.py --live

clean:
	find . -name ".terraform" -type d -prune -exec rm -rf {} +
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
	find stacks -maxdepth 2 \( -name "tfplan" -o -name "plan*.out" -o -name "plan.json" -o -name "p1.json" -o -name "p2.json" \) -delete
	rm -rf .pytest_cache tools/.pytest_cache generated
