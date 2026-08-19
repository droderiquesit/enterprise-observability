#!/usr/bin/env python3
"""RUNBOOK CONTENT LIBRARIES.

The generator (`generate_runbooks.py`) turns the archetype catalog into a
complete, attachable Datadog runbook. The judgement that makes a runbook worth
opening at 3am does not live in the catalog, so it lives here: per-SIGNAL cause
and remediation libraries, per-DETECTION reading guidance, and per-RESOURCE
telemetry pointers.

Why libraries rather than 151 hand-written files: a hand-written corpus goes
stale silently and unevenly. Keying the judgement on (signal x detection x
resource family) means every archetype inherits real, specific guidance, and
correcting one library corrects every runbook that shares that failure mode.
The archetype-specific facts — query, metric, thresholds, grouping, SLO,
workflow, owner — are interpolated per runbook, so no two documents are the
same and none of them is a generic troubleshooting page.

Nothing here is a placeholder. `TODO` is banned by CI.
"""
from __future__ import annotations

# =============================================================================
# SIGNAL LIBRARY — what the signal means, and what to do about it.
#   measures   one sentence: what is physically being measured
#   causes     ranked, most frequent first. Specific, not "check the logs".
#   investigate ordered, each step answers a question that changes the response
#   remediate  safe actions, least destructive first, blast radius stated
#   rollback   how to undo the remediation if it makes things worse
#   recovery   what must be true before this is called resolved
# =============================================================================
SIGNALS: dict[str, dict] = {
    "availability": {
        "measures": "whether the resource answers at all — a binary up/down or a "
                    "success-ratio collapse, not a slow-down",
        "causes": [
            ("Process or instance died", "the workload crashed, was OOM-killed, or the host/VM was "
             "terminated. Check restart counts and exit codes before anything else."),
            ("A dependency it cannot start without", "database, secret store, config service or "
             "identity provider is unreachable, so the resource fails its own readiness check."),
            ("A deployment or configuration change", "a rollout replaced a working version with one "
             "that cannot bind, cannot authenticate, or fails health checks."),
            ("Network or DNS path loss", "the resource is alive but unreachable — security group, "
             "route, firewall rule, certificate or DNS record changed."),
            ("Capacity exhaustion", "connection pool, file handles, disk or memory hit a hard limit "
             "and the resource stopped accepting work."),
        ],
        "investigate": [
            "Confirm the scope from the alert's group tags: one member down is a member problem, "
            "all members down is a dependency or platform problem.",
            "Check whether the resource restarted — a restart loop and a clean outage need different "
            "responses.",
            "Check the correlated change events attached to this alert. Most availability loss is "
            "change-induced and the fastest fix is to reverse the change.",
            "Test the dependency path the resource needs to become ready, in the order it needs them.",
        ],
        "remediate": [
            "If a change correlates, roll it back. This is the highest-yield action and needs no "
            "further diagnosis.",
            "If a single member is down and the workload is replicated, remove it from the pool and "
            "let the platform replace it. Blast radius: one member.",
            "If a dependency is down, fail over to the standby or enable the degraded path. Record "
            "the decision on the incident.",
            "Restart the resource only after capturing diagnostics — a restart destroys the evidence "
            "that explains the outage.",
        ],
        "rollback": "Re-deploy the previously known-good version, or restore the member to the pool. "
                    "If a failover was performed, fail back only after the primary has been healthy "
                    "for a full evaluation window — flapping between primary and standby is worse "
                    "than staying on the standby.",
        "recovery": "the resource reports healthy for a full evaluation window, its dependents have "
                    "stopped erroring, and the replacement or restored member is serving traffic",
    },
    "error_rate": {
        "measures": "the proportion or count of requests that failed, not how slow they were",
        "causes": [
            ("A deployment", "the most common cause of a step change in errors. Check the correlated "
             "change events first."),
            ("A downstream dependency failing", "errors surfacing here are often produced elsewhere; "
             "the failing call is usually visible in the trace."),
            ("Bad or unexpected input", "a partner, client version or upstream schema change is "
             "sending requests the service rejects."),
            ("Resource exhaustion", "connection pool, thread pool or rate limiter is shedding load, "
             "which surfaces as errors rather than latency."),
            ("Authentication or certificate expiry", "credentials, tokens or TLS material rotated or "
             "expired and calls now fail closed."),
        ],
        "investigate": [
            "Break the error rate down by the alert's grouping dimensions to find whether the errors "
            "are concentrated or spread. Concentrated is a code or endpoint problem; spread is "
            "usually a dependency or platform problem.",
            "Read the actual error responses, not just the count — the status code and message "
            "usually name the cause.",
            "Follow a failing trace end to end and find the first span that errors. That span, not "
            "the one that alerted, is where the fault is.",
            "Compare against the deploy timeline for this service and its dependencies.",
        ],
        "remediate": [
            "If a deploy correlates, roll it back before diagnosing further.",
            "If one dependency is responsible, enable the circuit breaker or fallback path for that "
            "dependency. Blast radius: the feature that depends on it.",
            "If a single client or partner is responsible, rate-limit that caller rather than "
            "degrading everyone.",
            "If credentials expired, rotate and redeploy the secret; do not disable verification.",
        ],
        "rollback": "Redeploy the previous release. If a circuit breaker or fallback was enabled, "
                    "disable it only once the dependency has been error-free for a full evaluation "
                    "window, and re-enable immediately if errors return.",
        "recovery": "the error rate is back to its pre-incident level (not merely under the "
                    "threshold), no new error signatures remain, and the SLO has stopped burning",
    },
    "latency": {
        "measures": "how long work takes at the stated percentile — the service is still succeeding, "
                    "just slower",
        "causes": [
            ("A slow dependency", "most latency regressions are inherited. The trace shows which "
             "downstream call grew."),
            ("Database or query degradation", "a plan change, a missing index, lock contention or a "
             "growing table turns a fast query slow."),
            ("Saturation", "CPU, connection pool, thread pool or GC pressure adds queueing time "
             "before any real work starts."),
            ("A deployment", "a new code path, an added synchronous call, or a serialization change."),
            ("Traffic-shape change", "more expensive requests, larger payloads, or a cache-hit-rate "
             "collapse making the expensive path the common path."),
        ],
        "investigate": [
            "Confirm whether throughput changed at the same time. Latency up with traffic up is "
            "capacity; latency up with traffic flat is a regression.",
            "Open a slow trace and compare span durations against a fast one from before the change. "
            "The span that grew is the answer.",
            "Check the cache hit rate and the database's own latency for the same window.",
            "Check saturation on the serving tier before blaming code — a queued request looks slow "
            "everywhere.",
        ],
        "remediate": [
            "If a deploy correlates, roll it back.",
            "If a dependency is slow, apply the timeout and fallback for that call so slowness does "
            "not become an outage. Blast radius: that feature degrades rather than hangs.",
            "If saturation is the cause, add capacity or shed the most expensive traffic path first.",
            "If a query regressed, restore the previous plan or index; do not raise the timeout to "
            "hide it.",
        ],
        "rollback": "Revert the release, index or configuration change that was applied. Timeouts "
                    "and fallbacks that were tightened during the incident should be returned to "
                    "their documented defaults once the dependency is healthy, one change at a time.",
        "recovery": "the percentile is back to its pre-incident band for a full evaluation window, "
                    "queue depth and saturation have normalised, and no fallback remains enabled",
    },
    "saturation": {
        "measures": "how close a bounded resource is to its limit — the point past which work queues "
                    "rather than completes",
        "causes": [
            ("Organic growth", "demand grew into the headroom and the limit was never revisited."),
            ("A leak", "memory, connections, file handles or threads are acquired and never "
             "released; the shape is a steady climb that survives traffic troughs."),
            ("A change in workload", "a new feature, a batch job, or a retry storm is consuming far "
             "more of the resource per unit of work."),
            ("Under-provisioning after a scaling change", "an autoscaler bound, node pool size, or "
             "instance class was lowered."),
            ("A stuck consumer or backlog", "work is arriving faster than it drains, so the buffer "
             "fills."),
        ],
        "investigate": [
            "Establish the shape: a step change points at a deployment or config change; a steady "
            "climb that ignores traffic troughs points at a leak.",
            "Identify the largest consumer using the alert's grouping dimensions before adding "
            "capacity — adding capacity to a leak only buys time.",
            "Check whether the limit itself changed recently (autoscaler bounds, quotas, instance "
            "class, pool size).",
            "Project the time to exhaustion so the response is matched to the lead time available.",
        ],
        "remediate": [
            "If there is real headroom to buy, scale out or raise the bound — this is the safe, "
            "reversible action and it buys diagnosis time.",
            "If a leak is confirmed, recycle the affected members on a rolling basis to reclaim the "
            "resource. Blast radius: brief per-member capacity loss.",
            "Shed or defer the largest non-critical consumer (batch, backfill, report) to protect "
            "interactive traffic.",
            "Fix the leak or the workload change; scaling is mitigation, not resolution.",
        ],
        "rollback": "Return the bound, replica count or quota to its previous documented value once "
                    "consumption is back in band. Record the new baseline if the higher value is "
                    "being kept, so the next reviewer does not treat it as drift.",
        "recovery": "utilisation is back inside its normal band with the original limits restored, "
                    "the projection no longer crosses the limit inside the forecast horizon, and any "
                    "deferred work has been drained",
    },
    "capacity": {
        "measures": "remaining headroom against a hard, physical or contractual limit that cannot be "
                    "exceeded",
        "causes": [
            ("Sustained growth", "consumption grew predictably and the limit was not raised in time."),
            ("Retention or cleanup stopped", "old data, snapshots, logs or artifacts are no longer "
             "being expired."),
            ("A large one-off consumer", "a backfill, migration, import or debug-level logging run "
             "consumed the headroom."),
            ("A quota or limit reduction", "the ceiling moved down rather than usage moving up."),
        ],
        "investigate": [
            "Confirm the limit and the current value — the alert is about the ratio, and both sides "
            "of it can move.",
            "Identify the largest consumers and whether any are unexpected or reclaimable.",
            "Check whether cleanup, retention or expiry jobs are still running successfully.",
            "Calculate the time remaining at the current rate to decide between now and next "
            "business day.",
        ],
        "remediate": [
            "Reclaim first: expire, archive or delete what is already safe to remove. Blast radius: "
            "none if retention policy is followed.",
            "Then raise the limit or add capacity, within the approved budget.",
            "Stop or throttle the consumer responsible if it is non-critical.",
        ],
        "rollback": "If a limit was raised, it can stay — but record it. If data was archived to "
                    "reclaim space, confirm the archive is readable before deleting the source, and "
                    "restore from archive if anything downstream breaks.",
        "recovery": "headroom is back above the policy threshold, the reclaim or expansion is "
                    "permanent rather than manual, and the projection no longer breaches",
    },
    "telemetry_health": {
        "measures": "whether the platform can still see the estate — the monitoring of the monitoring",
        "causes": [
            ("Agent or collector stopped", "the shipper died, lost credentials, or was removed by a "
             "rollout."),
            ("A pipeline or integration change", "a processor, filter, index or exclusion was "
             "changed and is now dropping data."),
            ("Credential or quota loss", "the API key was rotated or the ingest quota was exhausted, "
             "so data is rejected."),
            ("The source genuinely stopped", "the workload was decommissioned or scaled to zero — "
             "absence of telemetry is correct and the monitor should be retired."),
            ("Network path loss to the collector", "egress, proxy or firewall change."),
        ],
        "investigate": [
            "Decide first whether the source still exists. Silent decommissioning and silent breakage "
            "look identical and have opposite responses.",
            "Check the agent or integration status on a sample of the affected members.",
            "Check the ingest pipeline for recent changes: exclusion filters, sampling, index limits, "
            "quota.",
            "Compare against a neighbouring source that is still reporting to separate 'this source' "
            "from 'this pipeline'.",
        ],
        "remediate": [
            "Restore the collector or credential. Blast radius: none — this restores visibility, it "
            "does not change the workload.",
            "Reverse the pipeline change that dropped the data.",
            "If the source is genuinely gone, retire the monitor and the resource record so the gap "
            "stops alerting.",
        ],
        "rollback": "Reverting a pipeline change restores the previous volume immediately; if ingest "
                    "cost is the reason the filter existed, re-apply a narrower version rather than "
                    "the original blanket filter.",
        "recovery": "the expected volume has resumed for a full evaluation window, the coverage "
                    "report shows no gap for this source, and any monitor muted during the outage "
                    "has been unmuted",
    },
    "job_failure": {
        "measures": "whether a scheduled or batch unit of work completed successfully",
        "causes": [
            ("Bad input data", "a malformed, missing or unexpectedly large input file or partition."),
            ("A dependency unavailable at run time", "source database, object store, or partner "
             "endpoint was down during the window."),
            ("Credential or permission expiry", "the job's identity lost access to something it "
             "needs."),
            ("Resource limits", "the job was killed for exceeding memory, disk or wall-clock limits."),
            ("A code or configuration change", "a release changed the job's behaviour or its "
             "expectations of the input."),
        ],
        "investigate": [
            "Read the job's own failure output first — batch jobs almost always name their own cause.",
            "Establish whether this is the first failure or a repeat; a repeat with the same error is "
            "a defect, an isolated failure is often transient.",
            "Check the inputs the run expected: presence, size, schema and freshness.",
            "Confirm the downstream consumers that are now missing this output, so impact is known "
            "before the rerun.",
        ],
        "remediate": [
            "If the cause was transient and the job is idempotent, rerun it. Blast radius: none for "
            "an idempotent job — confirm idempotency in the service registry before rerunning.",
            "If the input is wrong, correct the input and rerun rather than forcing the job past it.",
            "If the job is not idempotent, follow its documented restart procedure; a blind rerun can "
            "double-write.",
            "Notify downstream consumers if the output will be late past their own deadline.",
        ],
        "rollback": "If a rerun produced partial or duplicate output, remove the partial partition "
                    "or run the job's compensating cleanup before rerunning again. Never leave two "
                    "partial outputs in place for a consumer to merge.",
        "recovery": "the run completes successfully, the output is present and the expected size, "
                    "downstream consumers have picked it up, and the schedule's next run starts on "
                    "time",
    },
    "schedule_miss": {
        "measures": "that an expected run never started — nothing errored, nothing ran",
        "causes": [
            ("The scheduler itself is down or partitioned", "no jobs at all started in the window; "
             "check whether peers also missed."),
            ("The schedule was disabled or edited", "someone paused it, or a deploy replaced the "
             "schedule definition."),
            ("An upstream dependency gate never released", "the run is waiting on a predecessor that "
             "never completed."),
            ("Calendar or timezone error", "a daylight-saving transition or calendar change moved "
             "the window."),
            ("Quota or concurrency limit", "the run was rejected because too many jobs were already "
             "running."),
        ],
        "investigate": [
            "Confirm whether other scheduled work ran in the same window. Nothing running is a "
            "scheduler incident; only this job is a job problem.",
            "Check the schedule definition and whether it was changed, paused or superseded.",
            "Check for a blocking predecessor or an unreleased dependency gate.",
            "Confirm the expected next-run time against the timezone the schedule is defined in.",
        ],
        "remediate": [
            "Trigger the run manually if the window still permits it and the job is idempotent.",
            "Re-enable or restore the schedule definition, and record who disabled it and why.",
            "If the scheduler is down, escalate to the platform owner — individual reruns will not "
            "fix a systemic miss.",
        ],
        "rollback": "A manual trigger that clashes with a recovered automatic run can double-process. "
                    "If both fired, stop the later one and verify the output was written exactly "
                    "once before releasing it downstream.",
        "recovery": "the run has completed for the missed window, the schedule is enabled and shows "
                    "a correct next-run time, and the following scheduled run starts automatically",
    },
    "freshness": {
        "measures": "the age of the newest available data against the maximum age the consumers "
                    "accepted",
        "causes": [
            ("The producing job failed or never ran", "the most common cause; check the producer "
             "before anything else."),
            ("The producer is running but slow", "the pipeline is still working and will catch up, "
             "which changes the response from fix to wait."),
            ("An upstream source stopped delivering", "the partner, export or replication feed is "
             "late, not the pipeline."),
            ("A silent schema or partition change", "data is arriving but landing where nothing reads "
             "it."),
        ],
        "investigate": [
            "Check the producing job's last successful run and current state — late-and-running and "
            "failed-and-stopped need opposite responses.",
            "Confirm the upstream source actually delivered its input for this window.",
            "Check whether the data is present but in an unexpected partition, path or schema.",
            "Identify which downstream consumers and reports are already affected.",
        ],
        "remediate": [
            "If the producer failed, fix and rerun it — freshness is a symptom, the job is the cause.",
            "If the upstream is late, notify consumers with a revised ETA rather than reprocessing.",
            "If the landing location changed, correct the path or partition mapping and reprocess "
            "the affected window.",
        ],
        "rollback": "If a reprocess wrote to a corrected location, remove the incorrect partition "
                    "only after confirming no consumer read from it; if one did, re-run that "
                    "consumer after the correction.",
        "recovery": "the newest record is inside the freshness objective, the producer's schedule is "
                    "back on time, and affected downstream reports have been refreshed",
    },
    "volume": {
        "measures": "whether the amount of data arriving matches what the pipeline normally receives",
        "causes": [
            ("An upstream producer stopped or reduced output", "a partial feed is the usual cause of "
             "a volume drop."),
            ("A filter or routing change", "records are being dropped or routed elsewhere before "
             "they arrive."),
            ("A genuine business change", "a real drop in activity — seasonality, a closed region, a "
             "retired client."),
            ("Duplicate delivery", "for a volume spike, the same batch delivered twice."),
        ],
        "investigate": [
            "Compare against the same period last week before treating this as a defect — volume is "
            "the signal most often explained by seasonality.",
            "Break the volume down by source to find whether one producer or all of them changed.",
            "Check for recent filter, routing or sampling changes in the ingestion path.",
            "For a spike, check for duplicate batch identifiers before reprocessing anything.",
        ],
        "remediate": [
            "If a producer stopped, escalate to its owner — the fix is upstream.",
            "If a filter change is responsible, reverse it.",
            "If duplicates arrived, de-duplicate before the data reaches consumers; do not let "
            "downstream aggregate twice.",
        ],
        "rollback": "Reversing a filter restores volume immediately. If de-duplication removed "
                    "records, verify the retained set is complete against the source manifest "
                    "before closing.",
        "recovery": "volume is back inside its expected band for the period, per-source counts "
                    "reconcile against the producer's manifest, and no consumer double-counted",
    },
    "correctness": {
        "measures": "whether the data satisfies the quality contract its consumers rely on, "
                    "independent of whether it arrived on time",
        "causes": [
            ("An upstream schema or semantics change", "the field still exists but no longer means "
             "what the check assumed."),
            ("Partial or duplicated input", "an incomplete load passes freshness but fails the "
             "contract."),
            ("A transformation defect", "a release changed a join, filter or cast."),
            ("A legitimate business change", "the rule itself is now wrong and needs updating — "
             "confirm with the data owner before overriding."),
        ],
        "investigate": [
            "Identify exactly which rule failed and on which rows or partitions; a contract failure "
            "is only actionable when the failing subset is known.",
            "Check whether the upstream schema or source definition changed in this window.",
            "Confirm whether the run was complete — partial loads commonly fail correctness rather "
            "than freshness.",
            "Ask whether the rule is still correct before assuming the data is wrong.",
        ],
        "remediate": [
            "Quarantine the failing partition so consumers do not read it. Blast radius: consumers "
            "see the previous good version rather than bad data.",
            "Correct the transformation or the input and reprocess the affected window.",
            "If the rule is obsolete, update it through review — do not silence the check.",
        ],
        "rollback": "Republish the previous known-good partition to consumers if the corrected "
                    "reprocess cannot complete inside their deadline, and mark the window as "
                    "restated so downstream reporting is consistent.",
        "recovery": "the quality rules pass on the reprocessed data, quarantine is lifted, and "
                    "consumers have re-read the corrected partition",
    },
    "throughput": {
        "measures": "the rate of work completed — too low means work is not being processed, too "
                    "high can mean a retry storm",
        "causes": [
            ("Consumers stopped or reduced", "instances died, scaled down, or lost their assignment."),
            ("Upstream stopped producing", "there is genuinely less work, which is not a defect."),
            ("A poison message or stuck partition", "one bad item blocks progress for its partition."),
            ("Downstream backpressure", "the consumer is throttled by whatever it writes to."),
        ],
        "investigate": [
            "Establish whether input also dropped. Output down with input down is upstream; output "
            "down with input steady is the consumer.",
            "Check consumer instance count, assignment and lag distribution — one stuck member often "
            "explains an aggregate drop.",
            "Look for a repeatedly redelivered item at the head of the queue or partition.",
            "Check the consumer's own downstream for throttling or errors.",
        ],
        "remediate": [
            "Restore or scale the consumers. Blast radius: none if the work is idempotent.",
            "Move a poison item to the dead-letter destination so the rest can drain, and record it "
            "for analysis.",
            "Relieve downstream backpressure before adding consumers, or the added consumers will "
            "also stall.",
        ],
        "rollback": "Scale the consumer group back to its documented size once the backlog has "
                    "drained; leaving it scaled up hides the underlying limit and inflates cost.",
        "recovery": "the processing rate matches the arrival rate, backlog is drained to its normal "
                    "band, and no partition remains stuck",
    },
    "replication_lag": {
        "measures": "how far a replica trails its primary, in time or position",
        "causes": [
            ("A heavy write burst on the primary", "the replica cannot apply as fast as the primary "
             "produces."),
            ("A long-running query blocking apply", "on the replica, a reader can stall replay."),
            ("Network throughput or latency between sites", "especially cross-region."),
            ("A schema change or large transaction", "a single expensive statement replays serially."),
        ],
        "investigate": [
            "Determine whether lag is growing, flat or shrinking — shrinking lag needs patience, "
            "growing lag needs action.",
            "Check the primary's write rate for a burst that explains it.",
            "Check for long-running queries on the replica that block replay.",
            "Confirm whether any read traffic is being served from this replica, because that "
            "traffic is now reading stale data.",
        ],
        "remediate": [
            "Move read traffic off the lagging replica so consumers stop reading stale data. Blast "
            "radius: more load on the primary or other replicas.",
            "Kill the blocking query on the replica if one is identified.",
            "Throttle the bulk write on the primary that is producing the backlog.",
        ],
        "rollback": "Return read traffic to the replica only after lag has been inside its objective "
                    "for a sustained period; returning traffic early re-creates the stale-read "
                    "problem the failover was meant to solve.",
        "recovery": "lag is back inside the objective, it stays there across a write burst, and read "
                    "routing has been restored to its normal distribution",
    },
    "dlq_depth": {
        "measures": "how many messages failed processing badly enough to be set aside",
        "causes": [
            ("A poison-message class", "a specific payload shape the consumer cannot handle."),
            ("A downstream dependency outage", "everything failed while the dependency was down and "
             "was parked."),
            ("A schema or contract change", "the producer changed the payload and the consumer was "
             "not updated."),
            ("Expired credentials or permissions", "the consumer could not complete a side effect."),
        ],
        "investigate": [
            "Sample the dead-lettered messages and classify them — one cause usually explains almost "
            "all of them.",
            "Establish the time window they arrived in and what else was failing then.",
            "Confirm whether the underlying cause is already fixed before replaying anything.",
            "Check whether these messages are still business-relevant; some are safe to discard.",
        ],
        "remediate": [
            "Fix the cause first. Replaying into a broken consumer refills the dead-letter queue.",
            "Replay in a controlled batch and watch the failure rate. Blast radius: replayed side "
            "effects can duplicate — confirm consumer idempotency first.",
            "Discard only with the data owner's agreement, and record what was discarded.",
        ],
        "rollback": "If a replay produced duplicate side effects, run the documented compensating "
                    "action for that consumer. Stop the replay immediately if the failure rate on "
                    "replayed messages exceeds the original.",
        "recovery": "the dead-letter queue is drained or explicitly accepted, the cause is fixed, "
                    "and no new messages are arriving in it",
    },
    "certificate_expiry": {
        "measures": "days remaining before a certificate or secret stops being trusted — nothing is "
                    "broken yet",
        "causes": [
            ("Automated renewal is not configured", "the certificate was issued manually and nobody "
             "owns the renewal."),
            ("Renewal automation is failing silently", "the job runs but cannot complete validation "
             "or write the new material."),
            ("The certificate is deployed in more places than are tracked", "renewal succeeded "
             "centrally but one consumer still holds the old material."),
        ],
        "investigate": [
            "Identify every place this certificate or secret is installed — the alert names one, "
            "the risk is all of them.",
            "Check whether renewal automation exists and when it last succeeded.",
            "Confirm the issuing authority and validation method still work before the renewal window "
            "closes.",
        ],
        "remediate": [
            "Renew and deploy well before expiry, during business hours. Blast radius: a rotation "
            "done calmly is routine; one done at expiry is an outage.",
            "Fix or create the renewal automation so the next cycle is not manual.",
            "Verify every consumer picked up the new material, not just the primary.",
        ],
        "rollback": "Keep the previous certificate available until every consumer is confirmed on "
                    "the new one; if a consumer fails, restore the old material and retry the "
                    "rollout for that consumer alone.",
        "recovery": "the new material is live everywhere it is used, the expiry date has moved out "
                    "beyond the alert threshold, and renewal automation is scheduled",
    },
    "backup_age": {
        "measures": "how long since a successful, restorable backup — a recoverability risk, not an "
                    "availability one",
        "causes": [
            ("The backup job failed silently", "the schedule ran, the job errored, nobody looked."),
            ("The destination is full or unreachable", "the backup produced nothing to store."),
            ("Credentials or permissions to the destination expired", ""),
            ("The source grew past the backup window", "the job is now truncated by its own timeout."),
        ],
        "investigate": [
            "Confirm the age of the last backup that is actually restorable, not just the last job "
            "that reported success.",
            "Check the destination for space, reachability and permissions.",
            "Check whether the backup duration has been growing towards its window limit.",
            "Establish the current recovery point exposure and whether it breaches policy.",
        ],
        "remediate": [
            "Run a backup now, out of schedule. Blast radius: load on the source during the run — "
            "prefer a replica if one exists.",
            "Fix the destination or credential problem so the schedule succeeds unattended.",
            "Extend the window or change the strategy (incremental, replica-sourced) if duration is "
            "the constraint.",
        ],
        "rollback": "None required — taking a backup is additive. If the out-of-schedule run caused "
                    "load problems on the source, stop it and re-run against a replica instead.",
        "recovery": "a recent backup exists AND has been restore-tested, the schedule has succeeded "
                    "unattended at least once, and the recovery point is back inside policy",
    },
    "drift": {
        "measures": "that live configuration no longer matches the declared, reviewed source of truth",
        "causes": [
            ("A manual change made during an incident", "the most common and most forgivable — it "
             "still has to be reconciled."),
            ("A change made outside the pipeline", "console or CLI edit that bypassed review."),
            ("An automated process outside this platform", "another controller managing the same "
             "object."),
            ("A failed or partial apply", "the pipeline itself left the object half-changed."),
        ],
        "investigate": [
            "Identify exactly which fields differ — drift is only actionable at field level.",
            "Find who made the change and when, from the audit trail.",
            "Decide whether the live state or the declared state is correct. Sometimes the emergency "
            "change was right and the code is wrong.",
            "Check whether the same drift exists in other environments.",
        ],
        "remediate": [
            "If the declared state is correct, re-apply it through the pipeline. Blast radius: the "
            "live change is reverted — confirm it is not load-bearing first.",
            "If the live state is correct, codify it in the repository and apply through review so "
            "the two agree.",
            "Never resolve drift by silencing the check.",
        ],
        "rollback": "Re-applying declared state is itself reversible: the previous live values are "
                    "in the audit trail and the prior state file. If the re-apply breaks something, "
                    "restore the recorded live values and reconcile the code instead.",
        "recovery": "a plan against the live estate is empty, the change is either codified or "
                    "reverted, and the audit trail records which was chosen and why",
    },
    "change": {
        "measures": "that a change happened which needs attention — the event itself is the signal",
        "causes": [
            ("A planned change executing normally", "expected; the alert exists for the audit trail."),
            ("An unplanned or out-of-window change", "needs review against the change policy."),
            ("An automated remediation acting", "a controller or workflow changed something in "
             "response to another condition."),
        ],
        "investigate": [
            "Identify the actor, the object and whether a change record exists.",
            "Determine whether the change was inside an approved window.",
            "Correlate against any active alerts — a change during an incident is usually the "
            "remediation, not the cause.",
        ],
        "remediate": [
            "If the change is unapproved and risky, reverse it and raise a change record "
            "retrospectively.",
            "If it is approved, annotate the incident timeline and close.",
        ],
        "rollback": "Reversal is the remediation. Confirm with the change owner before reversing "
                    "anything that has already been depended on downstream.",
        "recovery": "the change is either approved and recorded, or reversed, and no dependent alert "
                    "remains open",
    },
    "auth_anomaly": {
        "measures": "authentication behaviour that deviates from the established pattern — a security "
                    "signal, not a performance one",
        "causes": [
            ("Credential stuffing or brute force", "high-volume failures across many identities."),
            ("A compromised credential in use", "successful authentication from an unusual location, "
             "device or time."),
            ("A broken client or integration", "a misconfigured service retrying with stale "
             "credentials — the most common benign explanation."),
            ("An identity-provider or policy change", "an MFA or conditional-access change altering "
             "the pattern legitimately."),
        ],
        "investigate": [
            "Separate failures from anomalous successes. A successful anomalous authentication is "
            "the more serious of the two.",
            "Identify the accounts, source addresses and user agents involved and whether they "
            "cluster.",
            "Check for a recent identity-provider or policy change that explains the shift.",
            "Preserve the evidence before changing anything — follow the security team's handling "
            "rules.",
        ],
        "remediate": [
            "Engage the security team as the primary responder; the owning team supports. Do not "
            "act unilaterally on a suspected compromise.",
            "Block or rate-limit the offending source once security agrees. Blast radius: legitimate "
            "traffic from that source is also blocked.",
            "Force credential rotation for confirmed-affected identities.",
        ],
        "rollback": "Lift a block only with security's agreement and after the source has been "
                    "clean for an agreed period. Rotations are not rolled back — reissue instead.",
        "recovery": "the authentication pattern is back to baseline, security has confirmed no "
                    "compromise remains, and any block or rotation is recorded on the case",
    },
    "control_failure": {
        "measures": "that a required security or compliance control is not functioning — an audit "
                    "and risk exposure",
        "causes": [
            ("The control was disabled", "deliberately during troubleshooting, or accidentally by a "
             "template change."),
            ("A dependency the control needs is unavailable", "log destination, key service or "
             "policy engine."),
            ("A resource was created outside the guarded path", "so the control was never applied to "
             "it."),
            ("The control's own definition changed", "and no longer matches the estate."),
        ],
        "investigate": [
            "Identify which specific control failed and on which resources.",
            "Establish how long it has been failing — exposure duration is what the auditor asks for.",
            "Determine whether the resource was ever compliant or was created outside the guarded "
            "path.",
            "Check whether the same control is failing elsewhere.",
        ],
        "remediate": [
            "Restore the control. Blast radius: re-enabling enforcement can reject workloads that "
            "have been non-compliant — confirm before enforcing broadly.",
            "Bring the non-compliant resources into compliance, or remove them.",
            "Record the exposure window for the compliance evidence trail.",
        ],
        "rollback": "If re-enabling enforcement breaks a legitimate workload, move that workload to "
                    "a documented, time-boxed exception rather than disabling the control estate-wide.",
        "recovery": "the control reports enforcing on every in-scope resource, the exposure window "
                    "is documented, and any exception is time-boxed and approved",
    },
    "cost": {
        "measures": "spend rate against the expected envelope — a financial signal with no immediate "
                    "customer impact",
        "causes": [
            ("A new or resized workload", "someone scaled up and the cost followed."),
            ("A leak or runaway process", "orphaned resources, a retry storm, or a job that never "
             "terminates."),
            ("Telemetry or data volume growth", "ingestion and retention are common surprises."),
            ("A pricing or commitment change", "the rate changed, not the usage."),
        ],
        "investigate": [
            "Break the increase down by resource and owner before acting — cost alerts are only "
            "actionable when attributed.",
            "Establish whether usage or unit price moved.",
            "Look for orphaned resources: unattached volumes, idle instances, forgotten environments.",
            "Check whether the increase correlates with a known launch.",
        ],
        "remediate": [
            "Remove orphaned and idle resources. Blast radius: verify nothing references them first.",
            "Right-size or schedule down non-production capacity.",
            "Raise the budget deliberately if the growth is legitimate, rather than letting the "
            "alert stay red.",
        ],
        "rollback": "Anything deleted for cost reasons should be recoverable from backup or "
                    "recreatable from code; confirm that before deleting, and restore immediately "
                    "if a dependency surfaces.",
        "recovery": "spend rate is back inside the envelope or the envelope has been formally "
                    "raised, and the responsible resources are attributed to an owner",
    },
}

