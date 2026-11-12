"""Fill unnatural gaps: add return visits in months right after acquisition.

Makes cohort heatmaps look like gradual retention instead of a summer spike.
"""

from __future__ import annotations

import json
import random
import sys
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from altegio_client import AltegioClient, AltegioError
from seed_realistic_visits import (
    CAMPAIGNS,
    match_campaign,
    _print,
    create_arrived_visit,
    day_slot,
    pick_services,
    service_price,
    vary_cost,
)
from sync_from_altegio import parse_date, client_id_of

rng = random.Random(20261021)

# Probability of a return visit in month offset N after first visit.
RETENTION = {
    CAMPAIGNS[0]: {1: 0.28, 2: 0.12, 3: 0.06},   # Beauty — weak
    CAMPAIGNS[1]: {1: 0.72, 2: 0.55, 3: 0.42},   # Google — strong gradual
    CAMPAIGNS[2]: {1: 0.48, 2: 0.32, 3: 0.18},   # Instagram — medium
    CAMPAIGNS[3]: {1: 0.22, 2: 0.10, 3: 0.05},   # SEO — rare, high ticket later
}

SERVICE_PREFER = {
    CAMPAIGNS[0]: ["hair", "color", "cut", "manicure", "hawaiian"],
    CAMPAIGNS[1]: ["hair", "men", "cut", "beard", "color", "express"],
    CAMPAIGNS[2]: ["manicure", "pedicure", "nail", "hardware", "shellac"],
    CAMPAIGNS[3]: ["botox", "lazer", "laser", "face", "lifting"],
}


def add_months(ym: str, offset: int) -> str:
    y, m = map(int, ym.split("-"))
    m += offset
    while m > 12:
        m -= 12
        y += 1
    while m < 1:
        m += 12
        y -= 1
    return f"{y}-{m:02d}"


def random_day_in_month(ym: str, earliest: date | None = None) -> date | None:
    y, m = map(int, ym.split("-"))
    if m == 12:
        last = date(y + 1, 1, 1) - timedelta(days=1)
    else:
        last = date(y, m + 1, 1) - timedelta(days=1)
    start = date(y, m, 1)
    if earliest and earliest > start:
        start = earliest + timedelta(days=1)
    if start > last:
        return None
    span = (last - start).days
    return start + timedelta(days=rng.randint(0, span))


def main() -> None:
    api = AltegioClient()
    if not api.user_token:
        raise SystemExit("ALTEGIO_USER_TOKEN missing. Run: python scripts/auth_user_token.py")

    staff = [s for s in api.staff() if s.get("id") and not s.get("fired") and s.get("name") != "Online booking"]
    services_all = api.services()
    staff_ids = [int(s["id"]) for s in staff]
    if not staff_ids or not services_all:
        raise SystemExit("Need staff and services")

    # Prefer recently active staff.
    recent = api.iter_records((date.today() - timedelta(days=45)).isoformat(), date.today().isoformat())
    counts: dict[int, int] = {}
    for rec in recent:
        sid = (rec.get("staff") or {}).get("id") if isinstance(rec.get("staff"), dict) else rec.get("staff_id")
        if sid:
            counts[int(sid)] = counts.get(int(sid), 0) + 1
    staff_ids = sorted(staff_ids, key=lambda sid: (-counts.get(sid, 0), sid))

    pools = {
        camp: pick_services(services_all, SERVICE_PREFER[camp], 8)
        for camp in CAMPAIGNS
    }

    clients_raw = api.iter_clients()
    campaign_clients: dict[str, list[dict[str, Any]]] = {c: [] for c in CAMPAIGNS}
    for client in clients_raw:
        camp = match_campaign(client)
        if camp:
            campaign_clients[camp].append(client)

    # Visit months already present per client (avoid double-filling a month).
    lookback_start = date(2025, 1, 1)
    records = api.iter_records(lookback_start.isoformat(), date.today().isoformat())
    months_by_client: dict[int, set[str]] = defaultdict(set)
    first_by_client: dict[int, str] = {}
    for rec in records:
        cid = client_id_of(rec)
        d = parse_date(rec.get("date") or rec.get("datetime"))
        if cid is None or not d:
            continue
        months_by_client[cid].add(d[:7])
        if cid not in first_by_client or d < first_by_client[cid]:
            first_by_client[cid] = d

    as_of = date.today().replace(day=1)
    created = 0
    skipped = 0
    failed = 0
    by_campaign: dict[str, int] = {c: 0 for c in CAMPAIGNS}

    for campaign, clients in campaign_clients.items():
        probs = RETENTION[campaign]
        pool = pools[campaign] or services_all
        for i, client in enumerate(clients):
            cid = int(client["id"]) if client.get("id") is not None else None
            if cid is None:
                continue
            first = first_by_client.get(cid)
            if not first:
                continue
            first_day = date.fromisoformat(first)
            existing = months_by_client.get(cid, set())
            for offset, prob in probs.items():
                target_ym = add_months(first[:7], offset)
                # Don't create future months beyond current month.
                ty, tm = map(int, target_ym.split("-"))
                if date(ty, tm, 1) > as_of:
                    continue
                if target_ym in existing:
                    skipped += 1
                    continue
                if rng.random() > prob:
                    skipped += 1
                    continue
                day = random_day_in_month(target_ym, earliest=first_day)
                if not day:
                    skipped += 1
                    continue
                service = rng.choice(pool)
                rotated = staff_ids[i % len(staff_ids):] + staff_ids[: i % len(staff_ids)]
                try:
                    create_arrived_visit(
                        api,
                        staff_ids=rotated,
                        service=service,
                        client=client,
                        when=day_slot(day),
                        cost=vary_cost(service_price(service), 0.85, 1.35),
                        comment=f"{campaign} · adjacent return M{offset}",
                    )
                    created += 1
                    by_campaign[campaign] += 1
                    existing.add(target_ym)
                    time.sleep(0.1)
                except AltegioError as exc:
                    failed += 1
                    _print({"warn": "adjacent_failed", "client": client.get("name"), "month": target_ym, "error": str(exc)})

    _print(
        {
            "ok": True,
            "created_returns": created,
            "skipped": skipped,
            "failed": failed,
            "by_campaign": by_campaign,
        }
    )
    _print("Next: python scripts/sync_from_altegio.py")


if __name__ == "__main__":
    try:
        main()
    except AltegioError as exc:
        _print({"ok": False, "error": str(exc)})
        raise SystemExit(1) from exc
