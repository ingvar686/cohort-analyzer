/* Local automation settings, synthetic preview, and server-backed worker control. */
'use strict';
const $=id=>document.getElementById(id);
const escapeHtml=value=>String(value??'').replace(/[&<>"']/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
const catalog=window.SANDBOX_CATALOG,engine=window.AutomationSandbox;
const branches=catalog.branches,states=new Map();
const modeNames={no_visits:'Только новые клиенты',explicit:'Пометка «Новый клиент»',any:'Все клиенты'};
const triggerNames={booking:'При бронировании',arrived:'После визита',paid:'После полной оплаты'};
const statusNames={add:'Добавили бы',existing:'Уже есть',skip:'Пропустили бы'};
let currentBranch=branches[0],editingId=null,previewRows=[],toastTimer;
function storageKey(branch){return 'altegioAutomationSandbox:v1:'+branch.id}
function defaultRules(branch){
 if(branch.id!==764940)return[];
 const rules=[];
 const website=branch.widgets.find(x=>x.id===814275),seo=branch.categories.find(x=>x.id===10104259);
 const instagram=branch.widgets.find(x=>x.id===818559),target=branch.categories.find(x=>x.id===9822869);
 if(website&&seo)rules.push({id:'example-website',name:'Новые клиенты с сайта',widgetId:website.id,categoryId:seo.id,clientMode:'no_visits',trigger:'booking',startDate:'',endDate:'',enabled:true});
 if(instagram&&target)rules.push({id:'example-instagram',name:'Новые клиенты из Instagram',widgetId:instagram.id,categoryId:target.id,clientMode:'no_visits',trigger:'booking',startDate:'',endDate:'',enabled:true});
 return rules;
}
function state(){
 if(!states.has(currentBranch.id)){
  let saved=null;
  try{saved=JSON.parse(localStorage.getItem(storageKey(currentBranch))||'null')}catch(e){}
  const valid=saved?.schema_version===1&&saved.branch_id===currentBranch.id&&Array.isArray(saved.rules)&&saved.rules.every(r=>engine.validate(r,currentBranch,saved.rules).length===0);
  states.set(currentBranch.id,valid?{rules:saved.rules,settings:{protectFirstSource:saved.settings?.protectFirstSource!==false,interval:['1','5','15','manual'].includes(saved.settings?.interval)?saved.settings.interval:'5'},enabled:false,savedAt:saved.saved_at,dirty:false}:{rules:defaultRules(currentBranch),settings:{protectFirstSource:true,interval:'5'},enabled:false,savedAt:null,dirty:false});
 }
 return states.get(currentBranch.id);
}
function toast(text){clearTimeout(toastTimer);$('toast').textContent=text;$('toast').hidden=false;toastTimer=setTimeout(()=>$('toast').hidden=true,4200)}
function dirty(){state().dirty=true;updateSaveState();$('previewStatus').classList.add('stale');$('previewStatus').textContent='Настройки изменены. Запустите проверку ещё раз.'}
function updateSaveState(){const s=state();$('saveState').classList.toggle('dirty',s.dirty);$('saveState').textContent=s.dirty?'Есть несохранённые изменения':s.savedAt?'Сохранено на этом компьютере · '+new Intl.DateTimeFormat('ru-RU',{hour:'2-digit',minute:'2-digit'}).format(new Date(s.savedAt)):'Примеры правил · ещё не сохранены';$('save').textContent=s.dirty?'Сохранить изменения':'Сохранить правила';$('automationEnabled').checked=s.enabled;$('workerStatus').classList.toggle('is-enabled',s.enabled)}
function showWorkerStatus(status,error=''){
 const title=$('workerStatusTitle'),text=$('workerStatusText'),enabled=state().enabled;
 $('workerStatus').classList.toggle('is-enabled',enabled);
 if(error){title.textContent='Сервер автоматизации недоступен';text.textContent=error;return}
 if(!status){title.textContent=enabled?'Автоматизация включена':'Автоматизация выключена';text.textContent=enabled?'Сохранённые правила начнут работать, когда локальный сервер запущен.':'Сохраните настройки на локальный сервер.';return}
 if(!status.enabled){title.textContent='Автоматизация выключена';text.textContent='Правила сохранены, но категории в Altegio не меняются.';return}
 title.textContent='Автоматизация включена · опрос раз в '+state().settings.interval+' мин.';
 const bits=[];if(status.last_run)bits.push('Последняя проверка '+new Intl.DateTimeFormat('ru-RU',{dateStyle:'short',timeStyle:'short'}).format(new Date(status.last_run)));
 if(status.added)bits.push('добавлено категорий за проход: '+status.added);if(status.pending)bits.push('ошибок в очереди: '+status.pending);
 if(status.last_error)bits.push('последняя ошибка: '+status.last_error);text.textContent=bits.join(' · ')||'Ожидает новые бронирования.';
}
function options(select,items,placeholder='Выберите…'){
 select.replaceChildren();
 if(placeholder!==null){const option=document.createElement('option');option.value='';option.textContent=placeholder;select.append(option)}
 for(const item of items){const option=document.createElement('option');option.value=String(item.id);option.textContent=item.title;select.append(option)}
}
function widgetTitle(id){return currentBranch.widgets.find(x=>Number(x.id)===Number(id))?.title||'Другой виджет (тест)'}
function categoryTitle(id){return currentBranch.categories.find(x=>Number(x.id)===Number(id))?.title||'—'}
function renderRules(){
 const s=state();$('ruleCount').textContent=s.rules.length;$('emptyRules').hidden=!!s.rules.length;
 $('rules').innerHTML=s.rules.map(rule=>`<article class="rule-card ${rule.enabled?'':'is-off'}"><div class="rule-mapping"><div class="mapping-box"><span class="mapping-title">${escapeHtml(widgetTitle(rule.widgetId))}</span><span class="mapping-id">Виджет #${Number(rule.widgetId)}</span></div><span class="map-arrow" aria-hidden="true">→</span><div class="mapping-box"><span class="mapping-title">${escapeHtml(categoryTitle(rule.categoryId))}</span><span class="mapping-id">Категория #${Number(rule.categoryId)}</span></div></div><div class="rule-bottom"><div class="rule-meta"><span class="chip">${modeNames[rule.clientMode]}</span><span class="chip">${triggerNames[rule.trigger]}</span>${rule.startDate||rule.endDate?`<span class="chip">${escapeHtml(rule.startDate||'…')} — ${escapeHtml(rule.endDate||'…')}</span>`:''}</div><div class="rule-tools"><button type="button" class="rule-edit" data-edit="${escapeHtml(rule.id)}" aria-label="Настроить правило: ${escapeHtml(rule.name)}">Настроить</button><label class="switch"><input type="checkbox" data-toggle="${escapeHtml(rule.id)}" ${rule.enabled?'checked':''}><span></span><span class="sr-only">Учитывать в пробном прогоне: ${escapeHtml(rule.name)}</span></label><button type="button" class="icon-button delete" data-delete="${escapeHtml(rule.id)}" aria-label="Удалить правило: ${escapeHtml(rule.name)}">×</button></div></div></article>`).join('');
 const first=s.rules.find(x=>x.enabled)||s.rules[0];
 $('exampleWidget').textContent=first?widgetTitle(first.widgetId):'Выберите виджет';
 $('exampleCategory').textContent=first?categoryTitle(first.categoryId):'Выберите категорию';
 $('addRule').disabled=!currentBranch.widgets.length||!currentBranch.categories.length;
 updateSaveState();
}
function renderBranch(){
 const s=state();
 $('catalogCounts').textContent=`Виджетов: ${currentBranch.widgets.length} · Категорий клиентов: ${currentBranch.categories.length}`;
 $('protectSource').checked=s.settings.protectFirstSource;$('interval').value=s.settings.interval;
 options($('testWidget'),currentBranch.widgets,null);
 options($('testSource'),currentBranch.widgets,'Ещё не зафиксирован');
 $('testWidget').value=String(s.rules[0]?.widgetId||currentBranch.widgets[0]?.id||'');
 $('manualResult').textContent='';renderRules();runPreview();
}
function updateModeHelp(){const texts={no_visits:'Неизвестная история не считается нулевой: такое бронирование будет пропущено.',explicit:'Если API не передал пометку, правило пропустит бронирование. Не подменяем её догадкой.',any:'Подходит и новым, и постоянным клиентам. Для когорт привлечения обычно выбирают только новых.'};$('modeHelp').textContent=texts[$('ruleMode').value]}
function openEditor(id=null){
 editingId=id;const existing=state().rules.find(x=>x.id===id);
 $('ruleForm').reset();$('formError').textContent='';$('periodDetails').open=false;
 $('dialogTitle').textContent=existing?'Настройки правила':'Новое правило';
 options($('ruleWidget'),currentBranch.widgets,'Выберите виджет');options($('ruleCategory'),currentBranch.categories,'Выберите категорию');
 if(existing){$('ruleName').value=existing.name;$('ruleWidget').value=String(existing.widgetId);$('ruleCategory').value=String(existing.categoryId);$('ruleMode').value=existing.clientMode;$('ruleTrigger').value=existing.trigger;$('ruleStart').value=existing.startDate||'';$('ruleEnd').value=existing.endDate||'';$('ruleEnabled').checked=existing.enabled;$('periodDetails').open=!!existing.startDate||!!existing.endDate}
 updateModeHelp();$('ruleDialog').showModal();
}
function saveRule(event){
 event.preventDefault();
 const rule={id:editingId||crypto.randomUUID(),name:$('ruleName').value.trim(),widgetId:Number($('ruleWidget').value),categoryId:Number($('ruleCategory').value),clientMode:$('ruleMode').value,trigger:$('ruleTrigger').value,startDate:$('ruleStart').value,endDate:$('ruleEnd').value,enabled:$('ruleEnabled').checked};
 const errors=engine.validate(rule,currentBranch,state().rules);
 if(errors.length){$('formError').textContent=errors.join('\n');return}
 if(editingId)state().rules=state().rules.map(x=>x.id===editingId?rule:x);else state().rules.push(rule);
 $('ruleDialog').close();dirty();renderRules();toast('Правило обновлено. Сохраните настройки выбранного филиала.');
}
function packageSettings(){const s=state();return{schema_version:1,mode:'local_automation',location_id:currentBranch.id,branch_id:currentBranch.id,branch_title:currentBranch.title,catalog_date:catalog.captured_at,saved_at:new Date().toISOString(),enabled:s.enabled,settings:s.settings,rules:s.rules}}
async function saveSettings(){
 const s=state(),errors=s.rules.flatMap(rule=>engine.validate(rule,currentBranch,s.rules));
 if(errors.length){toast(errors[0]);return}
 s.enabled=$('automationEnabled').checked;const data=packageSettings();$('save').disabled=true;
 try{
  const response=await fetch('/api/automation/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location_id:currentBranch.id,enabled:s.enabled,settings:s.settings,rules:s.rules})});
  const result=await response.json();if(!response.ok||!result.ok)throw new Error(result.error||'Не удалось сохранить правила.');
  localStorage.setItem(storageKey(currentBranch),JSON.stringify({...data,saved_at:result.config.updated_at}));
  s.savedAt=result.config.updated_at;s.dirty=false;updateSaveState();showWorkerStatus(result.status);
  toast(s.enabled?'Правила сохранены и включены. Новые совпадения будут обработаны локальным сервером.':'Правила сохранены. Автоматическое изменение Altegio выключено.');
 }catch(e){s.enabled=$('automationEnabled').checked;updateSaveState();showWorkerStatus(null,e.message||'Локальный сервер недоступен. Запустите scripts/server.py.');toast(e.message||'Не удалось сохранить настройки на локальный сервер.')}
 finally{$('save').disabled=false}
}
function exportSettings(){const data=packageSettings(),blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`automation-settings-${currentBranch.id}-${catalog.captured_at}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
function sampleEvents(){
 const rules=state().rules,first=rules.find(x=>x.enabled)||rules[0],source=first?.widgetId||currentBranch.widgets[0]?.id||0;
 const category=first?.categoryId||currentBranch.categories[0]?.id;
 const other=currentBranch.widgets.find(x=>Number(x.id)!==Number(source))?.id||999999999;
 const base={branchId:currentBranch.id,widgetId:source,priorVisits:0,explicitNew:true,createdAt:'2026-11-18T10:00:00',arrived:false,paidInFull:false,categories:[],cancelled:false};
 const sample=(id,title,extra={})=>({...base,id,clientId:'synthetic-client-'+id,client:title,...extra});
 const events=[
  sample('demo-01','Новый клиент'),
  sample('demo-02','Постоянный клиент',{priorVisits:5,explicitNew:false}),
  sample('demo-03','История неизвестна',{priorVisits:null,explicitNew:null}),
  sample('demo-04','Категория уже назначена',{categories:category?[category]:[]}),
  sample('demo-05','Сохранён первый источник',{firstSourceWidgetId:other}),
  sample('demo-06','Отменённое бронирование',{cancelled:true}),
  sample('demo-07','Пришёл, но не оплатил',{arrived:true}),
  sample('demo-08','Пришёл и полностью оплатил',{arrived:true,paidInFull:true}),
  sample('demo-09','Другой виджет',{widgetId:other}),
  sample('demo-10','Нет пометки «Новый клиент»',{explicitNew:false}),
  sample('demo-11','Бронирование прошлого года',{createdAt:'2025-06-01T10:00:00'}),
  sample('demo-01','Повтор того же события'),
 ];
 return events;
}
function runPreview(){
 const events=sampleEvents(),s=state();previewRows=engine.evaluate(events,s.rules,s.settings,currentBranch);
 const count=status=>previewRows.filter(x=>x.status===status).length;
 $('statAdd').textContent=count('add');$('statExisting').textContent=count('existing');$('statSkip').textContent=count('skip');
 $('previewStatus').classList.remove('stale');$('previewStatus').textContent=`Проверены ${events.length} вымышленных событий. В Altegio ничего не отправлено.`;
 $('results').innerHTML=previewRows.map(row=>`<tr><td><strong>${escapeHtml(row.client)}</strong><small>${escapeHtml(row.id)} · тестовые данные</small></td><td>${escapeHtml(widgetTitle(row.widgetId))}</td><td>${row.newClient?'Нет прошлых визитов':row.explicitNew===null?'История неизвестна':'Был раньше'}</td><td><span class="result-badge ${row.status}">${statusNames[row.status]}</span>${row.status==='add'?`<small>${escapeHtml(categoryTitle(row.categoryId))}</small>`:''}</td><td class="reason">${escapeHtml(row.reason)}</td></tr>`).join('');
}
function runManual(event){
 event.preventDefault();const type=$('testStatus').value,flag=$('testFlag').value;
 const input={id:'manual-test',clientId:'manual-client',client:'Свой сценарий',branchId:currentBranch.id,widgetId:Number($('testWidget').value),priorVisits:Number($('testVisits').value),explicitNew:flag==='unknown'?null:flag==='true',createdAt:$('testDate').value+'T12:00:00',arrived:type==='arrived'||type==='paid',paidInFull:type==='paid',cancelled:type==='cancelled',categories:[],firstSourceWidgetId:Number($('testSource').value)||null};
 const row=engine.evaluate([input],state().rules,state().settings,currentBranch)[0];
 $('manualResult').textContent=`${statusNames[row.status]}${row.status==='add'?' «'+categoryTitle(row.categoryId)+'»':''}. ${row.reason}.`;
}
let settingsLoadGeneration=0;
async function loadServerSettings(branchId){
 const generation=++settingsLoadGeneration;showWorkerStatus(null);
 try{
  const response=await fetch('/api/automation/settings?location_id='+encodeURIComponent(branchId),{cache:'no-store'});
  const result=await response.json();if(!response.ok||!result.ok)throw new Error(result.error||'Не удалось прочитать настройки.');
  if(generation!==settingsLoadGeneration||currentBranch.id!==branchId)return;
  const config=result.config||{};
  if(config.updated_at){
   const branch=branches.find(item=>item.id===branchId),rules=Array.isArray(config.rules)?config.rules:[];
   const valid=rules.every(rule=>engine.validate(rule,branch,rules).length===0);
   if(!valid)throw new Error('Сохранённые правила требуют проверки.');
   const saved={schema_version:1,branch_id:branchId,saved_at:config.updated_at,enabled:config.enabled===true,settings:config.settings||{},rules};
   states.set(branchId,{rules,settings:{protectFirstSource:saved.settings.protectFirstSource!==false,interval:['1','5','15'].includes(String(saved.settings.interval))?String(saved.settings.interval):'5'},enabled:saved.enabled,savedAt:saved.saved_at,dirty:false});
   try{localStorage.setItem(storageKey(branch),JSON.stringify(saved))}catch(e){}
  }else{
   const current=state();current.enabled=false;
   if(current.rules.length)current.dirty=true;
  }
  renderBranch();showWorkerStatus(result.status);
 }catch(e){if(generation===settingsLoadGeneration)showWorkerStatus(null,e.message||'Запустите локальный сервер проекта.')}
}
async function refreshWorkerStatus(){
 const s=state();if(!s.savedAt||s.dirty)return;
 try{const response=await fetch('/api/automation/settings?location_id='+encodeURIComponent(currentBranch.id),{cache:'no-store'});const result=await response.json();if(response.ok&&result.ok)showWorkerStatus(result.status)}catch(e){}
}
options($('branch'),branches,null);$('branch').value=String(currentBranch.id);
$('branch').onchange=()=>{currentBranch=branches.find(x=>x.id===Number($('branch').value));renderBranch();loadServerSettings(currentBranch.id)};
$('addRule').onclick=()=>openEditor();$('firstRule').onclick=()=>openEditor();
$('closeDialog').onclick=$('cancelDialog').onclick=()=>$('ruleDialog').close();
$('ruleForm').onsubmit=saveRule;$('ruleMode').onchange=updateModeHelp;
$('rules').onclick=event=>{
 const edit=event.target.closest('[data-edit]');if(edit){openEditor(edit.dataset.edit);return}
 const remove=event.target.closest('[data-delete]');if(remove){state().rules=state().rules.filter(x=>x.id!==remove.dataset.delete);dirty();renderRules();toast('Правило удалено из настроек песочницы.')}
};
$('rules').onchange=event=>{const id=event.target.dataset.toggle;if(!id)return;const rule=state().rules.find(x=>x.id===id);if(rule){rule.enabled=event.target.checked;dirty();renderRules()}};
$('protectSource').onchange=()=>{state().settings.protectFirstSource=$('protectSource').checked;dirty()};
$('interval').onchange=()=>{state().settings.interval=$('interval').value;dirty()};
$('automationEnabled').onchange=()=>{state().enabled=$('automationEnabled').checked;dirty();showWorkerStatus(null)};
$('save').onclick=saveSettings;$('export').onclick=exportSettings;$('run').onclick=runPreview;$('testForm').onsubmit=runManual;
try{const theme=localStorage.getItem('altegioAutomationSandbox:theme');if(['light','dark'].includes(theme)){document.documentElement.dataset.theme=theme;$('theme').value=theme}}catch(e){}
$('theme').onchange=()=>{document.documentElement.dataset.theme=$('theme').value;try{localStorage.setItem('altegioAutomationSandbox:theme',$('theme').value)}catch(e){}};
renderBranch();
loadServerSettings(currentBranch.id);
setInterval(refreshWorkerStatus,30000);
if(new URLSearchParams(location.search).get('embedded')==='1'){
 document.documentElement.dataset.embedded='true';
 const sendHeight=()=>parent.postMessage({channel:'altegio-automation-sandbox',type:'resize',height:document.documentElement.scrollHeight},location.origin);
 window.addEventListener('message',event=>{
  if(event.origin!==location.origin||event.source!==parent||event.data?.channel!=='altegio-dashboard'||event.data.type!=='theme')return;
  document.documentElement.dataset.theme=event.data.theme==='dark'?'dark':'light';
 });
 if('ResizeObserver' in window)new ResizeObserver(sendHeight).observe(document.body);
 window.addEventListener('load',sendHeight);window.addEventListener('resize',sendHeight);sendHeight();
}
