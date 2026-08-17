# Self-service monitor requests

One YAML file per request. See `docs/self-service-guide.md` for the field
reference and `payments-checkout-latency.yaml` for a complete compliant
example. CI validates every file here with `tools/validate_manifests.py`;
non-compliant manifests block the PR with per-field explanations.

Deleting a file deletes the monitor on the next apply.
