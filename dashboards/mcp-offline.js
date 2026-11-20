/* Portable report: explicitly imported data only; no API credentials or network. */
function normalizeMcpPayload(payload) {
  const branches = Array.isArray(payload.locations) ? payload.locations : payload.location ? [payload] : [];
  if (!branches.length) throw Error('В файле нет данных филиала. Попросите чат сохранить JSON по инструкции.');
  const ids = new Set();
  const date = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value + 'T00:00:00Z')) && new Date(value + 'T00:00:00Z').toISOString().slice(0,10) === value;
  return branches.map(raw => {
    const coverage = raw.coverage || payload.coverage;
    const id = Number(raw.location?.id);
    if (!Number.isSafeInteger(id) || id <= 0 || ids.has(id) || !raw.location?.name) throw Error('Проверьте ID и название филиала.');
    ids.add(id);
    if (!/^[A-Z]{3}$/.test(raw.location.currency || '')) throw Error('Укажите валюту филиала, например EUR.');
    if (!date(raw.as_of) || !coverage || coverage.complete !== true || !date(coverage.from) || !date(coverage.to) || coverage.from > coverage.to || coverage.to > raw.as_of) {
      throw Error('Нужны дата отчёта и подтверждение полной загрузки выбранного периода (coverage). Неполные данные не показываем как полный отчёт.');
    }
    if (!Array.isArray(raw.clients)) throw Error('В файле отсутствует список клиентов.');
    const clientIds = new Set();
    const clients = raw.clients.map(client => {
      if (!Number.isSafeInteger(Number(client.id)) || Number(client.id)<=0 || clientIds.has(String(Number(client.id))) || !Array.isArray(client.visits)) throw Error('Нужны уникальные ID клиентов и список их визитов.');
      clientIds.add(String(Number(client.id)));
      const visitIds = new Set();
      const visits = client.visits.map(visit => {
        const key = visit.appointment_id ?? visit.visit_id;
        if (!Number.isSafeInteger(Number(key)) || Number(key)<=0 || visitIds.has(String(Number(key))) || !date(visit.date) || visit.date > raw.as_of) throw Error('У визита нет уникального ID или корректной даты.');
        visitIds.add(String(Number(key)));
        const attendance = visit.attendance ?? visit.status;
        const paid = visit.paid_in_full === true && !(Number(visit.amount_due) > 0) && ['arrived',1].includes(attendance);
        if (paid && (typeof visit.revenue !== 'number' || !Number.isFinite(visit.revenue) || visit.revenue < 0)) throw Error('Для оплаченного визита нужна фактическая сумма revenue. Не подменяйте её ценой услуги.');
        const names = (visit.services?.length ? visit.services : visit.service ? [visit.service] : []).map(s => typeof s === 'string' ? s : s.title || s.name || '').filter(Boolean);
        return {...visit, appointment_id:Number(key), paid_in_full:paid, revenue:Number(visit.revenue) || 0,
          attendance:attendance === 1 ? 'arrived' : attendance || 'unknown',
          services:names, service:names.join(', ')};
      });
      const categories = (client.categories || []).map(c => typeof c === 'string' ? c : c.title || c.name || '').filter(Boolean);
      return {...client, id:Number(client.id), name:String(client.name || client.id), categories, phone:String(client.phone || ''), visits};
    });
    const budgets=raw.default_budgets || {};
    if (Object.values(budgets).some(value=>typeof value!=='number'||!Number.isFinite(value)||value<0)) throw Error('Бюджеты должны быть числами; неизвестные бюджеты не указывайте.');
    const catalog=raw.service_catalog || {categories:[],services:[]};
    if (!Array.isArray(catalog.categories)||!Array.isArray(catalog.services)) throw Error('Неверный каталог услуг.');
    const categories=catalog.categories.map(c=>{if(!Number.isSafeInteger(Number(c.id))||Number(c.id)<=0)throw Error('Неверный ID категории услуг.');return {id:Number(c.id),title:String(c.title||c.id)}});
    const services=catalog.services.map(s=>{if(!Number.isSafeInteger(Number(s.id))||Number(s.id)<=0)throw Error('Неверный ID услуги.');return {id:Number(s.id),category_id:Number(s.category_id),title:String(s.title||s.id),active:s.active!==false}});
    return {...raw, location:{...raw.location,id}, source:'altegio_mcp', coverage, clients,
      campaigns:[], default_budgets:budgets, directory:clients, service_catalog:{categories,services}};
  });
}

