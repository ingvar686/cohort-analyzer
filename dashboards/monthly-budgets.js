(function (root) {
  'use strict';
  const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  const validMonth = k => /^\d{4}-(0[1-9]|1[0-2])$/.test(k);
  function money(value) {
    const n = Number(value);
    if (!Number.isFinite(n) || n < 0) throw new RangeError('Budget must be a non-negative number');
    return Math.round(n * 100) / 100;
  }
  class MonthlyBudgetModel {
    constructor(aggregates = {}, saved = {}) {
      this.aggregates = aggregates;
      this.campaigns = Object.create(null);
      if (saved?.version !== 1 || !saved.campaigns) return;
      for (const [name, entry] of Object.entries(saved.campaigns)) {
        if (!entry || typeof entry !== 'object') continue;
        try {
          const months = Object.create(null);
          for (const [month, amount] of Object.entries(entry.months || {})) {
            if (validMonth(month) && amount !== null && amount !== '') months[month] = money(amount);
          }
          this.campaigns[name] = {months, unallocated: money(entry.unallocated || 0)};
        } catch { /* Keep malformed saved entries from replacing a valid campaign total. */ }
      }
    }
    isMonthly(name) { return own(this.campaigns, name); }
    month(name, month) {
      const entry = this.campaigns[name];
      return entry && own(entry.months, month) ? entry.months[month] : null;
    }
    months(name) { return Object.keys(this.campaigns[name]?.months || {}).sort(); }
    unallocated(name) {
      return this.isMonthly(name) ? this.campaigns[name].unallocated : money(this.aggregates[name] || 0);
    }
    total(name) {
      if (!this.isMonthly(name)) return money(this.aggregates[name] || 0);
      const entry = this.campaigns[name];
      return (Math.round(entry.unallocated * 100) + Object.values(entry.months).reduce((sum, n) => sum + Math.round(n * 100), 0)) / 100;
    }
    ensure(name) {
      if (!this.isMonthly(name)) this.campaigns[name] = {months: Object.create(null), unallocated: this.total(name)};
      return this.campaigns[name];
    }
    setMonth(name, month, value) {
      if (!validMonth(month)) throw new RangeError('Invalid acquisition month');
      const next = value === '' || value === null ? null : money(value);
      const entry = this.ensure(name), previous = entry.months[month] || 0;
      // First allocations consume the legacy aggregate rather than counting it twice.
      if (next !== null && next > previous) entry.unallocated = money(Math.max(0, entry.unallocated - next + previous));
      if (next === null) delete entry.months[month]; else entry.months[month] = next;
      return this.total(name);
    }
    setUnallocated(name, value) { this.ensure(name).unallocated = money(value); return this.total(name); }
    toJSON() { return {version: 1, campaigns: this.campaigns}; }
  }
  root.MonthlyBudgetModel = MonthlyBudgetModel;
  if (typeof module === 'object' && module.exports) module.exports = MonthlyBudgetModel;
})(globalThis);
