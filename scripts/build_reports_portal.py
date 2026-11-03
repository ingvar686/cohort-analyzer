#!/usr/bin/env python3
"""Build the autonomous Altegio AI reports portal.

Inputs are text snapshots returned by Altegio MCP `appointments_list`. The
generated HTML has no runtime network dependency and contains no real contact
details: campaign contacts use reserved +1-202-555-01xx demo numbers.
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
from collections import Counter
from datetime import date, timedelta
from pathlib import Path


CAMPAIGNS = {
    "beauty": "Paid advertisement. Beauty Blogger XXX. February 2026",
    "google": "Target. GoogleMaps. January - April 2026",
    "instagram": "Target. Instagram. May 2026",
    "seo": "SEO. Website. September - December 2026",
}

DEFAULT_BUDGETS = {
    CAMPAIGNS["beauty"]: 1200,
    CAMPAIGNS["google"]: 2400,
    CAMPAIGNS["instagram"]: 1500,
    CAMPAIGNS["seo"]: 2000,
}


def month_age(first: str, current: str) -> int:
    fy, fm = map(int, first[:7].split("-"))
    cy, cm = map(int, current[:7].split("-"))
    return (cy - fy) * 12 + cm - fm


def campaign_clients() -> list[dict]:
    clients: list[dict] = []

    def add(prefix: str, names: list[str], phone_start: int, campaign: str,
            first_dates: list[str], price: float, service: str,
            repeats: dict[int, list[str]]) -> None:
        for i, (name, first_date) in enumerate(zip(names, first_dates)):
            visits = [{"date": first_date, "revenue": price, "service": service}]
            visits.extend(
                {"date": d, "revenue": price, "service": service}
                for d in repeats.get(i, [])
            )
            clients.append({
                "name": f"{prefix} {name}",
                "phone": f"+1 202 555 {phone_start + i:04d}",
                "campaign": campaign,
                "first_visit": first_date,
                "visits": visits,
                "visit_count": len(visits),
                "revenue": round(sum(v["revenue"] for v in visits), 2),
            })

    beauty_names = [
        "Emma Carter", "Olivia Bennett", "Sophia Turner", "Mia Collins",
        "Ava Mitchell", "Isabella Parker", "Amelia Brooks", "Harper Reed",
        "Evelyn Foster", "Charlotte Hayes", "Lily Morgan", "Grace Cooper",
        "Chloe Ward", "Ella Murphy", "Zoe Richardson",
    ]
    beauty_dates = [f"2026-02-{d:02d}" for d in range(2, 17)]
    add("BBF26", beauty_names, 100, CAMPAIGNS["beauty"], beauty_dates, 95,
        "Hawaiian haircut", {0: ["2026-03-10"], 1: ["2026-04-12"], 2: ["2026-03-25"]})

    google_names = [
        "Liam Anderson", "Noah Thompson", "Ethan Walker", "Lucas Harris",
        "Mason Clark", "Logan Lewis", "James Robinson", "Benjamin Hall",
        "Henry Allen", "Alexander Young", "Daniel King", "Matthew Wright",
        "Jackson Scott", "Sebastian Green", "Jack Baker", "Samuel Adams",
        "David Nelson", "Joseph Hill", "Owen Campbell", "Leo Mitchell",
    ]
    google_dates = [
        "2026-01-05", "2026-01-08", "2026-01-12", "2026-01-17", "2026-01-23",
        "2026-02-04", "2026-02-09", "2026-02-14", "2026-02-19", "2026-02-24",
        "2026-03-03", "2026-03-08", "2026-03-13", "2026-03-18", "2026-03-23",
        "2026-04-02", "2026-04-07", "2026-04-12", "2026-04-17", "2026-04-22",
    ]
    google_repeats: dict[int, list[str]] = {}
    for i in range(20):
        day = 5 + i % 5
        if i < 5:
            months = (5, 6, 7)
        elif i < 10:
            months = (6, 7, 8)
        elif i < 15:
            months = (5, 7, 8)
            day += 10
        else:
            months = (5, 6, 8)
            day += 20
        google_repeats[i] = [f"2026-{m:02d}-{day:02d}" for m in months]
    add("GM26", google_names, 115, CAMPAIGNS["google"], google_dates, 95,
        "Hawaiian haircut", google_repeats)

    instagram_names = [
        "Aria Wilson", "Scarlett Moore", "Victoria Taylor", "Madison White",
        "Layla Martin", "Nora Jackson", "Hannah Lee", "Stella Perez",
        "Lucy Roberts", "Maya Evans", "Naomi Edwards", "Ruby Stewart",
    ]
    instagram_dates = [f"2026-05-{d:02d}" for d in range(2, 14)]
    instagram_repeats = {
        0: ["2026-06-06", "2026-07-06"],
        1: ["2026-06-08", "2026-07-08"],
        2: ["2026-06-10", "2026-07-10"],
        3: ["2026-06-12", "2026-07-12"],
        4: ["2026-06-14"], 5: ["2026-06-16"],
        6: ["2026-07-14"], 7: ["2026-07-16"],
    }
    add("IGM26", instagram_names, 135, CAMPAIGNS["instagram"], instagram_dates, 80,
        "Hardware manicure", instagram_repeats)

    seo_names = [
        "Elena Rossi", "Camila Santos", "Sofia Romano", "Natalia Costa",
        "Laura Bianchi", "Diana Moretti", "Clara Silva", "Alice Ferrari",
        "Marta Ricci", "Eva Marino",
    ]
    seo_dates = [
        "2025-09-03", "2025-09-20", "2025-10-05", "2025-10-18",
        "2025-11-04", "2025-11-15", "2025-11-28", "2025-12-06",
        "2025-12-14", "2025-12-22",
    ]
    add("SEO25", seo_names, 147, CAMPAIGNS["seo"], seo_dates, 400,
        "Botox procedure", {})
    return clients


def cross_sell_from_exports(paths: list[Path]) -> dict:
    status: dict[int, str] = {}
    appointment_services: dict[int, list[str]] = {}
    line_re = re.compile(r"^- Appointment (\d+): .* · ([a-z_]+) ·")
    services_re = re.compile(r"^appointment (\d+) services: (.+)$")
    for path in paths:
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = re.sub(r"^\s*\d+\|", "", raw).strip()
            match = line_re.match(line)
            if match:
                status[int(match.group(1))] = match.group(2)
                continue
            match = services_re.match(line)
            if match:
                appointment_services[int(match.group(1))] = [
                    x.strip() for x in match.group(2).split(", ") if x.strip()
                ]
    singles: Counter[str] = Counter()
    pairs: Counter[tuple[str, str]] = Counter()
    multi = 0
    for appointment_id, services in appointment_services.items():
        if status.get(appointment_id) != "arrived":
            continue
        unique = sorted(set(services))
        singles.update(unique)
        if len(unique) > 1:
            multi += 1
            pairs.update(itertools.combinations(unique, 2))
    top_services = [name for name, _ in singles.most_common(7)]
    matrix = [
        [pairs.get(tuple(sorted((a, b))), 0) if a != b else singles[a] for b in top_services]
        for a in top_services
    ]
    pair_rows = [
        {"a": a, "b": b, "count": count}
        for (a, b), count in pairs.most_common(8)
    ]
    opportunities = []
    for service, count in singles.most_common(8):
        paired = sum(v for (a, b), v in pairs.items() if service in (a, b))
        solo_estimate = max(0, count - paired)
        opportunities.append({
            "service": service,
            "solo": solo_estimate,
            "potential": round(solo_estimate * 45, 2),
        })
    return {
        "services": top_services,
        "matrix": matrix,
        "pairs": pair_rows,
        "opportunities": opportunities,
        "arrived_with_multiple_services": multi,
    }


RECENT_APPOINTMENTS = [
    ("2026-10-04", 14, "Cosmetologist Anna"), ("2026-10-02", 15, "Hairdresser Jenny"),
    ("2026-10-01", 13, "Nail master Chen"), ("2026-09-30", 17, "Nataly N."),
    ("2026-09-30", 15, "Hairdresser Maria"), ("2026-09-30", 14, "Cosmetologist Anna"),
    ("2026-09-29", 18, "Doctor Nick"), ("2026-09-29", 13, "Nataly N."),
    ("2026-09-28", 19, "Hairdresser Maria"), ("2026-09-24", 15, "Nataly N."),
    ("2026-09-24", 15, "Hairdresser Jenny"), ("2026-09-23", 19, "Hairdresser Jenny"),
    ("2026-09-23", 15, "Hairdresser Jenny"), ("2026-09-22", 16, "Nataly N."),
    ("2026-09-20", 14, "Doctor Nick"), ("2026-09-20", 11, "Trainer Travis"),
    ("2026-09-18", 18, "Nataly N."), ("2026-09-17", 13, "Cosmetologist Anna"),
    ("2026-09-17", 12, "Hairdresser Jenny"), ("2026-09-15", 18, "Cosmetologist Anna"),
    ("2026-09-13", 13, "Nail master Chen"), ("2026-09-12", 14, "Nail master Chen"),
    ("2026-09-11", 16, "Nataly N."), ("2026-09-11", 9, "Nataly N."),
    ("2026-09-09", 14, "Cosmetologist Anna"), ("2026-09-07", 15, "Nail master Chen"),
]


def portal_data(export_paths: list[Path]) -> dict:
    clients = campaign_clients()
    for client in clients:
        first = client["first_visit"]
        for visit in client["visits"]:
            visit["age"] = month_age(first, visit["date"])
    return {
        "as_of": "2026-10-05",
        "location": {"id": 764940, "name": "Casa House", "currency": "EUR"},
        "campaigns": list(CAMPAIGNS.values()),
        "default_budgets": DEFAULT_BUDGETS,
        "clients": clients,
        "rfm": {
            "base_size": 436,
            "segments": [
                {"name": "VIP", "count": 3, "color": "#f0b429"},
                {"name": "Постоянные", "count": 26, "color": "#2f80ed"},
                {"name": "Спящие", "count": 24, "color": "#9b51e0"},
                {"name": "В зоне риска", "count": 383, "color": "#e05260"},
            ],
            "rules": "VIP: активны ≤60 дней и lifetime spend ≥€1,000; Постоянные: остальные активные ≤60 дней; Спящие: 61–90 дней; Риск: >90 дней.",
        },
        "cross_sell": cross_sell_from_exports(export_paths),
        "capacity": {
            "period": "2026-09-06 — 2026-10-05",
            "location": {"occupancy": 0.5, "revenue": 1529.71, "avg_check": 101.98, "appointments": 32},
            "staff": [
                {"name": "Hairdresser Jenny", "occupancy": 1.5, "revenue": 609.80, "avg_check": 152.45, "scheduled_hours": 245},
                {"name": "Nail master Chen", "occupancy": 0.6, "revenue": 84.55, "avg_check": 42.28, "scheduled_hours": 336},
                {"name": "Cosmetologist Anna", "occupancy": 0.0, "revenue": 0, "avg_check": 0, "scheduled_hours": 245},
                {"name": "Nataly N.", "occupancy": 1.9, "revenue": 530.81, "avg_check": 75.83, "scheduled_hours": 337},
            ],
            "appointments": [
                {"date": d, "hour": h, "staff": s} for d, h, s in RECENT_APPOINTMENTS
            ],
        },
        "overview": {
            "period": "2026-01-01 — 2026-10-05",
            "revenue": 41586.43, "services_revenue": 30703.15,
            "products_revenue": 10883.28, "avg_check": 171.14,
            "occupancy": 1.0, "appointments": 406, "completed": 261,
            "clients": 86, "new_clients": 81, "returning_clients": 5,
        },
    }


HTML = r"""<!doctype html>
<html lang="ru" data-theme="dark">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Altegio Intelligence · Reports Portal</title>
<style>
:root{--bg:#0b0e14;--side:#111620;--panel:#151b26;--panel2:#1b2230;--ink:#f3f6fb;--muted:#91a0b6;--line:#283244;--accent:#70e1b1;--accent2:#5ca8ff;--danger:#ff6b7a;--warn:#f0b429;--good:#5ee098;--cell:#243144}
[data-theme=light]{--bg:#f3f5f8;--side:#fff;--panel:#fff;--panel2:#f8fafc;--ink:#18202c;--muted:#66758b;--line:#dce2ea;--accent:#087f5b;--accent2:#1769e0;--danger:#cf3345;--warn:#9a6700;--good:#178a4d;--cell:#e8eef6}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 Inter,Segoe UI,Arial,sans-serif}.app{min-height:100vh;display:grid;grid-template-columns:250px 1fr}
.side{background:var(--side);border-right:1px solid var(--line);padding:22px 15px;position:sticky;top:0;height:100vh}.brand{padding:5px 10px 24px}.brand b{font-size:18px;letter-spacing:-.3px}.brand small{display:block;color:var(--muted);margin-top:4px}
.nav{display:grid;gap:7px}.nav button{border:0;background:transparent;color:var(--muted);padding:12px;text-align:left;border-radius:8px;font-weight:600;cursor:pointer}.nav button.active{background:var(--panel2);color:var(--ink)}.nav .num{display:inline-flex;width:22px;height:22px;border:1px solid var(--line);border-radius:6px;align-items:center;justify-content:center;margin-right:8px;font-size:11px}
.side-foot{position:absolute;bottom:20px;left:25px;color:var(--muted);font-size:11px}.main{min-width:0}.top{height:72px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 28px;position:sticky;top:0;background:color-mix(in srgb,var(--bg) 92%,transparent);backdrop-filter:blur(10px);z-index:10}
.top h1{font-size:18px;margin:0}.status{display:flex;gap:8px;align-items:center;color:var(--muted);font-size:12px}.pulse{width:8px;height:8px;border-radius:50%;background:var(--good)}.theme{border:1px solid var(--line);background:var(--panel);color:var(--ink);padding:8px 10px;border-radius:7px;cursor:pointer}
.content{padding:26px;max-width:1540px;margin:auto}.tab{display:none}.tab.active{display:block}.hero{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;margin-bottom:20px}.hero h2{font-size:25px;margin:0 0 4px;letter-spacing:-.5px}.hero p,.caption,.meta{color:var(--muted);margin:0}
.filters{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px}.field{display:grid;gap:5px;min-width:170px;flex:1}.field.wide{min-width:340px;flex:2}.field label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.45px}
select,input{width:100%;border:1px solid var(--line);background:var(--panel2);color:var(--ink);padding:10px 11px;border-radius:7px;outline:none}input[readonly]{opacity:.8;cursor:default}.seg{display:flex;flex-wrap:wrap;border:1px solid var(--line);border-radius:8px;overflow:hidden}.seg button{border:0;border-right:1px solid var(--line);border-bottom:1px solid var(--line);background:var(--panel2);color:var(--muted);padding:9px 11px;cursor:pointer;flex:1 1 auto}.seg button.active{background:var(--accent);color:#07120e}
.kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:16px}.kpi{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:15px;min-width:0}.kpi label{display:block;color:var(--muted);font-size:11px;min-height:32px}.kpi strong{display:block;font-size:22px;margin:3px 0;white-space:nowrap}.kpi small{color:var(--muted)}.positive{color:var(--good)!important}.negative{color:var(--danger)!important}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:17px;min-width:0}.panel h3{font-size:15px;margin:0 0 4px}.chart{width:100%;height:280px}.chart text{font-family:Inter,Segoe UI,Arial,sans-serif}.legend{display:flex;gap:14px;flex-wrap:wrap;color:var(--muted);font-size:11px;margin-top:8px}.legend i{display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:5px}
.table-wrap{overflow:auto;max-height:520px}table{width:100%;border-collapse:separate;border-spacing:0}th{font-size:11px;color:var(--muted);text-align:left;padding:10px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--panel);z-index:2}td{padding:10px;border-bottom:1px solid var(--line);font-size:12px}tbody tr:hover{background:var(--panel2)}.heat th{white-space:nowrap;min-width:72px}.heat th:first-child,.heat th:nth-child(2){min-width:110px}.heat td:not(:first-child):not(:nth-child(2)){text-align:center;border-left:3px solid var(--panel);border-bottom:3px solid var(--panel);border-radius:5px;white-space:nowrap}.heat tr{cursor:pointer}.heat tr.selected td:first-child{color:var(--accent)}
details{margin-top:14px}summary{cursor:pointer;color:var(--accent);font-weight:600;padding:8px 0}.pill{display:inline-block;padding:4px 8px;border-radius:99px;background:var(--panel2);border:1px solid var(--line);font-size:11px}.callout{padding:13px 15px;background:var(--panel2);border-left:3px solid var(--accent);border-radius:5px;color:var(--muted);margin:12px 0}
.segment-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:14px}.segment{padding:15px;background:var(--panel);border:1px solid var(--line);border-radius:10px}.segment strong{font-size:24px;display:block}.segment span{color:var(--muted)}
.bars{display:grid;gap:11px;margin-top:15px}.bar-row{display:grid;grid-template-columns:minmax(130px,1fr) 4fr 65px;gap:10px;align-items:center}.bar-track{height:10px;background:var(--panel2);border-radius:8px;overflow:hidden}.bar-fill{height:100%;background:var(--accent2);border-radius:8px}.matrix td{text-align:center}.matrix th:not(:first-child){min-width:72px;max-width:100px}.risk{color:var(--danger);font-weight:600}.recommend{max-width:340px;color:var(--muted)}
.staff-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:14px 0}.staff{padding:14px;border:1px solid var(--line);border-radius:10px;background:var(--panel2)}.staff b{display:block;margin-bottom:8px}.meter{height:7px;background:var(--bg);border-radius:8px;overflow:hidden;margin:8px 0}.meter i{height:100%;display:block;background:var(--accent)}
.hour-grid td{text-align:center;min-width:38px}.footnote{font-size:11px;color:var(--muted);padding:14px 2px}.empty{padding:30px;text-align:center;color:var(--muted)}
.metric-help{width:100%;color:var(--muted);font-size:12px;padding:2px 3px}.heat-wrap{margin-bottom:14px}.future{color:var(--muted);text-align:center}.partial{box-shadow:inset 0 0 0 1px var(--warn)}.comparison{margin-top:14px}.comparison input{min-width:105px;padding:7px 8px}.comparison td{white-space:nowrap}.comparison tr.best td:first-child{box-shadow:inset 3px 0 0 var(--good)}.comparison tr.risk-row td:first-child{box-shadow:inset 3px 0 0 var(--danger)}.comparison tr.total{background:var(--panel2)}.rank{display:inline-block;margin-left:5px;padding:2px 5px;border-radius:4px;background:color-mix(in srgb,var(--accent) 18%,transparent);color:var(--accent);font-size:9px;text-transform:uppercase;vertical-align:middle}.insight-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:9px;margin:12px 0 12px}.insight{background:var(--panel2);border:1px solid var(--line);border-radius:9px;padding:12px;min-width:0}.insight label{display:block;color:var(--muted);font-size:10px;text-transform:uppercase}.insight b{display:block;margin-top:5px;line-height:1.35}.maturity{color:var(--warn);font-size:10px;font-weight:600}.payback-yes{color:var(--good);font-weight:700}.payback-no{color:var(--danger);font-weight:700}.payback-wait{color:var(--warn);font-weight:700}
@media(max-width:1150px){.kpis{grid-template-columns:repeat(3,1fr)}.staff-grid,.segment-grid{grid-template-columns:repeat(2,1fr)}.insight-grid{grid-template-columns:repeat(2,1fr)}}@media(max-width:780px){.app{display:block}.side{position:static;height:auto;border-right:0;border-bottom:1px solid var(--line)}.brand,.side-foot{display:none}.nav{display:flex;overflow:auto}.nav button{white-space:nowrap}.top{padding:0 15px}.content{padding:15px}.grid2{grid-template-columns:1fr}.kpis,.insight-grid{grid-template-columns:1fr 1fr}.hero{display:block}.status span:not(.pulse){display:none}.filters{flex-direction:column}.field,.field.wide{min-width:0;width:100%;flex:none}.seg{flex-direction:column}.seg button{border-right:0;text-align:left}}
</style>
</head>
<body><div class="app">
<aside class="side"><div class="brand"><b>Altegio Intelligence</b><small>AI-powered business analytics</small></div>
<nav class="nav">
<button class="active" data-tab="cohort"><span class="num">01</span>Когорты & LTV</button>
<button data-tab="rfm"><span class="num">02</span>RFM & Радар ухода</button>
<button data-tab="cross"><span class="num">03</span>Cross-Sell Matrix</button>
<button data-tab="idle"><span class="num">04</span>Простои мастеров</button>
</nav><div class="side-foot">Casa House · location 764940<br>Snapshot: 05.10.2026</div></aside>
<main class="main"><header class="top"><h1 id="page-title">Когортный анализ & LTV</h1><div class="status"><i class="pulse"></i><span>Altegio MCP snapshot · автономный режим</span><button class="theme" id="theme">Light</button></div></header>
<div class="content">
<section class="tab active" id="cohort">
 <div class="hero"><div><h2>Маркетинговые когорты</h2><p>Окупаемость каналов, retention и накопительный LTV</p></div><span class="pill">Главный отчёт</span></div>
 <div class="filters">
  <div class="field wide"><label>Маркетинговая кампания</label><select id="campaign"></select></div>
  <div class="field"><label>Затраты на маркетинг (€)</label><input id="budget" type="number" min="0" step="100"></div>
  <div class="field wide"><label>Метрика тепловой карты</label><div class="seg" id="metric"><button type="button" class="active" data-value="revenue">Общая выручка когорты</button><button type="button" data-value="ltv">LTV на клиента</button><button type="button" data-value="retention">Retention Rate</button></div></div>
  <div class="metric-help" id="metricHelp">В ячейке — выручка когорты за этот календарный месяц. Столбец «Итого» = сумма по всем месяцам строки.</div>
 </div>
 <div class="kpis">
  <div class="kpi"><label>Бюджет на рекламу</label><strong id="kBudget">—</strong><small>реактивный ввод</small></div>
  <div class="kpi"><label>Накопительная выручка LTV</label><strong id="kRevenue">—</strong><small>горизонт M0–M5</small></div>
  <div class="kpi"><label>Чистая прибыль</label><strong id="kProfit">—</strong><small>выручка − бюджет</small></div>
  <div class="kpi"><label>ROI / ROMI</label><strong id="kRoi">—</strong><small>(прибыль / бюджет) × 100%</small></div>
  <div class="kpi"><label>CAC</label><strong id="kCac">—</strong><small>бюджет / клиентов</small></div>
  <div class="kpi"><label>Окупаемость в M0</label><strong id="kM0">—</strong><small>выручка M0 / бюджет</small></div>
 </div>
 <div class="panel heat-wrap"><h3 id="heatTitle">Общая выручка когорты</h3><p class="caption" id="heatCaption">Строки — месяц первого визита, столбцы — календарный месяц оплаты/визита. Пустая ячейка = нет выручки в этом месяце. Нажмите строку, чтобы раскрыть клиентов.</p><div class="table-wrap"><table class="heat" id="heat"></table></div></div>
 <div class="grid2">
  <div class="panel"><h3>Точка окупаемости</h3><p class="caption">Накопительная выручка по месяцам жизни и уровень Ad Spend</p><svg class="chart" id="breakeven" viewBox="0 0 700 280"></svg><div class="legend"><span><i style="background:var(--accent2)"></i>Выручка</span><span><i style="background:var(--danger)"></i>Ad Spend</span></div></div>
  <div class="panel"><h3>Динамика роста LTV</h3><p class="caption">Накопительная выручка на одного привлечённого клиента</p><svg class="chart" id="ltvChart" viewBox="0 0 700 280"></svg></div>
 </div>
 <details open><summary>Откуда цифры · клиенты выбранной когорты</summary><div class="panel"><div id="cohortName" class="caption"></div><div class="table-wrap"><table id="clientsTable"></table></div></div></details>
 <div class="panel comparison"><h3>Сравнение маркетинговых кампаний</h3><p class="caption">Фактический бюджет каждой кампании редактируется отдельно и сохраняется в этом браузере. All Campaigns равен сумме и не редактируется. Любое изменение сразу пересчитывает KPI, графики и итог.</p><div class="insight-grid" id="comparisonInsights"></div><div id="horizonNote"></div><div class="table-wrap"><table id="campaignComparison"></table></div></div>
 <div class="footnote">Источник: Altegio MCP, Casa House. Кампании распознаны по тестовым префиксам и категориям карточек. SEO-когорта физически создана в сентябре–декабре 2025 как историческая симуляция будущего периода 2026. Revenue = sold amount; часть визитов ожидает ручной оплаты.</div>
