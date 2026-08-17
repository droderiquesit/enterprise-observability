TF ?= terraform
PY ?= python3
STACKS := stacks/foundation stacks/coverage
MODULES := $(wildcard modules/*)

.PHONY: setup fmt fmt-check validate lint test policy manifests plan plan-offline apply coverage inventory drift runbooks clean

setup:
	$(PY) -m pip install -r tools/requirements.txt
	for d in $(MODULES) $(STACKS); do (cd $$d && $(TF) init -backend=false -input=false >/dev/null); done

fmt:
	$(TF) fmt -recursive

fmt-check:
	$(TF) fmt -recursive -check

validate: fmt-check policy manifests
	for d in $(MODULES) $(STACKS); do echo "== $$d"; (cd $$d && $(TF) validate) || exit 1; done
	$(PY) -m pytest tests/ -q

policy:
	cd tools && $(PY) validate_policy.py

manifests:
	cd tools && $(PY) validate_manifests.py

test:
	$(PY) -m pytest tests/ -q

# Offline plan: no credentials, provider+monitor API validation disabled.
plan-offline:
	cd stacks/coverage && DD_API_KEY=offline DD_APP_KEY=offline $(TF) plan -input=false \
		-var datadog_validate=false -var adopt_existing_slos=false
	cd stacks/foundation && DD_API_KEY=offline DD_APP_KEY=offline $(TF) plan -input=false \
		-var datadog_validate=false -var manage_rbac=false

# Real plan/apply: DD_API_KEY/DD_APP_KEY must come from the secret store
# (svc-observability-terraform). Never run with personal keys.
plan:
	cd stacks/foundation && $(TF) plan -input=false -out=foundation.tfplan
	cd stacks/coverage && $(TF) plan -input=false -out=coverage.tfplan

apply:
	cd stacks/foundation && $(TF) apply -input=false foundation.tfplan
	cd stacks/coverage && $(TF) apply -input=false coverage.tfplan

inventory:
	cd tools && $(PY) build_inventory.py --live
	cd tools && $(PY) profile_engine.py

coverage:
	cd tools && $(PY) coverage_report.py --live

runbooks:
	cd tools && $(PY) publish_runbooks.py

drift:
	cd stacks/foundation && $(TF) plan -input=false -detailed-exitcode
	cd stacks/coverage && $(TF) plan -input=false -detailed-exitcode
	cd tools && $(PY) publish_runbooks.py --check

clean:
	find . -name ".terraform" -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache tests/__pycache__ tools/__pycache__
