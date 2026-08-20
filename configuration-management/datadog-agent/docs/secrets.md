# Secrets

**No secret is ever written to this repository, to a rendered configuration, or
to a command line.**

Rendered configuration contains `ENC[handle]`. The Agent's secret backend
resolves it at start-up and is the only component that sees a value.

That is not just hygiene — it is what makes the rest of the design possible. A
rendered config can be committed, diffed, hashed for drift detection and pasted
into a ticket precisely because it is not sensitive. You cannot compare hashes
of files people are not allowed to read.

## The backend

Azure Key Vault, reached through a small executable the Agent shells out to,
authenticating with the host's managed identity. It holds `secrets/get` on the
named handles and nothing else: it cannot list, cannot write, and cannot read a
secret it was not explicitly granted.

## Handles

`policies/secrets.yaml` — each entry names its purpose, owner, rotation period
and scope. It contains handles, never values.

## Why not a command-line argument

A key passed to a script lands in the NinjaOne activity log, the local event
log and the process table. `DD-Agent-Install.ps1` fetches it into a variable
scoped to the call and clears it in a `finally`. A test asserts no script
passes a literal secret as an argument.

## Enforcement

- `tools/agent_config.py` scans every rendered configuration for API-key,
  app-key and inline-credential shapes; `ENC[...]` is the one allowed form.
- Tests assert both that no rendered config trips the scanner **and** that the
  scanner fires on a planted credential — a secret scan that never fires is
  indistinguishable from one that is not running.
- The committed source files are scanned too, so a secret cannot be introduced
  in a layer and reach a render.
