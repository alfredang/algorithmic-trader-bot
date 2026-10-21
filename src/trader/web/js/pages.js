/* Page components (part 1): pipeline, dashboard, labs, data, strategies, builder, backtest. */
/* global Alpine, CodeMirror */
(function () {
  const Q = window.QTS;
  const DOT = { ok: 'bg-emerald-500', running: 'bg-blue-500', warning: 'bg-amber-500', error: 'bg-red-500', idle: 'bg-slate-400' };

  function figuresFor(n) {
    const m = n.metrics || {}; const p = Q.pct; const f = Q.num;
    switch (n.key) {
      case 'ingestion': return [`<b>${Q.int(m.bars_cached)}</b> bars · <b>${m.instruments || 0}</b> symbols`, `source: ${m.source}`];
      case 'quality': return [`OK <b>${m.ok || 0}</b> · CHECK <b>${m.check || 0}</b> · FAIL <b>${m.fail || 0}</b>`];
      case 'news': return [`<b>${m.headlines || 0}</b> headlines (${m.real_headlines || 0} real)`];
      case 'features': return [`${m.indicators} indicators · ${m.ml_features} ML features`];
      case 'strategy': return [`<b>${m.built_in}</b> built-in · <b>${m.custom}</b> custom`];
      case 'search': return [`<b>${m.runs || 0}</b> grid / walk-forward / regime runs`];
      case 'backtest': return m.last_id ? [`#${m.last_id} CAGR <b>${p(m.cagr, 1)}</b> · Sharpe <b>${f(m.sharpe)}</b>`, `MaxDD <b>${p(m.max_drawdown, 1)}</b> · ${m.trades} trades`] : ['no backtest yet'];
      case 'abtest': return [`A/B: ${(m.last_ab || '–').split(' - ')[0]}`, `Diag: ${(m.last_diagnostics || '–').split(' - ')[0]}`];
      case 'agents': return [`brain: <b>${m.provider}</b>`, `last: ${m.last_status || '–'} · awaiting approval <b>${m.pending_approval || 0}</b>`];
      case 'risk': return [m.kill_switch ? '<b class="neg">KILL SWITCH ON</b>' : 'kill switch off', `blocked (24h): <b>${m.blocked_today || 0}</b>`];
      case 'forward': return [`bots <b>${m.running}</b>/${m.bots} running · ${m.broker}`, `orders 24h <b>${m.orders_today}</b> · open pos <b>${m.open_positions}</b>`, `P&L <b class="${Q.cls(m.pnl)}">${Q.usd(m.pnl)}</b>`];
      case 'execution': return [`24h: <b>${m.orders_today}</b> orders · ${m.filled_today} filled`, `open ${m.open} · rejected ${m.rejected_today}`];
      case 'analytics': return m.backtest_id ? [`Sharpe <b>${f(m.sharpe)}</b> · Sortino ${f(m.sortino)} · Calmar ${f(m.calmar)}`, `Win ${p(m.win_rate, 0)} · PF ${f(m.profit_factor)} · β ${f(m.beta)}`] : ['–'];
      case 'reporting': return [`<b>${m.tearsheets || 0}</b> tearsheets exported`];
      case 'webhook': return [`<b>${m.alerts || 0}</b> alerts · last HTTP ${m.last_http || '–'}`];
      case 'scheduler': return [`worker: ${m.worker_heartbeat ? 'alive ' + Q.ago(m.worker_heartbeat) : (m.in_process ? 'in-process' : 'not running')}`, `always-on agent: <b>${m.always_on ? 'ON' : 'off'}</b>`];
      default: return [];
    }
  }

  window.pipelinePage = function () {
    return {
      view: Q.query().view || 'pipeline', data: { stages: [] }, main: [], side: [], paths: [], sel: null, events: [], busy: false,
      active: new Set(), activeUntil: 0, strategies: [], lcKey: Q.query().strategy || 'ema_cross', lc: {}, gate: 0.5, timer: null, QTS: Q,
      async init() {
        await this.load();
        Q.on('stage', (d) => this.onStage(d));
        Q.on('route', (r) => { if (r.params.view) this.setView(r.params.view); });
        window.addEventListener('resize', () => this.drawArrows());
        this.timer = setInterval(() => { const v = document.getElementById('view'); if (v && v.contains(this.$el)) this.load(true); else clearInterval(this.timer); }, 20000);
        if (this.view === 'lifecycle') this.setView('lifecycle');
      },
      async load(quiet) {
        try { this.data = await Q.get('/api/pipeline/status', quiet); } catch (e) { return; }
        this.main = this.data.stages.filter((s) => !s.side_input);
        this.side = this.data.stages.filter((s) => s.side_input);
        (this.data.active_path || []).forEach((k) => this.active.add(k));
        if ((this.data.active_path || []).length) this.activeUntil = Date.now() + 8000;
        if (this.sel) { this.sel = this.data.stages.find((s) => s.key === this.sel.key) || this.sel; }
        this.$nextTick(() => this.drawArrows());
      },
      onStage(d) {
        const st = (d.payload || {}).stage; if (!st) return;
        const key = { signals: 'strategy', positions: 'forward' }[st] || st;
        this.active.add(key); this.activeUntil = Date.now() + 8000;
        clearTimeout(this._deb); this._deb = setTimeout(() => this.load(true), 600);
        setTimeout(() => { if (Date.now() > this.activeUntil) { this.active = new Set(); this.drawArrows(); } }, 8500);
      },
      isActive(k) { return Date.now() < this.activeUntil && this.active.has(k); },
      nodeClass(n) { return `st-${n.status} ${n.disabled ? 'disabled' : ''} ${this.isActive(n.key) ? 'active' : ''} ${this.sel && this.sel.key === n.key ? 'selected' : ''}`; },
      dotColor(s) { return DOT[s] || DOT.idle; },
      figures(n) { return figuresFor(n); },
      ago: Q.ago,
      fmtVal(k, v) {
        if (v === null || v === undefined) return '–';
        if (typeof v === 'number') {
          if (['cagr', 'max_drawdown', 'total_return', 'volatility', 'win_rate', 'exposure', 'alpha', 'return'].includes(k)) return Q.pct(v);
          if (Number.isInteger(v)) return String(v);
          return Q.num(v, 3);
        }
        if (typeof v === 'object') return JSON.stringify(v);
        return String(v);
      },
      async select(n) {
        this.sel = n; this.events = [];
        try { this.events = await Q.get('/api/pipeline/events?stage=' + n.key, true); } catch (e) { /* */ }
      },
      openHref(n) {
        const id = n.ref_id;
        if (n.key === 'backtest' && n.metrics.last_id) return '#/backtest?id=' + n.metrics.last_id;
        if (n.key === 'analytics' && n.metrics.backtest_id) return '#/analytics?backtest=' + n.metrics.backtest_id;
        if (n.key === 'forward' && n.ref_type === 'bot' && id) return '#/trading?bot=' + id;
        if (n.key === 'abtest' && n.metrics.diag_id && n.message.startsWith('diagnostics')) return '#/research/diagnostics?id=' + n.metrics.diag_id;
        if (n.key === 'abtest' && n.metrics.ab_id) return '#/research/abtest?id=' + n.metrics.ab_id;
        if (n.key === 'agents' && n.metrics.last_id) return '#/agents?run=' + n.metrics.last_id;
        return '#/' + n.route;
      },
      drawArrows() {
        const wrap = this.$refs.wrap; if (!wrap || this.view !== 'pipeline') return;
        const box = wrap.getBoundingClientRect();
        const pos = {};
        wrap.querySelectorAll('.pnode[data-key]').forEach((el) => {
          const r = el.getBoundingClientRect();
          pos[el.dataset.key] = { l: r.left - box.left, r: r.right - box.left, t: r.top - box.top, b: r.bottom - box.top, cx: (r.left + r.right) / 2 - box.left, cy: (r.top + r.bottom) / 2 - box.top };
        });
        const out = [];
        (this.data.edges || []).forEach(([a, b]) => {
          const A = pos[a], B = pos[b]; if (!A || !B) return;
          const active = this.isActive(a) && this.isActive(b);
          let d;
          if (Math.abs(A.cy - B.cy) < 20 && B.l > A.r) d = `M${A.r + 2},${A.cy} L${B.l - 6},${B.cy}`;
          else if (Math.abs(A.cx - B.cx) < 20) d = `M${A.cx},${A.b + 2} L${B.cx},${B.t - 6}`;
          else { const midY = (A.b + B.t) / 2; d = `M${A.cx},${A.b + 2} L${A.cx},${midY} L${B.cx},${midY} L${B.cx},${B.t - 6}`; }
          out.push({ d, active });
        });
        this.side.forEach((s) => (s.feeds || []).forEach((t) => {
          const A = pos[s.key], B = pos[t]; if (!A || !B) return;
          out.push({ d: `M${A.cx},${A.t - 2} C${A.cx},${(A.t + B.b) / 2} ${B.cx},${(A.t + B.b) / 2} ${B.cx},${B.b + 6}`, side: true, active: this.isActive(s.key) });
        }));
        this.paths = out;
        if (this.$refs.arrows) this.$refs.arrows.innerHTML = out.map((p) => `<path d="${p.d}" class="flow-arrow ${p.active ? 'active' : ''} ${p.side ? 'side' : ''}"/>`).join('');
      },
      async demoCycle() {
        this.busy = true;
        try {
          const bots = await Q.get('/api/bots');
          if (!bots.length) { Q.toast('No bot yet - create one on the Paper Trading page (or seed the demo data).', 'error'); return; }
          const r = await Q.post(`/api/bots/${bots[0].id}/run-now`);
          Q.toast(`Bot "${bots[0].name}": ${r.result.message || r.result.status}`, r.result.status === 'error' ? 'error' : 'ok');
          await this.load(true);
        } finally { this.busy = false; }
      },
      async setView(v) {
        this.view = v;
        if (v === 'lifecycle') {
          if (!this.strategies.length) this.strategies = (await Q.get('/api/strategies')).filter((s) => !['execution', 'market_making'].includes(s.kind));
          this.loadLifecycle();
        } else this.$nextTick(() => this.drawArrows());
      },
      async loadLifecycle() { this.lc = await Q.get(`/api/pipeline/lifecycle?strategy_key=${this.lcKey}&sharpe_gate=${this.gate}`); },
    };
  };

  /* ------------------------------------------------------------------ dashboard */
  window.dashboardPage = function () {
    return {
      pipe: { stages: [] }, sum: { recent: [], bots: [], best: [] }, runs: [], orders: [], clock: {}, status: {}, QTS: Q,
      async init() {
        this.load();
        Q.on('*', (d, kind) => { if (['bot.cycle', 'order.filled', 'backtest.done', 'agents.run'].includes(kind)) { clearTimeout(this._t); this._t = setTimeout(() => this.load(), 800); } });
      },
      async load() {
        const [p, s, r, o, c, st] = await Promise.all([Q.get('/api/pipeline/status', true), Q.get('/api/analytics/summary', true),
          Q.get('/api/agents/runs?limit=5', true), Q.get('/api/orders?limit=8', true), Q.get('/api/clock', true), Q.get('/api/system/status', true)]);
        Object.assign(this, { pipe: p, sum: s, runs: r, orders: o, clock: c, status: st });
      },
      dot(s) { return DOT[s] || DOT.idle; },
      get totalEquity() { return this.sum.bots.reduce((a, b) => a + (b.equity || 0), 0); },
      get totalPnl() { return this.sum.bots.reduce((a, b) => a + ((b.equity || 0) - (b.starting_cash || 0)), 0); },
      get pending() { return this.runs.filter((r) => r.status === 'proposed').length; },
    };
  };

  /* ------------------------------------------------------------------ course labs */
  window.labsPage = function () {
    return {
      labs: [], topics: [], course: {}, lab: null, user: 'local', loading: true, showPy: {}, QTS: Q,
      async init() {
        await this.load();
        const id = Q.query().lab; if (id) this.open(parseInt(id, 10));
        Q.on('route', (r) => { if (r.params.lab) this.open(parseInt(r.params.lab, 10)); });
      },
      async load() { const d = await Q.get('/api/labs'); Object.assign(this, { labs: d.labs, topics: d.topics || [], course: d.course || {}, user: d.user, loading: false }); },
      byTopic(t) { return this.labs.filter((l) => l.topic === t.id); },
      async open(id) { this.lab = await Q.get('/api/labs/' + id); window.scrollTo(0, 0); },
      async toggle(step) {
        this.lab = await Q.post(`/api/labs/${this.lab.id}/steps/${step.index}`, { done: !step.done });
        this.load();
      },
      async reset() { if (!confirm('Reset your progress for this lab?')) return; this.lab = await Q.post(`/api/labs/${this.lab.id}/reset`); this.load(); },
      pctDone(l) { return l.n_steps ? Math.round((100 * l.completed) / l.n_steps) : 0; },
      get overall() { const t = this.labs.reduce((a, l) => a + l.n_steps, 0); const d = this.labs.reduce((a, l) => a + l.completed, 0); return t ? Math.round((100 * d) / t) : 0; },
    };
  };

  /* ------------------------------------------------------------------ data */
  window.dataPage = function () {
    const q = Q.query();
    return {
      tab: q.tab || 'chart', instruments: [], sources: [], symbol: (q.symbol || 'SPY').toUpperCase(), timeframe: q.timeframe || '1Day',
      start: q.start || '2024-01-01', end: q.end || '', overlays: (q.overlays || 'sma:20,ema:50').split(','), osc: q.osc || 'rsi', quality: null,
      fetchForm: { symbol: q.symbol || 'SPY', source: q.source || 'auto', timeframe: '1Day', start: '2018-01-01' }, fetching: false,
      news: [], sentiment: [], newsSource: 'auto', newsBusy: false, ref: null, refSymbol: q.ref || 'AAPL', refDate: '2025-12-31',
      tv: { open: '', high: '', low: '', close: '' }, catalog: [], QTS: Q, scoreText: '', scoreVal: null,
      async init() {
        const [i, s, c] = await Promise.all([Q.get('/api/instruments'), Q.get('/api/data/sources'), Q.get('/api/data/indicators')]);
        Object.assign(this, { instruments: i, sources: s, catalog: c });
        this.setTab(this.tab);
        Q.on('theme', () => this.drawChart());
        Q.on('data.ingested', async () => { this.instruments = await Q.get('/api/instruments', true); });
      },
      setTab(t) { this.tab = t; this.$nextTick(() => { if (t === 'chart') this.drawChart(); if (t === 'quality') this.loadQuality(); if (t === 'news') this.loadNews(); if (t === 'reference') this.loadRef(); }); },
      toggleOverlay(o) { const i = this.overlays.indexOf(o); if (i >= 0) this.overlays.splice(i, 1); else this.overlays.push(o); this.drawChart(); },
      async drawChart() {
        const ind = [...this.overlays, this.osc].filter(Boolean).join(',');
        let d;
        try { d = await Q.get(`/api/data/bars?symbol=${this.symbol}&timeframe=${this.timeframe}&start=${this.start}${this.end ? `&end=${this.end}` : ''}&indicators=${ind}`); } catch (e) { return; }
        const overlays = [];
        Object.entries(d.indicators).forEach(([k, v]) => { if (v.pane === 'price') Object.entries(v.series).forEach(([col, data]) => overlays.push({ name: `${k} ${col}`, data })); });
        const intraday = this.timeframe.endsWith('Hour');
        const pc = Q.priceChart(this.$refs.price, d.bars, overlays, [], { intraday });
        const os = d.indicators[this.osc];
        if (os) {
          const levels = this.osc === 'rsi' ? [30, 70] : this.osc === 'stochastic' ? [20, 80] : [];
          const ser = Object.entries(os.series).map(([col, data]) => ({ name: col, data, histogram: col === 'hist', levels }));
          const oc = Q.oscChart(this.$refs.osc, ser, { intraday });
          Q.syncCharts(pc, oc);
        } else if (this.$refs.osc) this.$refs.osc.innerHTML = '';
        this.lastBar = d.bars[d.bars.length - 1];
      },
      async fetchData() {
        this.fetching = true;
        try {
          const r = await Q.post('/api/data/fetch', { ...this.fetchForm, symbol: this.fetchForm.symbol.toUpperCase() });
          Q.toast(`${r.symbol} ${r.timeframe}: ${r.bars} bars from ${r.source} - quality ${r.quality.status}`, 'ok');
          this.instruments = await Q.get('/api/instruments'); this.symbol = r.symbol; this.quality = { symbol: r.symbol, ...r.quality };
        } finally { this.fetching = false; }
      },
      async loadQuality() { this.quality = await Q.get(`/api/data/quality?symbol=${this.symbol}&timeframe=${this.timeframe}`); },
      async loadNews() {
        [this.news, this.sentiment] = await Promise.all([Q.get('/api/news?symbol=' + this.symbol), Q.get('/api/sentiment?symbol=' + this.symbol)]);
        this.$nextTick(() => { if (this.$refs.sent) Q.barChart(this.$refs.sent, this.sentiment.map((s) => s.day), [{ label: 'Daily sentiment', data: this.sentiment.map((s) => s.score), colors: this.sentiment.map((s) => (s.score >= 0 ? '#10b981' : '#ef4444')) }]); });
      },
      async fetchNews() {
        this.newsBusy = true;
        try { const r = await Q.post('/api/news/fetch', { symbol: this.symbol, source: this.newsSource }); Q.toast(`${r.new_items} new headlines from ${r.source}. ${r.note || ''}`, 'ok'); await this.loadNews(); }
        finally { this.newsBusy = false; }
      },
      async score() { this.scoreVal = (await Q.post('/api/sentiment/score', { text: this.scoreText })).score; },
      async loadRef() { this.ref = await Q.get(`/api/data/reference/${this.refSymbol}?date=${this.refDate}`); },
      diff(field, base) { const v = parseFloat(this.tv[field]); if (!v || !base) return ''; return ((v / base - 1) * 100).toFixed(3) + '%'; },
      verdict() {
        if (!this.ref || !this.tv.close) return '';
        const c = parseFloat(this.tv.close);
        if (Math.abs(c / this.ref.raw.close - 1) < 0.001) return 'PASS - TradingView matches RAW (dividend-unadjusted) bars';
        if (Math.abs(c / this.ref.adjusted.close - 1) < 0.001) return "PASS - TradingView matches ADJUSTED bars ('Adjust data for dividends' is ticked)";
        return 'FAIL - matches neither series: check symbol, date, timeframe and session';
      },
    };
  };

  /* ------------------------------------------------------------------ strategy library */
  window.strategiesPage = function () {
    return {
      all: [], tax: {}, labs: {}, f: { q: '', category: '', lab: Q.query().lab || '', family: '', holding: '', model: '' }, sel: null, pine: null, QTS: Q,
      async init() {
        [this.all, this.tax] = await Promise.all([Q.get('/api/strategies'), Q.get('/api/strategies/taxonomy')]);
        const k = Q.query().key; if (k) this.sel = this.all.find((s) => s.key === k) || null;
        try { (await Q.get('/api/labs')).labs.forEach((l) => { this.labs[l.id] = l.title; }); } catch (e) { /* titles are optional */ }
      },
      // categories keep the API's lab order (trend -> momentum -> ... -> market making); the other filters sort A-Z
      opts(field) { const v = [...new Set(this.all.map((s) => (field === 'family' ? s.tags.family : field === 'category' ? s.tags.category : field === 'holding' ? s.tags.holding_period : s.tags.model_type)))]; return field === 'category' ? v : v.sort(); },
      labName(id) { return 'Lab ' + String(id).padStart(2, '0'); },
      labOpts() { return [...new Set(this.all.flatMap((s) => s.labs || []))].sort((a, b) => a - b).map((id) => ({ id: String(id), label: this.labName(id) + (this.labs[id] ? ' · ' + this.labs[id] : '') })); },
      get list() {
        const f = this.f; const q = f.q.toLowerCase();
        return this.all.filter((s) => (!q || (s.name + ' ' + s.summary + ' ' + s.key).toLowerCase().includes(q)) && (!f.category || s.tags.category === f.category) &&
          (!f.lab || (s.labs || []).includes(Number(f.lab))) &&
          (!f.family || s.tags.family === f.family) && (!f.holding || s.tags.holding_period === f.holding) && (!f.model || s.tags.model_type === f.model));
      },
      async showPine(s) { this.pine = { name: s.name, code: await Q.get(`/api/strategies/${s.key}/pine`) }; },
      kindLabel(k) { return { signal: 'Signal', portfolio: 'Multi-asset', execution: 'Execution sim', market_making: 'Market-making sim', agentic: 'Agentic' }[k] || k; },
      async remove(s) { if (!confirm(`Delete custom strategy ${s.name}?`)) return; await Q.del('/api/strategies/' + s.key); this.all = await Q.get('/api/strategies'); this.sel = null; },
    };
  };

  /* ------------------------------------------------------------------ strategy builder */
  window.builderPage = function () {
    const q = Q.query();
    return {
      cm: null, templates: [], customs: [], key: q.key || null, parent: null, symbols: q.symbols || 'SPY', result: null, busy: false,
      info: { summary: '', category: 'Custom', holding_period: 'Swing' }, QTS: Q,
      async init() {
        const [t, all] = await Promise.all([Q.get('/api/strategies/templates'), Q.get('/api/strategies')]);
        this.templates = t; this.customs = all.filter((s) => s.custom);
        this.cm = CodeMirror(this.$refs.editor, { value: t[0].code, mode: 'python', lineNumbers: true, indentUnit: 4,
          theme: document.documentElement.classList.contains('dark') ? 'material-darker' : 'default', extraKeys: { Tab: (cm) => cm.replaceSelection('    ') } });
        Q.on('theme', (dark) => this.cm.setOption('theme', dark ? 'material-darker' : 'default'));
        this.loadExamples();
        this.$watch('showCode', (v) => { if (v) setTimeout(() => this.cm.refresh(), 0); });
        if (q.clone) await this.clone(q.clone);
        else if (q.key) this.edit(this.customs.find((s) => s.key === q.key));
        else if (q.template) this.useTemplate(q.template);
      },
      useTemplate(k) { const t = this.templates.find((x) => x.key === k); if (t) { this.cm.setValue(t.code); this.key = null; this.parent = null; this.result = null; } },
      async clone(k) { const r = await Q.post(`/api/strategies/${k}/clone`); this.cm.setValue(r.code); this.key = null; this.parent = r.parent_key; this.result = null; Q.toast('Cloned ' + k + ' into the editor', 'ok'); },
      edit(s) { if (!s) return; this.cm.setValue(s.code || ''); this.key = s.key; this.parent = s.parent_key; this.info.summary = s.summary; this.result = s.validation; },
      body() { const syms = Q.symbolsFrom(this.symbols); return { code: this.cm.getValue(), symbol: syms[0] || 'SPY', symbols: syms, params: {} }; },
      async validate() {
        this.busy = true;
        try { this.result = await Q.post('/api/strategies/validate', this.body()); Q.toast(this.result.ok ? 'Valid - test run passed' : 'Validation found issues', this.result.ok ? 'ok' : 'error'); }
        finally { this.busy = false; }
      },
      async save() {
        this.busy = true;
        try {
          const s = await Q.post('/api/strategies', { ...this.body(), key: this.key, info: this.info, parent_key: this.parent });
          this.key = s.key; Q.toast(`Saved as ${s.key} - it now appears in the strategy list`, 'ok');
          this.customs = (await Q.get('/api/strategies')).filter((x) => x.custom);
        } finally { this.busy = false; }
      },
      async remove(s) { if (!confirm('Delete ' + s.name + '?')) return; await Q.del('/api/strategies/' + s.key); this.customs = this.customs.filter((x) => x.key !== s.key); if (this.key === s.key) this.key = null; },
      // ---- Idea -> Strategy (no coding): describe the idea, the app writes and checks the code
      idea: q.idea || '', ideaRes: null, ideaBusy: false, examples: [], showCode: !!(q.key || q.clone || q.template),
      async loadExamples() { this.examples = await Q.get('/api/strategies/idea/examples'); },
      async fromIdea() {
        this.ideaBusy = true; this.ideaRes = null;
        try {
          const sym = (Q.symbolsFrom(this.symbols)[0] || 'SPY');
          const r = await Q.post('/api/strategies/from-idea', { idea: this.idea, symbol: sym, save: true });
          this.ideaRes = r;
          if (r.ok) {
            this.cm.setValue(r.code); this.key = r.key; this.parent = null; this.result = r.validation;
            this.customs = (await Q.get('/api/strategies')).filter((x) => x.custom);
            Q.toast('Strategy ready: ' + r.name, 'ok');
          } else Q.toast(r.message || 'Could not build a strategy from that idea', 'error');
        } finally { this.ideaBusy = false; }
      },
      testUrl() { return '#/backtest?strategy=' + this.key + '&symbols=' + (Q.symbolsFrom(this.symbols)[0] || 'SPY') + '&costs=alpaca_retail&run=1'; },
    };
  };

  /* ------------------------------------------------------------------ backtest */
  window.backtestPage = function () {
    const q = Q.query();
    return {
      strategies: [], presets: {}, history: [], desc: null, key: q.strategy || 'ema_cross', symbols: q.symbols || '', params: {},
      cfg: { costs: q.costs || 'alpaca_retail', execution: q.execution || 'next_open', allow_short: q.allow_short === 'true', sizing: q.sizing || 'percent_equity', size_pct: 1.0,
        fixed_notional: 10000, vol_target: 0.15, max_leverage: 1.0, atr_risk_pct: 0.01, atr_mult: 2, stop_loss_pct: q.stop_loss_pct || '', take_profit_pct: q.take_profit_pct || '',
        initial_capital: 100000, whole_shares: false }, start: q.start || '', end: q.end || '', benchmark: q.benchmark || 'SPY', customCost: null, showAdv: !!q.stop_loss_pct,
      res: null, busy: false, tab: 'overview', QTS: Q, marketBars: null, day: '',
      async init() {
        const [s, p, h] = await Promise.all([Q.get('/api/strategies'), Q.get('/api/costs/presets'), Q.get('/api/backtests?limit=50')]);
        this.strategies = s; this.presets = p; this.history = h;
        this.pick(this.key, true);
        if (q.id) this.load(parseInt(q.id, 10));
        else if (q.run === '1') this.$nextTick(() => this.run());      // 'Test it now' from Idea -> Strategy
        Q.on('route', (r) => { if (r.params.id) this.load(parseInt(r.params.id, 10)); });
        Q.on('theme', () => this.draw());
      },
      groups() {
        const g = {};
        this.strategies.forEach((s) => { const k = s.custom ? 'Custom (Strategy Builder)' : s.tags.category; (g[k] = g[k] || []).push(s); });
        return Object.entries(g);
      },
      pick(k, fromQuery) {
        this.key = k; this.desc = this.strategies.find((s) => s.key === k) || null;
        if (!this.desc) return;
        const qp = fromQuery ? Q.query() : {};
        const vals = {};
        this.desc.params_schema.forEach((p) => { if (qp[p.name] !== undefined) vals[p.name] = qp[p.name]; });
        this.params = Q.paramForm(this.desc.params_schema, vals);
        if (!fromQuery || !this.symbols) this.symbols = (this.desc.default_symbols || ['SPY']).join(', ');
        if (this.desc.allow_short && this.desc.kind === 'portfolio') this.cfg.allow_short = true;
      },
      config() {
        const c = { ...this.cfg };
        c.costs = this.customCost ? { ...this.customCost, name: 'Custom route' } : c.costs;
        ['stop_loss_pct', 'take_profit_pct'].forEach((k) => { c[k] = c[k] === '' || c[k] === null ? null : parseFloat(c[k]) / 100; });
        return c;
      },
      async run() {
        this.busy = true;
        try {
          this.res = await Q.post('/api/backtests', { strategy_key: this.key, symbols: Q.symbolsFrom(this.symbols), params: Q.coerce(this.desc.params_schema, this.params),
            start: this.start || null, end: this.end || null, benchmark: this.benchmark, config: this.config(), day: this.day || null });
          this.history = await Q.get('/api/backtests?limit=50'); this.tab = 'overview';
          history.replaceState(null, '', '#/backtest?id=' + this.res.id);
          this.$nextTick(() => this.draw());
          Q.toast(`Backtest #${this.res.id} done in ${this.res.duration_ms} ms`, 'ok');
        } finally { this.busy = false; }
      },
      async load(id) { this.res = await Q.get('/api/backtests/' + id); this.tab = 'overview'; if (this.res.strategy_key !== this.key && this.strategies.length) { this.key = this.res.strategy_key; this.desc = this.strategies.find((s) => s.key === this.key); this.params = { ...this.res.params }; this.symbols = this.res.symbols.join(', '); } this.$nextTick(() => this.draw()); },
      useCustomCost() { this.customCost = this.customCost ? null : { ...(this.presets[this.cfg.costs] || this.presets.alpaca_retail) }; },
      setTab(t) { this.tab = t; this.$nextTick(() => this.draw()); },
      get kind() { return (this.res && this.res.kind) || 'signal'; },
      metricKeys: ['total_return', 'cagr', 'volatility', 'sharpe', 'sortino', 'calmar', 'max_drawdown', 'max_dd_duration', 'win_rate', 'profit_factor', 'expectancy',
        'avg_win', 'avg_loss', 'trades', 'exposure', 'turnover', 'alpha', 'beta', 'information_ratio', 'total_costs', 'break_even_bps'],
      async draw() {
        const r = this.res; if (!r || !r.series) return;
        if (this.kind === 'execution' || this.kind === 'market_making') return this.drawSpecial();
        if (this.tab === 'overview') {
          Q.lineChart(this.$refs.eq, [{ label: 'Strategy (net)', data: r.series.equity, color: '#1f4e79', width: 2 },
            { label: 'Strategy (gross)', data: r.series.equity_gross, color: '#7f9cc0', dashed: true, width: 1 },
            { label: r.benchmark + ' buy & hold', data: r.series.benchmark || [], color: '#e87122' }], { fmt: (v) => Q.usd(v) });
          Q.lineChart(this.$refs.dd, [{ label: 'Drawdown', data: r.series.drawdown, color: '#ef4444', fill: true },
            { label: r.benchmark + ' drawdown', data: r.series.benchmark_drawdown || [], color: '#e87122', width: 1 }], { fmt: (v) => Q.pct(v, 0) });
        }
        if (this.tab === 'charts') {
          Q.lineChart(this.$refs.roll, [{ label: 'Rolling Sharpe (126 bars)', data: r.series.rolling_sharpe, color: '#8b5cf6' }]);
          Q.lineChart(this.$refs.expo, [{ label: 'Net exposure', data: r.series.exposure, color: '#0ea5e9', fill: true, fillColor: 'rgba(14,165,233,.15)' }], { fmt: (v) => Q.pct(v, 0) });
        }
        if (this.tab === 'price') {
          const sym = r.symbols[0];
          const d = await Q.get(`/api/data/bars?symbol=${sym}&timeframe=${r.timeframe}${r.start ? '&start=' + r.start : ''}${r.end ? '&end=' + r.end : ''}`);
          const fills = await this.fills(r.id);
          Q.priceChart(this.$refs.price, d.bars, [], Q.markersFromFills(fills, sym), { height: 420 });
        }
        if (this.tab === 'costs' && r.cost_summary) {
          const c = r.cost_summary; const keys = ['commission', 'spread', 'slippage', 'reg_fees', 'borrow'];
          Q.barChart(this.$refs.costs, keys.map((k) => k.replace('_', ' ')), [{ label: 'USD', data: keys.map((k) => c[k] || 0), colors: Q.palette }], { horizontal: true, fmt: (v) => Q.usd(v) });
        }
      },
      async fills(id) { const r = await Q.get('/api/backtests/' + id); return (r.extra && r.extra.fills) || r.fills || this.fillsFromTrades(r.trades); },
      fillsFromTrades(trades) {
        const out = [];
        (trades || []).forEach((t) => {
          out.push({ date: t.entry_date, symbol: t.symbol, side: t.side.startsWith('long') ? 'buy' : 'sell', reason: 'signal' });
          if (!t.side.includes('open')) out.push({ date: t.exit_date, symbol: t.symbol, side: t.side.startsWith('long') ? 'sell' : 'buy', reason: t.exit_reason });
        });
        return out;
      },
      drawSpecial() {
        const r = this.res;
        if (this.kind === 'market_making') {
          Q.lineChart(this.$refs.eq, [{ label: 'Market-maker equity', data: r.series.equity, color: '#1f4e79' }], { fmt: (v) => Q.usd(v), timeLen: 16 });
          Q.lineChart(this.$refs.dd, [{ label: 'Inventory (shares)', data: r.series.inventory, color: '#e87122', fill: true, fillColor: 'rgba(232,113,34,.15)' }], { timeLen: 16 });
        } else {
          const ch = r.series.children || [];
          Q.barChart(this.$refs.eq, ch.map((c) => c.time.slice(11, 16)), [{ label: 'Child order (shares)', data: ch.map((c) => c.child_qty) }]);
          Q.lineChart(this.$refs.dd, [{ label: 'Fill price', data: ch.map((c) => [c.time, c.price]), color: '#1f4e79' }, { label: 'Bar typical price', data: ch.map((c) => [c.time, c.typical]), color: '#e87122', dashed: true }], { timeLen: 16 });
        }
      },
      createBot() { QTS.go(`trading?new=1&strategy=${this.res.strategy_key}&symbols=${this.res.symbols.join(',')}&params=${encodeURIComponent(JSON.stringify(this.res.params))}&backtest=${this.res.id}`); },
      heat() { return this.res && this.res.series ? Q.heatmap(this.res.series.monthly) : ''; },
    };
  };
})();
