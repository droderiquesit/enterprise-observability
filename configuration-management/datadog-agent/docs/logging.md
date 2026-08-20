# Application logging (Serilog)

```
Application → Serilog (compact JSON) → Datadog Agent → Datadog Logs
```

## Why JSON and not a grok pattern

A grok pattern is a second copy of the log format, maintained by a different
team, that breaks silently when the application changes a message. JSON moves
the contract into the application where it belongs and reduces the Agent's job
to reading a file.

## Required fields

`timestamp`, `level`, `message`, `service`, `env`, `version`, `trace_id`,
`span_id`, `correlation_id`, `request_id`, `host`, `team`, `application`,
`exception`.

`service`/`env`/`version` are what let Datadog join a log line to the metric and
the trace from the same request. Without all three the log is searchable and
not correlatable.

```csharp
Log.Logger = new LoggerConfiguration()
    .Enrich.FromLogContext()
    .Enrich.WithProperty("service", "reporting-portal")
    .Enrich.WithProperty("env", env)
    .Enrich.WithProperty("version", version)
    .WriteTo.File(new CompactJsonFormatter(),
                  @"C:\logs\reporting-portal\log-.json",
                  rollingInterval: RollingInterval.Day,
                  retainedFileCountLimit: 7)
    .CreateLogger();
```

`retainedFileCountLimit` matters: unbounded rolling files fill the disk, and
the Agent then collects a growing set of files it has already read.

## What the profile prevents

- **Debug and Verbose dropped at the Agent**, not at an indexing filter.
  Dropping them later means paying to transmit and ingest them first — the
  difference between a logging bill and a logging incident.
- **Health probes excluded.** The highest-volume, lowest-value lines in any web
  application.
- **Recursive paths refused.** `C:\**\*.log` finds IIS logs, Windows logs,
  another application's logs and eventually the Agent's own — a feedback loop
  that ends in a full disk. The renderer rejects the pattern.
- **Duplicate paths refused.** Collecting one file twice bills twice and
  double-counts every log-derived metric.
- **A cap of 8 log sources per node**, because a node collecting more than that
  is usually collecting something it did not mean to.

## Multiline

Java and SQL Server logs declare an explicit start pattern. Without one a
single stack trace becomes forty log lines and every error-rate signal is wrong
by a factor nobody can predict.
