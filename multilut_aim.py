#!/usr/bin/env python3
"""Aim training core for MultiLUT Controller: crosshair config + session stats.

Módulo puro Python (sem GTK) para poder ser testado sem ambiente gráfico.
Mantém o mesmo estilo do multilut_core: gravação atômica, erros em
português e validação de todos os valores antes de escrever em disco.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import math
import re

from multilut_core import MultiLUTError, _atomic_write


TRAINING_MODES: tuple[str, ...] = ("flick",)
TRAINING_MODE_LABELS = {"flick": "Flick"}
MAX_SESSIONS = 500

CROSSHAIR_DEFAULTS: dict = {
    "style": "cross",
    "color": "#00FF66",
    "length": 10,
    "thickness": 2,
    "gap": 4,
    "dot": False,
    "dot_size": 2,
    "outline": True,
    "opacity": 1.0,
}
CROSSHAIR_KEYS = tuple(CROSSHAIR_DEFAULTS)
_CROSSHAIR_LIMITS = {
    "length": (2, 40),
    "thickness": (1, 8),
    "gap": (0, 40),
    "dot_size": (1, 6),
}
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")

SESSION_REQUIRED_NUMBERS = (
    "targets",
    "misses",
    "avg_reaction_ms",
    "best_reaction_ms",
    "targets_per_minute",
    "duration_s",
)


def training_history_path() -> Path:
    return Path.home() / ".config/multilut-controller/training_history.json"


def _coerce_int(value, limits: tuple[int, int], default: int) -> int:
    low, high = limits
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return max(low, min(high, number))


def _coerce_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "sim")
    return default


def normalize_crosshair_config(raw: dict | None) -> dict:
    """Valida e limita as configurações do crosshair, retornando um dicionário seguro."""
    result = dict(CROSSHAIR_DEFAULTS)
    if not isinstance(raw, dict):
        return result
    color = raw.get("color")
    if isinstance(color, str) and _HEX_COLOR.match(color.strip()):
        result["color"] = color.strip().lower()
    for key, limits in _CROSSHAIR_LIMITS.items():
        result[key] = _coerce_int(raw.get(key), limits, CROSSHAIR_DEFAULTS[key])
    result["dot"] = _coerce_bool(raw.get("dot"), CROSSHAIR_DEFAULTS["dot"])
    result["outline"] = _coerce_bool(raw.get("outline"), CROSSHAIR_DEFAULTS["outline"])
    try:
        opacity = float(raw.get("opacity"))
    except (TypeError, ValueError):
        opacity = CROSSHAIR_DEFAULTS["opacity"]
    if math.isnan(opacity) or math.isinf(opacity):
        opacity = CROSSHAIR_DEFAULTS["opacity"]
    result["opacity"] = max(0.0, min(1.0, opacity))
    style = raw.get("style")
    result["style"] = style if style in ("cross",) else CROSSHAIR_DEFAULTS["style"]
    return {key: result[key] for key in CROSSHAIR_KEYS}


def crosshair_config_from_config(config: dict | None) -> dict:
    data = config.get("crosshair") if isinstance(config, dict) else None
    return normalize_crosshair_config(data)


def validate_training_session(data) -> list[str]:
    if not isinstance(data, dict):
        return ["A sessão de treino precisa ser um objeto."]
    errors: list[str] = []
    if data.get("mode") not in TRAINING_MODES:
        modes = ", ".join(TRAINING_MODES)
        errors.append(f"Modo de treino inválido; use um dos modos: {modes}.")
    for key in SESSION_REQUIRED_NUMBERS:
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"Campo {key} precisa ser um número.")
        elif not math.isfinite(float(value)) or value < 0:
            errors.append(f"Campo {key} precisa ser um número não negativo.")
    if "targets" in data and isinstance(data["targets"], (int, float)) and not isinstance(data["targets"], bool):
        if int(data["targets"]) <= 0:
            errors.append("A rodada precisa de pelo menos um alvo.")
    timestamp = data.get("timestamp")
    if timestamp is not None and not isinstance(timestamp, str):
        errors.append("O campo timestamp precisa ser um texto.")
    return errors


def _normalize_session(session: dict) -> dict:
    stored = {
        "timestamp": session.get("timestamp"),
        "mode": session["mode"],
        "targets": int(session["targets"]),
        "misses": int(session["misses"]),
        "avg_reaction_ms": round(float(session["avg_reaction_ms"]), 1),
        "best_reaction_ms": round(float(session["best_reaction_ms"]), 1),
        "targets_per_minute": round(float(session["targets_per_minute"]), 1),
        "duration_s": round(float(session["duration_s"]), 1),
    }
    if not isinstance(stored["timestamp"], str) or not stored["timestamp"]:
        stored["timestamp"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return stored


def load_training_sessions(path: Path | str | None = None, mode: str | None = None) -> list[dict]:
    target = Path(path) if path is not None else training_history_path()
    if not target.is_file():
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return []
    if not isinstance(data, list):
        return []
    sessions = [item for item in data if isinstance(item, dict)]
    if mode is not None:
        sessions = [item for item in sessions if item.get("mode") == mode]
    return sessions[-MAX_SESSIONS:]


def save_training_sessions(sessions: list[dict], path: Path | str | None = None) -> None:
    target = Path(path) if path is not None else training_history_path()
    payload = sessions[-MAX_SESSIONS:]
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    old_mode = target.stat().st_mode & 0o777 if target.exists() else 0o600
    _atomic_write(target, text, old_mode)


def append_training_session(session: dict, path: Path | str | None = None) -> dict:
    errors = validate_training_session(session)
    if errors:
        raise MultiLUTError("Sessão de treino inválida: " + " ".join(errors))
    stored = _normalize_session(session)
    sessions = load_training_sessions(path)
    sessions.append(stored)
    save_training_sessions(sessions, path)
    return stored


def clear_training_sessions(path: Path | str | None = None) -> None:
    save_training_sessions([], path)


def session_accuracy(session: dict) -> float:
    targets = float(session.get("targets", 0) or 0)
    misses = float(session.get("misses", 0) or 0)
    if targets + misses <= 0:
        return 0.0
    return 100.0 * targets / (targets + misses)


def summarize_sessions(sessions: list[dict]) -> dict:
    """Agrega sessões por modo; médias ponderadas pelo número de alvos."""
    rounds = len(sessions)
    total_targets = sum(int(item.get("targets", 0) or 0) for item in sessions)
    total_misses = sum(int(item.get("misses", 0) or 0) for item in sessions)
    if total_targets > 0:
        weight = float(total_targets)
        avg_reaction = sum(
            float(item.get("avg_reaction_ms", 0) or 0) * int(item.get("targets", 0) or 0)
            for item in sessions
        ) / weight
        avg_accuracy = sum(
            session_accuracy(item) * int(item.get("targets", 0) or 0)
            for item in sessions
        ) / weight
        avg_targets_per_minute = sum(
            float(item.get("targets_per_minute", 0) or 0) * int(item.get("targets", 0) or 0)
            for item in sessions
        ) / weight
    else:
        avg_reaction = 0.0
        avg_accuracy = 0.0
        avg_targets_per_minute = 0.0
    best_reaction_values = [
        float(item["best_reaction_ms"]) for item in sessions if item.get("best_reaction_ms")
    ]
    best_reaction = min(best_reaction_values) if best_reaction_values else 0.0
    best_accuracy = max((session_accuracy(item) for item in sessions), default=0.0)
    return {
        "rounds": rounds,
        "total_targets": total_targets,
        "total_misses": total_misses,
        "avg_reaction_ms": avg_reaction,
        "best_reaction_ms": best_reaction,
        "avg_accuracy": avg_accuracy,
        "best_accuracy": best_accuracy,
        "avg_targets_per_minute": avg_targets_per_minute,
    }


def moving_average(values: list[float], window: int = 5) -> list[float]:
    if window <= 0:
        raise ValueError("A janela da média móvel precisa ser positiva.")
    result: list[float] = []
    for index in range(len(values)):
        start = max(0, index - window + 1)
        chunk = values[start : index + 1]
        result.append(sum(chunk) / len(chunk))
    return result


def hex_to_rgb(color: str) -> tuple[float, float, float]:
    """Converte #RRGGBB em frações RGB (0–1); retorna verde padrão se inválido."""
    if not isinstance(color, str) or not _HEX_COLOR.match(color.strip()):
        return (0.0, 1.0, 0.4)
    text = color.strip().lstrip("#")
    return (
        int(text[0:2], 16) / 255.0,
        int(text[2:4], 16) / 255.0,
        int(text[4:6], 16) / 255.0,
    )
