"""Fail-closed HTTP adapter for the official CUMCM Q3 simulator."""
from __future__ import annotations

import copy
import json
import math
import threading
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

import requests


DEFAULT_BASE_URL = "http://127.0.0.1:2026"
DEFAULT_ARENA_ID = "default"


class OfficialSimulatorError(RuntimeError):
    """Base class for fail-closed official simulator errors."""


class OfficialTransportError(OfficialSimulatorError):
    """No trustworthy HTTP response was received after finite retries."""


class OfficialProtocolError(OfficialSimulatorError):
    """The server returned malformed or semantically invalid data."""


class OfficialActionRejected(OfficialSimulatorError):
    """The server formed a response but did not accept the action."""


def mask_robot_id(robot_id: str) -> str:
    """Return a stable-enough display mask without persisting the real id."""
    if len(robot_id) <= 2:
        return "*" * len(robot_id)
    return f"{robot_id[:1]}{'*' * min(8, len(robot_id) - 2)}{robot_id[-1:]}"


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


class OfficialRunLogger:
    """Append-only, robot-id-safe logs for one official rehearsal."""

    def __init__(self, run_dir: str | Path) -> None:
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self.started_at = time.time()
        self.started = time.perf_counter()
        self._lock = threading.Lock()
        for name in ("requests.jsonl", "responses.jsonl", "actions.jsonl", "run.log"):
            (self.run_dir / name).touch()

    def elapsed_s(self) -> float:
        return time.perf_counter() - self.started

    def _append_json(self, name: str, record: Mapping[str, Any]) -> None:
        line = json.dumps(_json_safe(record), ensure_ascii=False, allow_nan=False)
        with self._lock, (self.run_dir / name).open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def request(self, record: Mapping[str, Any]) -> None:
        self._append_json("requests.jsonl", record)

    def response(self, record: Mapping[str, Any]) -> None:
        self._append_json("responses.jsonl", record)

    def action(self, record: Mapping[str, Any]) -> None:
        self._append_json("actions.jsonl", record)

    def message(self, text: str) -> None:
        line = f"{self.elapsed_s():.6f}s {text}"
        with self._lock, (self.run_dir / "run.log").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        print(line, flush=True)


