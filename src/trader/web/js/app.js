/* Core: API client, formatters, store, router, live events (SSE), shell. No build step. */
/* global Alpine */
const QTS = (window.QTS = window.QTS || {});

QTS.api = async function (path, opts = {}) {
  const o = { method: opts.method || (opts.body !== undefined ? 'POST' : 'GET'), headers: {} };
  if (opts.body !== undefined) { o.headers['Content-Type'] = 'application/json'; o.body = JSON.stringify(opts.body); }
  const r = await fetch(path, o);
  const ct = r.headers.get('content-type') || '';
  const data = ct.includes('json') ? await r.json() : await r.text();
  if (!r.ok) {
    let msg = (data && data.detail) || data || r.statusText;
    if (typeof msg === 'object') msg = msg.message || JSON.stringify(msg);
    const err = new Error(msg); err.status = r.status; err.data = data;
    if (!opts.quiet) QTS.toast(String(msg).slice(0, 300), 'error');
    throw err;
  }
  return data;
};
QTS.get = (p, quiet) => QTS.api(p, { quiet });
QTS.post = (p, body, quiet) => QTS.api(p, { body: body === undefined ? {} : body, quiet });
QTS.put = (p, body) => QTS.api(p, { method: 'PUT', body });
QTS.del = (p) => QTS.api(p, { method: 'DELETE' });

QTS.toast = function (text, kind = 'info', ms = 4500) {
  const s = Alpine.store('app'); const id = Math.random();
  s.toasts.push({ id, text, kind });
  setTimeout(() => { s.toasts = s.toasts.filter((t) => t.id !== id); }, ms);
};

