/* Pure sandbox evaluator: no network, timers, CRM writes or input mutations. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.AutomationSandbox=api})(typeof globalThis==='object'?globalThis:this,function(){
 'use strict';
 const MODES=['no_visits','explicit','any'],TRIGGERS=['booking','arrived','paid'];
 function validDay(value){if(!/^\d{4}-\d{2}-\d{2}$/.test(value||''))return false;const d=new Date(value+'T12:00:00Z');return Number.isFinite(d.getTime())&&d.toISOString().slice(0,10)===value}
 function validate(rule,branch,others=[]){
  const errors=[];
  if(!String(rule.name||'').trim())errors.push('Укажите название правила.');
  if(!branch.widgets.some(x=>Number(x.id)===Number(rule.widgetId)))errors.push('Выберите виджет этого филиала.');
  if(!branch.categories.some(x=>Number(x.id)===Number(rule.categoryId)))errors.push('Выберите категорию клиентов этого филиала.');
  if(!MODES.includes(rule.clientMode))errors.push('Выберите условие для новых клиентов.');
  if(!TRIGGERS.includes(rule.trigger))errors.push('Выберите момент назначения категории.');
  if(rule.startDate&&!validDay(rule.startDate)||rule.endDate&&!validDay(rule.endDate))errors.push('Проверьте даты кампании.');
  if(rule.startDate&&rule.endDate&&rule.startDate>rule.endDate)errors.push('Начало кампании должно быть раньше окончания.');
  if(others.some(x=>x.id!==rule.id&&Number(x.widgetId)===Number(rule.widgetId)))errors.push('Для этого виджета уже есть правило. Отредактируйте его.');
  return errors;
 }
 function evaluate(events,rules,settings,branch){
  const clients=new Map(),seen=new Set();
  return events.map(event=>{
   const out={id:event.id,client:event.client,widgetId:event.widgetId,newClient:event.priorVisits===0,explicitNew:event.explicitNew,status:'skip',reason:'',categoryId:null,before:[],after:[]};
   if(Number(event.branchId)!==Number(branch.id))return{...out,reason:'Бронирование другого филиала'};
   if(!event.clientId)return{...out,reason:'У бронирования нет ID клиента'};
   const clientKey=branch.id+':'+event.clientId;
   if(!clients.has(clientKey))clients.set(clientKey,{categories:new Set((event.categories||[]).map(Number)),firstSource:event.firstSourceWidgetId||null});
   const client=clients.get(clientKey);out.before=[...client.categories];out.after=[...client.categories];
   if(event.cancelled)return{...out,reason:'Бронирование отменено'};
   const matching=rules.filter(r=>Number(r.widgetId)===Number(event.widgetId));
   if(!matching.length)return{...out,reason:'Для виджета нет правила'};
   const rule=matching.find(r=>r.enabled);
   if(!rule)return{...out,reason:'Правило выключено'};
   out.ruleId=rule.id;out.categoryId=Number(rule.categoryId);
   if(validate(rule,branch).length)return{...out,reason:'Настройки правила требуют проверки'};
   const dedupeKey=branch.id+':'+event.id+':'+rule.id;
   if(seen.has(dedupeKey))return{...out,reason:'Повторное событие: уже обработано'};
   if(rule.clientMode==='no_visits'){
    if(!Number.isInteger(event.priorVisits)||event.priorVisits<0)return{...out,reason:'История посещений неизвестна — нужна проверка'};
    if(event.priorVisits>0)return{...out,reason:'Клиент уже посещал салон'};
   }
   if(rule.clientMode==='explicit'){
    if(typeof event.explicitNew!=='boolean')return{...out,reason:'Пометка «Новый клиент» не передана'};
    if(!event.explicitNew)return{...out,reason:'Нет пометки «Новый клиент»'};
   }
   if(rule.startDate||rule.endDate){
    const day=String(event.createdAt||'').slice(0,10);
    if(!validDay(day))return{...out,reason:'Неизвестна дата создания бронирования'};
    if(rule.startDate&&day<rule.startDate||rule.endDate&&day>rule.endDate)return{...out,reason:'Бронирование создано вне периода кампании'};
   }
   if(rule.trigger!=='booking'&&!event.arrived)return{...out,reason:'Ожидаем состоявшийся визит'};
   if(rule.trigger==='paid'&&event.paidInFull!==true)return{...out,reason:'Ожидаем завершения оплаты'};
   if(client.categories.has(Number(rule.categoryId))){seen.add(dedupeKey);return{...out,status:'existing',reason:'Категория уже есть у клиента'}};
   if(settings.protectFirstSource&&client.firstSource&&Number(client.firstSource)!==Number(rule.widgetId))return{...out,reason:'Сохранён другой первый источник привлечения'};
   seen.add(dedupeKey);client.categories.add(Number(rule.categoryId));
   if(!client.firstSource)client.firstSource=Number(rule.widgetId);
   return{...out,status:'add',reason:'Условия выполнены: категория была бы добавлена',after:[...client.categories]};
  });
 }
 return{validate,evaluate,validDay};
});
