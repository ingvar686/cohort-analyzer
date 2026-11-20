const fs=require('fs'),vm=require('vm'),assert=require('assert');
const context={language:'ru',document:{getElementById:()=>({})}};
vm.createContext(context);
vm.runInContext(fs.readFileSync('dashboards/upsell.js','utf8'),context);
const catalog={categories:[{id:1,title:'Haircuts'},{id:2,title:'Cosmetology'}],services:[
  {id:11,title:'Cut A',category_id:1},{id:12,title:'Cut B',category_id:1},
  {id:21,title:'Facial',category_id:2}
]};
const options={category:'1',minimum:10,maximum:1,mode:'category',services:['Cut A','Cut B'],asOf:'2026-11-19'};
const criteria=context.buildUpsellCriteria(catalog,options,'category','2');
assert.equal(criteria.source_minimum_visits,10);
assert.equal(criteria.target_maximum_visits_exclusive,1);
assert.equal(criteria.source_all_services,true);
const name=context.upsellSuggestedName(criteria,100,'2026-11-19');
assert(name.includes('Стрижки ≥10 визитов'));
assert(name.includes('Косметология · 0 визитов'));
assert(name.length<=100);
assert(context.upsellCriteriaSummary(criteria).includes('не менее 10'));
options.minimum=99;
assert.equal(criteria.source_minimum_visits,10);
const partial=context.buildUpsellCriteria(catalog,{...options,minimum:5,maximum:2,services:['Cut A']},'service','21');
assert.equal(partial.source_all_services,false);
assert.equal(partial.target_category_maximum_visits_exclusive,2);
assert(context.upsellCriteriaSummary(partial).includes('выбранные услуги'));
assert(context.upsellCriteriaSummary(partial).includes('менее 2 визитов'));
const long=JSON.parse(JSON.stringify(criteria));long.source_category.title='Long category '.repeat(20);long.target.title='Long target '.repeat(20);
assert(context.upsellSuggestedName(long,100,'2026-11-19').length<=100);
assert(context.upsellSuggestedName(long,100,'2026-11-19').includes('≥10'));
context.language='en';
assert(context.upsellSuggestedName(criteria,100,'2026-11-19').startsWith('Loyal: Haircuts'));
assert(context.upsellCriteriaSummary(null).includes('not saved'));
console.log('PASS: exact thresholds, zero target visits, selected services, nested category condition, frozen criteria, English labels and CRM name length.');