class OfficialHttpSimulatorAdapter:
    """Synchronous RobotAPI-compatible adapter for official HTTP actions."""

    def __init__(
        self,
        robot_id: str,
        base_url: str = DEFAULT_BASE_URL,
        arena_id: str = DEFAULT_ARENA_ID,
        timeout_s: float = 5.0,
        max_retries: int = 1,
        session: requests.Session | None = None,
        logger: OfficialRunLogger | None = None,
        request_id_factory: Callable[[str], str] | None = None,
    ) -> None:
        self.robot_id = self._validate_identifier(robot_id, "robot_id", 64)
        self.base_url = self._validate_base_url(base_url)
        if arena_id != DEFAULT_ARENA_ID:
            raise ValueError('arena_id must be "default"')
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout_s must be a positive finite number")
        if type(max_retries) is not int or not 0 <= max_retries <= 5:
            raise ValueError("max_retries must be an integer in 0..5")
        self.arena_id = arena_id
        self.timeout_s = float(timeout_s)
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self.logger = logger
        self._request_id_factory = request_id_factory or self._new_request_id
        self._action_lock = threading.Lock()
        self._action_context_provider: Callable[[], Mapping[str, Any]] | None = None
        self.current_measure_channel: int | None = None
        self.last_response: dict[str, Any] | None = None
        self.enter_response: dict[str, Any] | None = None
        self.exit_response: dict[str, Any] | None = None
        self.logical_action_count = 0
        self.http_attempt_count = 0
        self.retry_count = 0

    @staticmethod
    def _validate_identifier(value: str, name: str, max_bytes: int) -> str:
        if not isinstance(value, str) or not 1 <= len(value.encode("utf-8")) <= max_bytes:
            raise ValueError(f"{name} must contain 1..{max_bytes} UTF-8 bytes")
        if any(unicodedata.category(char) in ("Cc", "Cf") for char in value):
            raise ValueError(f"{name} contains a control or formatting character")
        return value

    @staticmethod
    def _validate_base_url(value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        if parsed.path not in ("", "/") or parsed.params or parsed.query or parsed.fragment:
            raise ValueError("base_url must not include a path, query, or fragment")
        return value.rstrip("/")

    @staticmethod
    def _new_request_id(prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex}"

    def set_action_context_provider(self, provider: Callable[[], Mapping[str, Any]]) -> None:
        self._action_context_provider = provider

    def _base_payload(self, prefix: str) -> dict[str, Any]:
        request_id = self._validate_identifier(self._request_id_factory(prefix), "request_id", 128)
        return {"arena_id": self.arena_id, "robot_id": self.robot_id, "request_id": request_id}

    @staticmethod
    def _validate_position(position: Any) -> tuple[float, float]:
        try:
            x, y = position
            x, y = float(x), float(y)
        except (TypeError, ValueError) as exc:
            raise ValueError("position must contain exactly two numeric coordinates") from exc
        if not all(math.isfinite(value) and abs(value) <= 2_000_000 for value in (x, y)):
            raise ValueError("position coordinates must be finite and within +/-2000000")
        return x, y

    @staticmethod
    def _validate_channel(channel: Any) -> int:
        if type(channel) is not int or not 1 <= channel <= 20:
            raise ValueError("channel must be an integer in 1..20")
        return channel

    def _masked_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        masked = copy.deepcopy(dict(payload))
        masked["robot_id"] = mask_robot_id(self.robot_id)
        return masked

    def redact_for_logging(self, value: Any) -> Any:
        """Recursively remove a robot id even if an error response echoes it."""
        if isinstance(value, str):
            return value.replace(self.robot_id, mask_robot_id(self.robot_id))
        if isinstance(value, Mapping):
            return {str(key): self.redact_for_logging(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.redact_for_logging(item) for item in value]
        return value

    def _context(self) -> dict[str, Any]:
        if self._action_context_provider is None:
            return {}
        try:
            return copy.deepcopy(dict(self._action_context_provider()))
        except Exception as exc:
            return {"context_error": f"{type(exc).__name__}:{exc}"}

    @staticmethod
    def _http_hint(status: int) -> str:
        return {
            400: "invalid JSON, missing/invalid field, identifier, channel, or coordinate",
            404: "unknown endpoint or simulator mode is unavailable",
            405: "endpoint requires POST",
            409: "request_id conflict or concurrent different actions",
            413: "request body is too large",
            415: "Content-Type or Content-Encoding is unsupported",
            429: "traffic protection or idempotency-record limit was triggered",
            500: "official simulator internal error",
        }.get(status, "unexpected HTTP status")

    @staticmethod
    def _transport_message(exc: BaseException, url: str) -> str:
        detail = str(exc)
        lowered = detail.lower()
        if "10061" in detail or "connection refused" in lowered:
            reason = "connection refused"
        elif isinstance(exc, requests.exceptions.Timeout):
            reason = "network timeout; action response is unknown"
        elif "remote end closed" in lowered or "connection aborted" in lowered:
            reason = "connection closed; the rehearsal may have ended or the interface may be closed"
        else:
            reason = "connection failed; the rehearsal may have ended or the interface may be closed"
        return f"{reason}: {url}: {detail}"

    @staticmethod
    def _require_common(body: Mapping[str, Any], path: str) -> None:
        if body.get("accepted") is not True:
            raise OfficialActionRejected(f"accepted=false for {path}: {dict(body)!r}")
        for name in ("real_timestamp_ms", "virtual_time_s"):
            value = body.get(name)
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise OfficialProtocolError(f"{path} response has invalid {name}: {value!r}")

    def _validate_response(self, path: str, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise OfficialProtocolError(f"malformed JSON for {path}: expected an object")
        self._require_common(body, path)
        if path == "/enter":
            for name in ("max_virtual_duration_s", "max_real_duration_s", "remaining_real_duration_s"):
                value = body.get(name)
                if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    raise OfficialProtocolError(f"/enter response has invalid {name}: {value!r}")
        elif path == "/measure":
            kind = body.get("measure_result")
            if kind not in ("no_signal", "near", "direction"):
                raise OfficialProtocolError(f"invalid measure_result: {kind!r}")
            if kind == "direction":
                svd = body.get("svd_deg")
                if not isinstance(svd, (int, float)) or not math.isfinite(float(svd)) or not 0 <= float(svd) < 360:
                    raise OfficialProtocolError(f"direction response has invalid svd_deg: {svd!r}")
            elif "svd_deg" in body:
                raise OfficialProtocolError(f"{kind} response must not contain svd_deg")
        elif path == "/clear":
            if body.get("clear_result") not in ("success", "no_target_in_range"):
                raise OfficialProtocolError(f"invalid clear_result: {body.get('clear_result')!r}")
        elif path == "/exit" and not isinstance(body.get("exit_reason"), str):
            raise OfficialProtocolError("/exit response has invalid exit_reason")
        return dict(body)

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request_id = payload["request_id"]
        url = self.base_url + path
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        context = self._context()
        started = time.perf_counter()
        attempts = 0
        final_status = None
        final_body = None
        final_error = None
        with self._action_lock:
            self.logical_action_count += 1
            for attempt in range(1, self.max_retries + 2):
                attempts = attempt
                self.http_attempt_count += 1
                if attempt > 1:
                    self.retry_count += 1
                request_record = {
                    "wall_elapsed_s": self.logger.elapsed_s() if self.logger else None,
                    "request_id": request_id,
                    "path": path,
                    "attempt": attempt,
                    "is_retry": attempt > 1,
                    "payload": self._masked_payload(payload),
                    "context": context,
                }
                if self.logger:
                    self.logger.request(request_record)
                try:
                    response = self.session.post(url, data=encoded, headers=headers, timeout=self.timeout_s)
                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                    final_error = self.redact_for_logging(self._transport_message(exc, url))
                    if self.logger:
                        self.logger.response({
                            "wall_elapsed_s": self.logger.elapsed_s(), "request_id": request_id,
                            "path": path, "attempt": attempt, "exception": type(exc).__name__,
                            "error": final_error, "response_unknown": True,
                        })
                    if attempt <= self.max_retries:
                        continue
                    break
                except requests.exceptions.RequestException as exc:
                    final_error = self.redact_for_logging(f"HTTP client failure for {url}: {exc}")
                    if self.logger:
                        self.logger.response({
                            "wall_elapsed_s": self.logger.elapsed_s(), "request_id": request_id,
                            "path": path, "attempt": attempt, "exception": type(exc).__name__,
                            "error": final_error, "response_unknown": True,
                        })
                    break

                final_status = response.status_code
                try:
                    final_body = response.json()
                except ValueError:
                    safe_text = self.redact_for_logging(response.text[:500])
                    final_error = (
                        f"malformed JSON for {path}; HTTP {response.status_code}; "
                        f"body={safe_text!r}"
                    )
                    if self.logger:
                        self.logger.response({
                            "wall_elapsed_s": self.logger.elapsed_s(), "request_id": request_id,
                            "path": path, "attempt": attempt, "http_status": response.status_code,
                            "error": final_error, "body_text": safe_text,
                        })
                    break
                if self.logger:
                    self.logger.response({
                        "wall_elapsed_s": self.logger.elapsed_s(), "request_id": request_id,
                        "path": path, "attempt": attempt, "http_status": response.status_code,
                        "accepted": final_body.get("accepted") if isinstance(final_body, dict) else None,
                        "body": self.redact_for_logging(final_body),
                    })
                if response.status_code != 200:
                    accepted = final_body.get("accepted") if isinstance(final_body, dict) else None
                    final_error = (
                        f"HTTP {response.status_code} ({self._http_hint(response.status_code)}) for {path}; "
                        f"accepted={accepted!r}; response={self.redact_for_logging(final_body)!r}"
                    )
                    break
                try:
                    validated = self._validate_response(path, final_body)
                except OfficialSimulatorError as exc:
                    final_error = self.redact_for_logging(str(exc))
                    break
                self.last_response = validated
                if self.logger:
                    self.logger.action({
                        "wall_elapsed_s": self.logger.elapsed_s(), "wall_action_duration_s": time.perf_counter() - started,
                        "request_id": request_id, "path": path, "attempts": attempts,
                        "retries": attempts - 1, "http_status": final_status, "accepted": True,
                        "position": payload.get("position"), "channel": payload.get("channel"),
                        "virtual_time_before_s": context.get("virtual_time_before_s"),
                        "virtual_time_after_s": validated.get("virtual_time_s"),
                        "real_timestamp_ms": validated.get("real_timestamp_ms"),
                        "measure_result": validated.get("measure_result"), "svd_deg": validated.get("svd_deg"),
                        "clear_result": validated.get("clear_result"), "context": context,
                    })
                return validated

        if self.logger:
            self.logger.action({
                "wall_elapsed_s": self.logger.elapsed_s(), "wall_action_duration_s": time.perf_counter() - started,
                "request_id": request_id, "path": path, "attempts": attempts,
                "retries": max(0, attempts - 1), "http_status": final_status,
                "accepted": final_body.get("accepted") if isinstance(final_body, dict) else None,
                "position": payload.get("position"), "channel": payload.get("channel"),
                "virtual_time_before_s": context.get("virtual_time_before_s"),
                "exception": final_error, "context": context,
            })
        if final_status is not None and final_status != 200:
            raise OfficialActionRejected(final_error)
        if final_error and final_error.startswith("malformed JSON"):
            raise OfficialProtocolError(final_error)
        if final_body is not None:
            if isinstance(final_body, dict) and final_body.get("accepted") is not True:
                raise OfficialActionRejected(final_error)
            raise OfficialProtocolError(final_error or f"invalid response for {path}")
        raise OfficialTransportError(final_error or f"no response received for {path}")

    def enter(self) -> dict[str, Any]:
        response = self._post("/enter", self._base_payload("enter"))
        self.enter_response = response
        return response

    def measure(self, position: Any, channel: int) -> dict[str, Any]:
        x, y = self._validate_position(position)
        channel = self._validate_channel(channel)
        payload = self._base_payload("measure")
        payload.update({"position": {"x": x, "y": y}, "channel": channel})
        response = self._post("/measure", payload)
        self.current_measure_channel = channel
        return response

    def clear(self, position: Any, channel: int) -> dict[str, Any]:
        x, y = self._validate_position(position)
        channel = self._validate_channel(channel)
        payload = self._base_payload("clear")
        payload.update({"position": {"x": x, "y": y}, "channel": channel})
        return self._post("/clear", payload)

    def exit(self) -> dict[str, Any]:
        response = self._post("/exit", self._base_payload("exit"))
        self.exit_response = response
        return response
