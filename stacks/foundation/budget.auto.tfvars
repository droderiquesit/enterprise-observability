# The org's Datadog plan caps total Workflow Automation workflows (observed
# cap: ~20), and 18 of those slots are held by the 2026-08-07 experiment's
# workflows, which are owned by a different Datadog login
# (daveroderiques@gmail.com) — per-resource restriction policies stop the CI
# credentials from deleting them (403 even after a restriction-policy grant).
#
# TO RAISE THIS: log in as that owner (or an admin, via each workflow's
# Permissions UI), delete the 18 old "*-context" / "enrich-*-alert"
# workflows, then set this to 18 — or to 0 (full 27-workflow catalog) once
# the plan's cap allows it. Priority order lives in main.tf.
workflow_budget = 2
