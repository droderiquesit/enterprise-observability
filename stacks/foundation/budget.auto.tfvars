# The org's Datadog plan caps total Workflow Automation workflows (observed
# cap: ~20). 18 instantiates the highest-priority workflows (order defined in
# main.tf) with headroom for ad-hoc use. Committed as an auto-tfvars so every
# plan — deploy, idempotency gate, nightly drift, local — agrees on the same
# selection. Set to 0 when the plan allows the full 27-workflow catalog.
workflow_budget = 18
