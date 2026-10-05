#!/usr/bin/env python3
"""Build a self-contained cohort/LTV dashboard from Altegio appointment exports.

The input files are the text exports produced by the Altegio MCP
`appointments_list` tool. Only completed (`arrived`) appointments with a client
ID and a reported sold total are used. No names or contact details are stored.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path


APPOINTMENT_RE = re.compile(
    r"^- Appointment (?P<appointment>\d+): "
    r"(?P<when>\d{4}-\d{2}-\d{2}T[^\s]+) · "
    r"(?P<status>[a-z_]+) · client id (?P<client>\d+|not reported) · "
    r"team member id \d+ · \d+ service\(s\) · "
    r"total (?P<total>-?\d+(?:\.\d+)?|not reported)$"
)

CHANNEL_CLIENTS = {
    "Instagram Target": {
        153614853, 153761790, 153763991, 154385954, 181975366, 181998420,
        182078153, 182184655, 182267350, 182429809, 182635041, 182683823,
        182697972, 182755588, 182923411, 182957225, 182960803, 182995046,
        183048823, 183098217, 184070224, 184734687, 184844240, 184928737,
        185182674, 185395351, 186281041, 186468451, 186595906, 186788079,
        186810259, 186984894, 187002142, 187012615, 187121973,
    },
    "Google Maps": {182239971},
    "Instagram Story": {182477087},
}


def month_key(value: datetime) -> str:
    return value.strftime("%Y-%m")


def parse_exports(paths: list[Path], as_of: date) -> tuple[list[dict], dict]:
    appointments: dict[int, dict] = {}
    stats = {"lines": 0, "parsed": 0, "excluded_future": 0, "excluded_status": 0}

    for path in paths:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            stats["lines"] += 1
            line = re.sub(r"^\s*\d+\|", "", raw_line).strip()
            match = APPOINTMENT_RE.match(line)
            if not match:
                continue
            stats["parsed"] += 1
            item = match.groupdict()
            appointment_id = int(item["appointment"])
            when = datetime.fromisoformat(item["when"])
            if when.date() > as_of:
                stats["excluded_future"] += 1
                continue
            if item["status"] != "arrived":
                stats["excluded_status"] += 1
                continue
            if item["client"] == "not reported" or item["total"] == "not reported":
                continue
            appointments[appointment_id] = {
                "appointment_id": appointment_id,
                "client_id": int(item["client"]),
                "month": month_key(when),
                "revenue": float(item["total"]),
            }

    client_month: dict[tuple[int, str], dict] = {}
    for item in appointments.values():
        key = (item["client_id"], item["month"])
        if key not in client_month:
            client_month[key] = {
                "client_id": item["client_id"],
                "month": item["month"],
                "revenue": 0.0,
                "visits": 0,
            }
        client_month[key]["revenue"] += item["revenue"]
        client_month[key]["visits"] += 1

    first_month: dict[int, str] = {}
    for item in client_month.values():
        client_id = item["client_id"]
        first_month[client_id] = min(first_month.get(client_id, item["month"]), item["month"])

    def channel_for(client_id: int) -> str:
        for channel, ids in CHANNEL_CLIENTS.items():
            if client_id in ids:
                return channel
        return "Без маркетинговой метки"

    rows = []
    for item in sorted(client_month.values(), key=lambda x: (x["month"], x["client_id"])):
        cohort = first_month[item["client_id"]]
        cohort_year, cohort_month = map(int, cohort.split("-"))
        item_year, item_month = map(int, item["month"].split("-"))
        age = (item_year - cohort_year) * 12 + item_month - cohort_month
        rows.append({
            **item,
            "cohort": cohort,
            "age": age,
            "channel": channel_for(item["client_id"]),
            "revenue": round(item["revenue"], 2),
        })

    stats.update({
        "unique_appointments": len(appointments),
        "clients_with_arrived_visits": len(first_month),
        "client_month_rows": len(rows),
        "min_month": min((row["month"] for row in rows), default=None),
        "max_month": max((row["month"] for row in rows), default=None),
    })
    return rows, stats


HTML_TEMPLATE = r"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Casa House — когорты и LTV</title>
  <style>
    :root{--bg:#f5f7f4;--panel:#fff;--ink:#17211b;--muted:#66736b;--line:#dbe2dc;--accent:#176b45;--accent2:#96c7aa;--warn:#9a5b13}
    *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 Inter,Segoe UI,Arial,sans-serif}
    .wrap{max-width:1440px;margin:auto;padding:28px}.top{display:flex;justify-content:space-between;gap:24px;align-items:flex-end}
    h1{font-size:28px;margin:0 0 5px;letter-spacing:-.6px}.sub,.note{color:var(--muted)} .controls{display:flex;gap:10px;flex-wrap:wrap}
    select,button{border:1px solid var(--line);background:var(--panel);padding:9px 12px;border-radius:7px;color:var(--ink)}
    button.active{background:var(--accent);color:#fff;border-color:var(--accent)}
    .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:22px 0}.kpi{background:var(--panel);border:1px solid var(--line);padding:16px;border-radius:10px}
    .kpi .label{color:var(--muted);font-size:12px}.kpi .value{font-size:25px;font-weight:700;margin:5px 0}.kpi .meta{font-size:12px;color:var(--muted)}
    .grid{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(340px,.75fr);gap:16px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px;min-width:0}
    h2{font-size:17px;margin:0 0 3px}.caption{font-size:12px;color:var(--muted);margin-bottom:14px}
    .heat-wrap{overflow:auto;max-height:580px}.heat{border-collapse:separate;border-spacing:3px;width:100%;min-width:760px}
    .heat th{font-size:11px;color:var(--muted);font-weight:600;position:sticky;top:0;background:var(--panel);z-index:1}.heat td{height:34px;text-align:center;font-size:11px;border-radius:4px;min-width:55px}
    .heat td:first-child,.heat th:first-child{text-align:left;position:sticky;left:0;background:var(--panel);z-index:2;min-width:105px}
    .cohort-size{display:block;color:var(--muted);font-size:10px}.chart{width:100%;height:360px}.legend{display:flex;gap:12px;flex-wrap:wrap;font-size:11px;color:var(--muted);margin-top:8px}
    .dot{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:4px}.insights{margin-top:16px}.insights li{margin:8px 0}
    .foot{margin-top:16px;padding:14px 2px;border-top:1px solid var(--line);font-size:12px;color:var(--muted)}
    @media(max-width:900px){.wrap{padding:16px}.top{display:block}.controls{margin-top:14px}.kpis{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}}
  </style>
</head>
<body>
<main class="wrap">
  <div class="top">
    <div><h1>Когортный анализ выручки и LTV</h1><div class="sub">Casa House · данные Altegio · <span id="period"></span></div></div>
    <div class="controls">
      <select id="channel" aria-label="Маркетинговый канал"></select>
      <button class="metric active" data-metric="ltv">LTV</button>
      <button class="metric" data-metric="revenue">Выручка</button>
      <button class="metric" data-metric="retention">Revenue retention</button>
    </div>
  </div>
  <section class="kpis">
    <div class="kpi"><div class="label">LTV M3</div><div class="value" id="m3">—</div><div class="meta">зрелые когорты, накопительно M0–M3</div></div>
    <div class="kpi"><div class="label">LTV M6</div><div class="value" id="m6">—</div><div class="meta">зрелые когорты, накопительно M0–M6</div></div>
    <div class="kpi"><div class="label">Средний чек привлечения</div><div class="value" id="m0">—</div><div class="meta">выручка M0 / размер когорты</div></div>
    <div class="kpi"><div class="label">Лучшая категория по возврату</div><div class="value" id="topChannel">—</div><div class="meta" id="topChannelMeta">доля клиентов с визитом M1+</div></div>
  </section>
  <div class="grid">
    <section class="panel">
      <h2 id="heatTitle">LTV по когортам и месяцам жизни</h2>
      <div class="caption">Строка — месяц первого завершённого визита; M0 — месяц привлечения. EUR.</div>
      <div class="heat-wrap"><table class="heat" id="heat"></table></div>
    </section>
    <section class="panel">
      <h2>Накопительный LTV когорт</h2>
      <div class="caption">Последние 8 когорт · ось X: месяц жизни · ось Y: EUR на клиента</div>
      <svg class="chart" id="chart" viewBox="0 0 620 360" role="img" aria-label="Кривые накопительного LTV"></svg>
      <div class="legend" id="legend"></div>
      <div class="insights"><h2>Главные наблюдения</h2><ul id="insights"></ul></div>
    </section>
  </div>
  <div class="foot">
    Методика: только записи со статусом arrived, известным client_id и суммой продажи; будущие даты после {{AS_OF}} исключены.
    Выручка — сумма продажи записи, не банковский cash flow. Клиентская когорта определяется первым arrived-визитом в доступной истории.
    Неполные месяцы жизни не подставляются нулями. История начинается в сентябре 2023, поэтому самые ранние когорты могут быть неполными.
    Канал — текущая метка карточки клиента; она не доказывает, что именно этот канал привлёк клиента в дату первого визита.
    Источник: Altegio MCP, филиал 764940.
  </div>
</main>
<script>
const DATA={{DATA}};
const META={{META}};
const eur=new Intl.NumberFormat('ru-RU',{style:'currency',currency:'EUR',maximumFractionDigits:0});
const num=new Intl.NumberFormat('ru-RU',{maximumFractionDigits:0});
let metric='ltv';
const channel=document.getElementById('channel');
const channels=['Все категории',...new Set(DATA.map(d=>d.channel))];
channel.innerHTML=channels.map(x=>`<option>${x}</option>`).join('');
document.getElementById('period').textContent=`${META.min_month} — ${META.max_month}`;
document.querySelectorAll('.metric').forEach(b=>b.onclick=()=>{document.querySelectorAll('.metric').forEach(x=>x.classList.remove('active'));b.classList.add('active');metric=b.dataset.metric;render()});
channel.onchange=render;
function selected(){return channel.value==='Все категории'?DATA:DATA.filter(d=>d.channel===channel.value)}
function matrix(rows){
  const cohorts={};
  rows.forEach(r=>{cohorts[r.cohort]??={clients:new Set(),months:{}};cohorts[r.cohort].clients.add(r.client_id);cohorts[r.cohort].months[r.age]=(cohorts[r.cohort].months[r.age]||0)+r.revenue});
  return cohorts;
}
function matureLtv(rows,h){
  const cutoff=new Date(META.as_of+'T00:00:00'); cutoff.setMonth(cutoff.getMonth()-h);
  const eligible=new Set([...new Set(rows.map(r=>r.cohort))].filter(c=>new Date(c+'-01')<=cutoff));
  const clients=new Set(rows.filter(r=>eligible.has(r.cohort)).map(r=>r.client_id));
  const revenue=rows.filter(r=>eligible.has(r.cohort)&&r.age<=h).reduce((s,r)=>s+r.revenue,0);
  return clients.size?revenue/clients.size:0;
}
function renderKpis(rows,cohorts){
  document.getElementById('m3').textContent=eur.format(matureLtv(rows,3));
  document.getElementById('m6').textContent=eur.format(matureLtv(rows,6));
  const clients=new Set(rows.map(r=>r.client_id)).size;
  const m0=rows.filter(r=>r.age===0).reduce((s,r)=>s+r.revenue,0)/(clients||1);
  document.getElementById('m0').textContent=eur.format(m0);
  const byChannel={};
  DATA.forEach(r=>{byChannel[r.channel]??={all:new Set(),repeat:new Set()};byChannel[r.channel].all.add(r.client_id);if(r.age>0)byChannel[r.channel].repeat.add(r.client_id)});
  const ranked=Object.entries(byChannel).map(([k,v])=>[k,v.repeat.size/(v.all.size||1),v.all.size]).filter(x=>x[2]>=3).sort((a,b)=>b[1]-a[1]);
  const top=channel.value==='Все категории'?ranked[0]:ranked.find(x=>x[0]===channel.value);
  document.getElementById('topChannel').textContent=top?top[0]:'—';
  document.getElementById('topChannelMeta').textContent=top?`${(top[1]*100).toFixed(0)}% вернулись · ${top[2]} клиентов`:'недостаточно данных';
}
function heatColor(v,max){
  if(v===null)return 'transparent';
  const t=max?Math.max(0,Math.min(1,v/max)):0;
  return `color-mix(in srgb, #176b45 ${12+t*78}%, white)`;
}
function renderHeat(cohorts){
  const names=Object.keys(cohorts).sort().reverse();
  const maxAge=Math.min(12,Math.max(0,...names.flatMap(c=>Object.keys(cohorts[c].months).map(Number))));
  const vals=[];
  names.forEach(c=>{const x=cohorts[c],size=x.clients.size,m0=x.months[0]||0;for(let m=0;m<=maxAge;m++){const rev=x.months[m];vals.push(rev===undefined?null:metric==='revenue'?rev:metric==='ltv'?rev/size:m0?rev/m0*100:0)}});
  const max=Math.max(...vals.filter(v=>v!==null),1);
  const label=metric==='revenue'?'Выручка':metric==='retention'?'Revenue retention':'LTV';
  document.getElementById('heatTitle').textContent=`${label} по когортам и месяцам жизни`;
  let html='<thead><tr><th>Когорта</th>'+Array.from({length:maxAge+1},(_,i)=>`<th>M${i}</th>`).join('')+'</tr></thead><tbody>';
  names.forEach(c=>{const x=cohorts[c],size=x.clients.size,m0=x.months[0]||0;html+=`<tr><td>${c}<span class="cohort-size">${size} клиентов</span></td>`;
    for(let m=0;m<=maxAge;m++){const rev=x.months[m];let v=rev===undefined?null:metric==='revenue'?rev:metric==='ltv'?rev/size:m0?rev/m0*100:0;
      const text=v===null?'':metric==='retention'?`${v.toFixed(0)}%`:eur.format(v);
      html+=`<td style="background:${heatColor(v,max)};color:${v/max>.55?'white':'var(--ink)'}" title="${c}, M${m}: ${text}">${text}</td>`}
    html+='</tr>'});document.getElementById('heat').innerHTML=html+'</tbody>';
}
function renderChart(cohorts){
  const names=Object.keys(cohorts).sort().slice(-8),maxAge=Math.min(12,Math.max(0,...names.flatMap(c=>Object.keys(cohorts[c].months).map(Number))));
  const series=names.map(c=>{const x=cohorts[c],points=[],size=x.clients.size;let cum=0;for(let m=0;m<=maxAge;m++){cum+=x.months[m]||0;if(x.months[m]!==undefined||m===0)points.push([m,cum/size])}return {name:c,points}});
  const maxY=Math.max(1,...series.flatMap(s=>s.points.map(p=>p[1]))),W=620,H=360,L=52,R=15,T=14,B=42;
  const sx=x=>L+x/(maxAge||1)*(W-L-R),sy=y=>H-B-y/maxY*(H-T-B);
  const colors=['#176b45','#337a93','#8b5d33','#743f75','#506b2d','#a84b42','#486087','#777'];
  let svg='';for(let i=0;i<=4;i++){const y=maxY*i/4;svg+=`<line x1="${L}" y1="${sy(y)}" x2="${W-R}" y2="${sy(y)}" stroke="#dbe2dc"/><text x="${L-7}" y="${sy(y)+4}" text-anchor="end" font-size="10" fill="#66736b">${num.format(y)}</text>`}
  for(let i=0;i<=maxAge;i+=Math.max(1,Math.ceil(maxAge/6)))svg+=`<text x="${sx(i)}" y="${H-17}" text-anchor="middle" font-size="10" fill="#66736b">M${i}</text>`;
  series.forEach((s,i)=>{const d=s.points.map((p,j)=>`${j?'L':'M'}${sx(p[0])},${sy(p[1])}`).join(' ');svg+=`<path d="${d}" fill="none" stroke="${colors[i]}" stroke-width="2.5"/>`});
  svg+=`<text x="${(L+W-R)/2}" y="${H-2}" text-anchor="middle" font-size="11" fill="#66736b">Месяц жизни когорты</text><text transform="translate(12 ${(T+H-B)/2}) rotate(-90)" text-anchor="middle" font-size="11" fill="#66736b">Накопительный LTV, EUR/клиент</text>`;
  document.getElementById('chart').innerHTML=svg;document.getElementById('legend').innerHTML=series.map((s,i)=>`<span><i class="dot" style="background:${colors[i]}"></i>${s.name}</span>`).join('');
}
function renderInsights(rows,cohorts){
  const clients=new Set(rows.map(r=>r.client_id)),repeat=new Set(rows.filter(r=>r.age>0).map(r=>r.client_id));
  const revenue=rows.reduce((s,r)=>s+r.revenue,0),latest=Object.keys(cohorts).sort().slice(-3);
  const latestLtv=latest.map(c=>[c,Object.values(cohorts[c].months).reduce((a,b)=>a+b,0)/cohorts[c].clients.size]).sort((a,b)=>b[1]-a[1])[0];
  const notes=[`${clients.size} клиентов с завершёнными визитами; ${repeat.size} (${(repeat.size/(clients.size||1)*100).toFixed(0)}%) вернулись в последующий календарный месяц.`,`Наблюдаемая выручка выбранного среза — ${eur.format(revenue)}.`,latestLtv?`Среди трёх последних когорт максимальный текущий LTV у ${latestLtv[0]}: ${eur.format(latestLtv[1])}.`:''];
  document.getElementById('insights').innerHTML=notes.filter(Boolean).map(x=>`<li>${x}</li>`).join('');
}
function render(){const rows=selected(),cohorts=matrix(rows);renderKpis(rows,cohorts);renderHeat(cohorts);renderChart(cohorts);renderInsights(rows,cohorts)}
render();
</script>
</body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=Path("dashboards/index.html"))
    parser.add_argument("--as-of", default="2026-10-02")
    args = parser.parse_args()

    as_of = date.fromisoformat(args.as_of)
    rows, stats = parse_exports(args.inputs, as_of)
    if not rows:
        raise SystemExit("No eligible arrived appointments found")

    meta = {**stats, "as_of": args.as_of, "location_id": 764940, "location_name": "Casa House"}
    html = (
        HTML_TEMPLATE
        .replace("{{DATA}}", json.dumps(rows, ensure_ascii=False, separators=(",", ":")))
        .replace("{{META}}", json.dumps(meta, ensure_ascii=False, separators=(",", ":")))
        .replace("{{AS_OF}}", args.as_of)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