</section>
<section class="tab" id="rfm">
 <div class="hero"><div><h2>RFM-анализ & Радар ухода</h2><p>Сегментация клиентской базы по ценности и давности активности</p></div><span class="pill">436 клиентов</span></div>
 <div class="segment-grid" id="segments"></div>
 <div class="grid2">
  <div class="panel"><h3>Распределение клиентской базы</h3><p class="caption">Актуальный размер RFM-сегментов Altegio</p><div class="bars" id="segmentBars"></div></div>
  <div class="panel"><h3>Выручка демо-когорт по RFM-сегментам</h3><p class="caption">Фактический sold amount созданных демонстрационных клиентов</p><div class="bars" id="segmentRevenue"></div><div class="callout" id="rfmRules"></div></div>
 </div>
 <div class="panel"><h3>Клиенты в зоне риска</h3><p class="caption">Не возвращались более 90 дней · приоритет для win-back кампании</p><div class="table-wrap"><table id="riskTable"></table></div></div>
</section>
<section class="tab" id="cross">
 <div class="hero"><div><h2>Матрица кросс-продаж</h2><p>Какие услуги покупают вместе и где остаётся потенциал допродажи</p></div><span class="pill" id="multiCount"></span></div>
 <div class="panel"><h3>Пересечение услуг</h3><p class="caption">Диагональ — число продаж услуги; остальные ячейки — совместные покупки в одном arrived-визите</p><div class="table-wrap"><table class="matrix" id="matrix"></table></div></div>
 <div class="grid2" style="margin-top:14px">
  <div class="panel"><h3>Топ связок услуг</h3><p class="caption">Наиболее частые пары в одном визите</p><div class="bars" id="pairs"></div></div>
  <div class="panel"><h3>Неиспользованный потенциал</h3><p class="caption">Оценка: одиночные продажи × €45 среднего допроданного чека</p><div class="bars" id="opportunity"></div><div class="callout" id="potentialTotal"></div></div>
 </div>
