"""Minimal .env loader (no third-party deps)."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


def load_env(path: Path | None = None) -> dict[str, str]:
    env_file = path or ENV_PATH
    values: dict[str, str] = {}
    if env_file.exists():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            values[key] = value
            os.environ.setdefault(key, value)
    return values


def get_env(name: str, default: str = "") -> str:
    load_env()
    return os.environ.get(name, default).strip()


def upsert_env(updates: dict[str, str], path: Path | None = None) -> None:
    env_file = path or ENV_PATH
    existing: dict[str, str] = {}
    lines: list[str] = []
    if env_file.exists():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            if not raw.strip() or raw.strip().startswith("#") or "=" not in raw:
                lines.append(raw)
                continue
            key, value = raw.split("=", 1)
            key = key.strip()
            if key in updates:
                lines.append(f"{key}={updates[key]}")
                existing[key] = updates[key]
            else:
                lines.append(raw)
                existing[key] = value.strip()
    for key, value in updates.items():
        if key not in existing:
            lines.append(f"{key}={value}")
    env_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    for key, value in updates.items():
        os.environ[key] = value
