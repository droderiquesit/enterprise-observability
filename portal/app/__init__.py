"""Executive real-time web portal (requirement-traceability §47–§49).

The portal is a READ-ONLY VIEW. It owns no data: every number on the page is
either read from the platform's own report artifacts, derived from the same
`platform/policy/` files Terraform reads, or fetched live from Datadog. There
is deliberately no portal database — a second store of truth would drift from
the estate and would be believed anyway, which is the failure this repository
exists to prevent.
"""
