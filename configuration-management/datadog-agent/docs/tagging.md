# Tagging

The tag **keys** are not defined here. They come from
`platform/policy/global.yaml`, which is the same vocabulary the monitors, SLOs
and Service Catalog use. A key list maintained in two places is how
`resource_type` on a monitor stops matching `resource_type` on a host.

## Applied to every Agent

`env`, `team`, `criticality`, `managed_by:ninjaone`, `monitoring_profile`, plus
any of `service`, `version`, `platform`, `resource_type`, `resource_class`,
`application`, `business_unit`, `region`, `location`, `subscription`,
`resource_group`, `cost_center`, `data_classification`, `support_model`,
`owner` the node declares.

## Unified service tagging

`env` + `service` + `version` is the join between a metric, a log and a trace.
A node that ships logs or traces without it produces telemetry that cannot be
correlated to anything — which looks like coverage and is not. The renderer
refuses to produce such a configuration, and a test asserts the refusal.

`version` comes from the deploying pipeline, not from here. This folder can set
it on a node that declares one; it cannot make an application emit it.

## Service names

Normalised against the entity registry. A node whose `service` does not match a
registered entity produces a Service Catalog entry that looks like a new
service — which is how one application ends up as two.
