"""Pull Altegio data over REST and rebuild portal JSON. Zero AI tokens."""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from altegio_client import AltegioClient, AltegioError
from env_loader import ROOT, get_env

DATA_DIR = ROOT / "data"
PORTAL_PATH = DATA_DIR / "portal.json"
SEED_PATH = DATA_DIR / "portal.seed.json"

ARRIVED = {"arrived", "client_came", "success", "completed"}


def month_age(first: str, current: str) -> int:
    fy, fm = map(int, first[:7].split("-"))
    cy, cm = map(int, current[:7].split("-"))
    return (cy - fy) * 12 + cm - fm


def parse_date(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    if "T" in text:
        text = text.split("T", 1)[0]
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return None


def category_names(client: dict[str, Any]) -> list[str]:
    names: list[str] = []
    # In Altegio, client classifications are commonly exposed as card tags.
    for item in (client.get("tags") or []) + (client.get("categories") or []):
        if isinstance(item, dict):
            title = item.get("title") or item.get("name")
            if title:
                names.append(str(title))
        elif item:
            names.append(str(item))
    for key in ("category", "client_category", "labels"):
        value = client.get(key)
        if isinstance(value, str) and value:
            names.append(value)
        elif isinstance(value, list):
            names.extend(str(x) for x in value if x)
    return list(dict.fromkeys(names))


def record_attendance(record: dict[str, Any]) -> str:
    attendance = record.get("attendance")
    visit = record.get("visit_attendance")
    if isinstance(attendance, str):
        return attendance.lower()
    # Altegio docs: 1=came, 2=confirmed. Classic YClients often used 2=arrived.
    mapping = {
        1: "arrived",
        2: "arrived",
        -1: "client_cancelled",
        0: "waiting",
    }
    if isinstance(attendance, int):
        return mapping.get(attendance, str(attendance))
    if isinstance(visit, int):
        return mapping.get(visit, str(visit))
    return str(attendance or visit or "").lower()


def record_revenue(record: dict[str, Any]) -> float:
    # Do NOT read paid_full/paid here — those are 0/1 flags, not money.
    total = 0.0
    for service in record.get("services") or []:
        try:
            total += float(
                service.get("cost")
                or service.get("manual_cost")
                or service.get("first_cost")
                or service.get("amount_paid")
                or 0
            )
        except (TypeError, ValueError):
            pass
    if total > 0:
        return total
    for key in ("cost", "services_cost", "amount", "sold_amount", "paid_amount"):
        value = record.get(key)
        if value is None:
            continue
        try:
            num = float(value)
        except (TypeError, ValueError):
            continue
        # Ignore tiny flag-like values when services list is empty.
        if num > 1 or key in {"cost", "services_cost", "sold_amount", "paid_amount"}:
            return num
    return total


def record_services(record: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for service in record.get("services") or []:
        title = service.get("title") or service.get("name")
        if title:
            names.append(str(title))
    return names


def record_is_fully_paid(record: dict[str, Any], sold: float, paid: float = 0) -> bool:
    status = str(record.get("payment_status") or "").lower()
    if status in {"unpaid", "partly_paid", "partially_paid"}:
        return False
    if record.get("amount_due") is not None and float(record["amount_due"]) > 0.005:
        return False
    if status in {"fully_paid", "overpaid"}:
        return True
    for key in ("paid_in_full", "paid_full"):
        if record.get(key) is not None:
            return record[key] in (True, 1, "1", "true")
    # The legacy `paid` field is a flag only when boolean or 0/1.
    flag = record.get("paid")
    if isinstance(flag, bool) or (isinstance(flag, int) and flag in (0, 1)):
        return bool(flag)
    return sold > 0 and paid + 0.005 >= sold


def record_payment_history(record: dict[str, Any], sold: float) -> tuple[float, list[dict[str, Any]]]:
    """Return received amount and payment rows when the API includes them."""
    raw = record.get("payments") or record.get("payment_history") or record.get("payment") or []
    if isinstance(raw, dict):
        raw = [raw]
    rows: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            amount = float(item.get("amount") or item.get("sum") or item.get("paid") or 0)
        except (TypeError, ValueError):
            continue
        if amount <= 0:
            continue
        rows.append({
            "date": parse_date(item.get("date") or item.get("datetime")),
            "amount": round(amount, 2),
            "method": item.get("method") or item.get("pay_type") or item.get("account_title") or "",
        })
    paid = sum(row["amount"] for row in rows)
    if not rows and record_is_fully_paid(record, sold):
        paid = sold
        rows.append({"date": parse_date(record.get("date") or record.get("datetime")), "amount": round(sold, 2), "method": "paid"})
    return round(paid, 2), rows


def client_id_of(record: dict[str, Any]) -> int | None:
    client = record.get("client")
    if isinstance(client, dict):
        value = client.get("id")
        return int(value) if value is not None else None
    value = record.get("client_id")
    return int(value) if value is not None else None


def build_portal_from_api(client: AltegioClient) -> dict[str, Any]:
    lookback = int(get_env("SYNC_LOOKBACK_DAYS", "1460") or "1460")
    as_of = date.today()
    start = as_of - timedelta(days=lookback)
    company = client.company()
    clients_raw = client.iter_clients()
    # Fetch records in 90-day chunks to stay under API limits.
    records: list[dict[str, Any]] = []
    cursor = start
    while cursor <= as_of:
        chunk_end = min(cursor + timedelta(days=89), as_of)
        records.extend(client.iter_records(cursor.isoformat(), chunk_end.isoformat()))
        cursor = chunk_end + timedelta(days=1)

    clients_by_id = {int(c["id"]): c for c in clients_raw if c.get("id") is not None}
    # Current client tags are authoritative: removed categories must not be
    # restored from historical appointment comments.
    def client_categories(cid: int, raw: dict[str, Any]) -> list[str]:
        return category_names(raw)

    visits_by_client: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        cid = client_id_of(record)
        visit_date = parse_date(record.get("date") or record.get("datetime"))
        if cid is None or not visit_date:
            continue
        attendance = record_attendance(record)
        sold = record_revenue(record)
        revenue, payments = record_payment_history(record, sold)
        if attendance not in ARRIVED and not payments:
            continue
        services = record_services(record)
        visits_by_client[cid].append(
            {
                "date": visit_date,
                "revenue": round(revenue, 2),
                "sold": round(sold, 2),
                "paid": round(revenue, 2),
                "paid_in_full": record_is_fully_paid(record, sold, revenue),
                "payments": payments,
                "appointment_id": record.get("id"),
                "service": services[0] if services else "Service",
                "services": services,
                "attendance": attendance or "arrived",
            }
        )

    portal_clients: list[dict[str, Any]] = []
    category_counts: Counter[str] = Counter()
    directory: list[dict[str, Any]] = []
    for cid, raw in clients_by_id.items():
        cats = client_categories(cid, raw)
        category_counts.update(cats)
        directory.append({"id": cid, "name": raw.get("name") or raw.get("display_name") or f"Client {cid}", "categories": cats})
    for entry in directory:
        entry["category_count"] = len(entry["categories"])
    for cid, visits in visits_by_client.items():
        raw = clients_by_id.get(cid) or {}
        cats = client_categories(cid, raw)
        visits = sorted(visits, key=lambda v: v["date"])
        arrived_visits = [v for v in visits if v["attendance"] in ARRIVED]
        first = arrived_visits[0]["date"] if arrived_visits else visits[0]["date"]
        enriched = []
        for visit in visits:
            enriched.append(
                {
                    "date": visit["date"],
                    "revenue": visit["paid"],
                    "sold": visit["sold"],
                    "paid": visit["paid"],
                    "paid_in_full": visit["paid_in_full"],
                    "payments": visit["payments"],
                    "appointment_id": visit["appointment_id"],
                    "attendance": visit["attendance"],
                    "service": visit["service"],
                    "services": visit.get("services") or [visit["service"]],
                    "age": month_age(first, visit["date"]),
                }
            )
        portal_clients.append(
            {
                "id": cid,
                "name": raw.get("name") or raw.get("display_name") or f"Client {cid}",
                "phone": str(raw.get("phone") or ""),
                "campaign": cats[0] if cats else "Без категории",
                "categories": cats,
                "first_visit": first,
                "visits": enriched,
                "visit_count": len(enriched),
                "revenue": round(sum(v["revenue"] for v in enriched), 2),
                "sold": round(sum(v["sold"] for v in enriched), 2),
                "payment_history": [p for v in enriched for p in v.get("payments", [])],
            }
        )

    portal_clients.sort(key=lambda c: (c["campaign"], c["first_visit"], c["name"]))
    cohort_by_id = {c["id"]: c for c in portal_clients}
    for entry in directory:
        cohort = cohort_by_id.get(entry["id"], {})
        entry["first_visit"] = cohort.get("first_visit")
        entry["visits"] = cohort.get("visits", [])
        entry["payment_history"] = cohort.get("payment_history", [])
        entry["total_spent_in_snapshot"] = cohort.get("sold", 0)
        entry["paid_in_snapshot"] = cohort.get("revenue", 0)

    # RFM over all clients who have visits in the window.
    rfm_groups = {"VIP": 0, "Постоянные": 0, "Спящие": 0, "В зоне риска": 0}
    for cid, visits in visits_by_client.items():
        if not visits:
            continue
        last = max(v["date"] for v in visits)
        days = (as_of - date.fromisoformat(last)).days
        revenue = sum(v["revenue"] for v in visits)
        count = len(visits)
        if days > 90:
            rfm_groups["В зоне риска"] += 1
        elif days > 60:
            rfm_groups["Спящие"] += 1
        elif revenue >= 1000 and count >= 5:
            rfm_groups["VIP"] += 1
        else:
            rfm_groups["Постоянные"] += 1
    base_size = sum(rfm_groups.values()) or len(clients_raw) or 1

    # Cross-sell from arrived multi-service visits.
    singles: Counter[str] = Counter()
    pairs: Counter[tuple[str, str]] = Counter()
    multi = 0
    for record in records:
        if record_attendance(record) not in ARRIVED:
            continue
        services = sorted(set(record_services(record)))
        if not services:
            continue
        singles.update(services)
        if len(services) > 1:
            multi += 1
            pairs.update(itertools.combinations(services, 2))
    top_services = [name for name, _ in singles.most_common(7)]
    matrix = [
        [pairs.get(tuple(sorted((a, b))), 0) if a != b else singles[a] for b in top_services]
        for a in top_services
    ]
    pair_rows = [{"a": a, "b": b, "count": count} for (a, b), count in pairs.most_common(8)]
    opportunities = []
    for service, count in singles.most_common(8):
        paired = sum(v for (a, b), v in pairs.items() if service in (a, b))
        solo = max(0, count - paired)
        opportunities.append({"service": service, "solo": solo, "potential": round(solo * 45, 2)})

    # Capacity: last 30 days.
    period_start = as_of - timedelta(days=29)
    recent = [
        r
        for r in records
        if (d := parse_date(r.get("date") or r.get("datetime"))) and d >= period_start.isoformat()
    ]
    staff_stats: dict[str, dict[str, Any]] = {}
    appointments_plot = []
    for record in recent:
        staff = record.get("staff") or {}
        staff_name = staff.get("name") if isinstance(staff, dict) else str(staff or "Staff")
        bucket = staff_stats.setdefault(
            staff_name,
            {"name": staff_name, "revenue": 0.0, "appointments": 0, "scheduled_hours": 160},
        )
        bucket["revenue"] += record_revenue(record)
        bucket["appointments"] += 1
        visit_date = parse_date(record.get("date") or record.get("datetime"))
        hour = None
        raw_dt = str(record.get("datetime") or record.get("date") or "")
        if "T" in raw_dt:
            try:
                hour = datetime.fromisoformat(raw_dt.replace("Z", "+00:00")).hour
            except ValueError:
                hour = None
        if visit_date and hour is not None:
            appointments_plot.append({"date": visit_date, "hour": hour, "staff": staff_name})
    staff_rows = []
    for name, stats in sorted(staff_stats.items(), key=lambda x: -x[1]["revenue"])[:4]:
        appts = stats["appointments"]
        hours = stats["scheduled_hours"]
        occupancy = round((appts * 1.0 / max(hours, 1)) * 100, 1)
        avg_check = round(stats["revenue"] / appts, 2) if appts else 0
        staff_rows.append(
            {
                "name": name,
                "occupancy": occupancy,
                "revenue": round(stats["revenue"], 2),
                "avg_check": avg_check,
                "scheduled_hours": hours,
            }
        )
    recent_revenue = round(sum(record_revenue(r) for r in recent), 2)
    recent_count = len(recent)
    avg_check = round(recent_revenue / recent_count, 2) if recent_count else 0
    location_occupancy = round((recent_count / max(len(staff_rows) * 160, 1)) * 100, 1)

    return {
        "as_of": as_of.isoformat(),
        "synced_at": datetime.now().isoformat(timespec="seconds"),
        "source": "altegio_api",
        "location": {
            "id": int(company.get("id") or client.location_id),
            "name": company.get("title") or company.get("name") or "Casa House",
            "currency": company.get("currency_iso") or company.get("currency") or "EUR",
        },
        "campaigns": sorted(category_counts),
        "categories": [{"title": title, "client_count": count} for title, count in sorted(category_counts.items())],
        "directory": directory,
        "default_budgets": {},
        "clients": portal_clients,
        "rfm": {
            "base_size": base_size,
            "segments": [
                {"name": "VIP", "count": rfm_groups["VIP"], "color": "#f0b429"},
                {"name": "Постоянные", "count": rfm_groups["Постоянные"], "color": "#2f80ed"},
                {"name": "Спящие", "count": rfm_groups["Спящие"], "color": "#9b51e0"},
                {"name": "В зоне риска", "count": rfm_groups["В зоне риска"], "color": "#e05260"},
            ],
            "rules": "VIP: активны ≤60 дней и lifetime spend ≥€1,000; Постоянные: остальные активные ≤60 дней; Спящие: 61–90 дней; Риск: >90 дней.",
        },
        "cross_sell": {
            "services": top_services,
            "matrix": matrix,
            "pairs": pair_rows,
            "opportunities": opportunities,
            "arrived_with_multiple_services": multi,
        },
        "capacity": {
            "period": f"{period_start.isoformat()} — {as_of.isoformat()}",
            "location": {
                "occupancy": location_occupancy,
                "revenue": recent_revenue,
                "avg_check": avg_check,
                "appointments": recent_count,
            },
            "staff": staff_rows,
            "appointments": appointments_plot,
        },
        "overview": {
            "period": f"{start.isoformat()} — {as_of.isoformat()}",
            "revenue": round(sum(c["revenue"] for c in portal_clients), 2),
            "appointments": len(records),
            "completed": sum(1 for r in records if record_attendance(r) in ARRIVED),
            "clients": len(portal_clients),
            "raw_clients": len(clients_raw),
            "raw_records": len(records),
        },
    }


def load_seed() -> dict[str, Any]:
    if SEED_PATH.exists():
        return json.loads(SEED_PATH.read_text(encoding="utf-8"))
    # Fallback: import static demo from build_reports_portal.
    from build_reports_portal import portal_data

    data = portal_data([])
    data["source"] = "seed_demo"
    data["synced_at"] = None
    return data


def save_portal(data: dict[str, Any], path: Path = PORTAL_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    import os
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False, suffix='.tmp') as tmp:
        tmp.write(json.dumps(data, ensure_ascii=False, indent=2))
        temp_path = Path(tmp.name)
    try:
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)
    return path


def ensure_seed() -> Path:
    if not SEED_PATH.exists():
        save_portal(load_seed(), SEED_PATH)
    if not PORTAL_PATH.exists():
        save_portal(json.loads(SEED_PATH.read_text(encoding="utf-8")), PORTAL_PATH)
    return PORTAL_PATH


def sync_now() -> dict[str, Any]:
    return sync_location(None)


def portal_path_for(location_id: int) -> Path:
    return DATA_DIR / f"portal_{int(location_id)}.json"


def sync_location(location_id: int | None) -> dict[str, Any]:
    ensure_seed()
    selected_id = int(location_id or get_env("ALTEGIO_LOCATION_ID", "764940") or "764940")
    api = AltegioClient(location_id=selected_id)
    data = build_portal_from_api(api)
    if int(data['location']['id']) != selected_id:
        raise ValueError('Altegio returned a different location; existing data was preserved')
    selected_path = portal_path_for(selected_id)
    if selected_path.exists():
        previous = json.loads(selected_path.read_text(encoding='utf-8'))
        data['default_budgets'] = previous.get('default_budgets', {})
        # Preserve supplemental report metadata absent from the REST response.
        for key in ('service_catalog', 'services_catalog', 'service_categories'):
            if key in previous and key not in data:
                data[key] = previous[key]
        save_portal(previous, DATA_DIR / 'raw' / f'portal_{selected_id}.previous.json')
    save_portal(data, selected_path)
    if selected_id == int(get_env("ALTEGIO_LOCATION_ID", "764940") or "764940"):
        save_portal(data, PORTAL_PATH)
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Altegio portal data without AI tokens")
    parser.add_argument("--seed-only", action="store_true", help="Write demo seed/portal JSON only")
    args = parser.parse_args()
    if args.seed_only:
        data = load_seed()
        save_portal(data, SEED_PATH)
        save_portal(data, PORTAL_PATH)
        print(json.dumps({"ok": True, "source": data.get("source"), "clients": len(data.get("clients", []))}, ensure_ascii=False))
        return
    try:
        data = sync_now()
        print(
            json.dumps(
                {
                    "ok": True,
                    "source": data.get("source"),
                    "synced_at": data.get("synced_at"),
                    "campaign_clients": len(data.get("clients", [])),
                    "raw_clients": (data.get("overview") or {}).get("raw_clients"),
                    "raw_records": (data.get("overview") or {}).get("raw_records"),
                    "output": str(PORTAL_PATH),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except AltegioError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