# =============================================================================
# DETECTION LIBRARY — how to read the trigger, and its specific false-positive trap.
# =============================================================================
DETECTIONS: dict[str, dict] = {
    "threshold": {
        "reads": "a fixed threshold was crossed",
        "trap": "A fixed threshold is a judgement about what matters, not a law of nature. If the "
                "value is barely over and the trend is flat, the threshold may be the problem — "
                "raise that through review rather than muting the alert.",
    },
    "anomaly": {
        "reads": "the signal deviated from its own learned baseline by more than the configured "
                 "number of deviations. It did NOT cross a fixed number",
        "trap": "'The value looks normal to me' is not a reason to close this — the baseline is "
                "what moved. Conversely, a recent step change in traffic can make a healthy service "
                "look anomalous for a day while the baseline relearns.",
    },
    "seasonal_anomaly": {
        "reads": "the signal deviated from its learned SEASONAL baseline — same hour, same day of "
                 "week. Normal daily and weekly cycles are already accounted for",
        "trap": "Holidays, launches and marketing events are not in the seasonal model. Confirm "
                "there is no known calendar event before treating this as a defect.",
    },
    "forecast": {
        "reads": "extrapolating the recent trend, the resource is projected to cross its limit "
                 "inside the forecast horizon. It has NOT crossed it yet",
        "trap": "The lead time is the entire point — resolving this by waiting for the breach wastes "
                "it. Equally, a forecast built on a short-lived spike will retract on its own; "
                "confirm the trend is sustained before major action.",
    },
    "outlier": {
        "reads": "this member diverged from its peer group. Every peer receives comparable work, so "
                 "divergence is itself the defect",
        "trap": "If the peer group is not genuinely homogeneous — different hardware, different "
                "shard sizes, an intentional canary — the outlier may be correct. Verify the group "
                "before acting on the member.",
    },
    "rate_of_change": {
        "reads": "the signal changed faster than the configured percentage relative to its own "
                 "recent history. Speed of degradation, not absolute level",
        "trap": "A small absolute change on a small base can trip this. Check the absolute values "
                "before escalating; a drop from 4 to 2 requests is not an outage.",
    },
    "service_check": {
        "reads": "a check reported a non-OK status for consecutive evaluations",
        "trap": "A check can fail because the checker cannot reach the target, not because the "
                "target is down. Confirm from a second vantage point before declaring an outage.",
    },
    "event": {
        "reads": "a discrete platform event matched this monitor's search",
        "trap": "The event is a fact, not a diagnosis. It reports that something happened, not "
                "whether it was intended — check for an approved change record before treating it "
                "as an incident.",
    },
    "slo_burn": {
        "reads": "error budget is being consumed faster than sustainable, confirmed across a long "
                 "and a short window simultaneously",
        "trap": "A numerator that stops reporting looks identical to a perfect service, and a "
                "denominator that stops reporting looks identical to total failure. Rule out a "
                "telemetry gap before treating the burn as real.",
    },
}