/* ---------- formatting */
QTS.pct = (v, d = 2) => (v === null || v === undefined || isNaN(v) ? '–' : (v * 100).toFixed(d) + '%');
QTS.num = (v, d = 2) => (v === null || v === undefined || isNaN(v) ? '–' : Number(v).toFixed(d));
QTS.int = (v) => (v === null || v === undefined || isNaN(v) ? '–' : Math.round(v).toLocaleString());
QTS.usd = (v, d = 0) => (v === null || v === undefined || isNaN(v) ? '–' : '$' + Number(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d }));
QTS.cls = (v) => (v === null || v === undefined ? '' : v > 0 ? 'pos' : v < 0 ? 'neg' : '');
QTS.ago = function (iso) {
  if (!iso) return 'never';
  const t = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z').getTime();
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return Math.round(s) + 's ago'; if (s < 3600) return Math.round(s / 60) + 'm ago';
  if (s < 86400) return Math.round(s / 3600) + 'h ago'; return Math.round(s / 86400) + 'd ago';
};
QTS.fmtMetric = function (key, v) {
  const d = (Alpine.store('app').defs || {})[key] || {};
  switch (d.fmt) {
    case 'pct': return QTS.pct(v); case 'int': return QTS.int(v); case 'usd': return QTS.usd(v);
    case 'bps': return v === null || v === undefined ? '–' : QTS.num(v, 1) + ' bps';
    default: return v === null || v === undefined ? '–' : v === Infinity ? '∞' : QTS.num(v);
  }
};
QTS.metricTip = function (key) {
  const d = (Alpine.store('app').defs || {})[key];
  return d ? `${d.label}: ${d.help}\nFormula: ${d.formula}` : key;
};
QTS.label = (key) => ((Alpine.store('app').defs || {})[key] || {}).label || key;
QTS.copy = async function (text) { try { await navigator.clipboard.writeText(text); QTS.toast('Copied', 'ok', 1500); } catch (e) { QTS.toast('Copy failed', 'error'); } };
QTS.query = function () { return Alpine.store('app').route.params || {}; };
QTS.go = (route) => { location.hash = '#/' + route; };
QTS.download = (url) => { const a = document.createElement('a'); a.href = url; a.download = ''; document.body.appendChild(a); a.click(); a.remove(); };
QTS.ls = { get(k, d) { try { const v = localStorage.getItem('qts-' + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
           set(k, v) { try { localStorage.setItem('qts-' + k, JSON.stringify(v)); } catch (e) { /* storage blocked */ } } };

/* ---------- icons (inline SVG, stroke icons) */
const P = (d) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="w-5 h-5">${d}</svg>`;
QTS.icons = {
  map: P('<circle cx="5" cy="6" r="2"/><circle cx="12" cy="18" r="2"/><circle cx="19" cy="6" r="2"/><path d="M7 6h10M6 8l5 8M18 8l-5 8"/>'),
  home: P('<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>'),
  book: P('<path d="M4 4h6a3 3 0 0 1 3 3v13a2 2 0 0 0-2-2H4zM20 4h-6a3 3 0 0 0-3 3v13a2 2 0 0 1 2-2h7z"/>'),
  db: P('<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>'),
  layers: P('<path d="M12 3l9 5-9 5-9-5zM3 13l9 5 9-5"/>'),
  code: P('<path d="M8 6l-6 6 6 6M16 6l6 6-6 6"/>'),
  play: P('<path d="M6 4l14 8-14 8z"/>'),
  flask: P('<path d="M9 3h6M10 3v6l-6 10a1 1 0 0 0 1 2h14a1 1 0 0 0 1-2l-6-10V3"/>'),
  bot: P('<rect x="4" y="8" width="16" height="12" rx="3"/><path d="M12 4v4M8 14h.01M16 14h.01M9 18h6"/>'),
  chart: P('<path d="M3 3v18h18M7 15l4-4 3 3 5-6"/>'),
  brain: P('<path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 6 1V5a3 3 0 0 0-3-1zM15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-6 1"/>'),
  plug: P('<path d="M9 2v6M15 2v6M6 8h12v3a6 6 0 0 1-12 0zM12 17v5"/>'),
  gear: P('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z"/>'),
  help: P('<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 0 1 4.9.8c0 1.7-2.4 2.2-2.4 3.7M12 17h.01"/>'),
  menu: P('<path d="M4 6h16M4 12h16M4 18h16"/>'),
  sun: P('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'),
  moon: P('<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>'),
  trade: P('<path d="M7 17l-4-4 4-4M3 13h12M17 7l4 4-4 4M21 11H9"/>'),
};

/* ---------- navigation */
QTS.NAV = [
  { label: 'Overview', items: [
    { route: 'pipeline', label: 'Pipeline Map', icon: 'map' },
    { route: 'dashboard', label: 'Dashboard', icon: 'home' },
    { route: 'labs', label: 'Course Labs', icon: 'book' } ] },
  { label: 'Research workflow', items: [
    { route: 'data', label: 'Data', icon: 'db' },
    { route: 'strategies', label: 'Strategies', icon: 'layers' },
    { route: 'builder', label: 'Idea → Strategy', icon: 'code' },
    { route: 'backtest', label: 'Backtest', icon: 'play' },
    { route: 'research', label: 'Research', icon: 'flask', children: [
      { route: 'research/hypothesis', label: 'Hypothesis test' }, { route: 'research/grid', label: 'Strategy search' },
      { route: 'research/walkforward', label: 'Walk-forward' }, { route: 'research/ml', label: 'ML models' },
      { route: 'research/regime', label: 'Regimes' }, { route: 'research/abtest', label: 'A/B test' },
      { route: 'research/pairs', label: 'Pairs screen' }, { route: 'research/diagnostics', label: 'Diagnostics' },
      { route: 'research/execution', label: 'Execution algos' } ] } ] },
  { label: 'Automation', items: [
    { route: 'trading', label: 'Paper Trading', icon: 'bot', badge: 'openOrders' },
    { route: 'analytics', label: 'Analytics', icon: 'chart' },
    { route: 'agents', label: 'AI Agents', icon: 'brain', badge: 'agentRunning' } ] },
  { label: 'System', items: [
    { route: 'integrations', label: 'Integrations', icon: 'plug' },
    { route: 'settings', label: 'Settings', icon: 'gear' },
    { route: 'help', label: 'Help & Glossary', icon: 'help' } ] },
];
QTS.TITLES = { pipeline: 'Pipeline Map', dashboard: 'Dashboard', labs: 'Course Labs', data: 'Data', strategies: 'Strategy Library',
  builder: 'Idea → Strategy (no coding)', backtest: 'Backtest', research: 'Research', trading: 'Paper Trading',
  analytics: 'Performance Analytics', agents: 'AI Agents', integrations: 'Integrations', settings: 'Settings', help: 'Help & Glossary' };

QTS.parseHash = function () {
  const h = (location.hash || '#/pipeline').replace(/^#\/?/, '');
  const [path, qs] = h.split('?');
  const parts = path.split('/').filter(Boolean);
  const params = Object.fromEntries(new URLSearchParams(qs || ''));
  return { page: parts[0] || 'pipeline', sub: parts[1] || '', full: path || 'pipeline', params };
};

const pageCache = {};
QTS.charts = [];
QTS.destroyCharts = function () { QTS.charts.forEach((c) => { try { c.destroy ? c.destroy() : c.remove(); } catch (e) { /* gone */ } }); QTS.charts = []; };

QTS.loadPage = async function (page) {
  const view = document.getElementById('view');
  const name = QTS.TITLES[page] ? page : 'pipeline';
  if (!pageCache[name]) {
    const r = await fetch(`/static/pages/${name}.html`, { cache: 'no-cache' });
    pageCache[name] = r.ok ? await r.text() : `<div class="empty">Page not found: ${name}</div>`;
  }
  QTS.destroyCharts();
  view.innerHTML = pageCache[name];
  view.scrollTop = 0;
};

/* ---------- live events */
QTS.listeners = {};
QTS.on = function (kind, fn) { (QTS.listeners[kind] = QTS.listeners[kind] || []).push(fn); };
QTS.offAll = function () { QTS.listeners = {}; };
QTS.emitLocal = function (kind, data) { [...(QTS.listeners[kind] || []), ...(QTS.listeners['*'] || [])].forEach((f) => { try { f(data, kind); } catch (e) { console.error(e); } }); };

/* A datalist only offers options that match the box's text, so a box showing "SPY" hides every other symbol.
   Empty a one-symbol box on focus (no input event, so x-model keeps its value) to list them all, and put the
   value back on blur if nothing was picked. Boxes holding several symbols ("KO, PEP") are left alone. */
document.addEventListener('focusin', (e) => {
  const el = e.target;
  if (!el.matches || !el.matches('input[list="qts-symbols"]') || /[,\s]/.test(el.value.trim())) return;
  el.dataset.prev = el.value; el.dataset.ph = el.placeholder;
  if (el.value) el.placeholder = el.value;
  el.value = '';
});
document.addEventListener('focusout', (e) => {
  const el = e.target;
  if (!el.matches || !el.matches('input[list="qts-symbols"]') || el.dataset.prev === undefined) return;
  if (el.value === '') el.value = el.dataset.prev;
  el.placeholder = el.dataset.ph;
  delete el.dataset.prev; delete el.dataset.ph;
});

document.addEventListener('alpine:init', () => {
  Alpine.store('app', { toasts: [], defs: {}, route: QTS.parseHash(), status: {}, counts: { openOrders: 0, agentRunning: 0 }, symbols: [] });
  window.shell = function () {
    return {
      nav: QTS.NAV, sidebarOpen: false, dark: document.documentElement.classList.contains('dark'),
      status: {}, clock: {}, kill: false, live: false, title: '', route: QTS.parseHash(),
      onboard: { open: false, step: 0, seeding: false }, es: null,
      icon(n) { return QTS.icons[n] || ''; },
      isActive(r) { return this.route.page === r || this.route.full === r; },
      badge(k) { const v = Alpine.store('app').counts[k]; return v ? v : ''; },
      async init() {
        window.addEventListener('hashchange', () => this.navigate());
        try { Alpine.store('app').defs = await QTS.get('/api/metrics/definitions', true); } catch (e) { /* offline */ }
        await this.refreshStatus();
        this.loadSymbols();
        this.navigate();
        this.connect();
        this.tickClock(); setInterval(() => this.tickClock(), 30000);
        setInterval(() => this.refreshCounts(), 15000); this.refreshCounts();
        if (this.status.onboarding && !this.status.onboarding.done) this.onboard.open = true;
      },
      async refreshStatus() {
        try { this.status = await QTS.get('/api/system/status', true); Alpine.store('app').status = this.status; } catch (e) { /* server down */ }
        try { this.kill = (await QTS.get('/api/kill-switch', true)).on; } catch (e) { /* */ }
      },
      // symbols with stored bars plus the bundled demo set feed the <datalist id="qts-symbols"> behind every symbol box
      async loadSymbols() {
        try { Alpine.store('app').symbols = await QTS.get('/api/data/symbols', true); } catch (e) { /* server down */ }
      },
      async refreshCounts() {
        try {
          const [o, runs] = await Promise.all([QTS.get('/api/orders?status=open&limit=200', true), QTS.get('/api/agents/runs?limit=30', true)]);
          Alpine.store('app').counts = { openOrders: o.length, agentRunning: runs.filter((r) => r.status === 'running').length };
        } catch (e) { /* */ }
      },
      async tickClock() {
        try {
          const c = await QTS.get('/api/clock', true);
          const ny = new Date(c.now_et), sg = new Date(c.now_sgt);
          const f = (d, tz) => d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', timeZone: tz });
          this.clock = { ...c, ny: f(ny, 'America/New_York'), sg: f(sg, 'Asia/Singapore') };
        } catch (e) { /* */ }
      },
      navigate() {
        const r = QTS.parseHash();
        const samePage = this.route.page === r.page && this.route.sub === r.sub && document.getElementById('view').children.length;
        this.route = r; Alpine.store('app').route = r;
        this.title = (QTS.TITLES[r.page] || 'Pipeline Map') + (r.sub ? ' · ' + (r.sub.charAt(0).toUpperCase() + r.sub.slice(1)) : '');
        document.title = this.title + ' · Quant Trading Simulator';
        if (samePage) { QTS.emitLocal('route', r); return; }
        QTS.offAll();
        QTS.loadPage(r.page);
      },
      connect() {
        try { if (this.es) this.es.close(); } catch (e) { /* */ }
        const es = new EventSource('/api/events/stream');
        this.es = es;
        es.addEventListener('hello', () => { this.live = true; });
        es.onmessage = (m) => this.dispatch(m);
        ['stage', 'order.new', 'order.status', 'order.filled', 'bot.cycle', 'bot.status', 'bot.error', 'backtest.done',
         'research.done', 'agents.run', 'webhook.alert', 'kill_switch', 'data.ingested']
          .forEach((k) => es.addEventListener(k, (m) => this.dispatch(m)));
        es.onerror = () => { this.live = false; setTimeout(() => { if (es.readyState === 2) this.connect(); }, 4000); };
      },
      dispatch(m) {
        this.live = true;
        let d; try { d = JSON.parse(m.data); } catch (e) { return; }
        if (d.kind === 'kill_switch') this.kill = !!(d.payload || {}).on;
        if (d.kind === 'data.ingested') this.loadSymbols();
        if (d.kind && d.kind.startsWith('order.')) this.refreshCounts();
        if (d.kind && d.kind.startsWith('agents.')) this.refreshCounts();
        if (d.kind === 'order.filled') QTS.toast(`Filled: ${d.payload.side.toUpperCase()} ${d.payload.qty} ${d.payload.symbol} @ ${QTS.num(d.payload.price)}`, 'ok', 3000);
        QTS.emitLocal(d.kind, d);
      },
      async toggleKill() {
        const on = !this.kill;
        if (on && !confirm('Turn the GLOBAL kill switch ON? Every bot, webhook and agent order will be blocked and open simulator orders cancelled.')) return;
        await QTS.post('/api/kill-switch', { on });
        this.kill = on; QTS.toast(on ? 'Kill switch ON - all paper trading halted' : 'Kill switch off - trading may resume', on ? 'error' : 'ok');
      },
      toggleTheme() {
        this.dark = !this.dark;
        document.documentElement.classList.toggle('dark', this.dark);
        QTS.ls.set('theme-pref', this.dark ? 'dark' : 'light');
        try { localStorage.setItem('qts-theme', this.dark ? 'dark' : 'light'); } catch (e) { /* */ }
        QTS.emitLocal('theme', this.dark);
      },
      async seed() {
        this.onboard.seeding = true;
        try { await QTS.post('/api/system/seed'); QTS.toast('Demo data loaded', 'ok'); await this.refreshStatus(); this.onboard.step = 4; }
        finally { this.onboard.seeding = false; }
      },
      async finishOnboarding(go) {
        this.onboard.open = false;
        try { await QTS.post('/api/system/onboarding', { mode: this.status.alpaca ? 'alpaca' : 'offline' }, true); } catch (e) { /* */ }
        if (go) QTS.go(go);
      },
    };
  };
});

/* ---------- shared component helpers used by several pages */
QTS.paramForm = function (schema, values) {
  const v = { ...(values || {}) };
  (schema || []).forEach((p) => { if (v[p.name] === undefined) v[p.name] = p.default; });
  return v;
};
QTS.coerce = function (schema, values) {
  const out = {};
  (schema || []).forEach((p) => {
    let x = values[p.name];
    if (x === '' || x === undefined || x === null) return;
    if (p.type === 'int') x = parseInt(x, 10); else if (p.type === 'float') x = parseFloat(x);
    else if (p.type === 'bool') x = x === true || x === 'true' || x === 'on';
    out[p.name] = x;
  });
  return out;
};
QTS.symbolsFrom = (s) => String(s || '').split(/[\s,]+/).map((x) => x.trim().toUpperCase()).filter(Boolean);
QTS.statusBadge = function (s) {
  return { ok: 'badge-ok', done: 'badge-ok', filled: 'badge-ok', running: 'badge-info', new: 'badge-info', accepted: 'badge-info', long: 'badge-ok', short: 'badge-err',
    held: 'badge-muted', warning: 'badge-warn', partially_filled: 'badge-warn', error: 'badge-err', rejected: 'badge-err', canceled: 'badge-muted',
    executed: 'badge-ok', no_trade: 'badge-muted', stopped: 'badge-muted', halted: 'badge-err', idle: 'badge-muted', PASS: 'badge-ok',
    WARN: 'badge-warn', FAIL: 'badge-err', INFO: 'badge-info', pass: 'badge-ok', fail: 'badge-err', pending: 'badge-muted', failed: 'badge-err',
    buy: 'badge-ok', hold: 'badge-muted', none: 'badge-muted', cover: 'badge-info', sell: 'badge-warn' }[s] || 'badge-muted';
};
