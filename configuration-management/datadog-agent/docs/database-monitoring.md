# Database monitoring

Four technologies, three deployment shapes, one profile catalog.

| | Agent | Where it runs | DBM |
|---|---|---|---|
| SQL Server (on-prem) | Yes | On the instance, **or** a central poller | Yes |
| Azure SQL | Optional | Central poller only — there is no host | Yes |
| Cosmos DB | **No** | — | No |
| Snowflake | No | Account-level integration | No |

## Azure SQL and Cosmos DB have no host

They are PaaS. Microsoft owns the operating system and does not expose it, so
there is nowhere to install an Agent and no supported way to try. Telemetry
arrives from the **Azure integration**, configured once per subscription in
Terraform (`stacks/foundation`) — not per database, and not from this folder.

Azure SQL additionally supports DBM through a central poller reaching the
logical server over TCP 1433. That is the only part of Azure SQL monitoring
involving an Agent. **Cosmos DB has no equivalent**: no SQL endpoint to poll
and no DBM support, so a "Cosmos DB poller" would be a host running nothing.

## Central polling

One Agent reaching many instances. Correct when there is no host, and often
correct when the DBA team will not accept an agent on the instance.

Evaluated before centralising, because "centralize it" looks efficient until
the day it does not:

- **Blast radius** — one poller down is every database blind at once. Bounded
  by pairs and by `max_instances_per_poller: 40`.
- **Network path** — a poller reaching across a firewall turns every firewall
  change into a monitoring outage. Pollers sit in the same failure domain as
  what they watch.
- **Credentials** — a poller holds a login per instance, concentrating exactly
  what least privilege wants spread out. Read-only, per environment, never
  shared between prod and non-prod.
- **Load** — 40 instances × ~6 queries / 30s ≈ 8 queries/sec. The cap is
  derived from that, not guessed. Past it, add a poller rather than raising the
  cap; the cap is what bounds the failure domain.

## Least privilege

The monitoring login is not `db_owner` and not `sysadmin`:

```sql
CREATE LOGIN datadog_monitor WITH PASSWORD = '<from key vault>';
CREATE USER  datadog_monitor FOR LOGIN datadog_monitor;
GRANT VIEW SERVER STATE   TO datadog_monitor;   -- DMVs
GRANT VIEW ANY DEFINITION TO datadog_monitor;   -- object names in plans
-- msdb only, for backup age and failed jobs:
USE msdb; CREATE USER datadog_monitor FOR LOGIN datadog_monitor;
GRANT SELECT ON dbo.backupset   TO datadog_monitor;
GRANT SELECT ON dbo.sysjobs     TO datadog_monitor;
GRANT SELECT ON dbo.sysjobhistory TO datadog_monitor;
```

## Custom queries

Only where the native integration has **no** equivalent. Re-collecting what the
integration already provides doubles cost, and the two copies disagree during
exactly the incidents where the number matters. Today that is two queries:
backup age and failed SQL Agent jobs — both feeding archetypes that would
otherwise exist and never fire.