# =============================================================================
# RESOURCE FAMILIES — where the supporting telemetry for this kind of thing lives.
# Maps the 51 resource_types onto the handful of investigation surfaces that
# actually differ.
# =============================================================================
_FAMILY_BY_RESOURCE = {
    "apm": ["service", "api_gateway", "load_balancer"],
    "container": ["kube_deployment", "kube_pod", "kube_node", "kube_cluster", "kube_hpa",
                  "kube_pvc", "kube_cronjob"],
    "host": ["host", "esxi_host", "vsphere_vm", "vsphere_cluster", "vsphere_datastore",
             "azure_vm", "storage_volume"],
    "database": ["db_instance", "azure_sql", "azure_cosmos_db", "warehouse"],
    "messaging": ["queue", "stream", "stream_consumer", "messaging_namespace"],
    "data": ["pipeline", "data_product", "batch_job", "scheduled_job", "integration_flow",
             "backup_job"],
    "cloud": ["azure_subscription", "azure_app_service", "azure_app_service_plan", "azure_function",
              "azure_storage", "azure_application_gateway", "azure_key_vault", "azure_load_balancer"],
    "network": ["network_device", "network_path", "network_tunnel", "dns_zone"],
    "security": ["security_control", "certificate", "secret", "identity_provider", "log_source"],
    "synthetic": ["synthetic_check", "saas_vendor"],
    "platform": ["monitoring_platform"],
}
RESOURCE_FAMILY = {r: fam for fam, rs in _FAMILY_BY_RESOURCE.items() for r in rs}

