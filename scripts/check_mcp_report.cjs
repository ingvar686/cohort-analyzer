const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {normalizeMcpPayload} = require('../dashboards/mcp-offline.js');
const fixture = {format:'altegio-mcp-report-v1',locations:[{
  as_of:'2026-11-17',location:{id:991001,name:'MCP Test Studio',currency:'EUR'},
  coverage:{from:'2026-01-01',to:'2026-11-17',complete:true},
  categories:[{title:'Google Maps'}],default_budgets:{'Google Maps':100},
  service_catalog:{categories:[{id:10,title:'Haircuts'},{id:20,title:'Nails'}],services:[{id:11,category_id:10,title:'Haircut',active:true},{id:21,category_id:20,title:'Manicure',active:true}]},
  clients:[{id:1,name:'Test Client A',categories:['Google Maps'],visits:[
    {appointment_id:101,date:'2026-01-10',attendance:'arrived',paid_in_full:true,revenue:80,amount_due:0,services:['Haircut']},
    {appointment_id:102,date:'2026-02-10',attendance:'arrived',paid_in_full:true,revenue:60,amount_due:0,services:['Haircut']},
    {appointment_id:103,date:'2026-03-10',attendance:'arrived',paid_in_full:false,revenue:0,services:['Haircut']}
  ]},{id:2,name:'Test Client B',categories:['Google Maps'],visits:[
    {appointment_id:201,date:'2026-01-15',attendance:'arrived',paid_in_full:true,revenue:50,amount_due:0,services:['Haircut']}
  ]}]
}]};
const copy = () => JSON.parse(JSON.stringify(fixture));
const data = normalizeMcpPayload(copy())[0];
assert.equal(data.clients.length,2);assert.equal(data.source,'altegio_mcp');
assert.equal(data.clients[0].visits[2].paid_in_full,false);
const html = fs.readFileSync('dashboards/index.html','utf8');
const context = vm.createContext({});
for(const name of ['monthDistance','isFullyPaidVisit','buildPaidCohortClients']){
 const start=html.indexOf('function '+name+'('),end=html.indexOf('\n}',start);
 if(name==='buildPaidCohortClients')vm.runInContext(html.slice(start,html.indexOf('\nlet cohortClients',start)),context);
 else if(name==='isFullyPaidVisit')vm.runInContext(html.slice(start,html.indexOf('\nfunction buildPaidCohortClients',start)),context);
 else vm.runInContext(html.slice(start,html.indexOf('\n',start)),context);
}
context.clients=data.clients;
const eligible=vm.runInContext('buildPaidCohortClients(clients)',context);
assert.equal(eligible.length,2);assert.equal(eligible[0].visit_count,2);assert.equal(eligible[0].revenue,140);
let bad=copy();bad.locations[0].coverage.complete=false;assert.throws(()=>normalizeMcpPayload(bad),/coverage/);
bad=copy();delete bad.locations[0].clients[0].visits[0].revenue;assert.throws(()=>normalizeMcpPayload(bad),/revenue/);
bad=copy();bad.locations[0].clients[0].visits.push(bad.locations[0].clients[0].visits[0]);assert.throws(()=>normalizeMcpPayload(bad),/ID/);
bad=copy();bad.locations[0].clients[0].visits[0].amount_due=1;assert.equal(normalizeMcpPayload(bad)[0].clients[0].visits[0].paid_in_full,false);
bad=copy();bad.locations[0].default_budgets['Google Maps']='fake';assert.throws(()=>normalizeMcpPayload(bad),/Бюджет/);
bad=copy();bad.locations[0].clients[0].visits[0].date='2026-02-30';assert.throws(()=>normalizeMcpPayload(bad),/дат/);
const offline = fs.readFileSync('data/raw/altegio-report-mcp.html','utf8');
assert.ok(!/<script src=/.test(offline));assert.ok(offline.includes("connect-src 'none'"));
assert.ok(!offline.includes('const initialLoad=initializeLocations();'));
for(const script of offline.matchAll(/<script>([\s\S]*?)<\/script>/g))new vm.Script(script[1]);
fs.writeFileSync('data/raw/mcp-report-test.json',JSON.stringify(fixture));
console.log('Passed: paid visit eligibility, complete history, duplicate IDs, budgets, self-contained scripts and blocked network.');
