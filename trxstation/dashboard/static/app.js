// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 RF-DIY.COM
// openDashBoardDisplay : dessine l'état préparé par le serveur (/api/state, /api/history).
// Le serveur rédige déjà les textes ; la page ne fait que les placer. Aucune commande n'est envoyée.
'use strict';

const STATE_MS = 1000;           // état : une fois par seconde
const HISTORY_MS = 60000;        // historique 24 h : une fois par minute
const NOLINK_AFTER_MS = 5000;    // programme muet depuis 5 s : avertissement

const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const LEVEL = new Set(['ok', 'warn', 'crit', 'off']);
const lvl = (v) => (LEVEL.has(v) ? v : 'off');

let state = null;
let history = null;
let lastOk = 0;
const startedAt = Date.now();

// ------------------------------------------------------------------ disposition

function layout() {
  const w = window.innerWidth, h = window.innerHeight;
  const wide = w / h >= 1.3;
  document.body.classList.toggle('wide', wide);
  document.body.classList.toggle('tall', !wide);
  const screen = $('screen');
  screen.style.transform = wide ? `scale(${Math.min(w / 960, h / 480)})` : '';
}

// ------------------------------------------------------------------ horloge (celle du navigateur)

function clock() {
  const d = new Date();
  $('utc').textContent = d.toISOString().slice(11, 19);
  $('local').textContent = d.toLocaleDateString('fr-FR', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })
    + ' · ' + d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }) + ' locale';
  $('nolink').hidden = Date.now() - (lastOk || startedAt) <= NOLINK_AFTER_MS;
}

// ------------------------------------------------------------------ morceaux

const WARN_ICON = '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3 2 21h20L12 3z"/><path d="M12 10v5"/><path d="M12 18h.01"/></svg>';

function fn(f) {
  const cls = ['fn'];
  if (f.on) cls.push(f.tx ? 'txon' : 'on');
  if (f.value) cls.push('v');
  if (f.wide) cls.push('w2');
  return `<div class="${cls.join(' ')}"><span>${esc(f.label)}</span>${f.value ? `<b>${esc(f.value)}</b>` : ''}</div>`;
}

function tile(t) {
  const cls = t.level === 'warn' || t.level === 'crit' ? ` ${t.level}` : '';
  const val = t.kind === 'text'
    ? `<em>${esc(t.value)}</em>`
    : `<b>${esc(t.value)}${t.small ? ` <small>${esc(t.small)}</small>` : ''}</b>`;
  return `<div class="tile${cls}"><span>${esc(t.label)}</span>${val}</div>`;
}

function term(t) {
  const cls = t.state === 'tx' ? ' tx' : t.state === 'on' ? ' on' : '';
  return `<span class="term${cls}"><i></i>${esc(t.name)}${t.note ? ` <small>${esc(t.note)}</small>` : ''}</span>`;
}

// ------------------------------------------------------------------ station

function renderStation(s) {
  const r = s.rig || {};
  let meter = '';
  if (s.tx) {
    const pct = Math.min(100, 100 * s.tx.elapsed_s / Math.max(1, s.tx.tot_s));
    const warn = s.tx.warn_s ? `<s style="left:${(100 * s.tx.warn_s / s.tx.tot_s).toFixed(1)}%"></s>` : '';
    meter = `<div class="sline"><span class="small" style="font-size:13px">Durée TX</span><div class="track"><i style="width:${pct.toFixed(1)}%;background:var(--tx)"></i>${warn}</div><b>${Math.round(s.tx.elapsed_s)}/${Math.round(s.tx.tot_s)} s</b></div>`;
  } else if (r.smeter) {
    meter = `<div class="sline"><span class="small" style="font-size:13px">S-mètre</span><div class="track"><i style="width:${(100 * r.smeter.frac).toFixed(1)}%;background:var(--rx)"></i></div><b>${esc(r.smeter.text)}</b></div>`;
  }
  const freq = r.freq_text
    ? `<span class="freq">${esc(r.freq_text)}</span><span class="small" style="font-size:14px">MHz</span><span class="badge">${esc(r.mode || '—')}</span>`
    : '<span class="freq dim">--.---.---</span><span class="small" style="font-size:14px">MHz</span><span class="badge dim">---</span>';
  $('station').innerHTML = `
    <div class="head"><span class="label">STATION</span><span class="st"><span class="led ${lvl(r.level)}"></span>${esc(r.status_text)}</span></div>
    <div class="freqline">${freq}<span class="small" style="font-size:13px">${esc(r.detail_text)}</span></div>
    ${meter}
    <div class="fns">${(r.functions || []).map(fn).join('')}</div>
    <div class="tiles">${(r.tiles || []).map(tile).join('')}</div>
    ${(s.terminals || []).length ? `<div class="terms"><span>Terminaux</span>${s.terminals.map(term).join('')}</div>` : ''}`;
}

