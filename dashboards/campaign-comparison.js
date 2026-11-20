'use strict';

function comparisonText(ru, en) { return language === 'ru' ? ru : en; }
function repeatClientCount(clients) {
  return clients.filter(c => new Set(c.visits.map((v, i) => v.appointment_id ?? v.visit_id ?? `${v.date}:${i}`)).size >= 2).length;
}
function statsForClients(clients, name, spend, label) {
  const m0 = clients.reduce((sum, c) => sum + c.visits.filter(v => v.age === 0).reduce((n, v) => n + Number(v.revenue || 0), 0), 0);
  const revenue = clients.reduce((sum, c) => sum + c.visits.reduce((n, v) => n + Number(v.revenue || 0), 0), 0);
  const paid = paybackOf(clients, spend ?? 0);
  return {name, label, clients: clients.length, spend, m0, revenue,
    ltv: clients.length ? revenue / clients.length : null,
    cac: spend !== null && clients.length ? spend / clients.length : null,
    repeatRate: clients.length ? repeatClientCount(clients) / clients.length * 100 : null,
    payback: paid.payback, paybackState: spend === 0 ? 'no_cost' : paid.state,
    profit: spend === null ? null : revenue - spend,
    roi: spend > 0 ? (revenue - spend) / spend * 100 : null, age: paid.age};
}
function campaignClients(name, month = null) {
  return cohortClients.filter(c => c.categories.includes(name) && (!month || c.first_visit.slice(0, 7) === month));
}
function statsFor(name, month = null) {
  return statsForClients(campaignClients(name, month), name, month ? budgetBook.month(name, month) : budgetFor(name), campaignLabel(name));
}
function campaignMonthKeys(name) {
  const keys = campaignClients(name).map(c => c.first_visit.slice(0, 7));
  keys.push(...budgetBook.months(name));
  const sorted = [...new Set(keys)].sort();
  return sorted.length ? monthRange(sorted[0], sorted.at(-1)) : [];
}
const comparisonMetrics = [
  [
    "Кампания",
    "Campaign",
    "Клиенты с одной маркетинговой категорией. Раскройте строку, чтобы увидеть группы по месяцу первого оплаченного визита.",
    "Clients with the same marketing category. Expand a row to see groups by first paid-visit month."
  ],
  [
    "Привлечённые клиенты",
    "Acquired clients",
    "Сколько уникальных клиентов пришло по этой рекламе. Определяем их по категории кампании в Altegio и первому полностью оплаченному визиту. Каждый человек считается один раз. В строке месяца — клиенты, впервые оплатившие визит в этом месяце.",
    "How many unique clients came through this campaign. We identify them by the campaign category in Altegio and their first fully paid visit. Each person counts once. A monthly row includes clients whose first paid visit was that month."
  ],
  [
    "Бюджет на рекламу",
    "Ad spend",
    "Сколько потратили на привлечение этих клиентов. Бюджеты вы вводите сами. Суммы по месяцам складываются в бюджет кампании. Пустое поле — сумма неизвестна; 0 — затрат не было.",
    "What you spent to attract these clients. You enter the budgets. Monthly amounts add up to campaign spend. Blank means unknown; 0 means no spend."
  ],
  [
    "Выручка в первый месяц (M0)",
    "First-month revenue (M0)",
    "Сколько клиенты заплатили за визиты в месяц своего первого оплаченного визита. Для каждого клиента первый месяц определяется отдельно.",
    "What clients paid for visits in the month of their first paid visit. The first month is determined separately for each client."
  ],
  [
    "Выручка",
    "Revenue",
    "Складываем суммы полностью оплаченных состоявшихся визитов этих клиентов за весь доступный период. Неоплаченные и частично оплаченные визиты не считаем.",
    "Sum of fully paid, attended visits for these clients over all available history. Unpaid and partially paid visits are excluded."
  ],
  [
    "Выручка на клиента (LTV)",
    "Revenue per client (LTV)",
    "Выручка ÷ количество клиентов. Например, 2 000 € от 20 клиентов — это 100 € на клиента. Это уже полученная выручка, а не прогноз.",
    "Revenue ÷ number of clients. For example, €2,000 from 20 clients is €100 per client. This is revenue already received, not a forecast."
  ],
  [
    "Стоимость привлечения клиента (CAC)",
    "Client acquisition cost (CAC)",
    "Бюджет на рекламу ÷ количество клиентов. Например, потратили 400 € и получили 20 клиентов — привлечение одного клиента стоило 20 €.",
    "Ad spend ÷ number of clients. For example, €400 spent to attract 20 clients means €20 per client."
  ],
  [
    "Возвращаемость клиентов",
    "Repeat rate",
    "Какая часть клиентов пришла и полностью оплатила хотя бы два разных визита. Например, вернулись 6 из 20 — это 30%. Повтор в том же месяце тоже считается. Несколько услуг в одном визите считаются одним визитом.",
    "Share of clients with at least two separate, fully paid visits. If 6 of 20 returned, that is 30%. Same-month returns count. Several services in one appointment count as one visit."
  ],
  [
    "Месяц окупаемости",
    "Payback month",
    "Когда общая выручка этих клиентов впервые покрыла бюджет на рекламу. M0 — в первый месяц, M1 — в следующий. «Не закрыт» — месяц ещё идёт. Здесь учитываем только расходы на рекламу.",
    "When client revenue first covered ad spend. M0 means the first month; M1 means the next month. “Not closed” means the month is still in progress. Only ad costs are included."
  ],
  [
    "Выручка минус реклама",
    "Revenue minus ads",
    "Из выручки вычитаем бюджет на рекламу. Например, выручка 2 000 €, реклама 400 € — остаётся 1 600 €. Зарплаты, материалы, аренда и налоги здесь ещё не вычтены.",
    "Revenue minus ad spend. For example, €2,000 in revenue minus €400 in ads leaves €1,600. Salaries, materials, rent and taxes have not been deducted."
  ],
  [
    "Доходность рекламы (ROI)",
    "Ad return (ROI)",
    "Выручку минус рекламу делим на бюджет рекламы и умножаем на 100%. Например, выручка 800 € и реклама 400 € дают 100%: на каждый 1 € рекламы получен ещё 1 € сверх её стоимости. Остальные расходы салона не вычтены. При нулевом или неизвестном бюджете — прочерк.",
    "Revenue minus ad spend, divided by ad spend, times 100%. For example, €800 revenue and €400 in ads gives 100%: each €1 spent returned €1 above the ad cost. Other salon costs are not deducted. Zero or unknown spend gives a dash."
  ]
];
function metricHeading(index) {
 const metric=comparisonMetrics[index],name=comparisonText(metric[0],metric[1]);
 return `<span class="metric-heading">${htmlSafe(name)}<button type="button" class="metric-info" data-help="${index}" aria-label="${htmlSafe(comparisonText('Как считается: ','How this is calculated: ')+name)}">?</button></span>`;
}
function comparisonHeader(){return '<thead><tr>'+comparisonMetrics.flatMap((_,i)=>i===3?[]:[`<th scope="col">${metricHeading(i)}</th>`]).join('')+'</tr></thead>';}
function renderKpiMetadata(clients,spend){
 const cards=[['kBudget',2,'Введённые расходы','Entered spend'],['kRevenue',4,'За весь доступный период','All available history'],['kLtv',5,'Выручка ÷ клиенты','Revenue ÷ clients'],['kProfit',9,'Без остальных расходов салона','Before other salon costs'],['kRoi',10,'Результат рекламных затрат','Return on ad spend'],['kCac',6,'Реклама ÷ клиенты','Ad spend ÷ clients'],['kRepeat',7,'Пришли повторно','Returned for another visit']];
 cards.forEach(([id,index,ru,en])=>{const card=document.getElementById(id).closest('.kpi');card.querySelector('label').innerHTML=metricHeading(index);card.querySelector('small').textContent=comparisonText(ru,en)});
 const stats=statsForClients(clients,'selected',spend,'selected');
 document.getElementById('kLtv').textContent=comparisonAmount(stats.ltv);
 const value=document.getElementById('kRepeat');value.textContent=stats.repeatRate===null?'—':stats.repeatRate.toFixed(0)+'%';value.className='';
 setupComparisonTooltips();
}
function comparisonAmount(value) { return value === null ? '—' : euro.format(value); }
function comparisonInput(name, kind, value, month = '') {
  const label = `${comparisonText('Бюджет: ', 'Budget: ')}${campaignLabel(name)} · ${month ? monthLabel(month) : comparisonText(kind === 'unallocated' ? 'нераспределено' : 'вся кампания', kind === 'unallocated' ? 'unallocated' : 'whole campaign')}`;
  return `<input class="row-budget" data-campaign="${htmlSafe(name)}" data-kind="${kind}" data-month="${month}" type="number" min="0" step="0.01" inputmode="decimal" value="${value ?? ''}" placeholder="${comparisonText('Не указан', 'Not set')}" aria-label="${htmlSafe(label)}">`;
}
const campaignNoteLimit = 5000;
let campaignNoteContext = null;
function campaignNotesStorageKey() {
  if (!DB.location?.id) throw Error(comparisonText('Сначала выберите филиал.', 'Select a location first.'));
  return 'altegioCampaignNotes:v1:' + JSON.stringify([DB.connection_id || '', String(DB.location.id)]);
}
function campaignNoteKey(name, month = '') { return JSON.stringify([name, month || '']); }
function campaignNoteScopeIsCurrent(scope) {
  try { return scope === campaignNotesStorageKey(); } catch (error) { return false; }
}
function readCampaignNotes(scope = campaignNotesStorageKey()) {
  const raw = localStorage.getItem(scope);
  if (!raw) return {};
  const notes = JSON.parse(raw);
  if (!notes || typeof notes !== 'object' || Array.isArray(notes)) throw Error('Invalid notes');
  return notes;
}
function campaignNoteText(name, month = '') {
  try {
    const text = readCampaignNotes()[campaignNoteKey(name, month)];
    return typeof text === 'string' ? text : '';
  } catch (error) { return ''; }
}
function saveCampaignNote(name, month, text, scope = campaignNotesStorageKey()) {
  if (!campaignNoteScopeIsCurrent(scope)) throw Error(comparisonText('Филиал или аккаунт изменился. Откройте заметку заново.', 'The location or account changed. Reopen the note.'));
  if (typeof text !== 'string' || text.length > campaignNoteLimit) throw Error(comparisonText('Заметка должна быть не длиннее 5 000 символов.', 'Keep the note within 5,000 characters.'));
  const notes = readCampaignNotes(scope), key = campaignNoteKey(name, month);
  if (text.trim()) notes[key] = text.trim(); else delete notes[key];
  localStorage.setItem(scope, JSON.stringify(notes));
}
function campaignNoteButton(name, month = '') {
  const text = campaignNoteText(name, month), scope = campaignLabel(name) + (month ? ' · ' + monthLabel(month) : '');
  const label = comparisonText('Заметка о рекламе: ', 'Advertising note: ') + scope;
  const title = text ? comparisonText('Заметка: ', 'Note: ') + (text.length > 240 ? text.slice(0, 240) + '…' : text) : comparisonText('Добавить заметку о рекламе', 'Add an advertising note');
  return `<button type="button" class="campaign-note${text ? ' has-note' : ''}" data-campaign="${htmlSafe(name)}" data-month="${htmlSafe(month)}" aria-label="${htmlSafe(label)}" aria-haspopup="dialog" aria-controls="campaignNoteDialog" title="${htmlSafe(title)}"><svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 2.5h7l3 3v12H5zM12 2.5v4h3M8 10h4M8 13h4"/></svg></button>`;
}
function positionCampaignNoteDialog() {
  const dialog = document.getElementById('campaignNoteDialog');
  if (!dialog?.open || !campaignNoteContext?.anchor.isConnected) return;
  const anchor = campaignNoteContext.anchor.getBoundingClientRect(), box = dialog.getBoundingClientRect(), margin = 16;
  const left = Math.max(margin, Math.min(anchor.right + 8, window.innerWidth - box.width - margin));
  const top = anchor.bottom + 8 + box.height <= window.innerHeight - margin ? anchor.bottom + 8 : anchor.top - box.height - 8;
  dialog.style.left = left + 'px';
  dialog.style.top = Math.max(margin, Math.min(top, window.innerHeight - box.height - margin)) + 'px';
}
function ensureCampaignNoteDialog() {
  let dialog = document.getElementById('campaignNoteDialog');
  if (dialog) return dialog;
  dialog = document.createElement('dialog');
  dialog.id = 'campaignNoteDialog'; dialog.className = 'campaign-note-dialog';
  dialog.setAttribute('aria-labelledby', 'campaignNoteTitle');
  dialog.setAttribute('aria-describedby', 'campaignNoteScope');
  dialog.innerHTML = '<form id="campaignNoteForm"><h3 id="campaignNoteTitle"></h3><p id="campaignNoteScope" class="caption"></p><label for="campaignNoteText" id="campaignNoteLabel"></label><textarea id="campaignNoteText" rows="6" maxlength="5000"></textarea><div class="campaign-note-meta"><span id="campaignNoteHint"></span><span id="campaignNoteCount"></span></div><p id="campaignNoteStatus" role="status" aria-live="polite"></p><div class="campaign-note-actions"><button type="button" class="theme" id="campaignNoteClear"></button><span></span><button type="button" class="theme" id="campaignNoteCancel"></button><button type="submit" class="sync" id="campaignNoteSave"></button></div></form>';
  document.body.append(dialog);
  const text = document.getElementById('campaignNoteText'), status = document.getElementById('campaignNoteStatus');
  text.oninput = () => { status.textContent = ''; document.getElementById('campaignNoteCount').textContent = text.value.length + ' / ' + campaignNoteLimit; document.getElementById('campaignNoteClear').disabled = !text.value; };
  document.getElementById('campaignNoteCancel').onclick = () => dialog.close();
  document.getElementById('campaignNoteClear').onclick = () => { text.value = ''; text.oninput(); text.focus(); };
  document.getElementById('campaignNoteForm').onsubmit = event => {
    event.preventDefault();
    const context = campaignNoteContext;
    if (!context) return;
    try {
      saveCampaignNote(context.name, context.month, text.value, context.scope);
      dialog.close(); renderComparison(); translatePage();
    } catch (error) {
      status.textContent = error.message.includes('Invalid notes') ? comparisonText('Не удалось прочитать сохранённые заметки. Текст не перезаписан.', 'Saved notes could not be read. Nothing was overwritten.') : comparisonText('Не удалось сохранить заметку. Текст остался в окне. Проверьте доступность хранилища браузера.', 'Could not save the note. Your text is still here. Check browser storage access.');
      if (!campaignNoteScopeIsCurrent(context.scope)) status.textContent = comparisonText('Филиал или аккаунт изменился. Откройте заметку заново.', 'The location or account changed. Reopen the note.');
    }
  };
  dialog.addEventListener('close', () => {
    const context = campaignNoteContext; campaignNoteContext = null;
    if (context && campaignNoteScopeIsCurrent(context.scope)) [...document.querySelectorAll('.campaign-note')].find(button => button.dataset.campaign === context.name && button.dataset.month === context.month)?.focus();
  });
  window.addEventListener('resize', positionCampaignNoteDialog);
  return dialog;
}
function openCampaignNote(button) {
  hideComparisonTooltip();
  const name = button.dataset.campaign, month = button.dataset.month || '', dialog = ensureCampaignNoteDialog();
  campaignNoteContext = {name, month, scope: campaignNotesStorageKey(), anchor: button};
  document.getElementById('campaignNoteTitle').textContent = comparisonText('Заметка о рекламе', 'Advertising note');
  document.getElementById('campaignNoteScope').textContent = campaignLabel(name) + (month ? ' · ' + monthLabel(month) : comparisonText(' · вся кампания', ' · whole campaign'));
  document.getElementById('campaignNoteLabel').textContent = comparisonText('Что делали и на кого таргетировали', 'What you ran and whom you targeted');
  const text = document.getElementById('campaignNoteText');
  text.value = campaignNoteText(name, month);
  text.placeholder = comparisonText('Аудитория, география, услуги, предложение, креативы…', 'Audience, location, services, offer, creatives…');
  document.getElementById('campaignNoteHint').textContent = comparisonText('Сохраняется в этом браузере', 'Saved in this browser');
  document.getElementById('campaignNoteClear').textContent = comparisonText('Очистить', 'Clear');
  document.getElementById('campaignNoteCancel').textContent = comparisonText('Отмена', 'Cancel');
  document.getElementById('campaignNoteSave').textContent = comparisonText('Сохранить', 'Save');
  text.oninput();
  dialog.showModal(); positionCampaignNoteDialog(); text.focus();
}
function comparisonRow(x, month = null, classes = '') {
  const expanded = expandedCampaigns.has(x.name), count = campaignMonthKeys(x.name).length;
  const title = month
    ? `<span class="generation-label">${htmlSafe(x.label)} · ${monthLabel(month)}</span>`
    : `<button type="button" class="campaign-expand" data-campaign="${htmlSafe(x.name)}" aria-expanded="${expanded}"><span class="campaign-expand-icon" aria-hidden="true">${expanded ? '−' : '+'}</span><b>${htmlSafe(x.label)}</b><small>${count} ${comparisonText('мес.', 'mo.')}</small></button>`;
  const spend = month ? comparisonInput(x.name, 'month', x.spend, month)
    : budgetBook.isMonthly(x.name) ? `<b>${euro.format(x.spend)}</b><small class="budget-sum-label">${comparisonText('сумма бюджетов', 'budget total')}</small>`
      : comparisonInput(x.name, 'campaign', x.spend);
  const note = x.clients ? horizonNote(x.age) : '';
  return `<tr class="${month ? 'generation-row' : 'campaign-row'} ${classes}"><td><div class="campaign-title">${title}${campaignNoteButton(x.name, month || '')}</div>${note ? `<div class="maturity">${htmlSafe(localizeText(note))}</div>` : ''}</td><td>${x.clients}</td><td>${spend}</td><td>${euro.format(x.revenue)}</td><td>${comparisonAmount(x.ltv)}</td><td>${comparisonAmount(x.cac)}</td><td>${x.repeatRate === null ? '—' : x.repeatRate.toFixed(0) + '%'}</td><td class="${paybackClass(x.paybackState)}">${htmlSafe(localizeText(paybackText(x.paybackState, x.payback)))}</td><td class="${x.profit === null ? '' : x.profit >= 0 ? 'positive' : 'negative'}">${comparisonAmount(x.profit)}</td><td class="${x.roi === null ? '' : x.roi >= 0 ? 'positive' : 'negative'}">${x.roi === null ? '—' : x.roi.toFixed(0) + '%'}</td></tr>`;
}
function comparisonDetails(name) {
  if (!expandedCampaigns.has(name)) return '';
  return campaignMonthKeys(name).map(month => comparisonRow(statsFor(name, month), month)).join('');
}
function renderComparison() {
  const stats = activeCampaigns().map(name => statsFor(name));
  const table = document.getElementById('campaignComparison');
  hideComparisonTooltip();
  if (!stats.length) {
    document.getElementById('horizonNote').innerHTML = '';
    table.innerHTML = `<tbody><tr><td>${localizeText('Выберите маркетинговые категории, чтобы построить сравнение.')}</td></tr></tbody>`;
    return;
  }
  const mature = stats.filter(x => x.age > 5 && x.clients), pool = mature.length ? mature : stats.filter(x => x.clients);
  const top = (items, key, reverse = false) => items.filter(x => x[key] !== null).sort((a, b) => reverse ? a[key] - b[key] : b[key] - a[key])[0];
  const bestROI = top(pool.filter(x => x.spend > 0), 'roi');
  document.getElementById('horizonNote').innerHTML = `<div class="callout">${comparisonText('Месяцы под кампанией — поколения по первому полностью оплаченному визиту. Сравнивайте их на одинаковом возрасте; текущий месяц неполный. При расчёте возвращаемости учитываются повторные визиты в том же месяце.', 'Months under a campaign are generations by first fully paid visit. Compare them at the same age; the current month is incomplete. Repeat rate includes same-month returns.')}</div>`;
  let h = comparisonHeader() + '<tbody>';
  for (const x of stats) h += comparisonRow(x, null, bestROI === x ? 'best' : '') + comparisonDetails(x.name);
  const selected = new Set(activeCampaigns());
  const clients = cohortClients.filter(c => c.categories.some(name => selected.has(name)));
  const total = statsForClients(clients, 'All Campaigns', stats.reduce((sum, x) => sum + x.spend, 0), localizeText('All Campaigns'));
  h += `<tr class="total"><td><b>${localizeText('All Campaigns')}</b></td><td>${total.clients}</td><td><b>${euro.format(total.spend)}</b></td><td>${euro.format(total.revenue)}</td><td>${comparisonAmount(total.ltv)}</td><td>${comparisonAmount(total.cac)}</td><td>${total.repeatRate === null ? '—' : total.repeatRate.toFixed(0) + '%'}</td><td>${localizeText(paybackText(total.paybackState, total.payback))}</td><td class="${total.profit >= 0 ? 'positive' : 'negative'}">${comparisonAmount(total.profit)}</td><td class="${total.roi === null ? '' : total.roi >= 0 ? 'positive' : 'negative'}">${total.roi === null ? '—' : total.roi.toFixed(0) + '%'}</td></tr>`;
  table.innerHTML = h + '</tbody>';
  table.querySelectorAll('.campaign-note').forEach(button => button.onclick = () => openCampaignNote(button));
  table.querySelectorAll('.campaign-expand').forEach(button => button.onclick = () => {
    const name = button.dataset.campaign;
    if (expandedCampaigns.has(name)) expandedCampaigns.delete(name); else expandedCampaigns.add(name);
    renderComparison(); translatePage();
    [...table.querySelectorAll('.campaign-expand')].find(b => b.dataset.campaign === name)?.focus();
  });
  table.querySelectorAll('.row-budget').forEach(input => {
    input.oninput = () => input.setCustomValidity('');
    input.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); input.blur(); } };
    input.onchange = () => {
      if (!input.checkValidity()) { input.reportValidity(); return; }
      const name = input.dataset.campaign, value = input.value === '' ? null : Number(input.value);
      if (value !== null && (!Number.isFinite(value) || value < 0)) return;
      if (input.dataset.kind === 'month') budgetBook.setMonth(name, input.dataset.month, value);
      else { campaignBudgets[name] = value ?? 0; saveBudgets(); }
      saveMonthlyBudgets(); syncBudgetInput(); renderCohort();
    };
  });
  setupComparisonTooltips();
}

