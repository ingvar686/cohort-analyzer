"""Local, restart-safe category automation for the Altegio reports server.

The worker polls appointment creation time, so it catches up after the computer
or server was offline. Configuration and the idempotency journal stay under
data/automation/ and never contain client names, phones, or tokens.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from altegio_client import AltegioClient, AltegioError
from upsell_categories import add_client_category, list_categories


class AutomationStore:
    def __init__(self, data_dir: Path):
        self.root = data_dir / "automation"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, location_id: int, kind: str) -> Path:
        return self.root / f"{kind}_{int(location_id)}.json"

    def configured_locations(self) -> list[int]:
        found = []
        for path in self.root.glob("settings_*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                location_id = int(value.get("location_id") or 0)
                if location_id > 0 and value.get("enabled") is True:
                    found.append(location_id)
            except (OSError, ValueError, TypeError):
                continue
        return sorted(set(found))

    def _read(self, path: Path, default: dict[str, Any]) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else dict(default)
        except (OSError, ValueError):
            return dict(default)

    def _write(self, path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)

    def settings(self, location_id: int) -> dict[str, Any]:
        with self._lock:
            return self._read(self._path(location_id, "settings"), {
                "schema_version": 1, "location_id": int(location_id), "enabled": False,
                "settings": {"protectFirstSource": True, "interval": "5"}, "rules": [],
            })

    def save_settings(self, location_id: int, value: dict[str, Any], connection_fingerprint: str) -> dict[str, Any]:
        rules = value.get("rules")
        settings = value.get("settings") or {}
        if not isinstance(rules, list) or len(rules) > 200:
            raise ValueError("Некорректный список правил автоматизации.")
        enabled = value.get("enabled") is True
        interval = str(settings.get("interval", "5"))
        if interval not in {"1", "5", "15"}:
            if enabled:
                raise ValueError("Для активной автоматизации выберите интервал 1, 5 или 15 минут.")
            interval = "5"
        normalized = []
        used_widgets = set()
        for row in rules:
            if not isinstance(row, dict):
                raise ValueError("Некорректное правило автоматизации.")
            widget_id, category_id = row.get("widgetId"), row.get("categoryId")
            if type(widget_id) is not int or widget_id <= 0 or type(category_id) is not int or category_id <= 0:
                raise ValueError("В каждом правиле нужны корректные ID виджета и категории.")
            if widget_id in used_widgets:
                raise ValueError("Для одного виджета может быть только одно правило.")
            used_widgets.add(widget_id)
            mode = row.get("clientMode")
            trigger = row.get("trigger")
            if mode not in {"no_visits", "explicit", "any"} or trigger not in {"booking", "arrived", "paid"}:
                raise ValueError("Проверьте условие нового клиента и момент назначения категории.")
            if enabled and row.get("enabled", True) and (trigger != "booking" or mode != "no_visits"):
                raise ValueError("Для фонового режима выберите «При бронировании» и проверку по истории визитов. Документированная запись Altegio не гарантирует отдельную пометку нового клиента.")
            for key in ("startDate", "endDate"):
                value_date = str(row.get(key) or "")
                if value_date:
                    try:
                        datetime.strptime(value_date, "%Y-%m-%d")
                    except ValueError as exc:
                        raise ValueError("Проверьте даты периода кампании.") from exc
            normalized.append({
                "id": str(row.get("id") or f"widget-{widget_id}")[:100],
                "name": str(row.get("name") or "")[:100],
                "widgetId": widget_id, "categoryId": category_id,
                "clientMode": mode, "trigger": trigger,
                "startDate": str(row.get("startDate") or "")[:10],
                "endDate": str(row.get("endDate") or "")[:10],
                "enabled": row.get("enabled") is not False,
            })
        if enabled and not any(row["enabled"] for row in normalized):
            raise ValueError("Включите хотя бы одно правило перед активацией.")
        result = {
            "schema_version": 1, "location_id": int(location_id), "enabled": enabled,
            "connection_fingerprint": str(connection_fingerprint),
            "settings": {"protectFirstSource": settings.get("protectFirstSource") is not False, "interval": interval},
            "rules": normalized, "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        with self._lock:
            old = self.settings(location_id)
            self._write(self._path(location_id, "settings"), result)
            state = self.state(location_id)
            connection_changed = old.get("connection_fingerprint") != connection_fingerprint
            if connection_changed:
                state = {"location_id": int(location_id), "cursor": None, "enabled_since": None,
                         "processed": [], "pending": [], "first_sources": [], "last_run": None,
                         "last_error": None, "scanned": 0, "added": 0, "existing": 0, "skipped": 0}
            if enabled and (connection_changed or not old.get("enabled") or not state.get("cursor")):
                # Every activation starts at the current time; turning the
                # feature back on does not silently process bookings made while disabled.
                now = datetime.now(timezone.utc)
                state["cursor"] = now.isoformat(timespec="seconds")
                state["enabled_since"] = now.isoformat(timespec="seconds")
                self._write(self._path(location_id, "state"), state)
        return result

    def state(self, location_id: int) -> dict[str, Any]:
        with self._lock:
            return self._read(self._path(location_id, "state"), {
                "location_id": int(location_id), "cursor": None, "processed": [], "pending": [],
                "last_run": None, "last_error": None, "scanned": 0, "added": 0,
                "existing": 0, "skipped": 0,
            })

    def update_state(self, location_id: int, state: dict[str, Any]) -> None:
        with self._lock:
            self._write(self._path(location_id, "state"), state)

    def status(self, location_id: int) -> dict[str, Any]:
        config, state = self.settings(location_id), self.state(location_id)
        return {
            "enabled": bool(config.get("enabled")),
            "last_run": state.get("last_run"), "last_error": state.get("last_error"),
            "scanned": int(state.get("scanned") or 0), "added": int(state.get("added") or 0),
            "existing": int(state.get("existing") or 0), "skipped": int(state.get("skipped") or 0),
            "pending": len(state.get("pending") or []),
        }


def _resource(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    attrs = row.get("attributes")
    if isinstance(attrs, dict):
        result = dict(attrs)
        result.setdefault("id", row.get("id"))
        return result
    return row


def _page(api: AltegioClient, location_id: int, params: dict[str, Any]) -> list[dict[str, Any]]:
    base = api.api_base.rsplit("/api/", 1)[0] + "/api/v2"
    rows: list[dict[str, Any]] = []
    page = 1
    while page <= 1000:
        payload = api.request("GET", f"{base}/locations/{location_id}/appointments",
                              params={**params, "page": page, "limit": 100})
        chunk = payload.get("data") or []
        if not isinstance(chunk, list):
            raise RuntimeError("Altegio вернул список бронирований в неожиданном формате.")
        rows.extend(_resource(item) for item in chunk)
        if len(chunk) < 100:
            return rows
        page += 1
    raise RuntimeError("Слишком много страниц бронирований за один проход; курсор не продвинут.")


def _datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _aware_datetime(value: Any, default_zone=None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=default_zone or timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _bool_paid(row: dict[str, Any]) -> bool:
    return any(row.get(key) is True or row.get(key) == 1 for key in ("paid_in_full", "paid_full", "is_paid"))


class AutomationWorker:
    def __init__(self, store: AutomationStore, location_ids, sync_lock: threading.Lock, poll_seconds: int = 30):
        self.store, self.location_ids, self.sync_lock = store, location_ids, sync_lock
        self.poll_seconds = max(15, int(poll_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._next_run: dict[int, float] = {}
        self._timezones: dict[int, Any] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="AltegioAutomation", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                locations = self.location_ids()
            except Exception:
                locations = []
            for location_id in locations:
                if self._stop.is_set():
                    break
                config = self.store.settings(location_id)
                if not config.get("enabled"):
                    self._next_run.pop(location_id, None)
                    continue
                interval = int(config.get("settings", {}).get("interval", "5")) * 60
                if time.monotonic() < self._next_run.get(location_id, 0):
                    continue
                self._next_run[location_id] = time.monotonic() + interval
                if not self.sync_lock.acquire(blocking=False):
                    continue
                try:
                    self._poll_location(location_id, config)
                except Exception as exc:  # keep the loop alive; the cursor remains retryable
                    state = self.store.state(location_id)
                    state["last_error"] = self._safe_error(exc)
                    state["last_run"] = datetime.now().astimezone().isoformat(timespec="seconds")
                    self.store.update_state(location_id, state)
                finally:
                    self.sync_lock.release()
            self._stop.wait(self.poll_seconds)

    def _poll_location(self, location_id: int, config: dict[str, Any]) -> None:
        from branch_access import connection_id
        if config.get("connection_fingerprint") != connection_id():
            raise PermissionError("Подключение Altegio изменилось; сохраните настройки заново для нового аккаунта.")
        state = self.store.state(location_id)
        rules = [r for r in config.get("rules", []) if r.get("enabled")]
        api = AltegioClient(location_id=location_id)
        zone = self._location_timezone(api, location_id)
        now_utc = datetime.now(timezone.utc) - timedelta(seconds=30)
        now = now_utc.astimezone(zone).replace(tzinfo=None)
        cursor = _aware_datetime(state.get("cursor"))
        enabled_since = _aware_datetime(state.get("enabled_since")) or cursor or now_utc
        # The v2 appointments endpoint filters by appointment date, not by
        # booking creation time. Scan a rolling schedule window, then use
        # created_datetime locally to catch bookings made while this PC slept.
        scan_start = (now - timedelta(days=365)).replace(hour=0, minute=0, second=0)
        scan_end = now + timedelta(days=365)
        categories = {int(row["id"]): row for row in list_categories(api)}

        processed = set(str(value) for value in state.get("processed", []))
        first_sources = {str(key): int(value) for key, value in (state.get("first_sources") or {}).items()}
        pending = {str(row.get("appointment_id")) + ":" + str(row.get("rule_id")): row
                   for row in state.get("pending", []) if isinstance(row, dict)}
        counts = {key: 0 for key in ("scanned", "added", "existing", "skipped")}
        failed: set[str] = set()
        records = _page(api, location_id, {
            "filter[date_intersect_from]": scan_start.strftime("%Y-%m-%dT%H:%M:%S"),
            "filter[date_intersect_to]": scan_end.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        records.sort(key=lambda row: (_datetime(row.get("created_datetime")) or now, int(row.get("id") or 0)))
        for appointment in records:
            counts["scanned"] += 1
            appointment_id = str(appointment.get("id") or "")
            if not appointment_id:
                continue
            created_utc = _aware_datetime(appointment.get("created_datetime"), zone)
            if created_utc and created_utc < enabled_since:
                continue
            widget_id = int(appointment.get("bookform_id") or 0)
            for rule in rules:
                if int(rule.get("widgetId") or 0) != widget_id:
                    continue
                key = appointment_id + ":" + str(rule.get("id"))
                if key in processed:
                    continue
                try:
                    outcome = self._apply(api, location_id, appointment, rule, categories, config, first_sources)
                    counts[outcome] += 1
                    processed.add(key)
                    pending.pop(key, None)
                except Exception as exc:
                    pending[key] = {"appointment_id": appointment_id, "rule_id": str(rule.get("id"))}
                    failed.add(key)
                    state["last_error"] = self._safe_error(exc)

        # Commit the high-water mark only after every appointment page was read.
        # Per-event failures remain in `pending` and are retried next cycle.
        state.update({
            "cursor": now_utc.isoformat(timespec="seconds"), "enabled_since": enabled_since.isoformat(timespec="seconds"),
            "processed": list(processed)[-20000:], "pending": list(pending.values())[-1000:],
            "first_sources": dict(list(first_sources.items())[-20000:]),
            "last_run": datetime.now().astimezone().isoformat(timespec="seconds"),
            "scanned": counts["scanned"], "added": counts["added"],
            "existing": counts["existing"], "skipped": counts["skipped"],
            "last_error": state.get("last_error") if failed or pending else None,
        })
        self.store.update_state(location_id, state)

    def _location_timezone(self, api: AltegioClient, location_id: int):
        if location_id in self._timezones:
            return self._timezones[location_id]
        from env_loader import get_env
        key = get_env("ALTEGIO_TIMEZONE")
        if not key:
            try:
                base = api.api_base.rsplit("/api/", 1)[0] + "/api/v2"
                payload = api.request("GET", f"{base}/locations/{location_id}")
                row = _resource(payload.get("data") or {})
                key = str(row.get("timezone_name") or "")
            except Exception:
                key = ""
        try:
            zone = ZoneInfo(key) if key else datetime.now().astimezone().tzinfo
        except (ZoneInfoNotFoundError, ValueError):
            zone = datetime.now().astimezone().tzinfo
        self._timezones[location_id] = zone
        return zone

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        status = getattr(exc, "status", None)
        return f"Altegio HTTP {status}" if status else type(exc).__name__

    def _apply(self, api: AltegioClient, location_id: int, appointment: dict[str, Any], rule: dict[str, Any], categories: dict[int, dict[str, Any]], config: dict[str, Any], first_sources: dict[str, int]) -> str:
        status = str(appointment.get("attendance_status_slug") or appointment.get("status") or "").lower()
        if status == "cancelled" or appointment.get("deleted") is True:
            return "skipped"
        if rule.get("trigger") != "booking":
            raise ValueError("Для фоновой обработки пока поддерживается только событие «При бронировании».")
        client_id = int(appointment.get("client_id") or 0)
        if client_id <= 0 or int(appointment.get("clients_count") or 1) != 1:
            return "skipped"
        created = _datetime(appointment.get("created_datetime"))
        day = created.date().isoformat() if created else ""
        if not created or (rule.get("startDate") and day < rule["startDate"]) or (rule.get("endDate") and day > rule["endDate"]):
            return "skipped"
        category_id = int(rule.get("categoryId") or 0)
        if category_id not in categories:
            raise ValueError("Категория из правила больше не найдена в выбранном филиале.")
        if rule.get("clientMode") == "explicit":
            flag = appointment.get("is_new_client")
            if not isinstance(flag, bool):
                return "skipped"
            if not flag:
                return "skipped"
        elif rule.get("clientMode") == "no_visits":
            if self._prior_paid_visits(api, location_id, client_id, created):
                return "skipped"
        elif rule.get("clientMode") != "any":
            raise ValueError("Неизвестное условие нового клиента.")
        source_key = str(client_id)
        source = int(rule.get("widgetId") or 0)
        if config.get("settings", {}).get("protectFirstSource"):
            previous_source = first_sources.get(source_key)
            if previous_source and previous_source != source:
                return "skipped"
        added = add_client_category(api, client_id, categories[category_id], categories.values())
        first_sources.setdefault(source_key, source)
        return "added" if added else "existing"

    def _prior_paid_visits(self, api: AltegioClient, location_id: int, client_id: int, created: datetime) -> int:
        rows = _page(api, location_id, {
            "filter[client_id]": client_id,
            "filter[date_intersect_from]": "2000-01-01T00:00:00",
            "filter[date_intersect_to]": created.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        return sum(1 for row in rows
                   if str(row.get("attendance_status_slug") or row.get("status") or "").lower() in {"attended", "arrived"}
                   and _bool_paid(row)
                   and (_datetime(row.get("date")) or datetime.max) < created)