// ------------------------------------------------------------------ PC et historique

const W = 200, H = 20;

function y(v, lo, hi) {
  const c = Math.max(lo, Math.min(hi, v));
  return H - 1 - (c - lo) / (hi - lo) * (H - 2);
}

function spark(values, lo, hi, thr) {
  const n = values.length;
  if (!n) return '<svg viewBox="0 0 200 20" preserveAspectRatio="none" aria-hidden="true"></svg>';
  const x = (i) => (n === 1 ? W : i * W / (n - 1)).toFixed(1);
  // un trou (null) coupe la courbe : pas de ligne inventée là où rien n'a été mesuré
  const runs = [];
  let cur = [];
  values.forEach((v, i) => {
    if (v === null || v === undefined) { if (cur.length) runs.push(cur); cur = []; } else cur.push(`${x(i)},${y(v, lo, hi).toFixed(1)}`);
  });
  if (cur.length) runs.push(cur);
  const ty = y(thr, lo, hi).toFixed(1);
  const lines = runs.map((r) => {
    const first = r[0].split(',')[0], last = r[r.length - 1].split(',')[0];
    return `<polygon points="${first},${H} ${r.join(' ')} ${last},${H}" fill="#4FC3F7" fill-opacity="0.15"/>`
      + `<polyline points="${r.join(' ')}" fill="none" stroke="#4FC3F7" stroke-width="1.5" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>`;
  }).join('');
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true"><rect width="${W}" height="${H}" fill="#0B0F14"/>`
    + `<line x1="0" y1="${ty}" x2="${W}" y2="${ty}" stroke="#F5B83D" stroke-width="1" stroke-dasharray="3 3" vector-effect="non-scaling-stroke"/>${lines}</svg>`;
}

function internetStrip(values) {
  const n = values.length || 1, w = W / n;
  const rects = values.map((v, i) => {
    const color = v === null || v === undefined ? '#1E2935' : v >= 0.99 ? '#2E7D4F' : v >= 0.5 ? '#F5B83D' : '#FF5C4D';
    return `<rect x="${(i * w).toFixed(2)}" y="5" width="${(w + 0.05).toFixed(2)}" height="10" fill="${color}"/>`;
  }).join('');
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">${rects}</svg>`;
}

function alertStrip(marks, n) {
  const rects = marks.map((m) => `<rect x="${(m.i * W / n).toFixed(1)}" y="2" width="3" height="16" rx="1" fill="${m.level === 'crit' ? '#FF5C4D' : '#F5B83D'}"/>`).join('');
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true"><rect y="9" width="${W}" height="2" fill="#233040"/>${rects}</svg>`;
}

