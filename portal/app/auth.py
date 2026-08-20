"""Identity, and the single place an SSO integration lands (§49).

THERE IS NO IDENTITY PROVIDER IN THIS ENVIRONMENT, so this module does not
pretend to authenticate anyone. What it does is make the integration point a
real, tested seam rather than a paragraph in a README:

    every request → `identify(headers)` → a Principal → `require_read(...)`

An enterprise SSO deployment terminates authentication at the reverse proxy in
front of this process (Entra ID application proxy, Azure Front Door with Entra
authentication, or an OIDC sidecar such as oauth2-proxy). The proxy validates
the token and forwards the assertion as request headers; this module reads
them. That split is deliberate: token validation, key rotation and session
handling are solved problems that do not belong in a read-only view, and a
hand-rolled OIDC client in this file would be the least reviewed security code
in the repository.

TO ENABLE SSO
  1. Put the portal behind the proxy; deny direct access to PORTAL_PORT.
  2. Have the proxy inject the headers named in `HEADER_*` below.
  3. Set PORTAL_REQUIRE_SSO=1 so an un-asserted request is refused rather than
     falling back to the anonymous local principal.
  4. Map the IdP group that should see this page to `ROLE_EXEC` via
     PORTAL_EXEC_GROUPS (comma-separated).

WHAT THIS MODULE CANNOT DO
  Grant write access. There is no write path in the application: no handler
  mutates state, `datadog.py` issues only GETs, and the portal holds no
  database. The role model exists to decide who may LOOK, and that is all it
  can ever decide.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# Header names, matching what the common proxies emit. They are configurable
# because the header set is the one thing that genuinely differs per IdP.
HEADER_USER = os.environ.get("PORTAL_SSO_USER_HEADER", "X-Auth-Request-Email")
HEADER_NAME = os.environ.get("PORTAL_SSO_NAME_HEADER", "X-Auth-Request-Preferred-Username")
HEADER_GROUPS = os.environ.get("PORTAL_SSO_GROUPS_HEADER", "X-Auth-Request-Groups")

ROLE_EXEC = "executive_viewer"       # read-only; the only role that can view
ROLE_ANON = "local_anonymous"        # no SSO in front of the process

READ_ROLES = {ROLE_EXEC, ROLE_ANON}


@dataclass(frozen=True)
class Principal:
    subject: str
    display_name: str
    role: str
    groups: tuple[str, ...] = field(default_factory=tuple)
    authenticated: bool = False

    def to_dict(self) -> dict:
        # Groups are deliberately NOT returned to the browser: they are IdP
        # membership data, useful to nobody on the page and a small privacy
        # leak in a screenshot.
        return {
            "subject": self.subject,
            "display_name": self.display_name,
            "role": self.role,
            "authenticated": self.authenticated,
            "read_only": True,
            "can_write": False,
        }


def _exec_groups() -> set[str]:
    raw = os.environ.get("PORTAL_EXEC_GROUPS", "")
    return {g.strip() for g in raw.split(",") if g.strip()}


def require_sso() -> bool:
    return os.environ.get("PORTAL_REQUIRE_SSO", "").lower() in ("1", "true", "yes")


def identify(headers) -> Principal:
    """Resolve the caller from proxy-asserted headers.

    `headers` is anything with a case-insensitive `.get`. When no assertion is
    present the caller is the anonymous local principal — which is correct for
    `python portal/server.py` on a laptop and is refused outright when
    PORTAL_REQUIRE_SSO is set, so a misconfigured proxy fails closed instead of
    silently serving the estate to the internet.
    """
    subject = (headers.get(HEADER_USER) or "").strip()
    if not subject:
        return Principal(subject="anonymous", display_name="Local user",
                         role=ROLE_ANON, authenticated=False)
    groups = tuple(g.strip() for g in (headers.get(HEADER_GROUPS) or "").split(",")
                   if g.strip())
    allowed = _exec_groups()
    # With no group allow-list configured, a valid SSO assertion is enough:
    # the proxy has already decided who may reach the application at all.
    role = ROLE_EXEC if (not allowed or allowed & set(groups)) else ""
    return Principal(subject=subject,
                     display_name=(headers.get(HEADER_NAME) or subject).strip(),
                     role=role, groups=groups, authenticated=True)


def authorize(principal: Principal) -> tuple[bool, str]:
    """May this principal read the portal? Returns (allowed, reason)."""
    if require_sso() and not principal.authenticated:
        return False, ("SSO is required (PORTAL_REQUIRE_SSO=1) but the request "
                       "carried no identity assertion from the proxy")
    if principal.role not in READ_ROLES:
        return False, ("authenticated, but not a member of any group mapped to the "
                       "executive read-only role (PORTAL_EXEC_GROUPS)")
    return True, ""
