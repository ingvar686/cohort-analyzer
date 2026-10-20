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

CAMPAIGNS = [
    "Paid advertisement. Beauty Blogger XXX. February 2026",
    "Target. GoogleMaps. January - April 2026",
    "Target. Instagram. May 2026",
    "SEO. Website. September - December 2026",
]

DEFAULT_BUDGETS = {
    CAMPAIGNS[0]: 1200,
    CAMPAIGNS[1]: 2400,
    CAMPAIGNS[2]: 1500,
    CAMPAIGNS[3]: 2000,
}

PREFIX_CAMPAIGN = {
    "BBF26": CAMPAIGNS[0],
    "GM26": CAMPAIGNS[1],
    "IGM26": CAMPAIGNS[2],
    "SEO25": CAMPAIGNS[3],
    "SEO26": CAMPAIGNS[3],
}

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
    for item in client.get("categories") or []:
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
    return names


def match_campaign(client: dict[str, Any]) -> str | None:
    name = str(client.get("name") or client.get("display_name") or "")
    for prefix, campaign in PREFIX_CAMPAIGN.items():
        if name.upper().startswith(prefix.upper()):
            return campaign
    cats = " | ".join(category_names(client)).lower()
    for campaign in CAMPAIGNS:
        if campaign.lower() in cats:
            return campaign
    # soft match by distinctive fragments
    soft = [
        ("beauty blogger", CAMPAIGNS[0]),
        ("googlemaps", CAMPAIGNS[1]),
        ("google maps", CAMPAIGNS[1]),
        ("instagram", CAMPAIGNS[2]),
        ("seo. website", CAMPAIGNS[3]),
        ("seo website", CAMPAIGNS[3]),
    ]
    for fragment, campaign in soft:
        if fragment in cats or fragment in name.lower():
            return campaign
    return None


def record_attendance(record: dict[str, Any]) -> str:
    attendance = record.get("attendance")
    visit = record.get("visit_attendance")
    if isinstance(attendance, str):
        return attendance.lower()
    mapping = {
        1: "waiting",
        2: "arrived",
        -1: "client_cancelled",
        0: "no_show",
    }
    if isinstance(attendance, int):
        return mapping.get(attendance, str(attendance))
    if isinstance(visit, int):
        return mapping.get(visit, str(visit))
    return str(attendance or visit or "").lower()


def record_revenue(record: dict[str, Any]) -> float:
    for key in ("paid_full", "paid", "cost", "services_cost", "amount"):
        value = record.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    total = 0.0
    for service in record.get("services") or []:
        try:
            total += float(service.get("cost") or service.get("amount") or 0)
        except (TypeError, ValueError):
            pass
    return total


def record_services(record: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for service in record.get("services") or []:
        title = service.get("title") or service.get("name")
        if title:
            names.append(str(title))
    return names


def client_id_of(record: dict[str, Any]) -> int | None:
    client = record.get("client")
    if isinstance(client, dict):
        value = client.get("id")
        return int(value) if value is not None else None
    value = record.get("client_id")
    return int(value) if value is not None else None


def build_portal_from_api(client: AltegioClient) -> dict[str, Any]:
    lookback = int(get_env("SYNC_LOOKBACK_DAYS", "730") or "730")
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
    visits_by_client: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        cid = client_id_of(record)
        visit_date = parse_date(record.get("date") or record.get("datetime"))
        if cid is None or not visit_date:
            continue
        attendance = record_attendance(record)
        revenue = record_revenue(record)
        # Keep arrived/completed visits; also keep paid visits when attendance is ambiguous.
        paid_full = bool(record.get("paid_full") or record.get("paid"))
        if attendance not in ARRIVED and not (paid_full and revenue > 0):
            continue
        services = record_services(record)
        visits_by_client[cid].append(
            {
                "date": visit_date,
                "revenue": round(revenue, 2),
                "service": services[0] if services else "Service",
                "services": services,
                "attendance": attendance or "arrived",
            }
        )

    portal_clients: list[dict[str, Any]] = []
    for cid, visits in visits_by_client.items():
        raw = clients_by_id.get(cid) or {}
        campaign = match_campaign(raw)
        if not campaign:
            # also try matching from record client payload
            sample = next((r.get("client") for r in records if client_id_of(r) == cid), None)
            if isinstance(sample, dict):
                campaign = match_campaign(sample)
        if not campaign:
            continue
        visits = sorted(visits, key=lambda v: v["date"])
        first = visits[0]["date"]
        enriched = []
        for visit in visits:
            enriched.append(
                {
                    "date": visit["date"],
                    "revenue": visit["revenue"],
                    "service": visit["service"],
                    "services": visit.get("services") or [visit["service"]],
                    "age": month_age(first, visit["date"]),
                }
            )
        portal_clients.append(
            {
                "id": cid,
                "name": raw.get("name") or raw.get("display_name") or f"Client {cid}",
                "phone": raw.get("phone") or raw.get("phone_code") or "",
                "campaign": campaign,
                "first_visit": first,
                "visits": enriched,
                "visit_count": len(enriched),
                "revenue": round(sum(v["revenue"] for v in enriched), 2),
            }
        )

    portal_clients.sort(key=lambda c: (c["campaign"], c["first_visit"], c["name"]))

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
        "campaigns": CAMPAIGNS,
        "default_budgets": DEFAULT_BUDGETS,
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
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def ensure_seed() -> Path:
    if not SEED_PATH.exists():
        save_portal(load_seed(), SEED_PATH)
    if not PORTAL_PATH.exists():
        save_portal(json.loads(SEED_PATH.read_text(encoding="utf-8")), PORTAL_PATH)
    return PORTAL_PATH


def sync_now() -> dict[str, Any]:
    ensure_seed()
    api = AltegioClient()
    data = build_portal_from_api(api)
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
