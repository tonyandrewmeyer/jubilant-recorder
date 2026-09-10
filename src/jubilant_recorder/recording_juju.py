"""A jubilant ``Juju`` wrapper that records every call it makes."""

from __future__ import annotations

import contextlib
import dataclasses
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import jubilant
from jubilant.statustypes import Status

from jubilant_recorder.events import EventEnvelope
from jubilant_recorder.redaction import redact_config_dict, redact_payload, redact_string
from jubilant_recorder.session_log import SessionLog, _format_ts

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path


@dataclasses.dataclass
class _CLICapture:
    args: tuple[str, ...]
    start_ts: datetime
    end_ts: datetime
    stdout: str
    stderr: str
    exit_code: int = 0


def _infer_app_name(charm: str) -> str:
    last = charm.split("/")[-1]
    return last.split(".")[0]


def _redact_args(args_dict: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for k, v in args_dict.items():
        if isinstance(v, str):
            result[k], _ = redact_string(v)
        elif isinstance(v, dict):
            result[k], _ = redact_config_dict(v)
        else:
            result[k] = v
    return result


class RecordingJuju(jubilant.Juju):
    """A jubilant.Juju subclass that records all operations to a SessionLog."""

    def __init__(self, *, session_log: SessionLog, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._session_log = session_log
        self._suppress_recording: int = 0
        # The argv of the most recent `_cli()` call, held until either a
        # typed emitter claims it or the next `_cli()` flushes it as an
        # untyped one. See `_flush_pending_capture`.
        self._pending_capture: _CLICapture | None = None

    def _cli(
        self,
        *args: str,
        include_model: bool = True,
        stdin: str | None = None,
        log: bool = True,
        timeout: float | None = None,
    ) -> tuple[str, str]:
        if self._suppress_recording > 0:
            return jubilant.Juju._cli(
                self, *args, include_model=include_model, stdin=stdin, log=log, timeout=timeout
            )

        # Anything the previous call left unclaimed was a jubilant method
        # with no typed override here — flush it before this call's argv
        # replaces it, so the session log keeps the order they happened in.
        self._flush_pending_capture()

        start_ts = datetime.now(UTC)
        exc = None
        try:
            stdout, stderr = jubilant.Juju._cli(
                self, *args, include_model=include_model, stdin=stdin, log=log, timeout=timeout
            )
        except jubilant.CLIError as e:
            exc = e
            stdout, stderr = e.stdout or "", e.stderr or ""
        end_ts = datetime.now(UTC)
        self._pending_capture = _CLICapture(
            args=args,
            start_ts=start_ts,
            end_ts=end_ts,
            stdout=stdout,
            stderr=stderr,
            exit_code=exc.returncode if exc is not None else 0,
        )
        if exc is not None:
            raise exc
        return stdout, stderr

    def _flush_pending_capture(self) -> None:
        """Record an unclaimed ``_cli()`` call as a raw-argv event.

        `jubilant.Juju` has some thirty-odd public methods and this class
        overrides nine of them. Every other one — `ssh`, `exec`, `scp`,
        `refresh`, `trust`, `add_machine`, `model_config`, the secret
        readers — went through `_cli()`, had its argv captured into
        `_pending_capture`, and was then silently dropped, because nothing
        ever read that field. A scripted session that used any of them
        produced a test with those steps simply missing.

        Rather than write and maintain an override per method, the argv is
        recorded in the shape the PATH shim writes, and codegen's existing
        argv translation (`codegen/cli_translate.py`) turns it into the
        typed jubilant call or `juju.cli(...)`. One translation table, two
        front-ends.

        No model snapshot is taken: `_cli()` runs on every jubilant call
        including the nine typed ones, and snapshotting here would double
        the cost of a recording to add nothing the typed paths do not
        already capture. An untyped step is recorded, and carries no
        derived assertion.
        """
        capture = self._pending_capture
        self._pending_capture = None
        if capture is None or self._suppress_recording > 0:
            return
        argv = [redact_string(a)[0] for a in capture.args]
        stdout, _ = redact_string(capture.stdout)
        event = EventEnvelope(
            seq=self._session_log.next_seq(),
            op="shell",
            ts=_format_ts(capture.start_ts),
            args={"argv": argv, "basename": "juju", "source": "jubilant"},
            result={
                "captured": True,
                "exit_code": capture.exit_code,
                "stdout": stdout,
                "stderr": None,
                "stdout_truncated": False,
            },
            model_snapshot_before=None,
            model_snapshot_after=None,
            assertions=[],
            gesture=None,
            duration_ms=(capture.end_ts - capture.start_ts).total_seconds() * 1000,
        )
        self._session_log.append_event(event)

    def _take_snapshot(self) -> dict[str, Any] | None:
        self._suppress_recording += 1
        try:
            stdout, _ = self._cli("status", "--format", "json", log=False)
            status_json = json.loads(stdout)
            captured_at = _format_ts(datetime.now(UTC))
            return _parse_snapshot(status_json, captured_at)
        except Exception:
            return None
        finally:
            self._suppress_recording -= 1

    def _emit_event(
        self,
        op: str,
        args_dict: dict[str, Any],
        result_dict: dict[str, Any],
        snap_before: dict[str, Any] | None,
        snap_after: dict[str, Any] | None,
        start_ts: datetime,
        end_ts: datetime,
    ) -> None:
        # This call is being recorded with its own typed op, so the raw
        # argv `_cli()` captured for it is not also wanted.
        self._pending_capture = None
        duration_ms = (end_ts - start_ts).total_seconds() * 1000
        redacted_args = _redact_args(args_dict)
        # Results matter at least as much as args: `juju run` action output and
        # relation data are where charms hand back generated passwords and
        # connection strings. redact_payload walks the whole nested structure.
        redacted_result, _ = redact_payload(result_dict)
        event = EventEnvelope(
            seq=self._session_log.next_seq(),
            op=op,
            ts=_format_ts(start_ts),
            args=redacted_args,
            result=redacted_result,
            model_snapshot_before=snap_before,
            model_snapshot_after=snap_after,
            assertions=[],
            gesture=None,
            duration_ms=duration_ms,
        )
        self._session_log.append_event(event)

    def _inject_gesture_event(
        self,
        *,
        op: str,
        gesture: dict[str, Any],
        args: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:
        snap = self._take_snapshot()
        now = datetime.now(UTC)
        event = EventEnvelope(
            seq=self._session_log.next_seq(),
            op=op,
            ts=_format_ts(now),
            args=args or {},
            result=result or {},
            model_snapshot_before=snap,
            model_snapshot_after=snap,
            assertions=[],
            gesture=gesture,
            duration_ms=0.0,
        )
        self._session_log.append_event(event)

    def deploy(
        self,
        charm: Any,
        app: str | None = None,
        *,
        attach_storage: Any = None,
        base: str | None = None,
        bind: Any = None,
        channel: str | None = None,
        config: Any = None,
        constraints: Any = None,
        force: bool = False,
        num_units: int = 1,
        overlays: Any = (),
        resources: Any = None,
        revision: int | None = None,
        storage: Any = None,
        to: Any = None,
        trust: bool = False,
    ) -> None:
        snap_before = self._take_snapshot()
        start_ts = datetime.now(UTC)
        exc = None
        try:
            super().deploy(
                charm,
                app,
                attach_storage=attach_storage,
                base=base,
                bind=bind,
                channel=channel,
                config=config,
                constraints=constraints,
                force=force,
                num_units=num_units,
                overlays=overlays,
                resources=resources,
                revision=revision,
                storage=storage,
                to=to,
                trust=trust,
            )
        except jubilant.CLIError as e:
            exc = e
        end_ts = datetime.now(UTC)
        snap_after = None if exc else self._take_snapshot()
        app_name = app if app is not None else _infer_app_name(str(charm))
        result: dict[str, Any] = {"app_name": app_name}
        if exc:
            result["error"] = str(exc)
        # Capture the full kwarg surface of jubilant.deploy() so codegen can
        # round-trip a faithful invocation. Earlier versions only carried
        # app/channel/charm/config/num_units/resources, which silently lost
        # `base`, `revision`, `trust`, `constraints` and friends — surfaced by
        # the step 3 live-run carry. Keep keys present even when None so the
        # session-log shape is stable; codegen drops defaults from the emit.
        self._emit_event(
            "deploy",
            {
                "app": app,
                "attach_storage": attach_storage,
                "base": base,
                "bind": bind,
                "channel": channel,
                "charm": str(charm),
                "config": dict(config) if config else {},
                "constraints": constraints,
                "force": force,
                "num_units": num_units,
                "overlays": list(overlays) if overlays else [],
                "resources": dict(resources) if resources else {},
                "revision": revision,
                "storage": storage,
                "to": to,
                "trust": trust,
            },
            result,
            snap_before,
            snap_after,
            start_ts,
            end_ts,
        )
        if exc:
            raise exc

    def integrate(self, app1: str, app2: str, *, via: Any = None) -> None:
        snap_before = self._take_snapshot()
        start_ts = datetime.now(UTC)
        exc = None
        try:
            super().integrate(app1, app2, via=via)
        except jubilant.CLIError as e:
            exc = e
        end_ts = datetime.now(UTC)
        snap_after = None if exc else self._take_snapshot()
        result: dict[str, Any] = {}
        if exc:
            result["error"] = str(exc)
        self._emit_event(
            "integrate",
            {"app1_endpoint": app1, "app2_endpoint": app2},
            result,
            snap_before,
            snap_after,
            start_ts,
            end_ts,
        )
        if exc:
            raise exc

    def remove_relation(self, app1: str, app2: str, *, force: bool = False) -> None:
        snap_before = self._take_snapshot()
        start_ts = datetime.now(UTC)
        exc = None
        try:
            super().remove_relation(app1, app2, force=force)
        except jubilant.CLIError as e:
            exc = e
        end_ts = datetime.now(UTC)
        snap_after = None if exc else self._take_snapshot()
        result: dict[str, Any] = {}
        if exc:
            result["error"] = str(exc)
        self._emit_event(
            "remove_integration",
            {"app1_endpoint": app1, "app2_endpoint": app2},
            result,
            snap_before,
            snap_after,
            start_ts,
            end_ts,
        )
        if exc:
            raise exc

    def config(
        self,
        app: str,
        values: Any = None,
        *,
        app_config: bool = False,
        reset: Any = (),
    ) -> Any:
        is_get = values is None and not reset
        snap_before = self._take_snapshot()
        start_ts = datetime.now(UTC)
        exc = None
        config_result = None
        try:
            config_result = super().config(app, values, app_config=app_config, reset=reset)  # pyright: ignore[reportCallIssue]
        except jubilant.CLIError as e:
            exc = e
        end_ts = datetime.now(UTC)
        snap_after = None if exc else self._take_snapshot()
        if is_get:
            op = "config_get"
            args_dict: dict[str, Any] = {"app": app, "keys": None}
            result: dict[str, Any] = {
                "values": dict(config_result) if config_result is not None else {}
            }
        else:
            op = "config"
            args_dict = {"app": app, "values": dict(values) if values else {}}
            result = {}
        if exc:
            result["error"] = str(exc)
        self._emit_event(op, args_dict, result, snap_before, snap_after, start_ts, end_ts)
        if exc:
            raise exc
        return config_result

    def run(
        self,
        unit: str,
        action: str,
        params: Any = None,
        *,
        wait: float | None = None,
    ) -> jubilant.Task:
        snap_before = self._take_snapshot()
        start_ts = datetime.now(UTC)
        exc = None
        task = None
        try:
            task = super().run(unit, action, params, wait=wait)
        except jubilant.CLIError as e:
            exc = e
        end_ts = datetime.now(UTC)
        snap_after = None if exc else self._take_snapshot()
        if task is not None:
            result: dict[str, Any] = {
                "success": task.success,
                "results": dict(task.results),
                "message": task.message or None,
            }
        else:
            result = {"success": False, "results": {}, "message": None}
        if exc:
            result["error"] = str(exc)
        self._emit_event(
            "run",
            {"unit": unit, "action": action, "params": dict(params) if params else {}},
            result,
            snap_before,
            snap_after,
            start_ts,
            end_ts,
        )
        if exc:
            raise exc
        return task  # type: ignore[return-value]

    def status(self) -> Status:
        snap_before = self._take_snapshot()
        start_ts = datetime.now(UTC)
        exc = None
        jubilant_status = None
        try:
            jubilant_status = super().status()
        except jubilant.CLIError as e:
            exc = e
        end_ts = datetime.now(UTC)
        snap_after = None if exc else self._take_snapshot()
        result: dict[str, Any] = {"snapshot": snap_after}
        if exc:
            result["error"] = str(exc)
        self._emit_event("status", {}, result, snap_before, snap_after, start_ts, end_ts)
        if exc:
            raise exc
        return jubilant_status  # type: ignore[return-value]

    def wait(
        self,
        ready: Callable[[Status], bool],
        *,
        error: Callable[[Status], bool] | None = None,
        delay: float = 1.0,
        timeout: float | None = None,
        successes: int = 3,
    ) -> Status:
        snap_before = self._take_snapshot()
        start_ts = datetime.now(UTC)
        exc = None
        result_status = None
        self._suppress_recording += 1
        try:
            result_status = super().wait(
                ready,
                error=error,
                delay=delay,
                timeout=timeout,
                successes=successes,
            )
        except Exception as e:
            exc = e
        finally:
            self._suppress_recording -= 1
        end_ts = datetime.now(UTC)
        snap_after = self._take_snapshot()
        settled_at = _format_ts(end_ts) if exc is None else None
        result: dict[str, Any] = {"settled_at": settled_at}
        if exc:
            result["error"] = str(exc)
        self._emit_event(
            "wait_for_idle",
            {"apps": None, "timeout": timeout},
            result,
            snap_before,
            snap_after,
            start_ts,
            end_ts,
        )
        if exc:
            raise exc
        return result_status  # type: ignore[return-value]

    def remove_application(
        self, *app: str, destroy_storage: bool = False, force: bool = False
    ) -> None:
        snap_before = self._take_snapshot()
        start_ts = datetime.now(UTC)
        exc = None
        try:
            super().remove_application(*app, destroy_storage=destroy_storage, force=force)
        except jubilant.CLIError as e:
            exc = e
        end_ts = datetime.now(UTC)
        snap_after = None if exc else self._take_snapshot()
        result: dict[str, Any] = {}
        if exc:
            result["error"] = str(exc)
        self._emit_event(
            "remove_application",
            {"app": list(app) if len(app) > 1 else app[0] if app else ""},
            result,
            snap_before,
            snap_after,
            start_ts,
            end_ts,
        )
        if exc:
            raise exc

    def add_unit(
        self,
        app: str,
        *,
        attach_storage: Any = None,
        num_units: int = 1,
        to: Any = None,
    ) -> None:
        snap_before = self._take_snapshot()
        start_ts = datetime.now(UTC)
        exc = None
        try:
            super().add_unit(app, attach_storage=attach_storage, num_units=num_units, to=to)
        except jubilant.CLIError as e:
            exc = e
        end_ts = datetime.now(UTC)
        snap_after = None if exc else self._take_snapshot()
        result: dict[str, Any] = {}
        if exc:
            result["error"] = str(exc)
        self._emit_event(
            "scale",
            {"app": app, "units": num_units},
            result,
            snap_before,
            snap_after,
            start_ts,
            end_ts,
        )
        if exc:
            raise exc

    @classmethod
    @contextlib.contextmanager
    def start(cls, log_path: Path | str, **kwargs: Any) -> Generator[RecordingJuju, None, None]:
        from jubilant_recorder.gestures import _active_session

        model = kwargs.get("model", "") or ""
        with SessionLog.open(log_path, model=model) as log:
            juju = cls(session_log=log, **kwargs)
            token = _active_session.set(juju)
            try:
                yield juju
            except Exception as e:
                # The call that raised was still a call the session made.
                juju._flush_pending_capture()
                log.record_session_error(e)
                raise
            else:
                # The last jubilant call in the body may have been one with
                # no typed override, and nothing after it to flush it.
                juju._flush_pending_capture()
            finally:
                _active_session.reset(token)


def _parse_snapshot(status_json: dict[str, Any], captured_at: str) -> dict[str, Any]:
    status = Status._from_dict(status_json)
    apps: dict[str, Any] = {}
    for app_name, app_status in status.apps.items():
        units: dict[str, Any] = {}
        for unit_name, unit_status in app_status.units.items():
            units[unit_name] = {
                "workload_status": unit_status.workload_status.current or "unknown",
                "workload_message": unit_status.workload_status.message or "",
                "agent_status": unit_status.juju_status.current or "unknown",
            }
        apps[app_name] = {"units": units}

    seen: set[frozenset[str]] = set()
    relations: list[dict[str, Any]] = []
    for app_name, app_status in status.apps.items():
        for local_ep, related_list in app_status.relations.items():
            for rel in related_list:
                remote_app = rel.related_app
                remote_ep = _find_remote_endpoint(status, remote_app, app_name)
                local_full = f"{app_name}:{local_ep}"
                remote_full = f"{remote_app}:{remote_ep}" if remote_ep else remote_app
                pair = frozenset([local_full, remote_full])
                if pair not in seen:
                    seen.add(pair)
                    endpoints = sorted([local_full, remote_full])
                    relations.append({"endpoints": endpoints})

    return {
        "schema_version": 1,
        "captured_at": captured_at,
        "apps": apps,
        "relations": relations,
    }


def _find_remote_endpoint(status: Status, remote_app: str, local_app: str) -> str | None:
    if remote_app not in status.apps:
        return None
    remote_app_status = status.apps[remote_app]
    for ep, related_list in remote_app_status.relations.items():
        for rel in related_list:
            if rel.related_app == local_app:
                return ep
    return None
