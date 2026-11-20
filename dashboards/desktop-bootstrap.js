/* Local desktop shell: official browser sign-in, no passwords in this page. */
(() => {
  const originalFetch=window.fetch.bind(window);
  window.fetch=(input,options={})=>{
    const url=new URL(typeof input==='string'?input:input.url,location.href);
    if(url.origin===location.origin&&url.pathname.startsWith('/api/')){
      const headers=new Headers(options.headers||{});headers.set('X-App-Token',window.__desktopToken);
      return originalFetch(input,{...options,headers});
    }
    return originalFetch(input,options);
  };
})();
let desktopPolling=null;
const desktopClientEdition=document.body.hasAttribute('data-client-edition');
async function desktopRequest(path,body){
 const response=await fetch(path,body===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const data=await response.json();if(!response.ok)throw Error(data.error||'Не удалось связаться с локальным приложением.');return data;
}
function desktopPrivacyNote(){
 if(document.getElementById('desktopPrivacy'))return;
 const note=document.createElement('p');note.id='desktopPrivacy';note.className='caption';note.style='margin:12px 28px';
 note.textContent=desktopClientEdition
  ? 'Данные филиала хранятся на этом компьютере. Доступ к Altegio открыт на чтение.'
  : 'Данные Altegio — только чтение · Рассылки и результаты сохраняются на этом компьютере · ИИ-чат не используется';
 document.getElementById('reportContent').before(note);
 const logout=document.createElement('button');logout.className='theme';logout.type='button';logout.textContent='Сменить аккаунт';
 logout.onclick=async()=>{logout.disabled=true;try{await desktopRequest('/api/desktop/logout',{});location.reload()}catch(e){logout.disabled=false;syncStatus.textContent=e.message}};
 document.querySelector('.status').append(logout);
 const originalLanguage=document.getElementById('language').onclick;
 document.getElementById('language').onclick=()=>{
  if(!DB.location?.id){language=language==='ru'?'en':'ru';document.getElementById('language').textContent=language==='ru'?'EN':'RU';return}
  originalLanguage();euro=new Intl.NumberFormat(language==='ru'?'ru-RU':'en-GB',{style:'currency',currency:DB.location.currency,maximumFractionDigits:0});renderAll();
 };
 const style=document.createElement('style');style.textContent='#desktopConnection .field{max-width:540px;margin:18px 0}#desktopConnection h2{margin-top:0}#desktopConnection .sync{min-height:44px}#desktopConnection .caption{max-width:650px}';document.head.append(style);
 window.addEventListener('message',event=>{
  if(event.origin===location.origin&&event.source===document.getElementById('automationFrame')?.contentWindow&&event.data?.channel==='altegio-automation-sandbox'&&event.data.type==='open-upsell')document.querySelector('[data-tab="cross"]').click();
 });
}
function desktopLogin(message=''){
 const root=document.getElementById('connectionNotice');root.hidden=false;document.getElementById('reportContent').hidden=true;
 document.getElementById('sideFoot').textContent='Локальный отчёт · нет подключения';
 syncBtn.disabled=true;syncStatus.textContent='Войдите в свой аккаунт Altegio';
 document.querySelectorAll('.nav button').forEach(b=>b.disabled=true);
 root.innerHTML='<div id="desktopConnection"><h2>Подключите свой аккаунт Altegio</h2><p>Войдите в Altegio и выберите филиал для анализа.</p><p class="caption">Вход откроется на официальной странице Altegio. Приложение запрашивает доступ на чтение.</p><label style="display:flex;gap:10px;align-items:center;margin:20px 0"><input type="checkbox" id="desktopContacts" style="width:auto">Загружать телефоны для CSV (необязательно)</label><button class="sync" id="desktopLogin" type="button">Войти через Altegio</button><p id="desktopError" role="status" class="caption"></p></div>';
 document.getElementById('desktopError').textContent=message;
 document.getElementById('desktopLogin').onclick=async event=>{
  const button=event.currentTarget;button.disabled=true;button.textContent='Открываем вход Altegio…';
  try{const data=await desktopRequest('/api/desktop/login',{contacts:document.getElementById('desktopContacts').checked});location.assign(data.url)}
  catch(e){document.getElementById('desktopError').textContent=e.message;button.disabled=false;button.textContent='Войти через Altegio'}
 };
}
async function initializeDesktopReport(){
 desktopPrivacyNote();
 if(!desktopClientEdition) openUpsellCategoryForm=async(key,override=null)=>{
  const group=override||upsellGroups.get(key);if(!group)return;
  let dialog=document.getElementById('desktopCategoryInfo');
  if(!dialog){dialog=document.createElement('dialog');dialog.id='desktopCategoryInfo';dialog.className='mailing-dialog';document.body.append(dialog)}
  const ids=[...new Set(group.rows.map(r=>Number(r.client.id)).filter(Boolean))];
  dialog.innerHTML='<h3>'+upText('Добавить клиентов в категорию Altegio','Add clients to an Altegio category')+'</h3><p>'+htmlSafe(group.title)+' · '+ids.length+' '+upText('клиентов','clients')+'</p><p class="callout">'+upText('Создайте категорию в кабинете Altegio и вручную добавьте в неё выбранных клиентов. Предлагаемое название можно скопировать из поля выше.','Create the category in Altegio and manually add the selected clients. You can copy the suggested name from the field above.')+'</p><p>'+upText('Скачайте список клиентов для этого шага. Сохранённая рассылка будет отслеживать покупки именно этой аудитории.','Download the client list for this step. The saved campaign will track purchases by this exact audience.')+'</p><div class="upsell-dialog-actions"><button class="theme" type="button" id="desktopCategoryClose">'+upText('Закрыть','Close')+'</button><button class="sync" type="button" id="desktopCategoryExport">'+upText('Скачать выбранных клиентов CSV','Download selected clients CSV')+'</button></div>';
  const nameField=document.createElement('div');nameField.className='field';
  const nameLabel=document.createElement('label');nameLabel.htmlFor='desktopCategoryName';nameLabel.textContent=upText('Предлагаемое название категории','Suggested category name');
  const nameInput=document.createElement('input');nameInput.id='desktopCategoryName';nameInput.readOnly=true;nameInput.value=group.criteria?upsellSuggestedName(group.criteria,100):group.title.slice(0,100);
  nameField.append(nameLabel,nameInput);dialog.querySelector('h3').after(nameField);
  dialog.querySelector('#desktopCategoryClose').onclick=()=>dialog.close();
  dialog.querySelector('#desktopCategoryExport').onclick=()=>exportMailing({id:'audience-'+DB.location.id,name:group.title,client_ids:ids,services:upsellCatalog().services.filter(s=>(group.service_ids||[]).includes(Number(s.id)))});
  dialog.showModal();
 };
 showConnectionNeeded=message=>{
  DB={location:{},clients:[],directory:[],categories:[],campaigns:[],default_budgets:{}};
  cohortClients=[];
  if(!desktopClientEdition)mailingCache.clear();
  upsellBranch=null;
  desktopLogin(message);
 };
 const root=document.getElementById('connectionNotice');
 root.innerHTML='<h2>Открываем локальный отчёт…</h2><p>Проверяем сохранённое подключение к Altegio.</p>';
 document.querySelectorAll('.nav button').forEach(b=>b.disabled=true);syncBtn.disabled=true;
 try{
  const state=await desktopRequest('/api/desktop/state');
  if(!state.connected){desktopLogin(state.login_error||'');return false}
  const response=await desktopRequest('/api/locations');
  const branches=response.items||[];
  if(!branches.length){desktopLogin('В подключённом аккаунте нет доступных филиалов. Проверьте выбранные права или войдите другим аккаунтом.');return false}
  locationSelect.innerHTML=branches.map(row=>`<option value="${Number(row.id)}">${htmlSafe(row.title)}</option>`).join('');
  root.innerHTML='<div id="desktopConnection"><h2>Какой филиал открыть?</h2><p>Категории клиентов, услуги и история загрузятся из выбранного филиала.</p><div class="field"><label for="desktopBranch">Ваш филиал Altegio</label><select id="desktopBranch"></select></div><div class="field"><label for="desktopCurrency">Валюта отчёта</label><select id="desktopCurrency"><option value="">Выберите валюту</option>'+['EUR','USD','GBP','PLN','UAH','RUB','BRL','KZT','CZK','HUF','RON','ILS','AED','TRY','GEL','ARS','MXN','COP','CLP'].map(code=>`<option value="${code}">${code}</option>`).join('')+'</select></div><button class="sync" id="desktopOpen" type="button" disabled>Загрузить мой отчёт</button><p class="caption" id="desktopLoadMessage" role="status">При первой загрузке потребуется получить историю клиентов. Это может занять несколько минут.</p></div>';
  const branch=document.getElementById('desktopBranch'),currency=document.getElementById('desktopCurrency'),button=document.getElementById('desktopOpen');
  branch.innerHTML='<option value="">Выберите филиал</option>'+locationSelect.innerHTML;
  const select=async()=>{
   button.disabled=true;currency.value='';
   if(!branch.value)return;
   document.getElementById('desktopLoadMessage').textContent='Проверяем филиал…';
   try{const info=(await desktopRequest('/api/desktop/location?location_id='+branch.value)).location;
    if(info.currency){if(![...currency.options].some(o=>o.value===info.currency)){const o=document.createElement('option');o.value=info.currency;o.textContent=info.currency;currency.append(o)}currency.value=info.currency}
    button.disabled=!currency.value;document.getElementById('desktopLoadMessage').textContent=currency.value?'Данные будут загружены только с доступом на чтение.':'Уточните валюту филиала.';
   }catch(e){document.getElementById('desktopLoadMessage').textContent=e.message}
  };
  branch.onchange=select;currency.onchange=()=>{button.disabled=!branch.value||!currency.value};
  const open=async()=>{
   button.disabled=true;branch.disabled=true;currency.disabled=true;button.textContent='Загружаем историю…';
   document.getElementById('desktopLoadMessage').textContent='При первом запуске загрузка может занять несколько минут. Не закрывайте приложение.';
   try{
    await desktopRequest('/api/desktop/open',{location_id:Number(branch.value),currency:currency.value});
    locationSelect.value=branch.value;
    if(!await loadRemoteData(branch.value))throw Error('Не удалось открыть загруженный отчёт.');
    document.querySelectorAll('.nav button').forEach(b=>b.disabled=false);syncBtn.disabled=false;
    syncStatus.textContent='Altegio · данные на этом компьютере';
   }catch(e){document.getElementById('desktopLoadMessage')&&(document.getElementById('desktopLoadMessage').textContent=e.message);button.disabled=false;button.textContent='Повторить загрузку';branch.disabled=false;currency.disabled=false;}
  };
  button.onclick=open;
  locationSelect.onchange=async()=>{
   document.getElementById('reportContent').hidden=true;root.hidden=false;
   branch.value=locationSelect.value;await select();if(currency.value)await open();
  };
  document.getElementById('upsellLocation').onchange=async event=>{locationSelect.value=event.target.value;await locationSelect.onchange()};
  if(desktopPolling)clearInterval(desktopPolling);
  desktopPolling=setInterval(async()=>{
   try{const status=await desktopRequest('/api/desktop/state');if(status.progress.running){syncStatus.textContent=status.progress.message;const message=document.getElementById('desktopLoadMessage');if(message)message.textContent=status.progress.message}}
   catch(e){
    const executable=document.body.hasAttribute('data-macos')?'Start macOS.command'
      :desktopClientEdition?'AltegioAnalyticsClient.exe':'AltegioAnalytics.exe';
    syncStatus.textContent='Приложение остановлено. Откройте '+executable+' снова.';
    clearInterval(desktopPolling);
   }
  },2000);
  if(state.selected_location&&branches.some(b=>Number(b.id)===state.selected_location)){
   branch.value=String(state.selected_location);await select();if(currency.value)await open();
  }else if(branch.options.length===2){branch.selectedIndex=1;await select()}
  return true;
 }catch(e){desktopLogin(e.message);return false}
}