FAMILIES: dict[str, dict] = {
    "apm": {
        "telemetry": "APM traces and service pages are the primary surface. Use the service map to "
                     "see which dependency is contributing the failure, and the endpoint list to "
                     "find whether it is concentrated on one route.",
        "logs": "service:{svc} env:{env} status:error",
        "traces": "APM > Traces, filtered to `service:{svc} env:{env}`, sorted by duration or "
                  "filtered to errored spans.",
    },
    "container": {
        "telemetry": "The Kubernetes explorer shows pod state, restart counts and the controlling "
                     "workload. Events on the namespace usually explain evictions, scheduling "
                     "failures and OOM kills.",
        "logs": "kube_namespace:* service:{svc} env:{env} status:error",
        "traces": "APM traces where the workload is instrumented; otherwise container logs and "
                  "Kubernetes events are the trace substitute.",
    },
    "host": {
        "telemetry": "The host or VM page shows the process list, resource usage and the agent's own "
                     "health. Compare against neighbouring hosts in the same group.",
        "logs": "host:* service:{svc} env:{env}",
        "traces": "Not usually applicable at host level; use process metrics and system logs.",
    },
    "database": {
        "telemetry": "Database Monitoring shows query-level activity, waits and plan changes. Start "
                     "from the top queries by total time in the alert window.",
        "logs": "service:{svc} env:{env} source:database",
        "traces": "APM traces from calling services show the client-side view of the same "
                  "statements — useful to confirm whether the client or the engine is the "
                  "bottleneck.",
    },
    "messaging": {
        "telemetry": "Broker and consumer-group metrics: depth, arrival rate, drain rate, consumer "
                     "count and per-partition lag. Aggregate depth hides a single stuck partition, "
                     "so always look per partition.",
        "logs": "service:{svc} env:{env} status:error",
        "traces": "Distributed traces that span produce and consume, where propagation is "
                  "instrumented.",
    },
    "data": {
        "telemetry": "Pipeline run history, per-run duration and record counts. The run's own logs "
                     "name the failure more precisely than any metric.",
        "logs": "service:{svc} env:{env} source:pipeline",
        "traces": "Not usually applicable; the run history and job output are the equivalent trail.",
    },
    "cloud": {
        "telemetry": "The cloud provider integration surfaces resource-level metrics and platform "
                     "health. Check the provider's own status and the resource's activity log for "
                     "changes.",
        "logs": "service:{svc} env:{env} source:azure",
        "traces": "APM traces where an application sits in front of the resource.",
    },
    "network": {
        "telemetry": "Network device and path metrics: interface state, error counters, latency and "
                     "loss per hop. Network path tests localise the failing segment.",
        "logs": "service:{svc} env:{env} source:network",
        "traces": "Network path analysis rather than APM traces.",
    },
    "security": {
        "telemetry": "Security signals, the audit trail and the control's own reporting. Evidence "
                     "preservation matters more than speed here.",
        "logs": "service:{svc} env:{env} source:audit",
        "traces": "Audit-trail events are the trail; APM is rarely relevant.",
    },
    "synthetic": {
        "telemetry": "Synthetic test results with per-location breakdown, plus the vendor's public "
                     "status page. A single failing location is a probe problem, not an outage.",
        "logs": "service:{svc} env:{env}",
        "traces": "Synthetic test steps and, where enabled, the trace generated by the test request.",
    },
    "platform": {
        "telemetry": "Datadog's own usage and ingestion metrics, plus the platform's coverage "
                     "report. This class of alert means the estate may be going blind, so treat "
                     "loss of signal as the incident.",
        "logs": "service:{svc} env:{env}",
        "traces": "Not applicable; use ingestion and usage metrics.",
    },
}

