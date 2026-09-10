"""Emit jubilant code for recorded ``juju.cli("revoke-secret", ...)`` calls."""

from __future__ import annotations

from typing import Any


def emit(event: dict[str, Any], indent: int) -> str:
    """Emit a ``juju.cli("revoke-secret", ...)`` call for this recorded event.

    Corresponds to ``Secrets.RevokeSecret``.  jubilant has no
    ``revoke_secret()`` client method — checked at 1.12.0, not just the 1.10
    ``SECRETS-GAPS.md`` was written against — so this uses ``juju.cli()``, the
    public escape hatch (``jubilant/_juju.py:527``, already used by jubilant's
    own ``bootstrap()``).  Same route the 4 CMR ops and the 8 ``Application.*``
    ops took; the sibling ``secret_grant`` emitter can call
    ``juju.grant_secret()`` directly only because that method happens to exist.

    ``juju revoke-secret <ID>|<name> <application>[,<application>...]``
    (verified against juju 3.6.27).  A multi-application revoke is rendered
    as the comma-joined list the CLI accepts; the correlator no longer
    narrows it to the first target.
    """
    args = event["args"]
    identifier = args.get("identifier") or ""
    app = args.get("app") or ""
    apps = ",".join(app) if isinstance(app, list) else app
    return " " * indent + f'juju.cli("revoke-secret", {identifier!r}, {apps!r})'
