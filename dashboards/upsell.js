/* Counts appointments, rather than individual service lines. */
function buildUpsellAudience(clients, catalog, options) {
  const normalize = value => String(value || '').trim().toLocaleLowerCase();
  const byTitle = new Map();
  const services = catalog.services || [];
  services.forEach(s => { const key = normalize(s.title); if (!byTitle.has(key)) byTitle.set(key, []); byTitle.get(key).push(s); });
  const selected = new Set(options.services.map(normalize));
  const offers = options.mode === 'service'
    ? services.filter(s => s.active !== false && String(s.category_id) !== options.category).map(s => ({key:String(s.id), title:s.title, category:String(s.category_id), names:new Set([normalize(s.title)])}))
    : (catalog.categories || []).filter(c => String(c.id) !== options.category).map(c => ({key:String(c.id),title:c.title,category:String(c.id),names:new Set(services.filter(s=>String(s.category_id)===String(c.id)).map(s=>normalize(s.title)))})).filter(c=>services.some(s=>String(s.category_id)===c.key&&s.active!==false));
  const targets = offers.filter(o => !options.target || o.key === options.target);
  let unresolved = 0;
  const audience = [];
  let loyal = 0;
  clients.forEach(client => {
    const visits = new Map();
    (client.visits || []).forEach((v,index) => {
      if (v.attendance != null && !['arrived','1',1].includes(v.attendance)) return;
      if (options.asOf && v.date > options.asOf) return;
      const key = v.appointment_id ? String(v.appointment_id) : 'row:'+index;
      if (!visits.has(key)) visits.set(key,{date:v.date,names:new Set()});
      (v.services?.length?v.services:v.service?[v.service]:[]).forEach(raw=>{
        const title=normalize(typeof raw==='string'?raw:raw.title||raw.name);
        const matches=byTitle.get(title)||[];
        if (!matches.length || new Set(matches.map(s=>String(s.category_id))).size>1) {unresolved++;return;}
        visits.get(key).names.add(title);
      });
    });
    const base = [...visits.values()].filter(v=>[...v.names].some(n=>selected.has(n)));
    if (!selected.size || base.length < options.minimum) return;
    loyal++;
    const opportunities = targets.map(o=>({...o,count:[...visits.values()].filter(v=>[...v.names].some(n=>o.names.has(n))).length})).filter(o=>o.count<options.maximum);
    if(opportunities.length) audience.push({client,count:base.length,last:base.map(v=>v.date).sort().at(-1)||'',opportunities});
  });
  audience.sort((a,b)=>b.count-a.count||a.client.name.localeCompare(b.client.name));
  return {audience,loyal,offers,unresolved};
}
let upsellCatalogs = {}, upsellBranch = null, upsellRows = [], upsellGroups = new Map(), upsellSelection = null;
const upText = (ru,en) => language === 'ru' ? ru : en;
function upsellCategoryDisplayName(title){
  const ru={haircuts:'Стрижки',cosmetology:'Косметология',coloring:'Окрашивания',manicure:'Маникюр',pedicure:'Педикюр',massage:'Массаж'};
  return language==='ru'?(ru[String(title).trim().toLowerCase()]||title):title;
}
function buildUpsellCriteria(catalog,options,kind,targetId){
  const source=catalog.categories.find(c=>String(c.id)===String(options.category));
  const target=(kind==='service'?catalog.services:catalog.categories).find(s=>String(s.id)===String(targetId));
  if(!source||!target)return null;
  const category=kind==='service'?catalog.categories.find(c=>String(c.id)===String(target.category_id)):target;
  return {version:1,source_category:{id:Number(source.id),title:source.title},
    source_services:catalog.services.filter(s=>String(s.category_id)===String(source.id)&&options.services.includes(s.title)).map(s=>({id:Number(s.id),title:s.title})),
    source_minimum_visits:options.minimum,
    source_all_services:catalog.services.filter(s=>String(s.category_id)===String(source.id)).every(s=>options.services.includes(s.title)),
    target:{kind,id:Number(target.id),title:target.title,category_id:Number(category?.id),category_title:category?.title||target.title},
    target_maximum_visits_exclusive:options.maximum,
    target_category_maximum_visits_exclusive:kind==='service'&&options.mode==='category'?options.maximum:null,
    as_of:options.asOf||null};
}
function upsellVisitLimit(maximum,compact=false){
  return maximum===1?upText('0 визитов','0 visits'):compact?upText(`<${maximum} визитов`,`<${maximum} visits`):upText(`менее ${maximum} визитов`,`fewer than ${maximum} visits`);
}
function upsellCriteriaSummary(criteria){
  if(!criteria)return upText('Фильтры отбора при создании не были сохранены','Selection filters were not saved when this campaign was created');
  const source=upsellCategoryDisplayName(criteria.source_category.title),target=criteria.target.kind==='category'?upsellCategoryDisplayName(criteria.target.title):criteria.target.title;
  const subset=criteria.source_all_services?'':upText(' (выбранные услуги)',' (selected services)');
  return `${source}${subset}: ${upText('не менее','at least')} ${criteria.source_minimum_visits} ${upText('визитов','visits')} → ${target}: ${upsellVisitLimit(criteria.target_maximum_visits_exclusive)}`;
}
function upsellSuggestedName(criteria,maxLength=160,date=new Intl.DateTimeFormat('sv-SE').format(new Date())){
  if(!criteria)return '';
  const trim=(text,limit)=>{text=String(text);if(text.length<=limit)return text;let part=text.slice(0,Math.max(0,limit-1));if(/[\uD800-\uDBFF]$/.test(part))part=part.slice(0,-1);return part+'…'};
  const source=upsellCategoryDisplayName(criteria.source_category.title)+(criteria.source_all_services?'':upText(' (выбор услуг)',' (selected services)'));
  const target=criteria.target.kind==='category'?upsellCategoryDisplayName(criteria.target.title):criteria.target.title;
  const prefix=upText('Лояльные: ','Loyal: '),middle=` ≥${criteria.source_minimum_visits} ${upText('визитов','visits')} → `,suffix=` · ${upsellVisitLimit(criteria.target_maximum_visits_exclusive,true)} · ${date}`;
  const available=maxLength-prefix.length-middle.length-suffix.length;
  const sourceLimit=Math.min(source.length,Math.max(6,Math.floor(available*.45))),targetLimit=Math.max(6,available-sourceLimit);
  return prefix+trim(source,Math.max(sourceLimit,available-Math.min(target.length,targetLimit)))+middle+trim(target,targetLimit)+suffix;
}
function upsellCatalog() { return DB.service_catalog || upsellCatalogs[DB.location?.id] || {categories:[],services:[]}; }
function renderUpsellServices() {
  const catalog=upsellCatalog(),category=document.getElementById('upsellCategory').value;
  document.getElementById('upsellServices').innerHTML=catalog.services.filter(s=>String(s.category_id)===category).map(s=>`<label class="upsell-check"><input type="checkbox" value="${htmlSafe(s.title)}" checked><span>${htmlSafe(s.title)}</span></label>`).join('');
  document.querySelectorAll('#upsellServices input').forEach(el=>el.onchange=updateUpsellResults);
}
function renderCross() {
  const branch=document.getElementById('upsellLocation');
  branch.innerHTML=locationSelect.innerHTML;branch.value=String(DB.location?.id||'');
  if(upsellBranch!==DB.location?.id){
    upsellBranch=DB.location?.id;
    const cats=upsellCatalog().categories;
    document.getElementById('upsellCategory').innerHTML=cats.map(c=>`<option value="${Number(c.id)}">${htmlSafe(c.title)}</option>`).join('');
    const preferred=cats.find(c=>/haircut|стриж/i.test(c.title));if(preferred)document.getElementById('upsellCategory').value=String(preferred.id);
    document.getElementById('upsellTarget').innerHTML='';renderUpsellServices();
  }
  updateUpsellResults();
  if(typeof renderMailings==='function')renderMailings();
}
function updateUpsellResults(){
  const category=document.getElementById('upsellCategory').value;
  const minimum=Math.max(1,Math.floor(Number(document.getElementById('upsellMinimum').value)||1));
  const maximum=Math.max(1,Math.floor(Number(document.getElementById('upsellMaximum').value)||1));
  const mode=document.getElementById('upsellMode').value,target=document.getElementById('upsellTarget');
  const options={category,minimum,maximum,mode,services:[...document.querySelectorAll('#upsellServices input:checked')].map(x=>x.value),asOf:DB.as_of,target:''};
  const all=buildUpsellAudience(DB.clients||[],upsellCatalog(),options),previous=target.value;
  target.innerHTML=`<option value="">${upText('Все варианты','All opportunities')}</option>`+all.offers.map(o=>`<option value="${htmlSafe(o.key)}">${htmlSafe(o.title)}</option>`).join('');
  if(all.offers.some(o=>o.key===previous))target.value=previous;
  options.target=target.value;
  const result=options.target?buildUpsellAudience(DB.clients||[],upsellCatalog(),options):all;
  upsellRows=result.audience;
  document.getElementById('upsellLoyal').textContent=result.loyal;
  document.getElementById('upsellAudience').textContent=result.audience.length;
  document.getElementById('upsellContacts').textContent=result.audience.filter(r=>r.client.phone).length;
  document.getElementById('upsellRule').textContent=upText(`Не менее ${minimum} завершённых визитов по выбранным услугам и меньше ${maximum} визитов по каждой предлагаемой категории или услуге. Один визит с несколькими услугами считается один раз.`,`At least ${minimum} completed visits for selected services and fewer than ${maximum} visits for each offered category or service. Each appointment counts once.`);
  document.getElementById('upsellCoverage').textContent=upText(`Источник: загруженная история филиала по ${DB.as_of||'—'}. Ноль означает отсутствие завершённых визитов в этой истории. Без телефона клиент остаётся в отчёте; контакт нужно дополнить перед рассылкой.${result.unresolved?' Часть услуг не сопоставлена с каталогом и не участвует в расчёте.':''}`,`Source: loaded branch history through ${DB.as_of||'—'}. Zero means no completed visits in this history. Clients without a phone remain in the report; add contact details before sending.${result.unresolved?' Some services could not be mapped to the catalog and are excluded.':''}`);
  renderUpsellGroups(result,options);
  document.getElementById('upsellEmpty').hidden=!!result.audience.length;
  document.getElementById('upsellEmpty').textContent=upText(!upsellCatalog().categories.length?'Каталог услуг филиала ещё не загружен.':!options.services.length?'Выберите хотя бы одну услугу.':'Клиенты по этим условиям не найдены. Уменьшите порог лояльности или расширьте выбор услуг.',!upsellCatalog().categories.length?'The branch service catalog has not been loaded.':!options.services.length?'Select at least one service.':'No clients match. Lower the loyalty threshold or select more services.');
  document.getElementById('upsellExport').disabled=!result.audience.length;
}
document.getElementById('upsellCategory').onchange=()=>{renderUpsellServices();document.getElementById('upsellTarget').value='';updateUpsellResults()};
['upsellMinimum','upsellMaximum'].forEach(id=>document.getElementById(id).oninput=updateUpsellResults);
['upsellMode','upsellTarget'].forEach(id=>document.getElementById(id).onchange=updateUpsellResults);
document.getElementById('upsellLocation').onchange=async e=>{e.target.disabled=true;locationSelect.value=e.target.value;const loaded=await loadRemoteData(e.target.value);if(!loaded)e.target.value=String(DB.location?.id||'');e.target.disabled=false};
function exportUpsellAudience(audience, suffix=''){
  const rows=[upText(['ID клиента','Имя','Телефон','Филиал','Лояльных визитов','Последний визит','Что предложить','Визитов по предложению'],['Client ID','Name','Phone','Location','Loyal visits','Last visit','Opportunity','Opportunity visits'])];
  audience.forEach(r=>r.opportunities.forEach(o=>rows.push([r.client.id||'',r.client.name,r.client.phone||'',DB.location?.name||'',r.count,r.last,o.title,o.count])));
  const safe=v=>'"'+String(/^[=+@\-\t\r]/.test(String(v))?"'"+v:v).replaceAll('"','""')+'"';
  const url=URL.createObjectURL(new Blob(['\uFEFF'+rows.map(row=>row.map(safe).join(';')).join('\r\n')],{type:'text/csv;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download=`upsell-${DB.location?.id}-${DB.as_of}${suffix}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
document.getElementById('upsellExport').onclick=()=>exportUpsellAudience(upsellRows);

function renderUpsellGroups(result,options){
  upsellGroups.clear();
  const clientEdition=document.body.hasAttribute('data-client-edition');
  const serviceResult=buildUpsellAudience(DB.clients||[],upsellCatalog(),{...options,mode:'service',target:''});
  const groupAction=(key,title,rows)=>{
    if(clientEdition){
      upsellGroups.set(key,{title,rows});
      return `<button class="sync" type="button" data-upsell-export="${htmlSafe(key)}" ${rows.length?'':'disabled'}>${upText('Скачать аудиторию CSV','Download audience CSV')}</button>`;
    }
    const [kind,id]=key.split(':');
    const catalog=upsellCatalog();
    const service_ids=catalog.services.filter(s=>kind==='service'?String(s.id)===id:String(s.category_id)===id).map(s=>Number(s.id));
    const criteria=buildUpsellCriteria(catalog,options,kind,id);
    upsellGroups.set(key,{title,rows,service_ids,criteria});
    return `<button class="sync" type="button" data-upsell-add="${htmlSafe(key)}" ${rows.some(r=>r.client.id)?'':'disabled'}>${upText('Добавить в категорию клиентов Altegio','Add to an Altegio client category')}</button><button class="theme mailing-new" type="button" data-mailing-new="${htmlSafe(key)}" ${rows.length&&service_ids.length?'':'disabled'}>${upText('Создать рассылку','Create campaign')}</button>`;
  };
  const table=rows=>`<div class="table-wrap"><table><thead><tr>${upText(['Клиент','Телефон','Визитов по выбранным услугам','Последний визит','Визитов по предложению'],['Client','Phone','Loyal visits','Last visit','Target visits']).map(x=>`<th>${x}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr><td>${htmlSafe(r.client.name)}</td><td>${htmlSafe(r.client.phone||'—')}</td><td>${r.count}</td><td>${htmlSafe(r.last)}</td><td>${r.targetCount}</td></tr>`).join('')}</tbody></table></div>`;
  document.getElementById('upsellGroups').innerHTML=result.offers.filter(o=>!options.target||o.key===options.target).map(cat=>{
    const rows=result.audience.filter(r=>r.opportunities.some(o=>o.key===cat.key)).map(r=>({...r,targetCount:r.opportunities.find(o=>o.key===cat.key).count}));
    const ids=new Set(rows.map(r=>r.client.id||r.client));
    const categoryButton=groupAction('category:'+cat.key,cat.title,rows);
    const services=serviceResult.offers.filter(s=>s.category===cat.key).map(service=>{
      const serviceRows=serviceResult.audience.filter(r=>ids.has(r.client.id||r.client)&&r.opportunities.some(o=>o.key===service.key)).map(r=>({...r,targetCount:r.opportunities.find(o=>o.key===service.key).count}));
      return `<details class="upsell-service"><summary>${htmlSafe(service.title)} <span class="pill">${serviceRows.length} ${upText('клиентов','clients')}</span></summary>${groupAction('service:'+service.key,service.title,serviceRows)}${table(serviceRows)}</details>`;
    }).join('');
    return `<details class="upsell-group"><summary>${htmlSafe(cat.title)} <span class="pill">${rows.length} ${upText('клиентов','clients')}</span></summary><div class="upsell-group-body">${categoryButton}<details><summary>${upText('Все клиенты категории','All category clients')} · ${rows.length}</summary>${table(rows)}</details>${services}</div></details>`;
  }).join('');
  document.querySelectorAll('[data-mailing-new]').forEach(b=>b.onclick=()=>openMailingForm(b.dataset.mailingNew));
  document.querySelectorAll('[data-upsell-add]').forEach(b=>b.onclick=()=>openUpsellCategoryForm(b.dataset.upsellAdd));
  document.querySelectorAll('[data-upsell-export]').forEach(button=>button.onclick=()=>{
    const key=button.dataset.upsellExport;
    const group=upsellGroups.get(key);
    const rows=group.rows.map(row=>({...row,opportunities:[{title:group.title,count:row.targetCount}]}));
    exportUpsellAudience(rows,'-'+key.replace(':','-'));
  });
}
async function openUpsellCategoryForm(key,override=null){
  const group=override||upsellGroups.get(key);if(!group)return;
  upsellSelection={...group,location_id:DB.location.id,client_ids:[...new Set(group.rows.map(r=>Number(r.client.id)).filter(id=>Number.isInteger(id)&&id>0))]};
  document.getElementById('upsellNewTagField').hidden=false;const dialog=document.getElementById('upsellAssign');dialog.showModal();
  document.getElementById('upsellAssignDescription').textContent=`${DB.location.name} · ${group.title} · ${upsellSelection.client_ids.length} ${upText('клиентов','clients')}`;
  const select=document.getElementById('upsellClientTag');select.innerHTML='';document.getElementById('upsellNewTag').value='';document.getElementById('upsellAssignStatus').textContent=upText('Загружаем категории…','Loading categories…');document.getElementById('upsellAssignSubmit').disabled=true;
  try{const r=await fetch('/api/client-categories?location_id='+DB.location.id,{cache:'no-store'});const p=await r.json();if(!r.ok||!p.ok)throw Error(p.error||r.status);
    if(!dialog.open||upsellSelection?.location_id!==DB.location.id)return;
    select.innerHTML=`<option value="">${upText('Создать новую категорию','Create a new category')}</option>`+p.items.map(t=>`<option value="${Number(t.id)}">${htmlSafe(t.title)}</option>`).join('');
    document.getElementById('upsellNewTag').value=group.criteria?upsellSuggestedName(group.criteria,100):group.title.slice(0,100);
    document.getElementById('upsellAssignStatus').textContent='';document.getElementById('upsellAssignSubmit').disabled=false;
  }catch(e){document.getElementById('upsellAssignStatus').textContent=upText('Не удалось загрузить категории: ','Could not load categories: ')+e.message;}
}
const upsellAssignForm=document.getElementById('upsellAssignForm');
if(upsellAssignForm){
 document.getElementById('upsellAssignClose').onclick=()=>document.getElementById('upsellAssign').close();
 document.getElementById('upsellClientTag').onchange=e=>document.getElementById('upsellNewTagField').hidden=!!e.target.value;
 upsellAssignForm.onsubmit=async e=>{
  e.preventDefault();const selected=upsellSelection;if(!selected)return;
  const submit=document.getElementById('upsellAssignSubmit'),status=document.getElementById('upsellAssignStatus');submit.disabled=true;
  status.textContent=upText('Добавляем клиентов…','Adding clients…');
  try{const r=await fetch('/api/upsell/assign-category',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location_id:selected.location_id,client_ids:selected.client_ids,tag_id:Number(document.getElementById('upsellClientTag').value)||null,new_title:document.getElementById('upsellNewTag').value,offer:selected.title})});
    const p=await r.json();if(!r.ok||!p.ok)throw Error(p.error||r.status);
    status.textContent=upText(`Добавлено: ${p.added}. Уже были в категории: ${p.existing}. Ошибок: ${p.failed.length}. Категория: ${p.category.title}. Список и дата сохранены для последующего сравнения.`,`Added: ${p.added}. Already included: ${p.existing}. Failed: ${p.failed.length}. Category: ${p.category.title}. Audience and date saved for future comparison.`);
    if(p.failed.length)status.textContent+=' '+p.failed.map(f=>`${f.client_id}: ${f.error}`).join('; ');
  }catch(err){status.textContent=upText('Не удалось завершить: ','Could not finish: ')+err.message;}
  finally{submit.disabled=false;}
 };
}