IMPACT_BUSINESS = {
    "customer_impact": "Customers are affected now, or a mission-critical capability is unavailable. "
                       "Treat as an outage until proven otherwise.",
    "degradation": "The service still functions but measurably worse; a subset of traffic, users or "
                   "records is failing or delayed.",
    "risk": "Nothing is broken yet. A boundary will be crossed if nobody acts within the lead time "
            "this monitor provides — the cost of ignoring it is that it becomes an outage on "
            "somebody else's shift.",
    "hygiene": "No direct customer impact. Our ability to see, govern or recover the estate is "
               "reduced, which raises the cost and duration of the next real incident.",
}

IMPACT_TECHNICAL = {
    "customer_impact": "Requests are failing or the capability is unavailable. Dependent services "
                       "will begin timing out, retrying and shedding load, so the blast radius "
                       "grows the longer it runs.",
    "degradation": "Error budget is being consumed and latency or failure is propagating to callers. "
                   "Retries amplify the load, so a degradation can become an outage without any new "
                   "fault.",
    "risk": "The system is operating inside its limits but the margin is shrinking. Once the "
            "boundary is crossed the failure mode is usually abrupt rather than gradual.",
    "hygiene": "Coverage, configuration or recoverability has drifted from the declared standard. "
               "The immediate effect is invisible, which is precisely why it is worth fixing now.",
}
