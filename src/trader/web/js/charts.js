/* Chart helpers: Chart.js for analytics, TradingView Lightweight Charts v5 for price + indicators + trade markers. */
/* global Chart, LightweightCharts */
(function () {
  const Q = window.QTS;
  Q.palette = ['#1f4e79', '#e87122', '#10b981', '#8b5cf6', '#ef4444', '#0ea5e9', '#f59e0b', '#64748b'];
  const isDark = () => document.documentElement.classList.contains('dark');
  const grid = () => (isDark() ? 'rgba(148,163,184,.12)' : 'rgba(100,116,139,.12)');
  const txt = () => (isDark() ? '#cbd5e1' : '#475569');

  function el(target) { return typeof target === 'string' ? document.querySelector(target) : target; }

  /* datasets: [{label, data: [[date, value], ...], color, dashed, fill, yAxisID}] */
  Q.lineChart = function (target, datasets, opts = {}) {
    const canvas = el(target);
    if (!canvas) return null;
    const old = Chart.getChart(canvas); if (old) old.destroy();
    const first = datasets.find((d) => d.data && d.data.length) || { data: [] };
    const labels = first.data.map((p) => String(p[0]).slice(0, opts.timeLen || 10));
    const ds = datasets.map((d, i) => {
      const m = new Map((d.data || []).map((p) => [String(p[0]).slice(0, opts.timeLen || 10), p[1]]));
      return { label: d.label, data: labels.map((l) => (m.has(l) ? m.get(l) : null)), borderColor: d.color || Q.palette[i % 8],
        backgroundColor: d.fill ? (d.fillColor || 'rgba(239,68,68,.25)') : 'transparent', fill: !!d.fill, borderWidth: d.width || 1.6,
        borderDash: d.dashed ? [5, 4] : [], pointRadius: 0, tension: 0, spanGaps: true, yAxisID: d.yAxisID || 'y' };
    });
    const c = new Chart(canvas, {
      type: 'line', data: { labels, datasets: ds },
      options: { responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: 'index', intersect: false },
        plugins: { legend: { labels: { color: txt(), boxWidth: 12, font: { size: 11 } } },
          tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${opts.fmt ? opts.fmt(ctx.parsed.y) : Q.num(ctx.parsed.y)}` } } },
        scales: { x: { ticks: { color: txt(), maxTicksLimit: 8, maxRotation: 0, font: { size: 10 } }, grid: { color: grid() } },
          y: { ticks: { color: txt(), font: { size: 10 }, callback: opts.fmt ? (v) => opts.fmt(v) : undefined }, grid: { color: grid() } },
          ...(opts.y2 ? { y2: { position: 'right', ticks: { color: txt(), font: { size: 10 } }, grid: { display: false } } } : {}) } },
    });
    Q.charts.push(c);
    return c;
  };

  Q.barChart = function (target, labels, datasets, opts = {}) {
    const canvas = el(target);
    if (!canvas) return null;
    const old = Chart.getChart(canvas); if (old) old.destroy();
    const c = new Chart(canvas, {
      type: 'bar', data: { labels, datasets: datasets.map((d, i) => ({ label: d.label, data: d.data,
        backgroundColor: d.colors || d.color || Q.palette[i % 8], borderRadius: 3, stack: opts.stacked ? 's' : undefined })) },
      options: { responsive: true, maintainAspectRatio: false, animation: false, indexAxis: opts.horizontal ? 'y' : 'x',
        plugins: { legend: { display: datasets.length > 1, labels: { color: txt(), font: { size: 11 } } } },
        scales: { x: { stacked: !!opts.stacked, ticks: { color: txt(), font: { size: 10 } }, grid: { color: grid() } },
          y: { stacked: !!opts.stacked, ticks: { color: txt(), font: { size: 10 }, callback: opts.fmt ? (v) => opts.fmt(v) : undefined }, grid: { color: grid() } } } },
    });
    Q.charts.push(c);
    return c;
  };

  Q.scatterChart = function (target, datasets, opts = {}) {
    const canvas = el(target);
    if (!canvas) return null;
    const old = Chart.getChart(canvas); if (old) old.destroy();
    const c = new Chart(canvas, { type: 'scatter',
      data: { datasets: datasets.map((d, i) => ({ label: d.label, data: d.data, backgroundColor: d.color || Q.palette[i % 8], pointRadius: d.r || 2.5 })) },
      options: { responsive: true, maintainAspectRatio: false, animation: false,
        plugins: { legend: { labels: { color: txt(), font: { size: 11 } } } },
        scales: { x: { title: { display: !!opts.x, text: opts.x, color: txt() }, ticks: { color: txt() }, grid: { color: grid() } },
          y: { title: { display: !!opts.y, text: opts.y, color: txt() }, ticks: { color: txt() }, grid: { color: grid() } } } } });
    Q.charts.push(c);
    return c;
  };

  /* Lightweight Charts price chart.
     bars: [{time, open, high, low, close, volume}], overlays: [{name, data:[[time, v]], color}], markers: [{time, position, color, shape, text}] */
  Q.priceChart = function (target, bars, overlays = [], markers = [], opts = {}) {
    const container = el(target);
    if (!container || !window.LightweightCharts) return null;
    container.innerHTML = '';
    const LW = LightweightCharts;
    const chart = LW.createChart(container, {
      autoSize: true, height: opts.height || 380,
      layout: { background: { type: 'solid', color: 'transparent' }, textColor: txt(), fontSize: 11 },
      grid: { vertLines: { color: grid() }, horzLines: { color: grid() } },
      rightPriceScale: { borderVisible: false }, timeScale: { borderVisible: false, timeVisible: !!opts.intraday },
      crosshair: { mode: 0 },
    });
    const candles = chart.addSeries(LW.CandlestickSeries, { upColor: '#10b981', downColor: '#ef4444', borderVisible: false,
      wickUpColor: '#10b981', wickDownColor: '#ef4444' });
    candles.setData(bars.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));
    if (opts.volume !== false) {
      const vol = chart.addSeries(LW.HistogramSeries, { priceFormat: { type: 'volume' }, priceScaleId: 'vol', color: 'rgba(100,116,139,.35)' });
      chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      vol.setData(bars.map((b) => ({ time: b.time, value: b.volume, color: b.close >= b.open ? 'rgba(16,185,129,.35)' : 'rgba(239,68,68,.35)' })));
    }
    overlays.forEach((o, i) => {
      const s = chart.addSeries(LW.LineSeries, { color: o.color || Q.palette[(i + 1) % 8], lineWidth: o.width || 1.5, priceLineVisible: false,
        lastValueVisible: false, title: o.name });
      s.setData(o.data.filter((p) => p[1] !== null).map((p) => ({ time: p[0], value: p[1] })));
    });
    if (markers && markers.length && LW.createSeriesMarkers) {
      const times = new Set(bars.map((b) => b.time));
      LW.createSeriesMarkers(candles, markers.filter((m) => times.has(m.time)).sort((a, b) => (a.time > b.time ? 1 : -1)));
    }
    chart.timeScale().fitContent();
    const handle = { chart, remove: () => chart.remove(), destroy: () => chart.remove() };
    Q.charts.push(handle);
    return handle;
  };

  /* Oscillator pane (RSI / MACD / ATR) */
  Q.oscChart = function (target, series, opts = {}) {
    const container = el(target);
    if (!container || !window.LightweightCharts) return null;
    container.innerHTML = '';
    const LW = LightweightCharts;
    const chart = LW.createChart(container, { autoSize: true, height: opts.height || 160,
      layout: { background: { type: 'solid', color: 'transparent' }, textColor: txt(), fontSize: 10 },
      grid: { vertLines: { color: grid() }, horzLines: { color: grid() } }, rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: !!opts.intraday } });
    series.forEach((s, i) => {
      const kind = s.histogram ? LW.HistogramSeries : LW.LineSeries;
      const ser = chart.addSeries(kind, { color: s.color || Q.palette[i % 8], lineWidth: 1.5, priceLineVisible: false, title: s.name });
      ser.setData(s.data.filter((p) => p[1] !== null).map((p) => ({ time: p[0], value: p[1],
        ...(s.histogram ? { color: p[1] >= 0 ? 'rgba(16,185,129,.6)' : 'rgba(239,68,68,.6)' } : {}) })));
      (s.levels || []).forEach((lv) => ser.createPriceLine({ price: lv, color: '#94a3b8', lineWidth: 1, lineStyle: 2, axisLabelVisible: false }));
    });
    chart.timeScale().fitContent();
    const handle = { chart, remove: () => chart.remove(), destroy: () => chart.remove() };
    Q.charts.push(handle);
    return handle;
  };

  Q.syncCharts = function (a, b) {
    if (!a || !b) return;
    a.chart.timeScale().subscribeVisibleLogicalRangeChange((r) => { if (r) b.chart.timeScale().setVisibleLogicalRange(r); });
    b.chart.timeScale().subscribeVisibleLogicalRangeChange((r) => { if (r) a.chart.timeScale().setVisibleLogicalRange(r); });
  };

  Q.markersFromFills = function (fills, symbol) {
    return (fills || []).filter((f) => !symbol || f.symbol === symbol).map((f) => ({
      time: String(f.date).slice(0, 10), position: f.side === 'buy' ? 'belowBar' : 'aboveBar',
      color: f.side === 'buy' ? '#10b981' : '#ef4444', shape: f.side === 'buy' ? 'arrowUp' : 'arrowDown',
      text: (f.side === 'buy' ? 'B' : 'S') + (f.reason && f.reason !== 'signal' ? ' ' + f.reason.replace('_', ' ') : '') }));
  };

  /* Monthly returns heatmap as an HTML table */
  Q.heatmap = function (monthly) {
    if (!monthly || !monthly.years || !monthly.years.length) return '<div class="muted text-sm">No monthly data.</div>';
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const color = (v) => {
      if (v === null || v === undefined) return 'transparent';
      const a = Math.min(Math.abs(v) / 0.08, 1) * 0.75 + 0.08;
      return v >= 0 ? `rgba(16,185,129,${a})` : `rgba(239,68,68,${a})`;
    };
    let h = '<table class="heat w-full"><thead><tr><th class="text-left text-xs muted">Year</th>' + months.map((m) => `<th class="text-xs muted">${m}</th>`).join('') + '<th class="text-xs muted">Year</th></tr></thead><tbody>';
    monthly.years.forEach((y, i) => {
      const row = monthly.values[i] || [];
      const yr = row.reduce((acc, v) => (v === null || v === undefined ? acc : acc * (1 + v)), 1) - 1;
      h += `<tr><td class="text-left font-semibold">${y}</td>` + months.map((_, j) => {
        const v = row[j];
        return `<td style="background:${color(v)}">${v === null || v === undefined ? '' : (v * 100).toFixed(1)}</td>`;
      }).join('') + `<td class="font-semibold" style="background:${color(yr / 3)}">${(yr * 100).toFixed(1)}</td></tr>`;
    });
    return h + '</tbody></table>';
  };
})();