let comparisonTooltipAnchor = null;
let comparisonTooltipTimer = null;
function hideComparisonTooltip() {
  clearTimeout(comparisonTooltipTimer);
  const tip = document.getElementById('comparisonMetricTooltip');
  if (tip) tip.hidden = true;
  comparisonTooltipAnchor?.removeAttribute('aria-describedby');
  comparisonTooltipAnchor = null;
}
function showComparisonTooltip(button) {
  const tip = document.getElementById('comparisonMetricTooltip'), metric = comparisonMetrics[Number(button.dataset.help)];
  if (!tip || !metric) return;
  hideComparisonTooltip(); comparisonTooltipAnchor = button;
  tip.textContent = comparisonText(metric[2], metric[3]); tip.hidden = false;
  button.setAttribute('aria-describedby', tip.id);
  const rect = button.getBoundingClientRect(), margin = 12;
  tip.style.left = Math.max(margin, Math.min(rect.left, window.innerWidth - tip.offsetWidth - margin)) + 'px';
  let top = rect.bottom + 8;
  if (top + tip.offsetHeight > window.innerHeight - margin) top = rect.top - tip.offsetHeight - 8;
  tip.style.top = Math.max(margin, top) + 'px';
}
function setupComparisonTooltips() {
  const table = document.getElementById('campaignComparison');
  if (!document.getElementById('comparisonMetricTooltip')) {
    const tip = document.createElement('div'); tip.id = 'comparisonMetricTooltip'; tip.className = 'metric-tooltip'; tip.role = 'tooltip'; tip.hidden = true; document.body.append(tip);
    tip.onmouseenter = () => clearTimeout(comparisonTooltipTimer);
    tip.onmouseleave = () => { if (document.activeElement !== comparisonTooltipAnchor) hideComparisonTooltip(); };
    document.addEventListener('keydown', e => { if (e.key === 'Escape') hideComparisonTooltip(); });
    document.addEventListener('pointerdown', e => { if (!e.target.closest('.metric-info,.metric-tooltip')) hideComparisonTooltip(); });
    const reposition = () => {
      const anchor = comparisonTooltipAnchor;
      if (!anchor) return;
      const rect = anchor.getBoundingClientRect();
      if (rect.bottom < 0 || rect.top > window.innerHeight || rect.right < 0 || rect.left > window.innerWidth) hideComparisonTooltip();
      else showComparisonTooltip(anchor);
    };
    window.addEventListener('resize', reposition);
    document.addEventListener('scroll', reposition, true);
  }
  document.querySelectorAll('.metric-info').forEach(button => {
    button.onmouseenter = () => showComparisonTooltip(button);
    button.onmouseleave = () => { if (document.activeElement !== button) comparisonTooltipTimer = setTimeout(hideComparisonTooltip, 200); };
    button.onfocus = () => showComparisonTooltip(button);
    button.onblur = hideComparisonTooltip;
    button.onclick = () => showComparisonTooltip(button);
  });
}