</section>
<section class="tab" id="idle">
 <div class="hero"><div><h2>Упущенная выгода и простои</h2><p>Рабочие интервалы, фактическая загрузка и пустые окна мастеров</p></div><span class="pill">Последние 30 дней</span></div>
 <div class="kpis">
  <div class="kpi"><label>Загрузка локации</label><strong>0.5%</strong><small>Altegio Analytics</small></div>
  <div class="kpi"><label>Расчётные часы расписания</label><strong id="scheduledHours">—</strong><small>4 ключевых мастера</small></div>
  <div class="kpi"><label>Упущенная выручка</label><strong id="lostRevenue">—</strong><small>свободные часы × avg check</small></div>
  <div class="kpi"><label>Стоимость 1 часа простоя</label><strong>€102</strong><small>средний чек локации</small></div>
  <div class="kpi"><label>Выручка за 30 дней</label><strong>€1,530</strong><small>+20% к пред. периоду</small></div>
  <div class="kpi"><label>Завершённые записи</label><strong>14</strong><small>из 32 записей</small></div>
 </div>
 <div class="staff-grid" id="staff"></div>
 <div class="panel"><h3>Плотность пустых окон</h3><p class="caption">Оценка свободных часовых слотов по дням недели и времени на основе расписаний и записей</p><div class="table-wrap"><table class="hour-grid" id="hourGrid"></table></div></div>
 <div class="footnote">Упущенная выручка — сценарная оценка, а не бухгалтерский факт: свободный час умножается на средний чек €101.98. Расписания прочитаны из Altegio за 08.09–05.10.2026.</div>
