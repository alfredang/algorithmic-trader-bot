/* Page components (part 2): research, trading, analytics, agents, integrations, settings, help. */
/* global Alpine, marked */
(function () {
  const Q = window.QTS;

  /* ------------------------------------------------------------------ research */
  window.researchPage = function () {
    const q = Q.query();
    return {
      sub: Q.parseHash().sub || 'hypothesis', strategies: [], runs: [], res: null, busy: false, grids: {}, hsignals: {}, QTS: Q,
      hyp: { symbol: q.symbol || 'SPY', type: 'losing_streak', params: { n: 3 }, horizon: 1, alpha: 0.05, min_edge_bps: 3,
        h1: 'Mean next-day return after >= 3 consecutive down closes is HIGHER than on all other days',
        h0: 'Mean next-day return after >= 3 consecutive down closes EQUALS the mean on all other days' },
      grid: { strategy_key: q.strategy || 'sma_cross', symbol: q.symbol || 'SPY', split_date: '2021-12-31', costs: 'alpaca_retail', gridText: '' },
      wf: { strategy_key: q.strategy || 'sma_cross', symbol: q.symbol || 'SPY', train_bars: 756, test_bars: 252 },
      ab: { a: q.a || 'trend_filter', b: q.b || 'dip_buy', aParams: '{}', bParams: '{}', symbol: q.symbol || 'SPY', alpha: 0.05, tried: 20 },
      rg: { symbol: q.symbol || 'SPY', clusters: 3, base: 'ema_cross' },
      dg: { strategy_key: q.strategy || 'custom_lab18_biased_smoothed_momentum', symbol: q.symbol || 'SPY', trials: 76 },
      pr: { pairs: 'KO/PEP, JPM/BAC, XLF/JPM, SPY/QQQ, GLD/TLT', formation_end: '2022-12-31' },
      ml: { symbol: q.symbol || 'SPY', threshold: 0.55 }, ex: { symbol: q.symbol || 'SPY', day: '', side: 'buy', qty: 50000, participation: 0.1, impact_coef: 0.1 },
      kinds: { hypothesis: 'hypothesis', grid: 'grid', walkforward: 'walk_forward', abtest: 'abtest', regime: 'regime', diagnostics: 'diagnostics', pairs: 'pairs', ml: 'ml', execution: 'execution' },
      async init() {
        [this.strategies, this.grids, this.hsignals] = await Promise.all([Q.get('/api/strategies'), Q.get('/api/research/grids'), Q.get('/api/research/hypothesis/signals')]);
        this.setGridText();
        await this.loadRuns();
        if (q.id) this.open(parseInt(q.id, 10));
        Q.on('route', async (r) => { this.sub = r.sub || 'hypothesis'; this.res = null; await this.loadRuns(); if (r.params.id) this.open(parseInt(r.params.id, 10)); });
      },
      get signalStrategies() { return this.strategies.filter((s) => !s.multi_asset && !['execution', 'market_making'].includes(s.kind)); },
      setGridText() { this.grid.gridText = JSON.stringify(this.grids[this.grid.strategy_key] || {}, null, 0); },
      setHypType(t) { this.hyp.type = t; this.hyp.params = { ...(this.hsignals[t] || {}) }; },
      async loadRuns() { this.runs = await Q.get('/api/research?kind=' + this.kinds[this.sub] + '&limit=20', true); },
      async open(id) { this.res = await Q.get('/api/research/' + id); this.$nextTick(() => this.draw()); },
      async go(path, body) {
        this.busy = true;
        try { this.res = await Q.post('/api/research/' + path, body); await this.loadRuns(); this.$nextTick(() => this.draw()); Q.toast(`${this.res.kind} run #${this.res.id} done in ${this.res.duration_ms} ms`, 'ok'); }
        finally { this.busy = false; }
      },
      runHyp() { this.go('hypothesis', { symbol: this.hyp.symbol, signal: { type: this.hyp.type, ...this.hyp.params }, horizon: this.hyp.horizon, alpha: this.hyp.alpha, min_edge_bps: this.hyp.min_edge_bps, h0: this.hyp.h0, h1: this.hyp.h1 }); },
      runGrid() { let g; try { g = JSON.parse(this.grid.gridText); } catch (e) { Q.toast('Grid must be valid JSON', 'error'); return; } this.go('grid', { strategy_key: this.grid.strategy_key, symbol: this.grid.symbol, split_date: this.grid.split_date, grid: g, config: { costs: this.grid.costs } }); },
      runWF() { this.go('walk-forward', { ...this.wf, grid: this.grids[this.wf.strategy_key] }); },
      runAB() { let ap, bp; try { ap = JSON.parse(this.ab.aParams || '{}'); bp = JSON.parse(this.ab.bParams || '{}'); } catch (e) { Q.toast('Params must be JSON', 'error'); return; }
        this.go('abtest', { a: { strategy_key: this.ab.a, params: ap }, b: { strategy_key: this.ab.b, params: bp }, symbol: this.ab.symbol, alpha: this.ab.alpha, tried: this.ab.tried }); },
      runRegime() { this.go('regime', this.rg); },
      runDiag() { this.go('diagnostics', this.dg); },
      runPairs() { this.go('pairs', { pairs: this.pr.pairs.split(',').map((p) => p.trim().toUpperCase().split('/')).filter((p) => p.length === 2), formation_end: this.pr.formation_end }); },
      runML() { this.go('ml', this.ml); },
      runExec() { this.go('execution', { ...this.ex, day: this.ex.day || null }); },
      heatColor(v, lo = -0.5, hi = 1.5) { if (v === null || v === undefined) return 'transparent'; const t = Math.max(0, Math.min(1, (v - lo) / (hi - lo))); return t >= 0.5 ? `rgba(16,185,129,${(t - 0.5) * 1.6 + 0.1})` : `rgba(239,68,68,${(0.5 - t) * 1.6 + 0.1})`; },
      draw() {
        const r = this.res && this.res.result; if (!r) return;
        const k = this.res.kind;
        if (k === 'walk_forward') Q.lineChart(this.$refs.c1, [{ label: 'Walk-forward OOS (stitched)', data: r.equity, color: '#1f4e79' }, { label: 'Buy & hold', data: r.benchmark, color: '#e87122' }], { fmt: (v) => Q.usd(v) });
        if (k === 'abtest') {
          Q.lineChart(this.$refs.c1, [{ label: 'A: ' + r.a.strategy, data: r.equity_a, color: '#1f4e79' }, { label: 'B: ' + r.b.strategy, data: r.equity_b, color: '#e87122' }], { fmt: (v) => Q.usd(v) });
          const h = r.bootstrap_hist; const mids = h.edges.slice(0, -1).map((e, i) => ((e + h.edges[i + 1]) / 2).toFixed(2));
          Q.barChart(this.$refs.c2, mids, [{ label: 'Bootstrap Sharpe(A) - Sharpe(B)', data: h.counts, colors: mids.map((m) => (parseFloat(m) >= r.ci[0] && parseFloat(m) <= r.ci[1] ? '#2f6db5' : '#cbd5e1')) }]);
        }
        if (k === 'regime') {
          Q.lineChart(this.$refs.c1, [{ label: 'Gated', data: r.equity_gated, color: '#10b981' }, { label: 'Ungated', data: r.equity_ungated, color: '#1f4e79' }, { label: 'Buy & hold', data: r.equity_bh, color: '#e87122' }], { fmt: (v) => Q.usd(v) });
          Q.barChart(this.$refs.c2, r.pca.explained_variance.map((_, i) => 'PC' + (i + 1)), [{ label: 'Explained variance', data: r.pca.explained_variance }], { fmt: (v) => Q.pct(v, 0) });
        }
        if (k === 'diagnostics') {
          const ov = (r.checks.find((c) => c.check.startsWith('4')) || {}).detail;
          if (ov) Q.scatterChart(this.$refs.c1, [{ label: 'skill-free random strategies', data: ov.random_is.map((x, i) => ({ x, y: ov.random_oos[i] })), color: 'rgba(100,116,139,.5)' },
            { label: r.name, data: [{ x: ov.strategy[0], y: ov.strategy[1] }], color: '#e87122', r: 7 }], { x: 'In-sample Sharpe', y: 'Out-of-sample Sharpe' });
        }
        if (k === 'ml') Q.barChart(this.$refs.c1, Object.keys(r.importance).slice(0, 14), [{ label: 'Random-forest feature importance', data: Object.values(r.importance).slice(0, 14) }], { horizontal: true });
        if (k === 'execution') {
          const algos = Object.keys(r.detail);
          Q.lineChart(this.$refs.c1, algos.map((a, i) => ({ label: a.toUpperCase() + ' fill price', data: r.detail[a].map((c) => [c.time, c.price]), color: Q.palette[i] })), { timeLen: 16 });
        }
      },
      segColor(rg) { return { 'Low vol': '#10b981', 'Moderate vol': '#f59e0b', 'High vol (stress)': '#ef4444' }[rg] || '#94a3b8'; },
    };
  };

  /* ------------------------------------------------------------------ paper trading */
  window.tradingPage = function () {
    const q = Q.query();
    return {
      tab: q.tab || 'bots', bots: [], orders: [], positions: [], accounts: [], fills: [], strategies: [], sel: null, cmp: null, clock: {}, QTS: Q,
      showNew: q.new === '1', expanded: {}, orderFilter: 'all',
      nb: { name: '', strategy_key: q.strategy || 'ema_cross', symbols: q.symbols || 'SPY', params: {}, schedule: 'every 10s', broker: 'sim', data_mode: 'replay',
        replay_start: '2025-01-02', pct: 0.95, max_position_pct: 0.95, max_order_value: 100000, max_daily_loss_pct: 0.02, long_only: true, extended_hours: true },
      ticket: { symbol: q.symbol || 'SPY', side: 'buy', qty: 10, type: 'auto', time_in_force: 'day', limit_price: '', stop_price: '', take_profit: '', stop_loss: '', extended_hours: false, order_class: 'simple', account: 'Default paper account', session_override: '' },
      ticketRes: null,
      async init() {
        this.strategies = (await Q.get('/api/strategies')).filter((s) => !['execution', 'market_making'].includes(s.kind));
        if (q.params) { try { this.nb.params = JSON.parse(q.params); } catch (e) { /* */ } }
        this.pickStrategy(this.nb.strategy_key, !!q.params);
        await this.load();
        if (q.bot) this.select(this.bots.find((b) => b.id === parseInt(q.bot, 10)));
        else if (this.bots.length && !this.showNew) this.select(this.bots[0]);
        ['bot.cycle', 'bot.status', 'order.new', 'order.status', 'order.filled', 'bot.error'].forEach((k) => Q.on(k, () => { clearTimeout(this._t); this._t = setTimeout(() => this.load(true), 400); }));
        Q.on('route', (r) => { if (r.params.tab) this.tab = r.params.tab; if (r.params.bot) this.select(this.bots.find((b) => b.id === parseInt(r.params.bot, 10))); });
      },
      async load(quiet) {
        const [b, o, p, a, c] = await Promise.all([Q.get('/api/bots', quiet), Q.get('/api/orders?limit=200', quiet), Q.get('/api/positions', quiet), Q.get('/api/accounts', quiet), Q.get('/api/clock', true)]);
        Object.assign(this, { bots: b, orders: o, positions: p, accounts: a, clock: c });
        if (this.sel) { this.sel = this.bots.find((x) => x.id === this.sel.id) || null; if (this.sel) this.drawBot(); }
      },
      get filteredOrders() { return this.orders.filter((o) => this.orderFilter === 'all' || (this.orderFilter === 'open' ? ['new', 'accepted', 'held', 'partially_filled'].includes(o.status) : o.source === this.orderFilter)); },
      pickStrategy(k, keepParams) {
        this.nb.strategy_key = k; const d = this.strategies.find((s) => s.key === k); if (!d) return;
        if (!keepParams) this.nb.params = Q.paramForm(d.params_schema, {}); else this.nb.params = Q.paramForm(d.params_schema, this.nb.params);
        if (!this.nb.name) this.nb.name = d.name + ' bot';
        if (d.multi_asset && !q.symbols) this.nb.symbols = d.default_symbols.join(',');
      },
      get nbDesc() { return this.strategies.find((s) => s.key === this.nb.strategy_key); },
      async createBot() {
        const d = this.nbDesc;
        const body = { name: this.nb.name, strategy_key: this.nb.strategy_key, params: Q.coerce(d.params_schema, this.nb.params), symbols: Q.symbolsFrom(this.nb.symbols),
          schedule: this.nb.schedule, broker: this.nb.broker, data_mode: this.nb.data_mode, replay_start: this.nb.replay_start, extended_hours: this.nb.extended_hours,
          sizing: { mode: 'percent_equity', pct: this.nb.pct }, risk: { max_position_pct: this.nb.max_position_pct, max_order_value: this.nb.max_order_value, max_daily_loss_pct: this.nb.max_daily_loss_pct, long_only: this.nb.long_only } };
        const b = await Q.post('/api/bots', body);
        Q.toast(`Bot "${b.name}" created - press Start`, 'ok'); this.showNew = false; await this.load(); this.select(this.bots.find((x) => x.id === b.id));
      },
      async act(b, action) {
        if (action === 'kill' && !confirm(`Kill switch for "${b.name}"? It halts the bot and cancels its open orders.`)) return;
        if (action === 'reset' && !confirm('Reset this bot to a fresh $100,000 simulator account and restart the replay? (old orders stay in the audit trail)')) return;
        const r = await Q.post(`/api/bots/${b.id}/${action}`);
        if (action === 'run-now') Q.toast(r.result.message || r.result.status, r.result.status === 'error' ? 'error' : 'ok');
        await this.load(true);
      },
      async select(b) { if (!b) return; this.sel = b; this.cmp = null; this.$nextTick(() => this.drawBot()); },
      async drawBot() {
        if (!this.sel || this.tab !== 'bots') return;
        const eq = await Q.get(`/api/bots/${this.sel.id}/equity`, true);
        if (this.$refs.beq) Q.lineChart(this.$refs.beq, [{ label: 'Bot equity (forward test)', data: eq.map((e) => [e.t, e.equity]), color: '#1f4e79' }], { fmt: (v) => Q.usd(v), timeLen: 16 });
        this.fills = await Q.get(`/api/fills?bot_id=${this.sel.id}&limit=50`, true);
      },
      async compare() {
        this.cmp = await Q.get(`/api/bots/${this.sel.id}/compare`);
        if (this.cmp.ready) this.$nextTick(() => Q.lineChart(this.$refs.bcmp, [{ label: 'Forward test (paper)', data: this.cmp.forward, color: '#1f4e79' }, { label: 'Backtest, same bars', data: this.cmp.backtest, color: '#e87122', dashed: true }], { fmt: (v) => Q.usd(v) }));
      },
      async place() {
        const t = { ...this.ticket };
        ['limit_price', 'stop_price', 'take_profit', 'stop_loss'].forEach((k) => { t[k] = t[k] === '' ? null : parseFloat(t[k]); });
        if (!t.session_override) t.session_override = null;
        if (t.take_profit && t.stop_loss) t.order_class = 'bracket';
        this.ticketRes = await Q.post('/api/orders', t);
        Q.toast(this.ticketRes.ok ? `Order ${this.ticketRes.order.status}: ${this.ticketRes.order.type} ${this.ticketRes.order.time_in_force}${this.ticketRes.order.extended_hours ? ' extended-hours' : ''}` : 'Blocked: ' + this.ticketRes.risk.reason, this.ticketRes.ok ? 'ok' : 'error');
        this.load(true);
      },
      async cancel(o) { await Q.post(`/api/orders/${o.id}/cancel`); this.load(true); },
      async processOrders() { const r = await Q.post('/api/orders/process' + (this.ticket.session_override ? '?session_override=' + this.ticket.session_override : '')); Q.toast(r.filled + ' working order(s) filled', 'ok'); this.load(true); },
      setTab(t) { this.tab = t; if (t === 'bots') this.$nextTick(() => this.drawBot()); },
      acctName(id) { const a = this.accounts.find((x) => x.id === id); return a ? a.name : id; },
    };
  };

  /* ------------------------------------------------------------------ analytics */
  window.analyticsPage = function () {
    const q = Q.query();
    return {
      list: [], bots: [], bt: null, selId: q.backtest ? parseInt(q.backtest, 10) : null, cmpIds: [], cmp: [], botId: q.bot ? parseInt(q.bot, 10) : null, botCmp: null, QTS: Q,
      keys: ['total_return', 'cagr', 'volatility', 'sharpe', 'sortino', 'calmar', 'max_drawdown', 'max_dd_duration', 'win_rate', 'profit_factor', 'expectancy', 'avg_win', 'avg_loss', 'trades', 'exposure', 'turnover', 'alpha', 'beta', 'information_ratio', 'total_costs', 'break_even_bps'],
      q: '', fStrat: '', folded: (() => { try { return JSON.parse(localStorage.getItem('qts.runs.folded')) || {}; } catch (e) { return {}; } })(),
      async init() {
        [this.list, this.bots] = await Promise.all([this.fetchList(), Q.get('/api/bots')]);
        if (!this.selId && this.list.length) this.selId = this.list[0].id;
        if (this.selId) this.load();
        if (this.botId) this.loadBot();
        Q.on('theme', () => this.draw());
      },
      async fetchList() {
        return (await Q.get('/api/backtests?limit=500')).filter((b) => b.status === 'done' && !['execution', 'market_making'].includes(b.kind));
      },
      settings(b) { return Object.entries(b.params || {}).map(([k, v]) => k.replace(/_/g, ' ') + ' ' + v).join(', ') || 'defaults'; },
      get strategyKeys() { return [...new Set(this.list.map((b) => b.strategy_key))].sort(); },
      get shown() {
        const words = this.q.toLowerCase().split(/\s+/).filter(Boolean);
        return this.list.filter((b) => (!this.fStrat || b.strategy_key === this.fStrat) && words.every((w) => {
          const hay = ['#' + b.id, b.name, b.strategy_key, (b.symbols || []).join(' '), this.settings(b)].join(' ').toLowerCase();
          return hay.includes(w) || ('#' + b.id) === w || String(b.id) === w;
        }));
      },
      // the learner's own runs on top, then the course samples - both newest first
      get groups() {
        const rows = [...this.shown].sort((a, b) => b.id - a.id);
        return [{ title: 'Your runs (newest first)', rows: rows.filter((b) => !b.sample) },
                { title: 'Course samples', rows: rows.filter((b) => b.sample) }];
      },
      get mine() { return this.list.filter((b) => !b.sample); },
      get selRow() { return this.list.find((b) => b.id === this.selId); },
      optLabel(b) { return `#${b.id} ${b.name} · ${this.settings(b)}`; },
      get ticked() { return this.cmpIds; },
      get tickedMine() { return this.list.filter((b) => !b.sample && this.cmpIds.includes(b.id)); },
      pick(id) { this.selId = id; this.load(); },
      fold(t) { this.folded = { ...this.folded, [t]: !this.folded[t] }; try { localStorage.setItem('qts.runs.folded', JSON.stringify(this.folded)); } catch (e) { /* private window */ } },
      async deleteRuns(body, msg) {
        if (!confirm(msg + '\nThe course sample runs are always kept. This cannot be undone.')) return;
        const r = await Q.post('/api/backtests/delete', body);
        Q.toast(`Deleted ${r.deleted.length} run${r.deleted.length === 1 ? '' : 's'}`, 'ok');
        this.cmpIds = this.cmpIds.filter((id) => !r.deleted.includes(id));
        this.cmp = this.cmp.filter((c) => !r.deleted.includes(c.id));
        this.list = await this.fetchList();
        if (r.deleted.includes(this.selId)) {
          const first = this.list.find((b) => b.sample) || this.list[0];
          this.selId = first ? first.id : null; this.bt = null;
          if (this.selId) this.load();
        }
      },
      removeOne(b) { return this.deleteRuns({ ids: [b.id] }, `Delete run #${b.id} ${b.name} (${this.settings(b)})?`); },
      removeTicked() { return this.deleteRuns({ ids: this.tickedMine.map((b) => b.id) }, `Delete the ${this.tickedMine.length} ticked run(s)?`); },
      clearMine() { return this.deleteRuns({ all: true }, `Delete all ${this.mine.length} of your runs?`); },
      async load() { this.bt = await Q.get('/api/backtests/' + this.selId); this.$nextTick(() => this.draw()); },
      draw() {
        const r = this.bt; if (!r || !r.series) return;
        Q.lineChart(this.$refs.eq, [{ label: 'Strategy (net)', data: r.series.equity, color: '#1f4e79', width: 2 }, { label: r.benchmark + ' buy & hold', data: r.series.benchmark || [], color: '#e87122' }], { fmt: (v) => Q.usd(v) });
        Q.lineChart(this.$refs.dd, [{ label: 'Drawdown', data: r.series.drawdown, color: '#ef4444', fill: true }], { fmt: (v) => Q.pct(v, 0) });
        Q.lineChart(this.$refs.roll, [{ label: 'Rolling Sharpe', data: r.series.rolling_sharpe, color: '#8b5cf6' }]);
      },
      toggleCmp(id) { const i = this.cmpIds.indexOf(id); if (i >= 0) this.cmpIds.splice(i, 1); else this.cmpIds.push(id); },
      async compare() {
        if (this.cmpIds.length < 2 || this.cmpIds.length > 5) { Q.toast('Tick 2-5 runs to compare', 'error'); return; }
        this.cmp = await Q.get('/api/backtests/compare?ids=' + this.cmpIds.join(','));
        this.$nextTick(() => {
          Q.lineChart(this.$refs.cmp, this.cmp.map((c, i) => { const base = (c.equity[0] || [0, 1])[1] || 1; return { label: '#' + c.id + ' ' + c.name, data: c.equity.map((p) => [p[0], p[1] / base * 100]), color: Q.palette[i] }; }), { fmt: (v) => Q.num(v, 0) });
        });
      },
      async loadBot() {
        if (!this.botId) return;
        this.botCmp = await Q.get(`/api/bots/${this.botId}/compare`);
        if (this.botCmp.ready) this.$nextTick(() => Q.lineChart(this.$refs.botc, [{ label: 'Forward test', data: this.botCmp.forward, color: '#1f4e79' }, { label: 'Backtest, same bars', data: this.botCmp.backtest, color: '#e87122', dashed: true }], { fmt: (v) => Q.usd(v) }));
      },
      heat() { return this.bt && this.bt.series ? Q.heatmap(this.bt.series.monthly) : ''; },
    };
  };

  /* ------------------------------------------------------------------ AI agents */
  // the agent flow: one column per desk stage, in the order the orchestrator runs them
  const FLOW = [['Analysts', [['technical_analyst', 'Technical'], ['sentiment_analyst', 'Sentiment'], ['fundamental_analyst', 'Fundamental']]],
    ['Debate ×2', [['bull_researcher', 'Bull'], ['bear_researcher', 'Bear']]], ['Decide', [['trader', 'Trader']]],
    ['Review', [['risk_manager', 'Risk mgr']]], ['Gate', [['risk_limits', 'Hard limits']]],
    ['Final call', [['portfolio_manager', 'PM']]], ['Human', [['human', 'Approval']]]];
  const FLOW_KEYS = FLOW.flatMap((c) => c[1].map((n) => n[0])).filter((k) => k !== 'human');
  window.agentsPage = function () {
    const q = Q.query();
    return {
      prov: { providers: [] }, roles: { roles: [], taxonomy: {}, risks: [], systems: [] }, runs: [], run: null, symbols: 'NVDA, AAPL, SPY', provider: '', orchestration: 'native',
      busy: false, limits: {}, ao: {}, memory: [], symSel: null, tab: 'desk', QTS: Q, live: null, FLOW,
      async init() {
        [this.prov, this.roles, this.runs, this.limits, this.ao, this.memory] = await Promise.all([Q.get('/api/agents/providers'), Q.get('/api/agents/roles'),
          Q.get('/api/agents/runs'), Q.get('/api/agents/limits'), Q.get('/api/agents/always-on'), Q.get('/api/agents/memory?limit=30')]);
        const id = q.run || (this.runs[0] && this.runs[0].id); if (id) this.open(id);
        ['agents.run', 'agents.approved', 'agents.rejected'].forEach((k) => Q.on(k, async () => { this.runs = await Q.get('/api/agents/runs', true); }));
      },
      async open(id) { this.run = await Q.get('/api/agents/runs/' + id); this.symSel = this.run.symbols[0]; },
      async go() {
        this.busy = true;
        const id = this.watch();
        try {
          this.run = await Q.post('/api/agents/run', { symbols: Q.symbolsFrom(this.symbols), provider: this.provider || null, orchestration: this.orchestration, live_id: id });
          this.symSel = this.run.symbols[0]; this.runs = await Q.get('/api/agents/runs'); this.memory = await Q.get('/api/agents/memory?limit=30');
          Q.toast(`Desk run #${this.run.id}: ${this.run.status} (${this.run.agents} agent calls)`, 'ok');
        } finally { this.busy = false; this.unwatch(); }
      },
      // poll the desk's live progress while the (long) run request is still open
      watch() {
        this.unwatch();
        const id = 'd' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
        const tick = async () => {
          try { const l = await Q.get('/api/agents/live/' + id, true); if (this._poll) { this.live = l; if (l.current) this.symSel = l.current; } } catch (e) { /* run not started yet */ }
        };
        this._poll = setInterval(tick, 700); tick();
        return id;
      },
      unwatch() { clearInterval(this._poll); this._poll = null; this.live = null; },
      // one shape for both views: the live progress, or a finished run rebuilt from its trace
      get flow() {
        if (this.live) {
          const l = this.live;
          return { live: true, title: 'running · ' + l.provider, ms: l.elapsed_ms, current: l.current,
            rows: l.symbols.map((s) => ({ symbol: s, nodes: { ...l.nodes[s], human: { state: 'waiting' } } })) };
        }
        if (!this.run) return null;
        const r = this.run;
        return { live: false, title: 'run #' + r.id + ' · ' + r.provider, ms: r.duration_ms, current: null,
          rows: r.symbols.map((s) => {
            const nodes = {}; FLOW_KEYS.forEach((k) => { nodes[k] = { state: 'skipped' }; });
            (r.trace || []).filter((t) => t.symbol === s).forEach((t) => {
              if (t.agent === 'orchestrator' && t.title === 'Data') FLOW_KEYS.forEach((k) => { nodes[k].error = t.error; });
              if (!nodes[t.agent]) return;
              nodes[t.agent] = { state: (t.brain || '').startsWith('rules (fallback') ? 'fallback' : 'done', brain: t.brain, ms: t.ms, round: t.round, output: t.output || {}, error: t.error };
            });
            return { symbol: s, nodes: { ...nodes, human: this.humanNode(s) } };
          }) };
      },
      humanNode(s) {
        const r = this.run, p = (r.proposals || []).find((x) => x.symbol === s);
        if (!p) return { state: 'idle', text: 'no order' };
        if (r.status === 'proposed') return { state: 'human', text: 'awaiting you' };
        if (r.status === 'rejected') return { state: 'blocked', text: (r.approved_by ? 'rejected' : 'blocked') };
        const o = (r.orders || []).find((x) => x.symbol === s);
        return o && o.ok ? { state: 'done', text: p.side + ' ' + p.qty + ' sent' } : { state: 'blocked', text: o ? 'order blocked' : r.status };
      },
      flowProgress(f) {
        const all = f.rows.length * FLOW_KEYS.length;
        const done = f.rows.reduce((a, row) => a + FLOW_KEYS.filter((k) => ['done', 'fallback'].includes(row.nodes[k].state)).length, 0);
        return { done, all, pct: all ? Math.round(100 * done / all) : 0 };
      },
      rowState(f, row) {
        if (f.current === row.symbol) return 'running';
        const st = FLOW_KEYS.map((k) => row.nodes[k].state);
        if (st.every((x) => ['done', 'fallback'].includes(x))) return 'done';
        if (st.some((x) => x === 'skipped')) return 'no data';
        return 'waiting';
      },
      nodeClass(key, n) {
        if (key === 'risk_limits' && n.state === 'done') return (n.output || {}).decision === 'REJECTED' ? 'af-blocked' : 'af-code';
        return 'af-' + n.state;
      },
      nodeText(key, n) {
        if (n.text) return n.text;
        const o = n.output || {}, sec = (ms) => (ms / 1000).toFixed(1) + 's';
        if (n.state === 'waiting') return 'waiting';
        if (n.state === 'skipped') return n.error ? 'skipped - no data' : 'skipped';
        if (n.state === 'running') return (['bull_researcher', 'bear_researcher'].includes(key) ? 'r' + (n.round || 1) + ' · ' : '') + sec(n.ms || 0);
        if (o.score !== undefined) return (o.score > 0 ? '+' : '') + Q.num(o.score);
        if (o.conviction !== undefined) return 'conv ' + Q.num(o.conviction);
        if (o.action) return o.action.toUpperCase() + ' ' + Q.num(o.confidence);
        if (key === 'risk_limits') return ({ APPROVED: 'pass', REJECTED: 'blocked', 'NO TRADE': 'no trade' }[o.decision] || o.decision) + (o.qty ? ' · ' + o.qty : '');
        if (o.decision) return o.decision;
        return 'done';
      },
      nodeTip(n, x) {
        const o = x.output || {};
        return [n[1], x.state, x.brain, x.ms ? (x.ms / 1000).toFixed(1) + ' s' : '', o.summary || o.rationale || (o.notes || []).join('; '), x.error].filter(Boolean).join(' · ');
      },
      colLit(row, ci) { return FLOW[ci][1].every((n) => ['done', 'fallback'].includes((row.nodes[n[0]] || {}).state)); },
      async decide(action) {
        if (action === 'approve' && !confirm('Send the approved proposals as PAPER orders? (Hard risk limits are applied again at order time.)')) return;
        this.run = await Q.post(`/api/agents/runs/${this.run.id}/${action}`); this.runs = await Q.get('/api/agents/runs');
        Q.toast(action === 'approve' ? 'Approved - paper orders sent' : 'Rejected', action === 'approve' ? 'ok' : 'info');
      },
      traceFor(sym) { return (this.run && this.run.trace || []).filter((t) => t.symbol === sym); },
      out(t) { return t.output || {}; },
      async saveLimits() { this.limits = await Q.put('/api/agents/limits', this.limits); Q.toast('Limits saved', 'ok'); },
      async saveAO() { this.ao = await Q.put('/api/agents/always-on', { enabled: this.ao.enabled, interval_min: parseInt(this.ao.interval_min, 10), symbols: Q.symbolsFrom(Array.isArray(this.ao.symbols) ? this.ao.symbols.join(',') : this.ao.symbols), provider: this.ao.provider, refresh_news: this.ao.refresh_news }); Q.toast('Always-on agent ' + (this.ao.enabled ? 'enabled' : 'disabled'), 'ok'); },
      async aoNow() {
        this.busy = true; this.tab = 'desk';
        const id = this.watch();
        try { this.run = await Q.post('/api/agents/always-on/run-now?live_id=' + id); this.symSel = this.run.symbols[0]; this.ao = await Q.get('/api/agents/always-on'); this.memory = await Q.get('/api/agents/memory?limit=30'); } finally { this.busy = false; this.unwatch(); }
      },
      brainBadge(b) { return (b || '').startsWith('rules (fallback') ? 'badge-warn' : (b || '').startsWith('rules') ? 'badge-muted' : (b || '').includes('code') ? 'badge-info' : 'badge-ok'; },
    };
  };

  /* ------------------------------------------------------------------ integrations */
  window.integrationsPage = function () {
    return {
      items: [], results: {}, busy: {}, tpl: null, alerts: [], wh: {}, reveal: false, strategies: [], QTS: Q, origin: location.origin,
      async init() { await this.load(); },
      async load() {
        [this.items, this.tpl, this.alerts, this.strategies] = await Promise.all([Q.get('/api/integrations'), Q.get('/api/webhooks/template'), Q.get('/api/webhooks/alerts?limit=20'), Q.get('/api/strategies')]);
        this.wh = { ...this.tpl.config };
      },
      async test(k) { this.busy[k] = true; try { this.results[k] = await Q.post(`/api/integrations/${k}/test`); if (k === 'tradingview') this.alerts = await Q.get('/api/webhooks/alerts?limit=20'); } finally { this.busy[k] = false; } },
      async toggleReveal() { this.reveal = !this.reveal; this.tpl = await Q.get('/api/webhooks/template?reveal=' + this.reveal); },
      async saveWh() { await Q.put('/api/webhooks/config', { ...this.wh, allowed_symbols: Q.symbolsFrom(Array.isArray(this.wh.allowed_symbols) ? this.wh.allowed_symbols.join(',') : this.wh.allowed_symbols), max_order_qty: parseFloat(this.wh.max_order_qty) }); Q.toast('Webhook settings saved', 'ok'); await this.load(); },
      byKey(k) { return this.items.find((i) => i.key === k); },
      forms: {}, show: {},
      badgeText(it) {
        const r = this.results[it.key];
        if (r) return r.ok ? 'connected' : 'key not working';
        if (!it.configured) return 'not configured';
        return (it.editable && it.editable.length) ? 'key saved - press Test' : 'connected';
      },
      badgeClass(it) {
        const r = this.results[it.key];
        if (r) return r.ok ? 'badge-ok' : 'badge-err';
        return it.configured ? ((it.editable && it.editable.length) ? 'badge-warn' : 'badge-ok') : 'badge-muted';
      },
      form(k) { return (this.forms[k] = this.forms[k] || {}); },
      async saveKeys(it) {
        const values = {};
        for (const f of it.editable) { const v = (this.form(it.key)[f.name] || '').trim(); if (v) values[f.name] = v; }
        if (!Object.keys(values).length) { Q.toast('Paste a key first', 'error'); return; }
        this.busy[it.key] = true;
        try {
          const r = await Q.put(`/api/integrations/${it.key}/keys`, { values });
          this.forms[it.key] = {}; Q.toast(r.message, 'ok');
          this.items = await Q.get('/api/integrations');
          if (this.byKey(it.key) && this.byKey(it.key).testable) await this.test(it.key);
        } finally { this.busy[it.key] = false; }
      },
      async clearKeys(it) {
        const names = it.editable.filter((f) => f.saved_in_app).map((f) => f.name);
        if (!names.length || !confirm('Remove the ' + it.name.split(' (')[0] + ' keys saved in the app?')) return;
        await Q.put(`/api/integrations/${it.key}/keys`, { clear: names });
        Q.toast('Removed', 'ok'); this.results[it.key] = null; this.items = await Q.get('/api/integrations');
      },
    };
  };

  /* ------------------------------------------------------------------ settings */
  window.settingsPage = function () {
    return {
      prefs: {}, env: {}, status: {}, kill: false, seeding: false, QTS: Q,
      async init() { const s = await Q.get('/api/settings'); this.prefs = s.preferences; this.env = s.env; this.status = await Q.get('/api/system/status'); this.kill = (await Q.get('/api/kill-switch')).on; },
      async save() { const s = await Q.put('/api/settings', this.prefs); this.prefs = s.preferences; Q.toast('Settings saved', 'ok');
        if (this.prefs.theme !== 'system') { document.documentElement.classList.toggle('dark', this.prefs.theme === 'dark'); try { localStorage.setItem('qts-theme', this.prefs.theme); } catch (e) { /* */ } } },
      async setKill(on) { await Q.post('/api/kill-switch', { on }); this.kill = on; },
      async seed() { this.seeding = true; try { const r = await Q.post('/api/system/seed'); Q.toast('Seed complete: ' + r.log.length + ' steps', 'ok'); this.status = await Q.get('/api/system/status'); } finally { this.seeding = false; } },
      onboarding() { Alpine.$data(document.body).onboard.open = true; Alpine.$data(document.body).onboard.step = 0; },
    };
  };

  /* ------------------------------------------------------------------ help */
  window.helpPage = function () {
    return {
      g: { metrics: {}, topics: [], algo_explain: {}, algo_classes: [], strategy_families: [], agentic_vs_agents: {} }, tab: Q.query().tab || 'glossary', guide: '', q: '', open: {}, QTS: Q,
      async init() { this.g = await Q.get('/api/glossary'); if (this.tab === 'guide') this.loadGuide(); },
      async loadGuide() { if (this.guide) return; try { const md = await Q.get('/guide.md', true); this.guide = window.marked ? marked.parse(md) : '<pre>' + md + '</pre>'; } catch (e) { this.guide = '<p>User guide not found (docs/USER_GUIDE.md).</p>'; } },
      setTab(t) { this.tab = t; if (t === 'guide') this.loadGuide(); },
      get metricList() { const q = this.q.toLowerCase(); return Object.entries(this.g.metrics).filter(([k, v]) => !q || (k + v.label + v.help).toLowerCase().includes(q)); },
    };
  };
})();
