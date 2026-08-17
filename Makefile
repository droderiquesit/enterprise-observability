TF ?= terraform
PY ?= python3
STACKS := stacks/coverage stacks/foundation
MODULES := $(wildcard modules/*)

.PHONY: setup fmt fmt-check validate policy manifests schema docs test plan plan-offline apply \
        coverage scorecard inventory runbooks matrix drift clean

# --- developer entry points --------------------------------------------------
setup:
	$(PY) -m venv .venv
	.venv/bin/pip install -r tools/requirements.txt
	for d in $(MODULES) $(STACKS); do (cd $$d && $(TF) init -backend=false -input=false >/dev/null); done

## validate — everything CI checks, runnable locally in under a minute
validate: fmt-check policy manifests docs scorecard test tf-validate

fmt:
	$(TF) fmt -recursive
fmt-check:
	$(TF) fmt -recursive -check

policy:            ## policy-as-code lint: 12 rule families
	cd tools && $(PY) validate_policy.py
manifests:         ## self-service YAML validation
	cd tools && $(PY) validate_monitors.py
schema:            ## JSON-schema validation of manifests and registrations
	cd tools && $(PY) -c "print('run via CI stage 2, or: pip install jsonschema')"
docs:              ## generated docs must match the catalog
	cd tools && $(PY) generate_matrix.py --check && $(PY) generate_runbooks.py --check
scorecard:         ## monitor quality score
	cd tools && $(PY) monitor_scorecard.py --min-fleet-score 85 --max-failing 0
test:
	$(PY) -m pytest tests/ -q

tf-validate:
	for d in $(MODULES) $(STACKS); do echo "== $$d"; (cd $$d && $(TF) validate) || exit 1; done

# --- regeneration ------------------------------------------------------------
matrix:            ## regenerate docs/monitor-coverage-matrix.md
	cd tools && $(PY) generate_matrix.py
runbooks:          ## regenerate runbook drafts from the archetype catalog
	cd tools && $(PY) generate_runbooks.py --report

# --- terraform ---------------------------------------------------------------
## plan-offline — no credentials; exercises every precondition and budget check
plan-offline:
	cd stacks/coverage && DD_API_KEY=offline DD_APP_KEY=offline $(TF) plan -input=false \
		-var datadog_validate=false
	cd stacks/foundation && DD_API_KEY=offline DD_APP_KEY=offline $(TF) plan -input=false \
		-var datadog_validate=false -var manage_rbac=false

## plan / apply — DD_API_KEY and DD_APP_KEY must come from the secret store
## (svc-observability-terraform). Never personal keys.
plan:
	cd stacks/foundation && $(TF) plan -input=false -out=tfplan
	cd stacks/coverage   && $(TF) plan -input=false -out=tfplan
apply:
	cd stacks/foundation && $(TF) apply -input=false tfplan
	cd stacks/coverage   && $(TF) apply -input=false tfplan

# --- operations --------------------------------------------------------------
inventory:         ## rebuild the inventory and reassign profiles
	cd tools && $(PY) build_inventory.py --live && $(PY) profile_engine.py
coverage:          ## coverage & compliance report against the live org
	cd tools && $(PY) coverage_report.py --live
drift:
	cd stacks/foundation && $(TF) plan -input=false -detailed-exitcode
	cd stacks/coverage   && $(TF) plan -input=false -detailed-exitcode
	cd tools && $(PY) publish_runbooks.py --check

clean:
	find . -name ".terraform" -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache tests/__pycache__ tools/__pycache__ **/*.tfplan **/plan*.out
