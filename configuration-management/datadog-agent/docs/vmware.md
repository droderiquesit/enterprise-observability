# VMware

Two dedicated poller nodes watch vCenter. No Agent is installed inside a VM for
the sake of VMware infrastructure telemetry.

## Active / standby, and why not active / active

Both pollers are configured identically; exactly one is `active`. The standby
runs the Agent and reports its own health, and collects nothing from vCenter.

Active/active with both polling the same objects **doubles every metric** —
redundancy that corrupts the data it was meant to protect. Splitting clusters
between two active pollers avoids that, but then losing one silently drops half
the estate rather than all of it. **A total, obvious outage is easier to detect
than a partial, quiet one**, so active/standby was chosen.

Failover: NinjaOne promotes the standby after the active fails validation twice
consecutively. Twice, not once, so a single transient vCenter timeout does not
flap the pair.

## Coverage

vCenter availability, ESXi hosts, clusters, datastores, VMs, CPU/memory/storage/
network, datastore latency, host connectivity, VM power state, vCenter alarms
and events, snapshot age, resource contention, cluster HA state.

Realtime intervals for hosts and VMs; historical for datastores and clusters.
Historical intervals are 5-minute rollups, and using one for a host means a
5-minute blind spot on the signal that pages.

## Credentials

A read-only vSphere account (`vSphere Read-Only` at datacenter scope). Every
metric this platform collects is available read-only; write access on a
monitoring account is a finding, not a convenience. `ssl_verify: true` — a
monitoring connection that ignores certificates is one that can be intercepted.

## Not covered

Orphaned and inaccessible VM detection, and HA/DRS event coverage beyond the
alarm stream, remain open (§23 of the traceability matrix).