function initializeMcpReport() {
  let branches = [], filename = '';
  const notice = document.getElementById('connectionNotice');
  notice.innerHTML = '<h2>Отчёт через Altegio MCP</h2><p>Загрузите в чат файл инструкции и попросите получить данные вашего салона через подключённый Altegio MCP. Затем выберите полученный JSON-файл здесь.</p><p>Python, локальный сервер и API-ключи для открытия отчёта не нужны. Файл читается локально: данные не отправляются на сервер.</p><button class="sync" id="mcpChoose" type="button">Выбрать файл данных</button><p id="mcpImportStatus" role="status"></p>';
  const picker = document.createElement('input');picker.type='file';picker.accept='.json,application/json';picker.hidden=true;document.body.append(picker);
  const tools = document.createElement('div');tools.className='caption';tools.style='padding:10px 28px;display:flex;align-items:center;gap:12px;flex-wrap:wrap';
  tools.innerHTML='<button class="theme" id="mcpReplace" type="button">Загрузить другой JSON</button><span id="mcpCoverage">Данные ещё не загружены.</span><span id="mcpStatus" role="status"></span>';
  document.getElementById('reportContent').before(tools);
  const help = document.createElement('dialog');help.id='mcpHelp';help.style='max-width:600px;padding:24px;border-radius:12px;background:var(--panel);color:var(--ink)';
  help.innerHTML='<h3>Обновление через чат</h3><p>Попросите чат: «Обнови JSON этого отчёта через мой Altegio MCP, сохрани тот же формат и выгрузи все страницы данных за выбранный период».</p><p>Скачайте новый JSON и нажмите «Загрузить другой JSON». Фильтры, бюджеты и CSV работают без обращения к чату. Добавление категорий в Altegio и отслеживание рассылок выполняйте через чат или серверную версию.</p><button class="theme" type="button">Закрыть</button>';
  document.body.append(help);help.querySelector('button').onclick=()=>help.close();
  const openPicker=()=>{picker.value='';picker.click()};
  document.getElementById('mcpChoose').onclick=openPicker;document.getElementById('mcpReplace').onclick=openPicker;
  const clear = () => {
    document.getElementById('reportContent').hidden=true;notice.hidden=false;
    syncBtn.disabled=true;document.querySelectorAll('.nav button').forEach(b=>b.disabled=true);
    syncStatus.textContent='Altegio MCP · выберите файл';document.getElementById('sideFoot').textContent='Данные салона не загружены';
  };
  const selectBranch = () => {
    const next=branches.find(b=>String(b.location.id)===locationSelect.value);if(!next)return;
    applyDataset(next);syncBtn.disabled=false;syncBtn.textContent='Обновить через чат';syncBtn.title='Как получить свежие данные через MCP';syncBtn.onclick=()=>help.showModal();
    document.querySelectorAll('.nav button').forEach(b=>b.disabled=false);
    document.getElementById('mcpCoverage').textContent=`${filename} · История ${next.coverage.from} — ${next.coverage.to}. Когорты по доступной истории.`;
    syncStatus.textContent='Altegio MCP · снимок на '+next.as_of;
  };
  // Replace operations requiring the local API. No call to the chatbot is implied.
  renderMailings=()=>{document.querySelector('.mailing-panel').hidden=true};
  openUpsellCategoryForm=async()=>help.showModal();
  openMailingForm=()=>help.showModal();
  openMailingSend=()=>help.showModal();
  locationSelect.onchange=selectBranch;
  document.getElementById('upsellLocation').onchange=event=>{locationSelect.value=event.target.value;selectBranch()};
  picker.onchange=async()=>{
    const file=picker.files[0];if(!file)return;
    try{
      const next=normalizeMcpPayload(JSON.parse(await file.text()));
      branches=next;filename=file.name;upsellBranch=null;mailingCache.clear();
      locationSelect.innerHTML=branches.map(b=>`<option value="${b.location.id}">${htmlSafe(b.location.name)}</option>`).join('');
      document.getElementById('mcpStatus').textContent='';document.getElementById('mcpImportStatus').textContent='';
      selectBranch();
    }catch(error){document.getElementById('mcpStatus').textContent=error.message;document.getElementById('mcpImportStatus').textContent=error.message;}
  };
  document.querySelector('.mailing-panel').hidden=true;
  const originalLanguage=document.getElementById('language').onclick;
  document.getElementById('language').onclick=()=>{if(DB.location?.id){originalLanguage();selectBranch()}else{language=language==='ru'?'en':'ru';translatePage()}};
  clear();
}

if (typeof module !== 'undefined' && module.exports) module.exports = {normalizeMcpPayload};
