"""Live libjuju → jubilant recording example (carry (d)).

Drives a small libjuju session (deploy ubuntu, wait_for_idle, status) through
the RecordingLibjuju driver and writes a SessionLog to disk. The log is
byte-compatible with the canonical SCHEMA; the existing codegen consumes it
unchanged.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from extensions.libjuju.recording import RecordingLibjuju
from juju.model import Model


async def main(log_path: Path, model_name: str) -> None:
    """Record a libjuju session to the given log path."""
    model = Model()
    await model.connect(model_name=model_name)
    try:
        with RecordingLibjuju(output_log_path=log_path, model=model_name):
            await model.deploy("ubuntu", application_name="ubuntu")
            await model.wait_for_idle(apps=["ubuntu"], timeout=600, wait_for_active=True)
            # Application.Get is bucket-1; brackets wait_for_idle so trailing
            # synthesis (carry b) has two user-facing RPCs to sit between.
            _ = await model.applications["ubuntu"].get_config()
    finally:
        await model.disconnect()


if __name__ == "__main__":
    log_path = Path(sys.argv[1])
    model_name = sys.argv[2]
    asyncio.run(main(log_path, model_name))