function renderPc(s) {
  const pc = s.pc || {};
  const h = history || { n: 0, cpu: [], mem: [], temp: [], internet: [], alerts: [], thresholds: { cpu: 75, mem: 80, temp: 75 }, temp_range: [30, 95] };
  const cur = (k) => pc[k] || { text: '—', level: 'ok' };
  const val = (c) => `<b class="${c.level === 'warn' || c.level === 'crit' ? c.level : ''}">${esc(c.text)}</b>`;
  const rows = [
    ['Processeur', spark(h.cpu, 0, 100, h.thresholds.cpu), cur('cpu')],
    ['Mémoire', spark(h.mem, 0, 100, h.thresholds.mem), cur('mem')],
    ['Temp. CPU', spark(h.temp, h.temp_range[0], h.temp_range[1], h.thresholds.temp), cur('temp')],
    ['Internet', internetStrip(h.internet), cur('internet')],
    ['Alertes', alertStrip(h.alerts, Math.max(1, h.n)), cur('alerts')],
  ];
  const svc = (pc.services || []).map((x) => `<span><span class="led ${lvl(x.level)}"></span>${esc(x.name)}<em class="${x.level === 'crit' ? 'crit' : ''}">${esc(x.text)}</em></span>`).join('');
  const sdr = s.sdr
    ? `<div class="sdr"><div class="head"><span class="label">SDR</span><span class="st"><span class="led ${lvl(s.sdr.level)}"></span>${esc(s.sdr.title)}</span></div>`
      + `<div class="g">${(s.sdr.cells || []).map(([a, b]) => `<div><span>${esc(a)}</span><b>${esc(b)}</b></div>`).join('')}</div></div>`
    : '';
  $('pc').innerHTML = `
    <div class="head"><span class="label">PC</span><span class="st">${pc.level && pc.level !== 'ok' ? `<span class="led ${lvl(pc.level)}"></span>` : ''}${esc(pc.title)}</span></div>
    <div class="hist" role="img" aria-label="Historique des 24 dernières heures : processeur, mémoire, température, Internet, alertes">
      ${rows.map(([name, svg, c]) => `<div class="hrow"><span>${name}</span>${svg}${val(c)}</div>`).join('')}
      <div class="haxis"><span></span><div><span>−24 h</span><span>−12 h</span><span>maint.</span></div><span></span></div>
    </div>
    <div class="sep"></div>
    <div class="svc">${svc}</div>
    ${sdr}`;
}

// ------------------------------------------------------------------ ensemble

const PILL = { rx: 'rx', tx: 'tx', safe: 'safe', off: 'off', nolink: 'off' };

function render() {
  const s = state;
  if (!s) return;
  $('station-name').textContent = s.station_name ? `station ${s.station_name}` : 'station';
  const pill = $('pill');
  pill.className = `pill ${PILL[s.mode] || 'off'}`;
  $('pilltext').innerHTML = esc(s.mode_text) + (s.tx ? ` <span class="t">${fmtDuration(s.tx.elapsed_s)}</span>` : '');
  $('banner').innerHTML = s.banner
    ? `<div class="alertband ${s.banner.level === 'warn' ? 'warn' : ''}">${WARN_ICON}<span><b>${esc(s.banner.title)}</b> ${esc(s.banner.text)}</span></div>`
    : '';
  renderStation(s);
  renderPc(s);
  $('footl').innerHTML = s.stale ? `<span class="stale">${esc(s.foot_left)}</span>` : esc(s.foot_left);
  $('footr').textContent = s.foot_right || '';
  document.title = `Station – ${s.mode_text}`;
}

function fmtDuration(sec) {
  const v = Math.max(0, Math.round(sec));
  return `${String(Math.floor(v / 60)).padStart(2, '0')}:${String(v % 60).padStart(2, '0')}`;
}

async function getJson(path) {
  const res = await fetch(path, { cache: 'no-store', credentials: 'same-origin' });
  if (!res.ok) throw new Error(`${path} : ${res.status}`);
  return res.json();
}

async function pollState() {
  try {
    state = await getJson('api/state');
    lastOk = Date.now();
    render();
  } catch (e) { /* l'avertissement « programme injoignable » s'affiche tout seul */ }
  setTimeout(pollState, STATE_MS);
}

async function pollHistory() {
  try {
    history = await getJson('api/history');
    render();
  } catch (e) { /* on garde le dernier historique reçu */ }
  setTimeout(pollHistory, HISTORY_MS);
}

window.addEventListener('resize', layout);
window.addEventListener('orientationchange', layout);
layout();
clock();
setInterval(clock, 1000);
pollHistory();
pollState();