</section>
</div></main></div>
<script>
const DB={{DATA}};
const euro=new Intl.NumberFormat('ru-RU',{style:'currency',currency:'EUR',maximumFractionDigits:0});
const number=new Intl.NumberFormat('ru-RU',{maximumFractionDigits:1});
const monthFmt=new Intl.DateTimeFormat('ru-RU',{month:'long',year:'numeric'});
const pageTitles={cohort:'Когортный анализ & LTV',rfm:'RFM-анализ & Радар ухода',cross:'Матрица кросс-продаж',idle:'Упущенная выгода и простои'};
document.querySelectorAll('.nav button').forEach(b=>b.onclick=()=>{document.querySelectorAll('.nav button,.tab').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.getElementById(b.dataset.tab).classList.add('active');document.getElementById('page-title').textContent=pageTitles[b.dataset.tab]});
document.getElementById('theme').onclick=()=>{const light=document.documentElement.dataset.theme==='light';document.documentElement.dataset.theme=light?'dark':'light';document.getElementById('theme').textContent=light?'Light':'Dark'};
const campaign=document.getElementById('campaign'),budget=document.getElementById('budget');
campaign.innerHTML=['All Campaigns',...DB.campaigns].map(x=>`<option>${x}</option>`).join('');
let heatMetric='revenue',selectedCohort='';
let campaignBudgets={...DB.default_budgets};try{campaignBudgets={...campaignBudgets,...JSON.parse(localStorage.getItem('altegioCampaignBudgets')||'{}')}}catch(e){}
function saveBudgets(){try{localStorage.setItem('altegioCampaignBudgets',JSON.stringify(campaignBudgets))}catch(e){}}
function budgetFor(name){return name==='All Campaigns'?DB.campaigns.reduce((s,n)=>s+(Number(campaignBudgets[n])||0),0):Number(campaignBudgets[name])||0}
const metricCopy={revenue:'В ячейке — выручка когорты за этот календарный месяц. Столбец «Итого» = сумма по всем месяцам строки.',ltv:'В ячейке — накопительный LTV на клиента к этому календарному месяцу (выручка с первого визита ÷ размер когорты).',retention:'Доля клиентов когорты, у которых был визит в этом календарном месяце.'};
const metricTitle={revenue:'Выручка по календарным месяцам',ltv:'LTV на клиента по месяцам',retention:'Retention Rate по месяцам'};
function syncBudgetInput(){budget.value=budgetFor(campaign.value);budget.readOnly=campaign.value==='All Campaigns';budget.title=budget.readOnly?'Сумма бюджетов всех кампаний':'Фактический бюджет выбранной кампании'}
campaign.onchange=()=>{syncBudgetInput();selectedCohort='';renderCohort()};budget.oninput=()=>{if(campaign.value!=='All Campaigns'){campaignBudgets[campaign.value]=Number(budget.value)||0;saveBudgets();renderCohort()}};
document.querySelectorAll('#metric button').forEach(b=>b.onclick=()=>{document.querySelectorAll('#metric button').forEach(x=>x.classList.remove('active'));b.classList.add('active');heatMetric=b.dataset.value;renderCohort()});
campaign.value='All Campaigns';syncBudgetInput();
function rows(){return DB.clients.filter(c=>campaign.value==='All Campaigns'||c.campaign===campaign.value)}
function cohortMap(clients){const out={};clients.forEach(c=>{const key=c.first_visit.slice(0,7);out[key]??={clients:[],monthly:{},calendar:{}};out[key].clients.push(c);c.visits.forEach(v=>{out[key].monthly[v.age]??={revenue:0,clients:new Set()};out[key].monthly[v.age].revenue+=v.revenue;out[key].monthly[v.age].clients.add(c.name);const ck=v.date.slice(0,7);out[key].calendar[ck]??={revenue:0,clients:new Set()};out[key].calendar[ck].revenue+=v.revenue;out[key].calendar[ck].clients.add(c.name)})});return out}
function monthRange(startKey,endKey){if(!startKey||!endKey||startKey>endKey)return[];const out=[];let[y,m]=startKey.split('-').map(Number);const[ey,em]=endKey.split('-').map(Number);while(y<ey||(y===ey&&m<=em)){out.push(`${y}-${String(m).padStart(2,'0')}`);m+=1;if(m>12){m=1;y+=1}if(out.length>48)break}return out}
function cumulativeSeries(clients,limit){const max=limit==null?5:limit,monthly=Array(max+1).fill(0);clients.forEach(c=>c.visits.forEach(v=>{if(v.age>=0&&v.age<=max)monthly[v.age]+=v.revenue}));let sum=0;return monthly.map(x=>(sum+=x))}
function svgAxes(W,H,L,B,maxY){let s='';for(let i=0;i<=4;i++){const y=maxY*i/4,py=H-B-(H-B-18)*i/4;s+=`<line x1="${L}" y1="${py}" x2="${W-12}" y2="${py}" stroke="var(--line)"/><text x="${L-8}" y="${py+4}" fill="var(--muted)" font-size="10" text-anchor="end">${Math.round(y)}</text>`}return s}
function renderBreakeven(clients,spend){const svg=document.getElementById('breakeven'),vals=cumulativeSeries(clients,seriesLimit(clients)),W=700,H=280,L=48,B=34,max=Math.max(spend,...vals,1)*1.15,plotH=H-B-18,step=(W-L-20)/Math.max(vals.length,1),openAt=youngestAge(clients);let s=svgAxes(W,H,L,B,max);vals.forEach((v,i)=>{const h=v/max*plotH,x=L+i*step+step*.18,y=H-B-h,open=i===openAt&&openAt<=5;s+=`<rect x="${x}" y="${y}" width="${step*.64}" height="${h}" rx="5" fill="${open?'var(--warn)':'var(--accent2)'}"/><text x="${x+step*.32}" y="${H-13}" fill="var(--muted)" text-anchor="middle" font-size="11">M${i}</text>`});const py=H-B-spend/max*plotH;s+=`<line x1="${L}" y1="${py}" x2="${W-12}" y2="${py}" stroke="var(--danger)" stroke-width="2" stroke-dasharray="6 5"/><text x="${W-14}" y="${Math.max(16,py-6)}" text-anchor="end" fill="var(--danger)" font-size="11">Ad Spend ${euro.format(spend)}</text>`;const bi=vals.findIndex(v=>v>=spend);if(bi>=0){const provisional=bi>(openAt>5?5:openAt-1),x=L+bi*step+step*.5,y=H-B-vals[bi]/max*plotH,color=provisional?'var(--warn)':'var(--accent)';s+=`<circle cx="${x}" cy="${y}" r="7" fill="${color}"/><text x="${x}" y="15" text-anchor="middle" fill="${color}" font-size="11">${provisional?`M${bi} · не закрыт`:`Break-even M${bi}`}</text>`}svg.innerHTML=s}
function renderLine(clients){const svg=document.getElementById('ltvChart'),vals=cumulativeSeries(clients,seriesLimit(clients)).map(x=>x/(clients.length||1)),W=700,H=280,L=48,B=34,max=Math.max(...vals,1)*1.15,plotH=H-B-18,step=(W-L-30)/Math.max(vals.length-1,1);let s=svgAxes(W,H,L,B,max),d='';vals.forEach((v,i)=>{const x=L+i*step,y=H-B-v/max*plotH;d+=`${i?'L':'M'}${x},${y} `;s+=`<circle cx="${x}" cy="${y}" r="4" fill="var(--accent)"/><text x="${x}" y="${H-13}" fill="var(--muted)" text-anchor="middle" font-size="11">M${i}</text>`});s+=`<path d="${d}" fill="none" stroke="var(--accent)" stroke-width="3"/>`;svg.innerHTML=s}
function heatColor(v,max){const p=max?Math.min(1,v/max):0;return `color-mix(in srgb,var(--accent2) ${10+p*75}%,var(--panel2))`}
function monthLabel(key){const [y,m]=key.split('-').map(Number);return monthFmt.format(new Date(y,m-1,1))}
function renderHeat(map){const keys=Object.keys(map).sort((a,b)=>a.localeCompare(b));if(!selectedCohort||!map[selectedCohort])selectedCohort=keys[0]||'';const asOf=(DB.as_of||'').slice(0,7);let start=keys.length?[...keys].sort()[0]:asOf;keys.forEach(k=>Object.keys(map[k].calendar||{}).forEach(ck=>{if(!start||ck<start)start=ck}));const cols=monthRange(start,asOf);let html=`<thead><tr><th>Первый визит</th><th>Клиенты</th>${cols.map(c=>`<th>${monthLabel(c)}</th>`).join('')}<th>Итого</th></tr></thead><tbody>`;const all=[];keys.forEach(k=>{const c=map[k],size=c.clients.length||1;let cum=0;cols.forEach(col=>{if(col<k||(asOf&&col>asOf))return;const d=c.calendar[col],period=d?.revenue||0;cum+=period;if(heatMetric==='revenue'){if(period>0)all.push(period)}else if(heatMetric==='ltv')all.push(cum/size);else all.push((d?.clients.size||0)/size*100)})});const max=Math.max(...all,1);keys.forEach(k=>{const c=map[k],size=c.clients.length||1;let cum=0;const seen=new Set();html+=`<tr data-cohort="${k}" class="${k===selectedCohort?'selected':''}"><td>${monthLabel(k)}</td><td>${size}</td>`;cols.forEach(col=>{if(col<k){html+='<td class="future"></td>';return}if(asOf&&col>asOf){html+='<td class="future" title="Месяц ещё не наступил">—</td>';return}const d=c.calendar[col],period=d?.revenue||0;cum+=period;if(d)d.clients.forEach(x=>seen.add(x));const partial=!!asOf&&col===asOf;let v=0,text='';if(heatMetric==='revenue'){v=period;text=period?euro.format(period):''}else if(heatMetric==='ltv'){v=cum/size;text=euro.format(v)}else{v=(d?.clients.size||0)/size*100;text=`${v.toFixed(0)}%`}if(heatMetric==='revenue'&&!period){html+=`<td class="${partial?'partial':''}"></td>`}else{html+=`<td class="${partial?'partial':''}" title="${partial?'Текущий месяц ещё не закрыт':monthLabel(col)}" style="${partial?'':'background:'+heatColor(v,max)}">${text}</td>`}});const total=heatMetric==='retention'?`${((seen.size/size)*100).toFixed(0)}%`:heatMetric==='ltv'?euro.format(cum/size):euro.format(cum);html+=`<td><b>${total}</b></td></tr>`});document.getElementById('heat').innerHTML=html+'</tbody>';document.querySelectorAll('#heat tbody tr').forEach(tr=>tr.onclick=()=>{selectedCohort=tr.dataset.cohort;renderCohort()})}
function renderClients(map){const c=map[selectedCohort];document.getElementById('cohortName').textContent=c?`${monthLabel(selectedCohort)} · ${c.clients.length} клиентов`:'';let h='<thead><tr><th>Имя</th><th>Телефон</th><th>Категория</th><th>Первый визит</th><th>Визитов</th><th>Выручка</th></tr></thead><tbody>';if(c)c.clients.forEach(x=>h+=`<tr><td>${x.name}</td><td>${x.phone}</td><td>${x.campaign}</td><td>${x.first_visit}</td><td>${x.visit_count}</td><td>${euro.format(x.revenue)}</td></tr>`);document.getElementById('clientsTable').innerHTML=h+'</tbody>'}
function monthDistance(a,b){const [ay,am]=a.slice(0,7).split('-').map(Number),[by,bm]=b.slice(0,7).split('-').map(Number);return (by-ay)*12+bm-am}
function cohortAge(key){return monthDistance(key+'-01',DB.as_of)}
function youngestAge(clients){return clients.length?Math.min(...clients.map(c=>monthDistance(c.first_visit,DB.as_of))):0}
function seriesLimit(clients){return clients.length?Math.min(5,Math.max(...clients.map(c=>monthDistance(c.first_visit,DB.as_of)))):0}
function horizonNote(age){if(age>5)return '';if(age>=5)return 'M5 ещё не закрыт';if(age>=3)return 'Неполный горизонт · нет M5';return 'Неполный горизонт · нет M3 и M5'}
function same(a,b){return Math.abs(a-b)<0.05}
function tint(value,values,invert,color){if(!values.length)return '';const min=Math.min(...values),max=Math.max(...values);let p=max===min?1:(value-min)/(max-min);if(invert)p=1-p;return `background:color-mix(in srgb,${color} ${Math.round(12+p*30)}%,transparent)`}
function campaignLabel(name){if(name.includes('Beauty Blogger'))return 'Beauty Blogger';if(name.includes('GoogleMaps'))return 'Google Maps';if(name.includes('Instagram'))return 'Instagram Target';return 'SEO Website'}
function paybackOf(clients,spend){const age=youngestAge(clients),limit=seriesLimit(clients),series=cumulativeSeries(clients,limit);let payback=-1;for(let i=0;i<=limit;i++){if(series[i]>=spend){payback=i;break}}const closed=age>5?5:age-1;let state='no';if(payback<0)state=age>5?'no':'early';else state=payback<=closed?'yes':'provisional';return{payback,state,age}}
function statsFor(name){const clients=DB.clients.filter(c=>c.campaign===name),spend=budgetFor(name),m0=clients.reduce((s,c)=>s+c.visits.filter(v=>v.age===0).reduce((a,v)=>a+v.revenue,0),0),revenue=clients.reduce((s,c)=>s+c.visits.filter(v=>v.age<=5).reduce((a,v)=>a+v.revenue,0),0),repeat=clients.filter(c=>c.visits.some(v=>v.age>0)).length,paid=paybackOf(clients,spend);return{name,label:campaignLabel(name),clients:clients.length,spend,m0,revenue,ltv:revenue/(clients.length||1),cac:spend/(clients.length||1),repeatRate:repeat/(clients.length||1)*100,payback:paid.payback,paybackState:paid.state,profit:revenue-spend,roi:spend?(revenue-spend)/spend*100:0,age:paid.age}}
function paybackText(state,month){if(state==='yes')return 'M'+month;if(state==='provisional')return 'M'+month+' · не закрыт';if(state==='early')return 'Рано оценивать';return 'Не достигнута'}
function paybackClass(state){if(state==='yes')return 'payback-yes';if(state==='no')return 'payback-no';return 'payback-wait'}
function renderComparison(){const stats=DB.campaigns.map(statsFor),mature=stats.filter(x=>x.age>5),roiPool=mature.length?mature:stats,ltvPool=roiPool,retainPool=stats.filter(x=>x.age>1),bestRoi=[...roiPool].sort((a,b)=>b.roi-a.roi)[0],bestLtv=[...ltvPool].sort((a,b)=>b.ltv-a.ltv)[0],bestCac=[...stats].sort((a,b)=>a.cac-b.cac)[0],paid=stats.filter(x=>x.paybackState==='yes').sort((a,b)=>a.payback-b.payback||b.roi-a.roi),weak=retainPool.length?[...retainPool].sort((a,b)=>a.repeatRate-b.repeatRate)[0]:null,bestRet=retainPool.length?Math.max(...retainPool.map(x=>x.repeatRate)):0,open=stats.filter(x=>x.age<=5),fastMonth=paid.length?paid[0].payback:null;document.getElementById('comparisonInsights').innerHTML=[
`<div class="insight"><label>Лучший ROI</label><b>${bestRoi.label} · ${bestRoi.roi.toFixed(0)}%</b></div>`,
`<div class="insight"><label>Минимальный CAC</label><b>${bestCac.label} · ${euro.format(bestCac.cac)}</b></div>`,
`<div class="insight"><label>Максимальный LTV</label><b>${bestLtv.label} · ${euro.format(bestLtv.ltv)}</b></div>`,
`<div class="insight"><label>Быстрее всех окупилась</label><b>${paid.length?paid.filter(x=>x.payback===fastMonth).map(x=>x.label).join(', ')+' · M'+fastMonth:'На закрытом горизонте ни одна'}</b></div>`,
`<div class="insight"><label>Риск низкого retention</label><b>${weak?weak.label+' · '+weak.repeatRate.toFixed(0)+'%':'Срок возврата ещё не наступил'}</b></div>`
].join('');document.getElementById('horizonNote').innerHTML=open.length?`<div class="callout">Неполный горизонт: ${open.map(x=>`${x.label} — ${horizonNote(x.age)}`).join('; ')}. Незакрытые месяцы не заполняются нулями и не участвуют в выборе лидера по LTV и ROI.</div>`:'';const ltvValues=ltvPool.map(x=>x.ltv),cacValues=stats.map(x=>x.cac),retValues=retainPool.map(x=>x.repeatRate),roiValues=roiPool.map(x=>x.roi);let h='<thead><tr><th>Кампания</th><th>Клиенты</th><th>Факт. бюджет</th><th>M0</th><th>Выручка M0–M5</th><th>LTV</th><th>CAC</th><th>Repeat rate</th><th>Окупаемость</th><th>Прибыль</th><th>ROI</th></tr></thead><tbody>';stats.forEach(x=>{const classes=[same(x.roi,bestRoi.roi)&&(x.age>5||!mature.length)?'best':'',weak&&retainPool.length>1&&!same(weak.repeatRate,bestRet)&&same(x.repeatRate,weak.repeatRate)?'risk-row':''].filter(Boolean).join(' ');const note=horizonNote(x.age);const ltvStyle=(x.age>5||!mature.length)?tint(x.ltv,ltvValues,false,'var(--accent)'):'';const retStyle=x.age>1?tint(x.repeatRate,retValues,false,'var(--accent)'):'';h+=`<tr class="${classes}"><td><b>${x.label}</b>${note?`<div class="maturity">${note}</div>`:''}</td><td>${x.clients}</td><td><input class="row-budget" data-campaign="${x.name}" type="number" min="0" step="100" inputmode="decimal" value="${x.spend}"></td><td>${euro.format(x.m0)}</td><td>${euro.format(x.revenue)}</td><td style="${ltvStyle}">${euro.format(x.ltv)}${same(x.ltv,bestLtv.ltv)&&(x.age>5||!mature.length)?'<span class="rank">лидер</span>':''}</td><td style="${tint(x.cac,cacValues,true,'var(--accent)')}">${euro.format(x.cac)}${same(x.cac,bestCac.cac)?'<span class="rank">лучший</span>':''}</td><td style="${retStyle}">${x.repeatRate.toFixed(0)}%${retainPool.length>1&&!same(weak.repeatRate,bestRet)&&same(x.repeatRate,weak.repeatRate)?'<span class="rank">риск</span>':''}${retainPool.length>1&&x.age>1&&same(x.repeatRate,bestRet)?'<span class="rank">лидер</span>':''}</td><td class="${paybackClass(x.paybackState)}">${paybackText(x.paybackState,x.payback)}${fastMonth!==null&&x.paybackState==='yes'&&x.payback===fastMonth?'<span class="rank">быстрее</span>':''}</td><td class="${x.profit>=0?'positive':'negative'}">${euro.format(x.profit)}</td><td class="${x.roi>=0?'positive':'negative'}" style="${(x.age>5||!mature.length)?tint(x.roi,roiValues,false,x.roi>=0?'var(--good)':'var(--danger)'):''}">${x.roi.toFixed(0)}%${same(x.roi,bestRoi.roi)&&(x.age>5||!mature.length)?'<span class="rank">лидер</span>':''}</td></tr>`});const allClients=DB.clients,totalSpend=stats.reduce((s,x)=>s+x.spend,0),totalM0=stats.reduce((s,x)=>s+x.m0,0),totalRevenue=stats.reduce((s,x)=>s+x.revenue,0),totalRepeat=allClients.filter(c=>c.visits.some(v=>v.age>0)).length,totalPaid=paybackOf(allClients,totalSpend),totalProfit=totalRevenue-totalSpend,totalRoi=totalSpend?totalProfit/totalSpend*100:0;h+=`<tr class="total"><td><b>All Campaigns</b>${horizonNote(totalPaid.age)?`<div class="maturity">${horizonNote(totalPaid.age)}</div>`:''}</td><td>${allClients.length}</td><td><b>${euro.format(totalSpend)}</b></td><td>${euro.format(totalM0)}</td><td>${euro.format(totalRevenue)}</td><td>${euro.format(totalRevenue/(allClients.length||1))}</td><td>${euro.format(totalSpend/(allClients.length||1))}</td><td>${allClients.length?(totalRepeat/allClients.length*100).toFixed(0):'0'}%</td><td class="${paybackClass(totalPaid.state)}">${paybackText(totalPaid.state,totalPaid.payback)}</td><td class="${totalProfit>=0?'positive':'negative'}">${euro.format(totalProfit)}</td><td class="${totalRoi>=0?'positive':'negative'}">${totalRoi.toFixed(0)}%</td></tr>`;document.getElementById('campaignComparison').innerHTML=h+'</tbody>';document.querySelectorAll('.row-budget').forEach(input=>input.oninput=()=>{const key=input.dataset.campaign;campaignBudgets[key]=Number(input.value)||0;saveBudgets();syncBudgetInput();renderCohort();const next=document.querySelector(`.row-budget[data-campaign="${CSS.escape(key)}"]`);if(next){next.focus();try{next.setSelectionRange(next.value.length,next.value.length)}catch(e){}}})}
function renderCohort(){const clients=rows(),map=cohortMap(clients),spend=budgetFor(campaign.value),revenue=clients.reduce((s,c)=>s+c.visits.filter(v=>v.age<=5).reduce((a,v)=>a+v.revenue,0),0),m0=clients.reduce((s,c)=>s+c.visits.filter(v=>v.age===0).reduce((a,v)=>a+v.revenue,0),0),profit=revenue-spend,roi=spend?profit/spend*100:0;document.getElementById('kBudget').textContent=euro.format(spend);document.getElementById('kRevenue').textContent=euro.format(revenue);document.getElementById('kProfit').textContent=euro.format(profit);document.getElementById('kProfit').className=profit>=0?'positive':'negative';document.getElementById('kRoi').textContent=`${roi.toFixed(1)}%`;document.getElementById('kRoi').className=roi>=0?'positive':'negative';document.getElementById('kCac').textContent=euro.format(spend/(clients.length||1));document.getElementById('kM0').textContent=spend?`${(m0/spend*100).toFixed(0)}%`:'—';document.getElementById('heatTitle').textContent=metricTitle[heatMetric];document.getElementById('metricHelp').textContent=metricCopy[heatMetric];renderHeat(map);renderBreakeven(clients,spend);renderLine(clients);renderClients(map);renderComparison()}
function demoRfm(){const now=new Date(DB.as_of+'T00:00:00'),groups={VIP:[],Постоянные:[],Спящие:[],'В зоне риска':[]};DB.clients.forEach(c=>{const last=new Date(c.visits.map(v=>v.date).sort().at(-1)+'T00:00:00'),days=Math.round((now-last)/86400000);let seg=days>90?'В зоне риска':days>60?'Спящие':c.revenue>=1000&&c.visit_count>=5?'VIP':'Постоянные';groups[seg].push({...c,days})});return groups}
function renderRfm(){document.getElementById('segments').innerHTML=DB.rfm.segments.map(s=>`<div class="segment"><span>${s.name}</span><strong style="color:${s.color}">${s.count}</strong><small class="meta">${(s.count/DB.rfm.base_size*100).toFixed(1)}% базы</small></div>`).join('');const max=Math.max(...DB.rfm.segments.map(s=>s.count));document.getElementById('segmentBars').innerHTML=DB.rfm.segments.map(s=>`<div class="bar-row"><span>${s.name}</span><div class="bar-track"><div class="bar-fill" style="width:${s.count/max*100}%;background:${s.color}"></div></div><b>${s.count}</b></div>`).join('');const groups=demoRfm(),rev=Object.entries(groups).map(([name,cs])=>[name,cs.reduce((s,c)=>s+c.revenue,0)]),maxR=Math.max(...rev.map(x=>x[1]),1);document.getElementById('segmentRevenue').innerHTML=rev.map(([n,v])=>`<div class="bar-row"><span>${n}</span><div class="bar-track"><div class="bar-fill" style="width:${v/maxR*100}%"></div></div><b>${euro.format(v)}</b></div>`).join('');document.getElementById('rfmRules').textContent=DB.rfm.rules;const risk=groups['В зоне риска'].sort((a,b)=>b.revenue-a.revenue).slice(0,15);document.getElementById('riskTable').innerHTML='<thead><tr><th>Имя</th><th>Телефон</th><th>Дней без визита</th><th>Потерянный LTV</th><th>ИИ-рекомендация</th></tr></thead><tbody>'+risk.map(c=>`<tr><td>${c.name}</td><td>${c.phone}</td><td class="risk">${c.days}</td><td>${euro.format(c.revenue)}</td><td class="recommend">${c.campaign.includes('SEO')?'Персональная консультация + бонус €40 на премиальную услугу':'Win-back сообщение с ограниченным бонусом 15% и быстрым слотом'}</td></tr>`).join('')+'</tbody>'}
function short(s){return s.length>26?s.slice(0,24)+'…':s}
function renderCross(){const c=DB.cross_sell;document.getElementById('multiCount').textContent=`${c.arrived_with_multiple_services} мульти-сервисных визитов`;let h='<thead><tr><th>Услуга</th>'+c.services.map(x=>`<th title="${x}">${short(x)}</th>`).join('')+'</tr></thead><tbody>';c.services.forEach((a,i)=>{h+=`<tr><td title="${a}">${short(a)}</td>`;c.services.forEach((b,j)=>{const v=c.matrix[i][j],max=Math.max(...c.matrix.flat(),1);h+=`<td style="background:${heatColor(v,max)}">${v}</td>`});h+='</tr>'});document.getElementById('matrix').innerHTML=h+'</tbody>';const pmax=Math.max(...c.pairs.map(x=>x.count),1);document.getElementById('pairs').innerHTML=c.pairs.length?c.pairs.map(x=>`<div class="bar-row"><span title="${x.a} + ${x.b}">${short(x.a)} + ${short(x.b)}</span><div class="bar-track"><div class="bar-fill" style="width:${x.count/pmax*100}%"></div></div><b>${x.count}</b></div>`).join(''):'<div class="empty">Совместные услуги не найдены</div>';const omax=Math.max(...c.opportunities.map(x=>x.potential),1);document.getElementById('opportunity').innerHTML=c.opportunities.map(x=>`<div class="bar-row"><span title="${x.service}">${short(x.service)}</span><div class="bar-track"><div class="bar-fill" style="width:${x.potential/omax*100}%;background:var(--warn)"></div></div><b>${euro.format(x.potential)}</b></div>`).join('');const total=c.opportunities.reduce((s,x)=>s+x.potential,0);document.getElementById('potentialTotal').textContent=`Потенциальный прирост при конверсии всех одиночных продаж в допродажу: ${euro.format(total)}.`}
function renderIdle(){const cap=DB.capacity,total=cap.staff.reduce((s,x)=>s+x.scheduled_hours,0),lost=cap.staff.reduce((s,x)=>s+x.scheduled_hours*(1-x.occupancy/100)*cap.location.avg_check,0);document.getElementById('scheduledHours').textContent=`${number.format(total)} ч`;document.getElementById('lostRevenue').textContent=euro.format(lost);document.getElementById('staff').innerHTML=cap.staff.map(x=>`<div class="staff"><b>${x.name}</b><span class="meta">Загрузка ${x.occupancy}%</span><div class="meter"><i style="width:${Math.max(1,x.occupancy)}%"></i></div><small class="meta">${euro.format(x.revenue)} · ${x.scheduled_hours} ч расписания</small></div>`).join('');const days=['Пн','Вт','Ср','Чт','Пт','Сб','Вс'],hours=Array.from({length:13},(_,i)=>9+i),counts={};cap.appointments.forEach(a=>{const d=new Date(a.date+'T00:00:00'),di=(d.getDay()+6)%7;counts[`${di}-${a.hour}`]=(counts[`${di}-${a.hour}`]||0)+1});let h='<thead><tr><th>День</th>'+hours.map(x=>`<th>${x}:00</th>`).join('')+'</tr></thead><tbody>';days.forEach((d,di)=>{h+=`<tr><td>${d}</td>`;hours.forEach(hr=>{const booked=counts[`${di}-${hr}`]||0,capacity=16,empty=Math.max(0,capacity-booked),p=empty/capacity;h+=`<td title="${empty} из ${capacity} слотов свободно" style="background:color-mix(in srgb,var(--danger) ${10+p*55}%,var(--panel2))">${empty}</td>`});h+='</tr>'});document.getElementById('hourGrid').innerHTML=h+'</tbody>'}
renderCohort();renderRfm();renderCross();renderIdle();
</script></body></html>"""


def load_existing_cross_sell(path: Path) -> dict | None:
    """Keep the last baked cross-sell snapshot if export files are not passed."""
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    start = text.find("const DB=")
    if start < 0:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(text[start + len("const DB="):])
    except json.JSONDecodeError:
        return None
    cross = data.get("cross_sell") or {}
    return cross if cross.get("services") else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("exports", nargs="*", type=Path)
    parser.add_argument("--output", type=Path, default=Path("dashboards/index.html"))
    args = parser.parse_args()
    data = portal_data(args.exports)
    if not data["cross_sell"]["services"]:
        preserved = load_existing_cross_sell(args.output)
        if preserved:
            data["cross_sell"] = preserved
    html = HTML.replace("{{DATA}}", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "campaign_clients": len(data["clients"]),
        "campaign_visits": sum(c["visit_count"] for c in data["clients"]),
        "cross_sell_services": len(data["cross_sell"]["services"]),
        "rfm_base": data["rfm"]["base_size"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
