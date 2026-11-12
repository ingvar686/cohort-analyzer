const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const MonthlyBudgetModel = require('../dashboards/monthly-budgets.js');

const book = new MonthlyBudgetModel({Instagram: 1500});
assert.equal(book.month('Instagram', '2026-05'), null);
assert.equal(book.setMonth('Instagram', '2026-05', 500), 1500);
assert.equal(book.unallocated('Instagram'), 1000);
assert.equal(book.setMonth('Instagram', '2026-06', 300), 1500);
assert.equal(book.unallocated('Instagram'), 700);
assert.equal(book.setUnallocated('Instagram', 0), 800);
assert.equal(book.setMonth('Instagram', '2026-05', 600), 900);
assert.equal(book.setMonth('Instagram', '2026-05', 400), 700);
book.setMonth('Instagram', '2026-07', 0);
assert.equal(book.month('Instagram', '2026-07'), 0);
book.setMonth('Instagram', '2026-07', '');
assert.equal(book.month('Instagram', '2026-07'), null);
assert.throws(() => book.setMonth('Instagram', '2026-05', -5), RangeError);
assert.throws(() => book.setMonth('Instagram', '2026-13', 5), RangeError);
assert.equal(book.total('Instagram'), 700);
const restored = new MonthlyBudgetModel({Instagram: 1500}, JSON.parse(JSON.stringify(book)));
assert.equal(restored.total('Instagram'), 700);
assert.equal(restored.month('Instagram', '2026-05'), 400);
assert.equal(new MonthlyBudgetModel({Instagram: 123}).total('Instagram'), 123);
const decimals = new MonthlyBudgetModel();
decimals.setMonth('A', '2026-01', 0.1); decimals.setMonth('A', '2026-02', 0.2);
assert.equal(decimals.total('A'), 0.3);

const html = fs.readFileSync(require.resolve('../dashboards/index.html'), 'utf8');
const inline = html.slice(html.indexOf('<script>') + 8, html.lastIndexOf('</script>'));
new vm.Script(inline);
const context = vm.createContext({language: 'ru', DB: {as_of: '2026-11-12'}});
const functions = ['monthDistance', 'youngestAge', 'seriesLimit', 'cumulativeSeries', 'paybackOf'];
for (const name of functions) {
  const line = inline.split('\n').find(l => l.startsWith(`function ${name}(`));
  assert.ok(line, name); vm.runInContext(line, context);
}
vm.runInContext(fs.readFileSync(require.resolve('../dashboards/campaign-comparison.js'), 'utf8'), context);
const visits = [
  {appointment_id: 1, date: '2026-05-01', age: 0, revenue: 60},
  {appointment_id: 2, date: '2026-05-15', age: 0, revenue: 40},
  {appointment_id: 3, date: '2026-06-10', age: 1, revenue: 30}
];
const clients = [{first_visit: '2026-05-01', visits}, {first_visit: '2026-05-03', visits: [{appointment_id: 4, age: 0, revenue: 50}]}];
const stats = context.statsForClients(clients, 'Instagram', 500, 'Instagram');
assert.equal(stats.clients, 2); assert.equal(stats.revenue, 180);
assert.equal(stats.m0, 150); assert.equal(stats.ltv, 90); assert.equal(stats.cac, 250);
assert.equal(stats.repeatRate, 50); assert.equal(stats.profit, -320); assert.equal(stats.roi, -64);
assert.equal(context.statsForClients(clients, 'A', null, 'A').cac, null);
assert.equal(context.statsForClients(clients, 'A', null, 'A').profit, null);
assert.equal(context.statsForClients(clients, 'A', 0, 'A').cac, 0);
assert.equal(context.statsForClients(clients, 'A', 0, 'A').paybackState, 'no_cost');
assert.equal(context.repeatClientCount([{visits: [visits[0], {...visits[0]}]}]), 0);
assert.equal(context.repeatClientCount([{visits: visits.slice(0, 2)}]), 1);
// A return later than M5 can now pay back the acquisition budget.
const late = context.paybackOf([{first_visit: '2026-01-01', visits: [{age: 0, revenue: 10}, {age: 6, revenue: 90}]}], 100);
assert.equal(late.payback, 6); assert.equal(late.state, 'yes');
console.log('Passed: budget migration, totals, persistence, zero/unknown spend, same-month repeat visits, and payback beyond M5.');
