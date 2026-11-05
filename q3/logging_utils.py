"""Compact JSON and CSV logging for evaluations and GA generations."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def write_json(path: str | Path, value: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(_jsonable(value), ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def save_evaluation(path: str | Path, evaluation: Any, debug_trace: bool = False) -> Path:
    payload = _jsonable(evaluation)
    if not debug_trace:
        for episode in payload.get("episodes", []):
            episode.pop("action_trace", None)
    return write_json(path, payload)


def append_evaluation_csv(path: str | Path, evaluation: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "seeds": ";".join(map(str, evaluation.seeds)),
        "mission_failure_count": evaluation.fitness.mission_failure_count,
        "timeout_count": evaluation.fitness.timeout_count,
        "missed_source_count": evaluation.fitness.missed_source_count,
        "cvar95_time_s": evaluation.fitness.cvar95_time_s,
        "mean_time_s": evaluation.fitness.mean_time_s,
        "params_json": json.dumps(evaluation.params.to_dict(), ensure_ascii=False, sort_keys=True),
    }
    exists = target.exists()
    with target.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        if not exists:
            writer.writeheader()
        writer.writerow(row)
    return target
