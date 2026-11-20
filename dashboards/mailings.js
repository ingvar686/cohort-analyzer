/* Campaign audiences are saved by the local server, never in browser storage. */
let mailingCache=new Map(),mailingSelection=null,mailingSending=null,mailingRequest=0;
const mailText=(ru,en)=>language==='ru'?ru:en;
const mailingMoney=(value,currency=DB.location?.currency||'EUR')=>new Intl.NumberFormat(language==='ru'?'ru-RU':'en-GB',{style:'currency',currency,maximumFractionDigits:2}).format(value);
const mailingDate=value=>value?new Intl.DateTimeFormat(language==='ru'?'ru-RU':'en-GB',{dateStyle:'short',timeStyle:'short'}).format(new Date(value)):'—';
function mailingClient(id){return [...(DB.directory||[]),...(DB.clients||[])].find(c=>Number(c.id)===Number(id))||{name:'#'+id};}
function mailingContact(id){return (DB.clients||[]).find(c=>Number(c.id)===Number(id))?.phone||mailingClient(id).phone||'';}
async function mailingApi(action,payload){
 const response=await fetch('/api/upsell/campaigns/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
 const data=await response.json();if(!response.ok||!data.ok)throw Error(data.error||response.status);return data.item;
}
function rememberMailing(item){const items=mailingCache.get(item.location_id)||[];mailingCache.set(item.location_id,[item,...items.filter(c=>c.id!==item.id)]);}
function mailingCriteriaDetails(campaign){
 const criteria=campaign.criteria;
 if(!criteria)return `<div class="mailing-criteria"><h4>${mailText('Фильтры отбора','Selection filters')}</h4><p>${mailText('Эта рассылка создана до сохранения фильтров. Укажите исходные условия вручную; получатели и результаты не изменятся.','This campaign predates saved filters. Enter its original selection conditions manually; recipients and results stay the same.')}</p><button class="theme" type="button" data-mailing-criteria="${campaign.id}">${mailText('Указать фильтры','Add selection filters')}</button></div>`;
 const source=upsellCategoryDisplayName(criteria.source_category.title),target=criteria.target.kind==='category'?upsellCategoryDisplayName(criteria.target.title):criteria.target.title;
 const parent=criteria.target_category_maximum_visits_exclusive;
 return `<div class="mailing-criteria"><h4>${campaign.criteria_origin==='manual'?mailText('Фильтры, указанные вручную','Manually recorded filters'):mailText('Фильтры при создании рассылки','Filters when the campaign was created')}</h4><p><b>${mailText('Лояльность:','Loyalty:')}</b> ${htmlSafe(source)} — ${mailText('не менее','at least')} ${criteria.source_minimum_visits} ${mailText('завершённых визитов по выбранным услугам','completed visits for the selected services')}</p><p><b>${mailText('Допродажа:','Cross-sell:')}</b> ${htmlSafe(target)} — ${htmlSafe(upsellVisitLimit(criteria.target_maximum_visits_exclusive))}</p>${parent===null||parent===undefined?'':`<p>${mailText('Дополнительно по всей категории','Also across the entire category')} ${htmlSafe(upsellCategoryDisplayName(criteria.target.category_title))} — ${htmlSafe(upsellVisitLimit(parent))}</p>`}<details><summary>${mailText('Выбранные услуги лояльности','Selected loyalty services')} · ${criteria.source_services.length}</summary><ul>${criteria.source_services.map(s=>`<li>${htmlSafe(s.title)}</li>`).join('')}</ul></details><small>${mailText('История для отбора по','Selection history through')} ${htmlSafe(criteria.as_of||'—')}. ${campaign.criteria_origin==='manual'?mailText('Описание добавлено вручную: ','Description recorded manually: ')+mailingDate(campaign.criteria_recorded_at)+'. ':''}${mailText('Один визит с несколькими выбранными услугами считается один раз.','Each appointment with multiple selected services counts once.')}</small></div>`;
}
async function renderMailings(force=false){
 const branch=Number(DB.location?.id),sequence=++mailingRequest,root=document.getElementById('mailingList');
 if(!mailingCache.has(branch)||force){
  root.textContent=mailText('Загружаем рассылки…','Loading campaigns…');
  try{const response=await fetch('/api/upsell/campaigns?location_id='+branch,{cache:'no-store'}),data=await response.json();if(!response.ok||!data.ok)throw Error(data.error||response.status);mailingCache.set(branch,data.items.reverse());}
  catch(e){if(sequence===mailingRequest)root.textContent=mailText('Не удалось загрузить рассылки: ','Could not load campaigns: ')+e.message;return;}
 }
 if(sequence!==mailingRequest||branch!==Number(DB.location?.id))return;
 const campaigns=mailingCache.get(branch)||[];
 document.getElementById('mailingHeading').textContent=mailText('Результаты рассылок','Mailing results');
 document.getElementById('mailingHelp').textContent=mailText('Создайте рассылку из категории или услуги выше. Сохраните группу, отправьте предложение из Altegio и отметьте фактическую отправку. Затем обновляйте результат здесь.','Create a campaign from a category or service above. Save its audience, send your offer from Altegio, then record the actual sending and refresh results here.');
 document.getElementById('mailingReload').textContent=mailText('Обновить результаты','Refresh results');
 document.getElementById('mailingAttribution').textContent=mailText('Считаем покупки после предложения, а не доказанный эффект рассылки. Учитываем только предложенные услуги и записи, созданные после отправки, с визитом в выбранный срок. Один клиент считается один раз; выручка включает все его подходящие оплаченные визиты.','These are purchases after the offer, not proven causal impact. Only offered services in appointments created after sending and scheduled within the chosen window count. Clients count once; revenue includes all their qualifying paid visits.');
 root.innerHTML=campaigns.length?campaigns.map(c=>{
  const r=c.result,ids=c.recipient_ids||c.client_ids;
  const status=c.status==='draft'?mailText('Готовится','Draft'):r?.complete?mailText('Срок завершён','Window ended'):mailText('Наблюдаем','Observing');
  const headers=mailText(['Получателей','Записались','Пришли и оплатили','Конверсия в покупку','Выручка предложения','Расходы'],['Recipients','Booked','Attended and paid','Purchase conversion','Offer revenue','Cost']);
  const values=[ids.length,r?.booked??'—',r?.buyers??'—',r?r.conversion.toFixed(1)+'%':'—',r?mailingMoney(r.revenue,c.currency):'—',mailingMoney(c.cost,c.currency)];
  return `<details class="mailing-card" data-mailing="${c.id}"><summary><span><b>${htmlSafe(c.name)}</b><small class="mailing-criteria-summary">${htmlSafe(upsellCriteriaSummary(c.criteria))}</small><small>${htmlSafe(c.services.map(s=>s.title).join(', '))}</small></span><span class="pill">${status}</span></summary><div class="mailing-body">${mailingCriteriaDetails(c)}<p class="caption">${c.sent_at?mailText('Отправлено: ','Sent: ')+mailingDate(c.sent_at)+' · '+mailText('Оцениваем до: ','Window ends: ')+mailingDate(r?.ends_at):mailText('Список сохранён. Отправка ещё не отмечена.','Audience saved. Sending has not been recorded.')} · ${c.window_days} ${mailText('дней','days')}</p><div class="mailing-metrics">${headers.map((h,i)=>`<button type="button" class="kpi" data-mailing-drill="${c.id}" data-filter="${i===1?'booked':i===2||i===3||i===4?'paid':'all'}"><label>${h}</label><strong>${values[i]}</strong></button>`).join('')}</div><div class="mailing-actions"><button class="theme" type="button" data-mailing-tag="${c.id}">${mailText('Добавить получателей в категорию Altegio','Add recipients to an Altegio category')}</button><button class="theme" type="button" data-mailing-export="${c.id}">${mailText('Скачать список CSV','Download audience CSV')}</button>${c.status==='draft'?`<button class="sync" type="button" data-mailing-sent="${c.id}">${mailText('Отметить фактическую отправку','Record actual sending')}</button>`:`<button class="sync" type="button" data-mailing-refresh="${c.id}">${mailText('Обновить результат из Altegio','Refresh results from Altegio')}</button>`}</div><p class="caption mailing-status" role="status"></p>${r?`<p class="caption">${mailText('Проверено: ','Checked: ')}${mailingDate(r.observed_at)}. ${r.cost_per_buyer===null?'':mailText('Расходы на одного покупателя: ','Cost per buyer: ')+mailingMoney(r.cost_per_buyer,c.currency)+'.'} ${mailText('Не засчитано: записи до отправки — ','Excluded: pre-existing bookings — ')}${r.excluded.preexisting}; ${mailText('неизвестны даты — ','unknown dates — ')}${r.excluded.unknown_dates}; ${mailText('отменены — ','cancelled — ')}${r.excluded.cancelled}.${r.excluded.unknown_revenue?' '+mailText('У части оплаченных услуг нет цены: показана только известная выручка.','Some paid services have no price: only known revenue is shown.'):''}</p>`:''}<div class="mailing-drill" hidden></div></div></details>`;
 }).join(''):`<div class="empty">${mailText('Пока нет сохранённых рассылок. В нужной категории или услуге нажмите «Создать рассылку».','No saved campaigns yet. Select “Create campaign” within a category or service.')}</div>`;
 root.querySelectorAll('[data-mailing-tag]').forEach(b=>{b.onclick=()=>{const c=campaigns.find(c=>c.id===b.dataset.mailingTag);openUpsellCategoryForm('',{title:c.name,criteria:c.criteria||null,service_ids:c.services.map(s=>s.id),rows:(c.recipient_ids||c.client_ids).map(id=>({client:{...mailingClient(id),id}}))})}});
 root.querySelectorAll('[data-mailing-criteria]').forEach(b=>b.onclick=()=>openLegacyCriteriaForm(b.dataset.mailingCriteria));
 root.querySelectorAll('[data-mailing-sent]').forEach(b=>b.onclick=()=>openMailingSend(b.dataset.mailingSent));
 root.querySelectorAll('[data-mailing-refresh]').forEach(b=>b.onclick=async()=>{
  const item=campaigns.find(c=>c.id===b.dataset.mailingRefresh),status=b.closest('.mailing-body').querySelector('.mailing-status');b.disabled=true;status.textContent=mailText('Читаем записи и оплаты Altegio…','Reading Altegio bookings and payments…');
  try{rememberMailing(await mailingApi('refresh',{location_id:branch,campaign_id:item.id}));await renderMailings();const card=document.querySelector(`[data-mailing="${item.id}"]`);if(card)card.open=true;}
  catch(e){status.textContent=e.message;b.disabled=false;}
 });
 root.querySelectorAll('[data-mailing-drill]').forEach(b=>b.onclick=()=>renderMailingClients(campaigns.find(c=>c.id===b.dataset.mailingDrill),b.dataset.filter));
 root.querySelectorAll('[data-mailing-export]').forEach(b=>b.onclick=()=>exportMailing(campaigns.find(c=>c.id===b.dataset.mailingExport)));
}
function renderMailingClients(c,filter){
 const target=document.querySelector(`[data-mailing="${c.id}"] .mailing-drill`),rows=c.result?.clients||(c.client_ids.map(client_id=>({client_id,records:[]})));
 const filtered=rows.filter(r=>filter==='all'||r[filter]);target.hidden=false;
 target.innerHTML=`<h4>${mailText('Клиенты','Clients')} · ${filtered.length}</h4><div class="table-wrap"><table><thead><tr>${mailText(['Клиент','Телефон','Результат','Выручка предложения','Визиты и оплаты'],['Client','Phone','Outcome','Offer revenue','Visits and payments']).map(s=>`<th>${s}</th>`).join('')}</tr></thead><tbody>${filtered.map(r=>`<tr><td>${htmlSafe(mailingClient(r.client_id).name)}</td><td>${htmlSafe(mailingContact(r.client_id)||'—')}</td><td>${r.paid?mailText('Пришёл и оплатил','Attended and paid'):r.booked?mailText('Записался','Booked'):c.status==='draft'?mailText('В сохранённой группе','Saved audience'):mailText('Покупки пока нет','No purchase yet')}</td><td>${c.result?mailingMoney(r.revenue,c.currency):'—'}</td><td>${r.records.map(v=>`<div class="mailing-visit">#${htmlSafe(String(v.id))} · ${mailingDate(v.visit_at)}<br>${htmlSafe(v.services.join(', '))}<br>${v.paid?mailText('Полностью оплачено','Fully paid'):mailText('Оплаченный визит ещё не состоялся','No completed paid visit yet')} · ${mailingMoney(v.revenue,c.currency)}<br><small>${mailText('Запись создана: ','Booking created: ')}${mailingDate(v.created_at)}</small></div>`).join('')||'—'}</td></tr>`).join('')}</tbody></table></div>`;
}
function openLegacyCriteriaForm(id){
 const campaign=(mailingCache.get(Number(DB.location.id))||[]).find(c=>c.id===id);
 if(!campaign||campaign.criteria)return;
 const catalog=upsellCatalog(),offered=new Set(campaign.services.map(s=>Number(s.id)));
 const categories=new Set(catalog.services.filter(s=>offered.has(Number(s.id))).map(s=>String(s.category_id)));
 let dialog=document.getElementById('mailingCriteriaDialog');
 if(!dialog){dialog=document.createElement('dialog');dialog.id='mailingCriteriaDialog';dialog.className='mailing-dialog';document.body.append(dialog);}
 const categoryOptions=catalog.categories.map(c=>`<option value="${Number(c.id)}">${htmlSafe(upsellCategoryDisplayName(c.title))}</option>`).join('');
 const targetOptions=catalog.categories.filter(c=>categories.has(String(c.id))).map(c=>`<option value="category:${Number(c.id)}">${mailText('Категория: ','Category: ')}${htmlSafe(upsellCategoryDisplayName(c.title))}</option>`).join('')+(campaign.services.length===1?`<option value="service:${Number(campaign.services[0].id)}">${mailText('Услуга: ','Service: ')}${htmlSafe(campaign.services[0].title)}</option>`:'');
 dialog.innerHTML=`<form id="mailingCriteriaForm"><h3>${mailText('Указать исходные фильтры','Record original selection filters')}</h3><p class="caption">${htmlSafe(campaign.name)}</p><p class="callout">${mailText('Укажите условия, которые использовали при отборе этой рассылки. Сохранится только описание: список клиентов и результаты не изменятся.','Enter the conditions originally used for this campaign. Only the description will be saved; recipients and results stay the same.')}</p><div class="field"><label for="mailingCriteriaSource">${mailText('Категория лояльности','Loyalty category')}</label><select id="mailingCriteriaSource" required><option value="">${mailText('Выберите исходную категорию','Choose the original category')}</option>${categoryOptions}</select></div><div class="field"><label for="mailingCriteriaMinimum">${mailText('Лояльность: не менее визитов','Loyalty: minimum visits')}</label><input id="mailingCriteriaMinimum" type="number" min="1" max="1000000" step="1" required></div><details open><summary>${mailText('Услуги для определения лояльности','Services used to measure loyalty')}</summary><div id="mailingCriteriaServices" class="upsell-services"></div></details><div class="field"><label for="mailingCriteriaTarget">${mailText('Куда предлагали допродажу','Cross-sell target')}</label><select id="mailingCriteriaTarget" required>${targetOptions}</select></div><div class="field"><label for="mailingCriteriaMaximum">${mailText('По предложению: меньше визитов','Target: fewer visits than')}</label><input id="mailingCriteriaMaximum" type="number" min="1" max="1000000" step="1" required><small class="caption">${mailText('Меньше 1 визита означает 0 визитов. Меньше 2 — 0 или 1 визит.','Fewer than 1 means 0 visits. Fewer than 2 means 0 or 1 visit.')}</small></div><label id="mailingCriteriaParentField" class="upsell-check" hidden><input id="mailingCriteriaParent" type="checkbox"><span>${mailText('Этот порог применялся и ко всей категории услуги','This limit also applied to the entire service category')}</span></label><p id="mailingCriteriaStatus" role="status"></p><div class="upsell-dialog-actions"><button class="theme" id="mailingCriteriaClose" type="button">${mailText('Закрыть','Close')}</button><button class="sync" id="mailingCriteriaSave" type="submit">${mailText('Сохранить описание фильтров','Save filter description')}</button></div></form>`;
 const source=dialog.querySelector('#mailingCriteriaSource'),target=dialog.querySelector('#mailingCriteriaTarget');
 source.onchange=()=>{dialog.querySelector('#mailingCriteriaServices').innerHTML=catalog.services.filter(s=>String(s.category_id)===source.value).map(s=>`<label class="upsell-check"><input type="checkbox" value="${Number(s.id)}" checked><span>${htmlSafe(s.title)}</span></label>`).join('');};
 target.onchange=()=>{dialog.querySelector('#mailingCriteriaParentField').hidden=!target.value.startsWith('service:');};
 if(campaign.services.length===1&&campaign.offer===campaign.services[0].title)target.value='service:'+campaign.services[0].id;
 target.onchange();
 dialog.querySelector('#mailingCriteriaClose').onclick=()=>dialog.close();
 dialog.querySelector('#mailingCriteriaForm').onsubmit=async event=>{
  event.preventDefault();const status=dialog.querySelector('#mailingCriteriaStatus'),button=dialog.querySelector('#mailingCriteriaSave');
  const [kind,targetId]=target.value.split(':'),selected=[...dialog.querySelectorAll('#mailingCriteriaServices input:checked')].map(el=>Number(el.value));
  if(!selected.length){status.textContent=mailText('Выберите хотя бы одну исходную услугу.','Choose at least one original service.');return;}
  const criteria=buildUpsellCriteria(catalog,{category:source.value,minimum:Number(dialog.querySelector('#mailingCriteriaMinimum').value),maximum:Number(dialog.querySelector('#mailingCriteriaMaximum').value),services:catalog.services.filter(s=>selected.includes(Number(s.id))).map(s=>s.title),mode:kind==='category'||dialog.querySelector('#mailingCriteriaParent').checked?'category':'service',asOf:campaign.snapshot_as_of||DB.as_of},kind,targetId);
  button.disabled=true;
  try{const updated=await mailingApi('criteria',{location_id:campaign.location_id,campaign_id:campaign.id,criteria});rememberMailing(updated);dialog.close();await renderMailings();const card=document.querySelector(`[data-mailing="${campaign.id}"]`);if(card){card.open=true;card.scrollIntoView({behavior:'smooth',block:'start'});}}
  catch(error){status.textContent=error.message;}finally{button.disabled=false;}
 };
 dialog.showModal();
}
function openMailingForm(key,override=null){
 const group=override||upsellGroups.get(key);if(!group)return;
 const serviceIds=group.service_ids||[],services=upsellCatalog().services.filter(s=>serviceIds.includes(Number(s.id)));
 mailingSelection={location_id:Number(DB.location.id),client_ids:[...new Set(group.rows.map(r=>Number(r.client.id)).filter(Boolean))],services,offer:group.title,criteria:group.criteria?JSON.parse(JSON.stringify(group.criteria)):null};
 updateMailingHelpLabels();
 document.getElementById('mailingFormTitle').textContent=mailText('Новая рассылка','New mailing campaign');
 document.getElementById('mailingAudience').textContent=`${DB.location.name} · ${mailingSelection.client_ids.length} ${mailText('клиентов в сохранённой группе','clients in the saved audience')}`;
 document.getElementById('mailingName').value=group.criteria?upsellSuggestedName(group.criteria,160):group.title+' · '+new Intl.DateTimeFormat('sv-SE').format(new Date());
 document.getElementById('mailingDays').value=30;document.getElementById('mailingCost').value=0;
 document.getElementById('mailingServices').innerHTML=services.map(s=>`<label class="upsell-check"><input type="checkbox" value="${Number(s.id)}" checked><span>${htmlSafe(s.title)}</span></label>`).join('');
 document.getElementById('mailingFormStatus').textContent='';document.getElementById('mailingSave').disabled=false;document.getElementById('mailingCreate').showModal();
}
document.getElementById('mailingForm').onsubmit=async e=>{
 e.preventDefault();const selection=mailingSelection;if(!selection)return;
 const button=document.getElementById('mailingSave'),status=document.getElementById('mailingFormStatus');button.disabled=true;
 try{const item=await mailingApi('create',{...selection,services:undefined,name:document.getElementById('mailingName').value,window_days:Number(document.getElementById('mailingDays').value),cost:Number(document.getElementById('mailingCost').value),service_ids:[...document.querySelectorAll('#mailingServices input:checked')].map(s=>Number(s.value))});rememberMailing(item);document.getElementById('mailingCreate').close();await renderMailings();if(Number(DB.location.id)===item.location_id){const card=document.querySelector(`[data-mailing="${item.id}"]`);card.open=true;card.scrollIntoView({behavior:'smooth',block:'start'});}}
 catch(err){status.textContent=err.message;}finally{button.disabled=false;}
};
function openMailingSend(id){
 const item=(mailingCache.get(Number(DB.location.id))||[]).find(c=>c.id===id);if(!item)return;mailingSending=item;
 const now=new Date(),local=new Date(now.getTime()-now.getTimezoneOffset()*60000).toISOString().slice(0,19);
 document.getElementById('mailingSentAt').value=local;
 document.getElementById('mailingSentTitle').textContent=item.name;
 document.getElementById('mailingRecipients').innerHTML=item.client_ids.map(cid=>`<label class="upsell-check"><input type="checkbox" value="${cid}" ${mailingContact(cid)?'checked':''}><span>${htmlSafe(mailingClient(cid).name)} · ${htmlSafe(mailingContact(cid)||mailText('телефон не загружен','phone unavailable'))}</span></label>`).join('');
 document.getElementById('mailingSentStatus').textContent='';document.getElementById('mailingSentSubmit').disabled=false;document.getElementById('mailingSent').showModal();
}
document.getElementById('mailingSentForm').onsubmit=async e=>{
 e.preventDefault();const item=mailingSending;if(!item)return;const button=document.getElementById('mailingSentSubmit'),status=document.getElementById('mailingSentStatus');button.disabled=true;status.textContent=mailText('Сохраняем получателей и проверяем записи Altegio…','Saving recipients and checking Altegio bookings…');
 try{const updated=await mailingApi('sent',{location_id:item.location_id,campaign_id:item.id,sent_at:new Date(document.getElementById('mailingSentAt').value).toISOString(),recipient_ids:[...document.querySelectorAll('#mailingRecipients input:checked')].map(i=>Number(i.value))});rememberMailing(updated);document.getElementById('mailingSent').close();await renderMailings();const card=document.querySelector(`[data-mailing="${item.id}"]`);if(card)card.open=true;}
 catch(err){status.textContent=err.message;}finally{button.disabled=false;}
};
function exportMailing(c){
 const rows=[mailText(['ID клиента','Имя','Телефон','Рассылка','Предложенные услуги'],['Client ID','Name','Phone','Campaign','Offered services']),...(c.recipient_ids||c.client_ids).map(id=>[id,mailingClient(id).name,mailingContact(id),c.name,c.services.map(s=>s.title).join(', ')])];
 const safe=v=>'"'+String(/^[=+@\-\t\r]/.test(String(v))?"'"+v:v).replaceAll('"','""')+'"';
 const url=URL.createObjectURL(new Blob(['\uFEFF'+rows.map(row=>row.map(safe).join(';')).join('\r\n')],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download='mailing-'+c.id+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
async function refreshMailingResults(){
 const branch=Number(DB.location?.id),button=document.getElementById('mailingReload');
 if(!branch||button.disabled)return;
 button.disabled=true;button.setAttribute('aria-busy','true');
 let status=document.getElementById('mailingRefreshStatus');
 if(!status){status=document.createElement('p');status.id='mailingRefreshStatus';status.className='caption';status.setAttribute('role','status');document.getElementById('mailingList').before(status);}
 status.textContent=mailText('Проверяем свежие записи и оплаты…','Checking current bookings and payments…');
 try{
  const response=await fetch('/api/upsell/campaigns?location_id='+branch,{cache:'no-store'}),data=await response.json();
  if(!response.ok||!data.ok)throw Error(data.error||response.status);
  mailingCache.set(branch,data.items.reverse());
  const sent=data.items.filter(c=>c.status==='sent');let failed=0;
  for(const item of sent){
   if(Number(DB.location?.id)!==branch)return;
   try{rememberMailing(await mailingApi('refresh',{location_id:branch,campaign_id:item.id}));}catch(e){failed++;}
  }
  if(Number(DB.location?.id)!==branch)return;
  await renderMailings();
  status.textContent=failed?mailText(`Не удалось обновить ${failed} рассылок. Для них сохранён прежний результат. Повторите обновление.`,`Could not refresh ${failed} campaigns. Their previous results were kept. Try again.`):mailText(`Результаты обновлены: ${sent.length} рассылок.`,`Results refreshed: ${sent.length} campaigns.`);
 }catch(e){status.textContent=mailText('Не удалось обновить результаты: ','Could not refresh results: ')+e.message;}
 finally{button.disabled=false;button.removeAttribute('aria-busy');}
}
document.getElementById('mailingReload').onclick=refreshMailingResults;
document.querySelectorAll('[data-mailing-close]').forEach(b=>b.onclick=()=>b.closest('dialog').close());

let mailingHelpAnchor=null;
function updateMailingHelpLabels(){
 document.querySelectorAll('[data-mailing-help]').forEach(button=>button.setAttribute('aria-label',mailText('Подсказка: ','Help: ')+(button.dataset.mailingHelp==='days'?mailText('Срок оценки','Evaluation window'):mailText('Расходы на рассылку','Mailing cost'))));
}
function hideMailingHelp(){
 document.getElementById('mailingHelpTooltip').hidden=true;
 if(mailingHelpAnchor){mailingHelpAnchor.setAttribute('aria-expanded','false');mailingHelpAnchor.removeAttribute('aria-describedby');}
 mailingHelpAnchor=null;
}
function showMailingHelp(button){
 const tip=document.getElementById('mailingHelpTooltip');hideMailingHelp();mailingHelpAnchor=button;
 tip.textContent=button.dataset.mailingHelp==='days'
  ?mailText('Сколько дней после отправки рассылки считать результат. Например, за 30 дней смотрим, кто записался, пришёл и оплатил предложенные услуги. Это срок наблюдения, а не срок действия скидки.','How many days after sending to track results. For example, over 30 days we count who booked, attended and paid for the offered services. This is an observation window, not the expiry date of a discount.')
  :mailText('Укажите расходы на отправку сообщений, например оплату SMS или сервиса рассылок. Сумма — в валюте выбранного филиала. Если отправка бесплатная, оставьте 0.','Enter the cost of sending messages, such as SMS charges or mailing service fees, in the selected branch’s currency. If sending is free, leave 0.');
 tip.hidden=false;button.setAttribute('aria-expanded','true');button.setAttribute('aria-describedby',tip.id);
 const rect=button.getBoundingClientRect(),bounds=button.closest('dialog').getBoundingClientRect(),margin=12;
 tip.style.maxWidth=Math.min(350,bounds.width-margin*2)+'px';
 tip.style.left=Math.max(margin,bounds.left+margin,Math.min(rect.left,Math.min(window.innerWidth,bounds.right)-tip.offsetWidth-margin))+'px';
 const below=rect.bottom+8,top=below+tip.offsetHeight<Math.min(window.innerHeight,bounds.bottom)-margin?below:rect.top-tip.offsetHeight-8;
 tip.style.top=Math.max(margin,top)+'px';
}
document.querySelectorAll('[data-mailing-help]').forEach(button=>{
 button.onpointerenter=()=>showMailingHelp(button);
 button.onpointerleave=()=>{if(document.activeElement!==button)hideMailingHelp()};
 button.onfocus=()=>showMailingHelp(button);button.onblur=hideMailingHelp;
 button.onclick=()=>showMailingHelp(button);
});
document.getElementById('mailingCreate').addEventListener('close',hideMailingHelp);
document.getElementById('mailingCreate').addEventListener('keydown',event=>{if(event.key==='Escape'&&mailingHelpAnchor){event.preventDefault();event.stopPropagation();hideMailingHelp()}});
document.addEventListener('pointerdown',event=>{if(!event.target.closest('[data-mailing-help],#mailingHelpTooltip'))hideMailingHelp()});
document.addEventListener('scroll',hideMailingHelp,true);
window.addEventListener('resize',hideMailingHelp);
