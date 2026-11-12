"""Create varied paid/arrived demo visits in Altegio for cohort realism.

Requires ALTEGIO_USER_TOKEN in .env:
  python scripts/auth_user_token.py
  python scripts/seed_realistic_visits.py
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from altegio_client import AltegioClient, AltegioError
from sync_from_altegio import category_names

# These legacy fixtures belong to the optional demo generator only. Production
# sync discovers campaigns from the current branch's client categories.
CAMPAIGNS = [
    "Paid advertisement. Beauty Blogger XXX. February 2026",
    "Target. GoogleMaps. January - April 2026",
    "Target. Instagram. May 2026",
    "SEO. Website. September - December 2026",
]
PREFIX_CAMPAIGN = dict(zip(("BBF26", "GM26", "IGM26", "SEO25"), CAMPAIGNS))
PREFIX_CAMPAIGN["SEO26"] = CAMPAIGNS[3]


def match_campaign(client: dict[str, Any]) -> str | None:
    name = str(client.get("name") or client.get("display_name") or "").upper().strip()
    for prefix, campaign in PREFIX_CAMPAIGN.items():
        if name == prefix or name.startswith(prefix + " "):
            return campaign
    categories = {title.casefold() for title in category_names(client)}
    return next((campaign for campaign in CAMPAIGNS if campaign.casefold() in categories), None)

rng = random.Random(20261020)

FIRST_NAMES = [
    "Nora", "Elena", "Mateo", "Iris", "Hugo", "Vera", "Omar", "Nina", "Leo", "Sara",
    "Yuki", "Pavel", "Ines", "Jonas", "Lara", "Felix", "Mila", "Theo", "Anya", "Kai",
]
LAST_NAMES = [
    "Novak", "Silva", "Berg", "Kowalski", "Moreau", "Costa", "Andersen", "Petrov",
    "Nakamura", "Rossi", "Dupont", "Ivanova", "Schmidt", "Almeida", "Horvat",
]


def service_price(svc: dict[str, Any]) -> float:
    for key in ("price_max", "price_min", "price", "cost", "amount"):
        val = svc.get(key)
        if val is None:
            continue
        try:
            num = float(val)
            if num > 0:
                return num
        except (TypeError, ValueError):
            continue
    return 0.0


def service_title(svc: dict[str, Any]) -> str:
    return str(svc.get("title") or svc.get("name") or f"Service {svc.get('id')}")


def service_duration(svc: dict[str, Any]) -> int:
    for key in ("duration", "seance_length", "length"):
        val = svc.get(key)
        if val:
            try:
                n = int(val)
                return n if n > 60 else n * 60
            except (TypeError, ValueError):
                pass
    return 3600


def pick_services(services: list[dict[str, Any]], prefer: list[str], n: int = 6) -> list[dict[str, Any]]:
    scored: list[tuple[int, dict[str, Any]]] = []
    for svc in services:
        price = service_price(svc)
        if price <= 0 or not svc.get("id"):
            continue
        title = service_title(svc).lower()
        score = 0
        for i, frag in enumerate(prefer):
            if frag.lower() in title:
                score += 10 - i
        if "tip" in title or "product" in title:
            score -= 5
        scored.append((score, svc))
    scored.sort(key=lambda x: (-x[0], service_price(x[1])))
    chosen = [s for score, s in scored if score > 0][:n]
    if len(chosen) < 3:
        fallback = [s for _, s in scored[:12]]
        chosen = fallback[: max(3, n)]
    return chosen


def vary_cost(base: float, low: float = 0.85, high: float = 1.25) -> float:
    return round(max(15.0, base * rng.uniform(low, high)), 2)


def day_slot(day: date, hour: int | None = None) -> str:
    h = hour if hour is not None else rng.choice([10, 11, 12, 13, 14, 15, 16, 17, 18])
    minute = rng.choice([0, 15, 30, 45])
    return f"{day.isoformat()}T{h:02d}:{minute:02d}:00"


def unique_phone(used: set[str], start: int = 2000) -> str:
    n = start
    while True:
        phone = f"+1202555{n:04d}"
        if phone not in used:
            used.add(phone)
            return phone
        n += 1


def client_name(prefix: str) -> str:
    return f"{prefix} {rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def existing_campaign_clients(api: AltegioClient) -> dict[str, list[dict[str, Any]]]:
    grouped = {c: [] for c in CAMPAIGNS}
    for client in api.iter_clients():
        campaign = match_campaign(client)
        if campaign:
            grouped[campaign].append(client)
    return grouped


def create_arrived_visit(
    api: AltegioClient,
    *,
    staff_ids: list[int],
    service: dict[str, Any],
    client: dict[str, Any],
    when: str,
    cost: float | None = None,
    comment: str = "",
) -> dict[str, Any]:
    price = cost if cost is not None else vary_cost(service_price(service))
    phone = str(client.get("phone") or client.get("phone_code") or "")
    name = str(client.get("name") or client.get("display_name") or "Client")
    cid = int(client["id"]) if client.get("id") is not None else None
    last_error: Exception | None = None
    record: dict[str, Any] = {}
    # Try several team members: some dates are outside individual schedules.
    for staff_id in staff_ids:
        try:
            record = api.create_appointment(
                staff_id=staff_id,
                service_id=int(service["id"]),
                service_cost=price,
                client_name=name,
                client_phone=phone,
                client_id=cid,
                datetime_iso=when,
                seance_length=service_duration(service),
                attendance=1,
                comment=comment or "cohort-demo realistic seed",
            )
            last_error = None
            break
        except AltegioError as exc:
            last_error = exc
            msg = str(exc).lower()
            if "schedule" in msg or "busy" in msg or "400" in msg:
                continue
            raise
    if last_error and not record:
        raise last_error
    rid = record.get("id")
    if rid:
        try:
            api.set_attendance(int(rid), 1)
        except AltegioError:
            try:
                api.set_attendance(int(rid), 2)
            except AltegioError:
                pass
    return {"record": record, "cost": price, "service": service_title(service), "when": when}


def add_new_clients(
    api: AltegioClient,
    *,
    campaign: str,
    prefix: str,
    dates: list[date],
    services: list[dict[str, Any]],
    staff_ids: list[int],
    used_phones: set[str],
    phone_start: int,
) -> list[dict[str, Any]]:
    created: list[dict[str, Any]] = []
    for i, first_day in enumerate(dates):
        name = client_name(prefix)
        phone = unique_phone(used_phones, phone_start + i * 3)
        client = api.create_client(
            name=name,
            phone=phone,
            comment=f"campaign:{campaign}",
        )
        if not client.get("id"):
            client = {"id": None, "name": name, "phone": phone}
        else:
            client = {**client, "name": name, "phone": phone}
        service = services[i % len(services)]
        # Rotate preferred staff, but create_arrived_visit can fall back to others.
        rotated = staff_ids[i % len(staff_ids):] + staff_ids[: i % len(staff_ids)]
        visit = create_arrived_visit(
            api,
            staff_ids=rotated,
            service=service,
            client=client,
            when=day_slot(first_day),
            cost=vary_cost(service_price(service), 0.9, 1.35),
            comment=f"{campaign} · first visit",
        )
        created.append({"client": client, "first_visit": visit, "campaign": campaign})
        time.sleep(0.15)
    return created


def add_returns(
    api: AltegioClient,
    clients: list[dict[str, Any]],
    *,
    windows: list[tuple[date, date]],
    services: list[dict[str, Any]],
    staff_ids: list[int],
    min_visits: int,
    max_visits: int,
    campaign: str,
) -> int:
    count = 0
    for i, client in enumerate(clients):
        n = rng.randint(min_visits, max_visits)
        for j in range(n):
            start, end = windows[j % len(windows)]
            span = max(0, (end - start).days)
            day = start + timedelta(days=rng.randint(0, span))
            service = rng.choice(services)
            rotated = staff_ids[(i + j) % len(staff_ids):] + staff_ids[: (i + j) % len(staff_ids)]
            try:
                create_arrived_visit(
                    api,
                    staff_ids=rotated,
                    service=service,
                    client=client,
                    when=day_slot(day),
                    cost=vary_cost(service_price(service), 0.8, 1.4),
                    comment=f"{campaign} · repeat",
                )
                count += 1
                time.sleep(0.12)
            except AltegioError as exc:
                _print({"warn": "return_failed", "client": client.get("name"), "error": str(exc)})
    return count


def _print(payload: Any) -> None:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((text + "\n").encode("utf-8", errors="replace"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    api = AltegioClient()
    if not api.user_token:
        raise SystemExit("ALTEGIO_USER_TOKEN missing. Run: python scripts/auth_user_token.py")

    company = api.company()
    staff = [s for s in api.staff() if s.get("id") and not s.get("fired") and s.get("name") != "Online booking"]
    services = api.services()
    if not staff:
        raise SystemExit("No staff found for location")
    if not services:
        raise SystemExit("No services found for location")

    # Prefer team members who already have recent appointments (they usually have schedules).
    recent = api.iter_records((date.today() - timedelta(days=45)).isoformat(), date.today().isoformat())
    recent_staff_counts: dict[int, int] = {}
    for rec in recent:
        sid = (rec.get("staff") or {}).get("id") if isinstance(rec.get("staff"), dict) else rec.get("staff_id")
        if sid:
            recent_staff_counts[int(sid)] = recent_staff_counts.get(int(sid), 0) + 1
    staff_ids = sorted(
        (int(s["id"]) for s in staff),
        key=lambda sid: (-recent_staff_counts.get(sid, 0), sid),
    )
    if not staff_ids:
        raise SystemExit("No usable staff ids")
    beauty_svcs = pick_services(services, ["hair", "color", "hawaiian", "cut", "manicure", "nail"], 8)
    maps_svcs = pick_services(services, ["hair", "men", "cut", "beard", "color", "manicure"], 8)
    ig_svcs = pick_services(services, ["manicure", "pedicure", "nail", "hardware", "polish"], 8)
    seo_svcs = pick_services(services, ["botox", "lazer", "laser", "face", "lifting", "cosmet"], 8)
    if not seo_svcs:
        seo_svcs = sorted(services, key=service_price, reverse=True)[:6]

    _print(
        {
            "location": company.get("title") or company.get("name"),
            "staff": len(staff_ids),
            "services_total": len(services),
            "pools": {
                "beauty": [service_title(s) for s in beauty_svcs],
                "google": [service_title(s) for s in maps_svcs],
                "instagram": [service_title(s) for s in ig_svcs],
                "seo": [service_title(s) for s in seo_svcs],
            },
        }
    )
    if args.dry_run:
        return

    existing = existing_campaign_clients(api)
    used_phones = {
        str(c.get("phone") or "")
        for group in existing.values()
        for c in group
        if c.get("phone")
    }

    summary: dict[str, Any] = {"new_clients": {}, "repeat_visits": {}}

    # Beauty: uneven new cohort sizes + sparse returns
    beauty_dates = (
        [date(2026, 2, d) for d in (3, 7, 11, 18, 22)]
        + [date(2026, 3, d) for d in (4, 9, 16)]
    )
    beauty_new = add_new_clients(
        api,
        campaign=CAMPAIGNS[0],
        prefix="BBF26",
        dates=beauty_dates,
        services=beauty_svcs,
        staff_ids=staff_ids,
        used_phones=used_phones,
        phone_start=2200,
    )
    summary["new_clients"]["beauty"] = len(beauty_new)
    beauty_old = existing[CAMPAIGNS[0]] + [x["client"] for x in beauty_new]
    summary["repeat_visits"]["beauty"] = add_returns(
        api,
        beauty_old,
        windows=[(date(2026, 3, 1), date(2026, 3, 28)), (date(2026, 4, 2), date(2026, 4, 27))],
        services=beauty_svcs,
        staff_ids=staff_ids,
        min_visits=0,
        max_visits=1,
        campaign=CAMPAIGNS[0],
    )

    # Google Maps: uneven monthly acquisition + strong but varied retention
    gm_dates = (
        [date(2026, 1, d) for d in (6, 14, 21)]
        + [date(2026, 2, d) for d in (5, 12, 19, 26)]
        + [date(2026, 3, d) for d in (8, 15, 22)]
        + [date(2026, 4, d) for d in (3, 10, 17, 24, 28)]
    )
    gm_new = add_new_clients(
        api,
        campaign=CAMPAIGNS[1],
        prefix="GM26",
        dates=gm_dates,
        services=maps_svcs,
        staff_ids=staff_ids,
        used_phones=used_phones,
        phone_start=2400,
    )
    summary["new_clients"]["google"] = len(gm_new)
    gm_old = existing[CAMPAIGNS[1]] + [x["client"] for x in gm_new]
    summary["repeat_visits"]["google"] = add_returns(
        api,
        gm_old,
        windows=[
            (date(2026, 5, 2), date(2026, 5, 28)),
            (date(2026, 6, 3), date(2026, 6, 27)),
            (date(2026, 7, 4), date(2026, 7, 29)),
            (date(2026, 8, 5), date(2026, 8, 28)),
        ],
        services=maps_svcs,
        staff_ids=staff_ids,
        min_visits=1,
        max_visits=3,
        campaign=CAMPAIGNS[1],
    )

    # Instagram: medium retention, beauty/nail mix
    ig_dates = [date(2026, 5, d) for d in (4, 8, 13, 19, 23, 27)] + [date(2026, 6, d) for d in (3, 11)]
    ig_new = add_new_clients(
        api,
        campaign=CAMPAIGNS[2],
        prefix="IGM26",
        dates=ig_dates,
        services=ig_svcs,
        staff_ids=staff_ids,
        used_phones=used_phones,
        phone_start=2600,
    )
    summary["new_clients"]["instagram"] = len(ig_new)
    ig_old = existing[CAMPAIGNS[2]] + [x["client"] for x in ig_new]
    summary["repeat_visits"]["instagram"] = add_returns(
        api,
        ig_old,
        windows=[(date(2026, 6, 5), date(2026, 6, 28)), (date(2026, 7, 6), date(2026, 7, 30))],
        services=ig_svcs,
        staff_ids=staff_ids,
        min_visits=0,
        max_visits=2,
        campaign=CAMPAIGNS[2],
    )

    # SEO: high-ticket varied services, few repeats
    seo_dates = [
        date(2025, 9, 8), date(2025, 9, 22),
        date(2025, 10, 9), date(2025, 10, 21),
        date(2025, 11, 7), date(2025, 11, 19),
        date(2025, 12, 4), date(2025, 12, 18),
    ]
    seo_new = add_new_clients(
        api,
        campaign=CAMPAIGNS[3],
        prefix="SEO25",
        dates=seo_dates,
        services=seo_svcs,
        staff_ids=staff_ids,
        used_phones=used_phones,
        phone_start=2800,
    )
    summary["new_clients"]["seo"] = len(seo_new)
    seo_old = existing[CAMPAIGNS[3]] + [x["client"] for x in seo_new]
    summary["repeat_visits"]["seo"] = add_returns(
        api,
        seo_old[:6],
        windows=[(date(2025, 11, 10), date(2025, 12, 20)), (date(2026, 1, 10), date(2026, 2, 20))],
        services=seo_svcs,
        staff_ids=staff_ids,
        min_visits=0,
        max_visits=1,
        campaign=CAMPAIGNS[3],
    )

    _print({"ok": True, "summary": summary})
    _print("Next: python scripts/sync_from_altegio.py")


if __name__ == "__main__":
    try:
        main()
    except AltegioError as exc:
        _print({"ok": False, "error": str(exc)})
        raise SystemExit(1) from exc
