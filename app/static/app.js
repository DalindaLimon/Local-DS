// Local DS frontend. Plain ES module, no build step.
// All user/remote text is inserted with textContent; only server-sanitized article HTML uses innerHTML.

/* ============================================================ utilities */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'html') el.innerHTML = v; // only for trusted constants / sanitized HTML
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, String(v));
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const ICONS = {
  heart: '<svg viewBox="0 0 24 24"><path d="M12 20.5s-7.5-4.6-9.3-9.2C1.4 8 3.3 4.5 6.9 4.5c2.1 0 3.7 1.2 5.1 3 1.4-1.8 3-3 5.1-3 3.6 0 5.5 3.5 4.2 6.8-1.8 4.6-9.3 9.2-9.3 9.2z"/></svg>',
  dislike: '<svg viewBox="0 0 24 24"><path d="M10 15.5V19a2.5 2.5 0 0 0 2.5 2.5L16 14V3.5H6.3a2 2 0 0 0-2 1.7L3.1 12.7a2 2 0 0 0 2 2.3H10z"/><path d="M16 3.5h2.7A1.8 1.8 0 0 1 20.5 5.3v7a1.8 1.8 0 0 1-1.8 1.7H16"/></svg>',
  comment: '<svg viewBox="0 0 24 24"><path d="M21 12a8.5 8.5 0 0 1-12.6 7.4L3 21l1.6-5.1A8.5 8.5 0 1 1 21 12z"/></svg>',
  external: '<svg viewBox="0 0 24 24"><path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>',
  back: '<svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg>',
  close: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  eye: '<svg viewBox="0 0 24 24"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>',
  eyeOff: '<svg viewBox="0 0 24 24"><path d="M3 3l18 18"/><path d="M10.6 5.1A10 10 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3.2 4.1M6.6 6.6C3.9 8.3 2 12 2 12s3.6 7 10 7a9.8 9.8 0 0 0 5.4-1.6"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg>',
  volume: '<svg viewBox="0 0 24 24"><path d="M4 9.5h3.5L12 5v14l-4.5-4.5H4z" class="fill"/><path d="M16 9a4 4 0 0 1 0 6M18.5 6.5a7.5 7.5 0 0 1 0 11"/></svg>',
  mute: '<svg viewBox="0 0 24 24"><path d="M4 9.5h3.5L12 5v14l-4.5-4.5H4z" class="fill"/><path d="M16.5 9.5l5 5M21.5 9.5l-5 5"/></svg>',
  play: '<svg viewBox="0 0 24 24"><path d="M8 5.5v13l10.5-6.5z" class="fill"/></svg>',
  pause: '<svg viewBox="0 0 24 24"><path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z" class="fill"/></svg>',
  plus: '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
  check: '<svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
  send: '<svg viewBox="0 0 24 24"><path d="M4 12l16-8-6 16-2.5-6.5z"/></svg>',
  sources: '<svg viewBox="0 0 24 24"><path d="M5 19a1 1 0 1 0 0-.01M4 11a9 9 0 0 1 9 9M4 4a16 16 0 0 1 16 16"/></svg>',
  compass: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/></svg>',
  history: '<svg viewBox="0 0 24 24"><path d="M3.5 12a8.5 8.5 0 1 0 2.5-6"/><path d="M3 4v4h4"/><path d="M12 8v4.5l3 2"/></svg>',
  user: '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>',
  shield: '<svg viewBox="0 0 24 24"><path d="M12 3l8 3v6c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V6z"/></svg>',
  refresh: '<svg viewBox="0 0 24 24"><path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/></svg>',
  trash: '<svg viewBox="0 0 24 24"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>',
  pencil: '<svg viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/></svg>',
  sparkle: '<svg viewBox="0 0 24 24"><path d="M11 3l1.9 5.1L18 10l-5.1 1.9L11 17l-1.9-5.1L4 10l5.1-1.9z"/><path d="M18.5 15l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/></svg>',
  flag: '<svg viewBox="0 0 24 24"><path d="M5 21V4"/><path d="M5 4h12l-2.5 4.5L17 13H5"/></svg>',
  clip: '<svg viewBox="0 0 24 24"><path d="M20 11.5l-8.2 8.2a5 5 0 0 1-7.1-7.1l8.6-8.6a3.4 3.4 0 0 1 4.8 4.8l-8.5 8.5a1.7 1.7 0 0 1-2.4-2.4l7.8-7.8"/></svg>',
  file: '<svg viewBox="0 0 24 24"><path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z"/><path d="M14 3v5h5"/></svg>',
  search: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></svg>',
};
function icon(name, cls = '') {
  const tpl = document.createElement('template');
  tpl.innerHTML = ICONS[name].trim();
  const svg = tpl.content.firstChild;
  svg.setAttribute('aria-hidden', 'true');
  if (cls) svg.setAttribute('class', cls);
  return svg;
}

function timeAgo(ts) {
  if (!ts) return '';
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return 'now';
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)}d`;
  if (s < 86400 * 30) return `${Math.floor(s / 604800)}w`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: s > 86400 * 300 ? 'numeric' : undefined });
}
function fmtDate(ts) {
  return ts ? new Date(ts * 1000).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '—';
}
function fmtBytes(n) {
  if (!n && n !== 0) return '—';
  const u = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`;
}
function hashHue(str) {
  let x = 0;
  for (const c of str || '') x = (x * 31 + c.charCodeAt(0)) | 0;
  return Math.abs(x) % 360;
}
function avatar(title, iconUrl) {
  const el = h('span', { class: 'avatar', style: { background: `hsl(${hashHue(title)} 55% 45%)` } });
  const letter = (title || '?').replace(/^r\//, '').trim().charAt(0).toUpperCase() || '?';
  if (iconUrl) {
    const img = h('img', { src: iconUrl, alt: '', loading: 'lazy', referrerpolicy: 'no-referrer', decoding: 'async' });
    img.onerror = () => { img.remove(); el.textContent = letter; };
    el.append(img);
  } else el.textContent = letter;
  return el;
}
const haptic = (ms = 10) => { try { navigator.vibrate?.(ms); } catch { /* unsupported */ } };
function safeUrl(u) {
  if (!u) return null;
  try { const x = new URL(u, location.href); return ['http:', 'https:'].includes(x.protocol) ? x.href : null; } catch { return null; }
}
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
};

/* ============================================================ API */

const state = { user: null, csrf: '', setupNeeded: false, version: '', ai: false };

function cookie(name) {
  const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : '';
}

class ApiError extends Error {
  constructor(msg, status) { super(msg); this.status = status; }
}

async function api(path, { method = 'GET', body, signal } = {}) {
  const opts = { method, credentials: 'same-origin', headers: { Accept: 'application/json' }, signal };
  if (method !== 'GET') {
    opts.headers['X-CSRF-Token'] = cookie('sf_csrf') || state.csrf;
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    if (e.name === 'AbortError') throw e;
    throw new ApiError('Network error. Are you online?', 0);
  }
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    let msg = data?.detail || `Error ${res.status}`;
    if (Array.isArray(msg)) msg = msg.map((d) => d.msg).join(', ');
    if (res.status === 401 && !path.startsWith('/api/login') && state.user) {
      state.user = null;
      render();
    }
    throw new ApiError(msg, res.status);
  }
  return data;
}

/* ============================================================ toast & sheets */

function toast(msg, { action, onAction, error = false, ms = 4000 } = {}) {
  const root = $('#toast-root');
  const el = h('div', { class: `toast${error ? ' err' : ''}`, role: 'status' }, h('span', {}, msg));
  let done = false;
  const close = () => { if (!done) { done = true; el.remove(); } };
  if (action) el.append(h('button', { type: 'button', onclick: () => { close(); onAction?.(); } }, action));
  root.append(el);
  while (root.children.length > 2) root.firstChild.remove();
  setTimeout(close, ms);
  return close;
}
const toastErr = (e) => { if (e?.name !== 'AbortError') toast(e?.message || String(e), { error: true }); };

let activeSheet = null;
function openSheet({ title, body, foot, tall = false, onClose }) {
  closeSheet();
  const root = $('#sheet-root');
  const backdrop = h('div', { class: 'sheet-backdrop', onclick: () => closeSheet() });
  const sheet = h('div', { class: `sheet${tall ? ' tall' : ''}`, role: 'dialog', 'aria-modal': 'true', 'aria-label': title },
    h('div', { class: 'sheet-handle' }),
    h('div', { class: 'sheet-head' }, h('h3', {}, title),
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Close', onclick: () => closeSheet() }, icon('close'))),
    h('div', { class: 'sheet-body' }, body),
    foot ? h('div', { class: 'sheet-foot' }, foot) : null);
  root.append(backdrop, sheet);

  // Keep the sheet above the on-screen keyboard (iOS does not resize the layout viewport).
  const vv = window.visualViewport;
  const fit = () => {
    if (!vv) return;
    const kb = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
    sheet.style.bottom = `${kb}px`;
    sheet.style.maxHeight = `${Math.min(vv.height - 12, 720)}px`;
    if (tall) sheet.style.height = kb > 0 ? `${Math.min(vv.height - 12, 720)}px` : '';
  };
  vv?.addEventListener('resize', fit);
  vv?.addEventListener('scroll', fit);
  fit();

  // Drag the handle down to close.
  let startY = null;
  const head = $('.sheet-head', sheet);
  const handle = $('.sheet-handle', sheet);
  for (const el of [head, handle]) {
    el.addEventListener('touchstart', (e) => { startY = e.touches[0].clientY; }, { passive: true });
    el.addEventListener('touchmove', (e) => {
      if (startY === null) return;
      const dy = Math.max(0, e.touches[0].clientY - startY);
      sheet.style.transform = `translate(-50%, ${dy}px)`;
    }, { passive: true });
    el.addEventListener('touchend', (e) => {
      const dy = (e.changedTouches[0]?.clientY ?? startY) - startY;
      startY = null;
      if (dy > 90) closeSheet(); else sheet.style.transform = '';
    });
  }
  const onKey = (e) => { if (e.key === 'Escape') closeSheet(); };
  document.addEventListener('keydown', onKey);
  activeSheet = {
    el: sheet,
    close: () => {
      vv?.removeEventListener('resize', fit);
      vv?.removeEventListener('scroll', fit);
      document.removeEventListener('keydown', onKey);
      backdrop.remove();
      sheet.remove();
      onClose?.();
    },
  };
  return sheet;
}
function closeSheet() {
  if (activeSheet) { const s = activeSheet; activeSheet = null; s.close(); }
}

/* ============================================================ reactions, seen, comments */

const seenQueue = { item: new Set(), short: new Set() };
async function flushSeen() {
  for (const type of ['item', 'short']) {
    const ids = [...seenQueue[type]].slice(0, 200);
    if (!ids.length) continue;
    ids.forEach((i) => seenQueue[type].delete(i));
    try { await api('/api/seen', { method: 'POST', body: { type, ids } }); } catch { ids.forEach((i) => seenQueue[type].add(i)); }
  }
}
setInterval(flushSeen, 3000);
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') flushSeen(); });

async function react(type, id, value) {
  return api('/api/react', { method: 'POST', body: { type, id, value } });
}

/** Wire a like + dislike button pair. `obj` holds {my, likes, dislikes}. */
function reactionButtons(type, obj, { onDislike, onChange, cls = 'act', showCounts = true } = {}) {
  const like = h('button', { type: 'button', class: `${cls} like`, 'aria-label': 'Like', 'aria-pressed': String(obj.my === 1) }, icon('heart'));
  const dis = h('button', { type: 'button', class: `${cls} dislike`, 'aria-label': 'Dislike', 'aria-pressed': String(obj.my === -1) }, icon('dislike'));
  const likeCount = h('span', {});
  const disCount = h('span', {});
  if (showCounts) { like.append(likeCount); dis.append(disCount); }
  const paint = () => {
    like.setAttribute('aria-pressed', String(obj.my === 1));
    dis.setAttribute('aria-pressed', String(obj.my === -1));
    likeCount.textContent = obj.likes ? String(obj.likes) : '';
    disCount.textContent = obj.dislikes ? String(obj.dislikes) : '';
  };
  paint();
  const set = async (value, btn) => {
    const prev = { my: obj.my, likes: obj.likes, dislikes: obj.dislikes };
    // optimistic
    if (obj.my === 1) obj.likes--;
    if (obj.my === -1) obj.dislikes--;
    if (value === 1) obj.likes++;
    if (value === -1) obj.dislikes++;
    obj.my = value;
    paint();
    haptic(value ? 12 : 6);
    btn.classList.remove('pop'); void btn.offsetWidth; btn.classList.add('pop');
    if (value === -1) onDislike?.(prev);
    try {
      const res = await react(type, obj.id, value);
      obj.likes = res.likes; obj.dislikes = res.dislikes; obj.my = res.value;
      if (res.why) obj.why = res.why;
      paint();
      onChange?.(res);
    } catch (e) {
      Object.assign(obj, prev);
      paint();
      toastErr(e);
    }
  };
  like.addEventListener('click', (e) => { e.stopPropagation(); set(obj.my === 1 ? 0 : 1, like); });
  dis.addEventListener('click', (e) => { e.stopPropagation(); set(obj.my === -1 ? 0 : -1, dis); });
  return { like, dis, paint, set };
}

function renderComment(c, onDelete) {
  const el = h('div', { class: 'comment' },
    h('div', { class: 'who' }, h('b', {}, c.user), h('span', {}, timeAgo(c.created_at)),
      c.can_delete ? h('button', { type: 'button', class: 'del', onclick: () => onDelete(c, el) }, 'Delete') : null),
    h('div', { class: 'text' }, c.body));
  return el;
}

/** Comment thread + composer. Returns {list, composer}. */
function commentThread(type, id, { onCount, compact = false } = {}) {
  const list = h('div', { class: 'comments' }, h('div', { class: 'muted small' }, 'Loading comments…'));
  let count = 0;
  const setCount = (n) => { count = n; onCount?.(n); };
  const onDelete = async (c, el) => {
    if (!confirm('Delete this comment?')) return;
    el.classList.add('pending');
    try {
      await api(`/api/comments/${c.id}`, { method: 'DELETE' });
      el.remove();
      setCount(count - 1);
      if (!list.children.length) list.append(emptyNote());
    } catch (e) { el.classList.remove('pending'); toastErr(e); }
  };
  const emptyNote = () => h('div', { class: 'muted small empty-note', style: { padding: '14px 0' } }, 'No comments yet. Say something!');
  api(`/api/comments?type=${type}&id=${id}`).then((d) => {
    list.replaceChildren(...(d.comments.length ? d.comments.map((c) => renderComment(c, onDelete)) : [emptyNote()]));
    setCount(d.comments.length);
  }).catch((e) => { list.replaceChildren(h('div', { class: 'error-msg' }, e.message)); });

  const ta = h('textarea', { class: 'input', rows: '1', maxlength: '2000', placeholder: 'Add a comment…', 'aria-label': 'Comment' });
  const autoGrow = () => { ta.style.height = 'auto'; ta.style.height = `${Math.min(ta.scrollHeight, 140)}px`; };
  ta.addEventListener('input', autoGrow);
  const send = h('button', { type: 'button', class: 'icon-btn', 'aria-label': 'Send', style: { color: 'var(--accent)' } }, icon('send'));
  const submit = async () => {
    const text = ta.value.trim();
    if (!text) return;
    if (text.length > 2000) { toast('Comment is too long (max 2000)', { error: true }); return; }
    const pending = renderComment({ user: state.user.username, body: text, created_at: Date.now() / 1000, can_delete: false }, onDelete);
    pending.classList.add('pending');
    $('.empty-note', list)?.remove();
    list.append(pending);
    ta.value = ''; autoGrow();
    pending.scrollIntoView({ block: 'nearest' });
    try {
      const c = await api('/api/comments', { method: 'POST', body: { type, id, body: text } });
      pending.replaceWith(renderComment(c, onDelete));
      setCount(count + 1);
      haptic(8);
    } catch (e) {
      pending.remove();
      ta.value = text;
      toastErr(e);
    }
  };
  send.addEventListener('click', submit);
  ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey && !compact) { e.preventDefault(); submit(); } });
  const composer = [ta, send];
  return { list, composer, focus: () => ta.focus() };
}

function openComments(type, id, { title = 'Comments', onCount } = {}) {
  const t = commentThread(type, id, { onCount });
  openSheet({ title, body: t.list, foot: t.composer, tall: true });
}

/* ============================================================ ask AI & priority */

const aiCache = new Map(); // "type:id" -> { text, note } of the last answer, kept while the page is open

/** "Ask AI" button for a post or Short; null when no LLM server is configured. */
function askButton(type, obj, cls = 'act') {
  if (!state.ai) return null;
  return h('button', { type: 'button', class: cls, 'aria-label': 'Ask AI', title: 'Ask AI', onclick: (e) => { e.stopPropagation(); openAsk(type, obj); } },
    icon('sparkle'), cls === 'act' ? null : h('span', {}, 'Ask'));
}

function openAsk(type, obj) {
  const key = `${type}:${obj.id}`;
  const out = h('div', { class: 'ai-answer', 'aria-live': 'polite' });
  const note = h('div', { class: 'muted small ai-note' });
  const q = h('textarea', { class: 'input', rows: '1', maxlength: '1000', placeholder: 'Ask anything about this…', 'aria-label': 'Question' });
  const stopBtn = h('button', { type: 'button', class: 'btn small', hidden: true, onclick: () => ctrl?.abort() }, 'Stop');
  let ctrl = null;
  const run = async (mode) => {
    if (mode === 'question' && !q.value.trim()) { q.focus(); return; }
    ctrl?.abort();
    const my = new AbortController();
    ctrl = my;
    let text = '';
    out.textContent = '';
    out.classList.add('loading');
    note.textContent = 'Thinking… local models can take a while.';
    stopBtn.hidden = false;
    try {
      const res = await fetch('/api/ai/ask', {
        method: 'POST', credentials: 'same-origin', signal: my.signal,
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': cookie('sf_csrf') || state.csrf },
        body: JSON.stringify({ type, id: obj.id, mode, question: mode === 'question' ? q.value : '' }),
      });
      if (!res.ok) {
        let msg = `Error ${res.status}`;
        try { msg = (await res.json()).detail || msg; } catch { /* not JSON */ }
        throw new Error(msg);
      }
      const label = `${res.headers.get('X-AI-Model') || 'AI'}${res.headers.get('X-AI-Article') === '1' ? ' · read the linked page' : ''}`;
      note.textContent = `${label} · answering…`;
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        text += dec.decode(value, { stream: true });
        out.textContent = text; // plain text only, never HTML
      }
      note.textContent = `${label} · AI answers can be wrong. Check important facts at the source.`;
      aiCache.set(key, { text, note: note.textContent });
    } catch (e) {
      if (e.name === 'AbortError') note.textContent = 'Stopped.';
      else { note.textContent = ''; out.textContent = text; out.append(h('div', { class: 'error-msg' }, e.message)); }
    } finally {
      out.classList.remove('loading');
      if (ctrl === my) stopBtn.hidden = true;
    }
  };
  const prev = aiCache.get(key);
  if (prev) { out.textContent = prev.text; note.textContent = prev.note; }
  const preset = (mode, label) => h('button', { type: 'button', class: 'btn small', onclick: () => run(mode) }, label);
  openSheet({
    title: 'Ask AI',
    tall: true,
    body: h('div', {},
      h('p', { class: 'ai-title' }, obj.title || '(untitled)'),
      h('div', { class: 'row ai-presets' }, preset('summary', 'Summarize'), preset('factcheck', 'Fact-check'), preset('explain', 'Explain')),
      note, out),
    foot: [q, stopBtn, h('button', { class: 'btn primary', type: 'button', 'aria-label': 'Ask', onclick: () => run('question') }, icon('send'))],
    onClose: () => ctrl?.abort(),
  });
}

const PRIORITIES = [['high', 'High'], ['medium', 'Medium'], ['low', 'Low']];
const priorityLabel = (p) => (PRIORITIES.find(([v]) => v === p) || [])[1] || '';

/** Flag button showing and changing this user's priority for a post or Short. */
function priorityButton(type, obj, cls = 'act') {
  const btn = h('button', { type: 'button', 'aria-label': 'Priority' });
  const paint = () => {
    btn.className = `${cls} prio${obj.priority ? ` prio-${obj.priority}` : ''}`;
    btn.title = obj.priority ? `Priority: ${priorityLabel(obj.priority)}` : 'Add to priority list';
    btn.replaceChildren(icon('flag'), h('span', {}, obj.priority ? priorityLabel(obj.priority) : (cls === 'act' ? '' : 'Priority')));
  };
  btn.addEventListener('click', (e) => { e.stopPropagation(); openPriority(type, obj, paint); });
  paint();
  return btn;
}

function openPriority(type, obj, onChange) {
  const pick = async (level) => {
    closeSheet();
    try {
      const r = await api('/api/me/priority', { method: 'POST', body: { type, id: obj.id, level } });
      obj.priority = r.priority;
      onChange?.();
      toast(r.priority ? `Priority: ${priorityLabel(r.priority)}` : 'Removed from your priority list', { ms: 1800 });
    } catch (e) { toastErr(e); }
  };
  openSheet({
    title: 'Priority',
    body: h('div', { class: 'menu-list' },
      ...PRIORITIES.map(([v, label]) => h('button', { type: 'button', class: `prio-${v}`, 'aria-pressed': String(obj.priority === v), onclick: () => pick(v) }, icon('flag'), label)),
      obj.priority ? h('button', { type: 'button', onclick: () => pick('none') }, icon('close'), 'Remove priority') : null),
  });
}

/* ============================================================ router */

/* ============================================================ appearance */

const THEMES = [['system', 'Auto'], ['dark', 'Dark'], ['black', 'Black'], ['light', 'Light']];
const ACCENTS = [['ember', 'Ember'], ['ocean', 'Ocean'], ['forest', 'Forest'], ['grape', 'Grape'], ['rose', 'Rose'], ['gold', 'Gold']];
const LAYOUTS = [['cards', 'Cards', 'Big cards with image'], ['compact', 'Compact', 'Dense list, small thumbnails'], ['magazine', 'Magazine', 'Edge-to-edge, image first']];

/** Apply the user's theme to <html>. Cached locally so the login page and next boot look the same. */
function applyTheme(prefs) {
  const p = { theme: 'system', accent: 'ember', layout: 'cards', ...(prefs || {}) };
  const root = document.documentElement;
  root.dataset.theme = p.theme;
  root.dataset.accent = p.accent;
  root.dataset.layout = p.layout;
  store.set('theme', { theme: p.theme, accent: p.accent, layout: p.layout });
  const bg = getComputedStyle(root).getPropertyValue('--bg').trim();
  if (bg) for (const m of $$('meta[name="theme-color"]')) m.setAttribute('content', bg);
}
applyTheme(store.get('theme', null));
matchMedia('(prefers-color-scheme: light)').addEventListener?.('change', () => applyTheme(store.get('theme', null)));

let cleanupView = null;
const routes = [
  [/^#\/feed$/, viewFeed],
  [/^#\/reels$/, viewReels],
  [/^#\/item\/(\d+)$/, viewItem],
  [/^#\/sources$/, viewSources],
  [/^#\/discover$/, viewDiscover],
  [/^#\/past$/, viewPast],
  [/^#\/account$/, viewAccount],
  [/^#\/activity$/, viewActivity],
  [/^#\/admin$/, viewAdmin],
];

function setTabs(active) {
  $('#tabbar').hidden = false;
  for (const t of $$('#tabbar [data-tab]')) {
    if (t.dataset.tab === active) t.setAttribute('aria-current', 'page'); else t.removeAttribute('aria-current');
  }
}

function render() {
  closeSheet();
  if (cleanupView) { const c = cleanupView; cleanupView = null; c(); }
  document.body.classList.remove('reels-mode', 'no-tabbar');
  const view = $('#view');
  const hash = location.hash || '#/feed';

  const inviteMatch = hash.match(/^#\/invite\/([A-Za-z0-9_-]{10,128})$/);
  if (inviteMatch && !state.user) { $('#tabbar').hidden = true; return viewRegister(view, inviteMatch[1]); }
  if (state.setupNeeded) { $('#tabbar').hidden = true; return viewSetup(view); }
  if (!state.user) { $('#tabbar').hidden = true; return viewLogin(view); }
  applyTheme(state.user);

  for (const [re, fn] of routes) {
    const m = hash.match(re);
    if (m) { window.scrollTo(0, 0); return fn(view, ...m.slice(1)); }
  }
  location.replace('#/feed');
}
window.addEventListener('hashchange', render);

/* ============================================================ auth views */

function authLayout(title, subtitle, form) {
  return h('div', { class: 'auth' }, h('div', { class: 'auth-box' },
    h('img', { class: 'logo', src: '/static/icons/icon.svg', alt: '' }),
    h('h1', {}, title), h('p', {}, subtitle), form));
}

function credForm({ submitLabel, onSubmit, confirmPw = false }) {
  const err = h('div', { class: 'error-msg', role: 'alert' });
  const user = h('input', { class: 'input', name: 'username', autocomplete: 'username', autocapitalize: 'none', spellcheck: 'false', required: true, minlength: '3', maxlength: '32', id: 'f-user' });
  const pw = h('input', { class: 'input', type: 'password', name: 'password', autocomplete: confirmPw ? 'new-password' : 'current-password', required: true, minlength: confirmPw ? '8' : '1', id: 'f-pw' });
  const pw2 = confirmPw ? h('input', { class: 'input', type: 'password', autocomplete: 'new-password', required: true, id: 'f-pw2' }) : null;
  const btn = h('button', { class: 'btn primary block', type: 'submit' }, submitLabel);
  const form = h('form', {
    onsubmit: async (e) => {
      e.preventDefault();
      err.textContent = '';
      if (pw2 && pw.value !== pw2.value) { err.textContent = 'Passwords do not match'; return; }
      btn.disabled = true;
      try { await onSubmit(user.value.trim(), pw.value); } catch (ex) { err.textContent = ex.message; } finally { btn.disabled = false; }
    },
  },
  h('div', { class: 'field' }, h('label', { for: 'f-user' }, 'Username'), user),
  h('div', { class: 'field' }, h('label', { for: 'f-pw' }, 'Password'), pw),
  pw2 ? h('div', { class: 'field' }, h('label', { for: 'f-pw2' }, 'Repeat password'), pw2) : null,
  err, btn);
  return form;
}

function viewSetup(view) {
  view.replaceChildren(authLayout('Welcome to Local DS', 'Create the admin account. This page only works once.',
    credForm({
      submitLabel: 'Create admin account', confirmPw: true,
      onSubmit: async (username, password) => {
        const r = await api('/api/setup', { method: 'POST', body: { username, password } });
        state.user = r.user; state.setupNeeded = false;
        location.hash = '#/discover';
        render();
      },
    })));
}

function viewLogin(view) {
  view.replaceChildren(authLayout('Local DS', 'Log in to continue.',
    credForm({
      submitLabel: 'Log in',
      onSubmit: async (username, password) => {
        const r = await api('/api/login', { method: 'POST', body: { username, password } });
        state.user = r.user;
        render();
      },
    })));
}

async function viewRegister(view, token) {
  view.replaceChildren(h('div', { class: 'boot' }, h('div', { class: 'spinner' })));
  try {
    await api(`/api/invite/${token}`);
  } catch (e) {
    view.replaceChildren(authLayout('Invite not valid', e.message, h('a', { class: 'btn block', href: '#/feed' }, 'Go to login')));
    return;
  }
  view.replaceChildren(authLayout('You are invited', 'Pick a username and password.',
    credForm({
      submitLabel: 'Create account', confirmPw: true,
      onSubmit: async (username, password) => {
        const r = await api('/api/register', { method: 'POST', body: { token, username, password } });
        state.user = r.user;
        location.hash = '#/feed';
        render();
      },
    })));
}

/* ============================================================ feed */

let feedCache = null; // keeps the feed DOM + scroll position while visiting an item

function skeletonCards(n = 3) {
  return Array.from({ length: n }, () => h('div', { class: 'card skeleton', 'aria-hidden': 'true' },
    h('div', { class: 'card-body' }, h('div', { class: 'sk sk-line', style: { width: '40%' } }), h('div', { class: 'sk sk-title' }),
      h('div', { class: 'sk sk-line' }), h('div', { class: 'sk sk-line', style: { width: '70%' } })),
    h('div', { class: 'sk sk-img' })));
}

function itemCard(item, ctx) {
  const card = h('article', { class: `card post${item.seen ? ' seen' : ''}`, dataset: { id: item.id } });
  const open = () => { ctx.saveScroll(); location.hash = `#/item/${item.id}`; };
  const img = item.image && safeUrl(item.image)
    ? h('img', { class: 'card-img', src: safeUrl(item.image), alt: '', loading: 'lazy', decoding: 'async', referrerpolicy: 'no-referrer', onclick: open })
    : null;
  if (img) img.onerror = () => img.remove();
  const atts = item.attachments || [];
  const firstVideo = !img ? atts.find((a) => a.kind === 'video') : null;
  const media = img || (firstVideo ? attachmentVideo(firstVideo, 'card-video') : null);
  const shown = img ? atts.find((a) => a.kind === 'image') : firstVideo;
  const more = atts.length - (shown ? 1 : 0);
  const why = h('p', { class: `why${item.explored ? ' explore' : ''}` }, ctx.mode === 'foryou' ? item.why : '');
  if (ctx.mode !== 'foryou') why.hidden = true;
  const body = h('div', { class: 'card-body', onclick: open, role: 'link', tabindex: '0', onkeydown: (e) => { if (e.key === 'Enter') open(); } },
    h('div', { class: 'meta' }, avatar(item.source.title, item.source.icon), h('span', { class: 'src' }, item.source.title),
      h('span', { class: 'dot' }), h('time', { datetime: new Date(item.published_at * 1000).toISOString() }, timeAgo(item.published_at))),
    h('h2', {}, item.title),
    item.excerpt ? h('p', { class: 'excerpt' }, item.excerpt) : null,
    more > 0 ? h('p', { class: 'att-count' }, icon('clip'), `${more} ${shown ? 'more ' : ''}attachment${more === 1 ? '' : 's'}`) : null,
    why);
  const commentsBtn = h('button', { type: 'button', class: 'act', 'aria-label': 'Comments', onclick: (e) => {
    e.stopPropagation();
    openComments('item', item.id, { title: item.title, onCount: (n) => { item.comments = n; cnt.textContent = n ? String(n) : ''; } });
  } }, icon('comment'));
  const cnt = h('span', {}, item.comments ? String(item.comments) : '');
  commentsBtn.append(cnt);
  const link = safeUrl(item.url);
  const rb = reactionButtons('item', item, {
    onDislike: (prev) => toast(`You'll see less from ${item.source.title}`, { action: 'Undo', onAction: () => rb.set(prev.my === -1 ? 0 : prev.my, rb.dis) }),
    onChange: (res) => { if (ctx.mode === 'foryou' && res.why) why.textContent = res.why; },
  });
  const delBtn = canDeletePost(item) ? h('button', { type: 'button', class: 'act', 'aria-label': 'Delete post', onclick: async (e) => {
    e.stopPropagation();
    if (await deletePost(item)) card.remove();
  } }, icon('trash')) : null;
  card.append(body, media || '', h('div', { class: 'actions' }, rb.like, rb.dis, commentsBtn, askButton('item', item),
    ctx.activity ? priorityButton('item', item) : null, delBtn,
    link ? h('a', { class: 'act grow', href: link, target: '_blank', rel: 'noopener noreferrer', 'aria-label': 'Open original', onclick: (e) => e.stopPropagation() }, icon('external')) : null));
  return card;
}

/* ============================================================ user posts */

const canDeletePost = (item) => item.source.kind === 'user' && (item.mine || state.user.is_admin);

async function deletePost(item) {
  if (!confirm('Delete this post? Its comments and reactions are deleted too.')) return false;
  try { await api(`/api/posts/${item.id}`, { method: 'DELETE' }); toast('Post deleted'); return true; } catch (e) { toastErr(e); return false; }
}

/** Upload one file as the raw request body; reports progress (fetch can't). Resolves to the attachment. */
function uploadFile(file, onProgress) {
  let xhr;
  const promise = new Promise((resolve, reject) => {
    xhr = new XMLHttpRequest();
    xhr.open('POST', `/api/uploads?name=${encodeURIComponent(file.name || 'file')}`);
    xhr.setRequestHeader('X-CSRF-Token', cookie('sf_csrf') || state.csrf);
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    xhr.onload = () => {
      let data = null;
      try { data = JSON.parse(xhr.responseText); } catch { /* empty */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new ApiError(data?.detail || (xhr.status === 413 ? 'File is too large' : `Upload failed (${xhr.status})`), xhr.status));
    };
    xhr.onerror = () => reject(new ApiError('Upload failed. Are you online?', 0));
    xhr.onabort = () => reject(new DOMException('aborted', 'AbortError'));
    xhr.send(file);
  });
  return { promise, abort: () => xhr.abort() };
}

const MAX_ATTACHMENTS = 10;

function openComposer(onPosted) {
  const title = h('input', { class: 'input', maxlength: '300', required: true, 'aria-label': 'Title', placeholder: 'Title' });
  const text = h('textarea', { class: 'input', rows: '6', maxlength: '10000', 'aria-label': 'Text', placeholder: 'Write something (optional)' });
  const url = h('input', { class: 'input', type: 'url', inputmode: 'url', maxlength: '2048', autocapitalize: 'none', spellcheck: 'false', 'aria-label': 'Link', placeholder: 'https://… (optional)' });
  const err = h('div', { class: 'error-msg' });
  const btn = h('button', { class: 'btn primary', type: 'submit' }, icon('send'), 'Post');
  // Files upload as soon as they are picked; the post only references their ids.
  const files = []; // { file, el, bar, att, up, error }
  const list = h('div', { class: 'att-list' });
  const picker = h('input', { type: 'file', multiple: true, hidden: true, onchange: () => { addFiles([...picker.files]); picker.value = ''; } });
  const addBtn = h('button', { class: 'btn', type: 'button', onclick: () => picker.click() }, icon('clip'), 'Add photos, videos or files');
  const busy = () => files.some((f) => !f.att && !f.error);
  const paintBtn = () => { btn.disabled = busy(); addBtn.disabled = files.length >= MAX_ATTACHMENTS; };
  const addFiles = (picked) => {
    for (const file of picked) {
      if (files.length >= MAX_ATTACHMENTS) { toast(`Up to ${MAX_ATTACHMENTS} files per post`); break; }
      const entry = { file, att: null, error: null };
      const bar = h('i', { style: { width: '0%' } });
      const status = h('span', { class: 'muted small' }, fmtBytes(file.size));
      const remove = h('button', { class: 'icon-btn', type: 'button', 'aria-label': `Remove ${file.name}`, onclick: () => {
        entry.up?.abort();
        if (entry.att) api(`/api/uploads/${entry.att.id}`, { method: 'DELETE' }).catch(() => {});
        files.splice(files.indexOf(entry), 1); entry.el.remove(); paintBtn();
      } }, icon('close'));
      const preview = file.type.startsWith('image/') ? h('img', { class: 'att-thumb', alt: '', src: URL.createObjectURL(file) }) : h('span', { class: 'att-thumb' }, icon('file'));
      entry.el = h('div', { class: 'att-row' }, preview,
        h('div', { class: 't' }, h('b', {}, file.name || 'file'), status, h('div', { class: 'bar small' }, bar)), remove);
      entry.up = uploadFile(file, (f) => { bar.style.width = `${Math.round(f * 100)}%`; status.textContent = `${Math.round(f * 100)}% of ${fmtBytes(file.size)}`; });
      entry.up.promise.then((att) => {
        entry.att = att; bar.style.width = '100%';
        status.textContent = `${fmtBytes(att.size)} · ${att.kind === 'file' ? 'file' : att.kind}`;
      }).catch((e) => {
        if (e.name === 'AbortError') return;
        entry.error = e; status.textContent = e.message; status.className = 'error-msg';
      }).finally(paintBtn);
      files.push(entry); list.append(entry.el);
    }
    paintBtn();
  };
  const form = h('form', { class: 'compose-form', onsubmit: async (e) => {
    e.preventDefault();
    err.textContent = '';
    if (!title.value.trim()) { err.textContent = 'Give your post a title.'; return; }
    if (busy()) { err.textContent = 'Wait for the uploads to finish.'; return; }
    if (files.some((f) => f.error)) { err.textContent = 'Remove the files that failed to upload first.'; return; }
    btn.disabled = true;
    try {
      const item = await api('/api/posts', { method: 'POST', body: { title: title.value, text: text.value, url: url.value, attachments: files.map((f) => f.att.id) } });
      files.length = 0;
      closeSheet();
      toast('Posted');
      onPosted?.(item);
    } catch (ex) { err.textContent = ex.message; } finally { paintBtn(); }
  } },
  h('div', { class: 'field' }, h('label', {}, 'Title'), title),
  h('div', { class: 'field' }, h('label', {}, 'Text'), text),
  h('div', { class: 'field' }, h('label', {}, 'Link'), url),
  h('div', { class: 'field' }, h('label', {}, 'Attachments'), list, addBtn, picker),
  err, btn);
  openSheet({ title: 'New post', body: form, tall: true });
  setTimeout(() => title.focus(), 50);
}

function attachmentVideo(a, cls = '') {
  const v = h('video', { class: cls, src: a.url, controls: true, playsinline: true, preload: 'metadata' });
  v.addEventListener('click', (e) => e.stopPropagation());
  return v;
}

/** Photos as a grid, videos and audio as players, everything else as download links. */
function attachmentsView(atts) {
  if (!atts?.length) return null;
  const images = atts.filter((a) => a.kind === 'image');
  return h('div', { class: 'attachments' },
    images.length ? h('div', { class: `att-grid n${Math.min(images.length, 3)}` },
      ...images.map((a) => h('a', { href: a.url, target: '_blank', rel: 'noopener', 'aria-label': `Open ${a.name}` }, h('img', { src: a.url, alt: a.name, loading: 'lazy' })))) : null,
    ...atts.filter((a) => a.kind === 'video').map((a) => attachmentVideo(a, 'att-video')),
    ...atts.filter((a) => a.kind === 'audio').map((a) => h('div', { class: 'att-audio' }, h('span', { class: 'small' }, a.name), h('audio', { src: a.url, controls: true, preload: 'metadata' }))),
    ...atts.filter((a) => a.kind === 'file').map((a) => h('a', { class: 'att-file', href: a.url, download: a.name },
      icon('file'), h('span', { class: 't' }, h('b', {}, a.name), h('span', {}, fmtBytes(a.size))))));
}

/** Admin: fetch all feeds + Shorts now, wait for the feed job, then call `done`. */
async function adminRefresh(btn, done) {
  if (btn.classList.contains('spinning')) return;
  btn.classList.add('spinning');
  try {
    const { started } = await api('/api/admin/refresh', { method: 'POST' });
    toast('Fetching all sources…', { ms: 2000 });
    for (let i = 0; i < 90; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      const rss = (await api('/api/admin/jobs')).jobs.rss;
      if (rss && !rss.running && rss.last_run >= started - 1) {
        toast(rss.ok ? `Feeds refreshed: ${rss.result} new posts. Shorts keep downloading in the background.` : `Refresh failed: ${rss.error}`, { error: !rss.ok, ms: 5000 });
        break;
      }
    }
    done?.();
  } catch (e) { toastErr(e); } finally { btn.classList.remove('spinning'); }
}

async function viewFeed(view) {
  setTabs('feed');
  const key = `${state.user.id}`;
  if (feedCache && feedCache.key === key) {
    view.replaceChildren(feedCache.el);
    requestAnimationFrame(() => window.scrollTo(0, feedCache.scrollY));
    feedCache.resume();
    cleanupView = feedCache.pause;
    return;
  }

  const st = {
    mode: state.user.feed_mode || 'latest',
    hideSeen: !!state.user.hide_seen,
    show: store.get('feed.show', 'all'), // all | liked | commented | disliked (unread = hideSeen)
    source: store.get('feed.source', null),
    cursor: null, done: false, loading: false, gen: 0, ids: new Set(),
  };
  const list = h('div', { class: 'list' });
  const sentinel = h('div', { class: 'sentinel' });
  const endNote = h('div', { class: 'end' });
  const ptr = h('div', { class: 'ptr' }, 'Pull to refresh');

  const modeLatest = h('button', { type: 'button', 'aria-pressed': String(st.mode === 'latest') }, 'Latest');
  const modeForYou = h('button', { type: 'button', 'aria-pressed': String(st.mode === 'foryou') }, 'For you');
  const seenBtn = h('button', { type: 'button', class: `icon-btn${st.hideSeen ? ' on' : ''}`, 'aria-label': 'Hide seen posts', title: 'Hide seen' }, icon(st.hideSeen ? 'eyeOff' : 'eye'));
  const chips = h('div', { class: 'chips', role: 'toolbar', 'aria-label': 'Filters' });
  const refreshBtn = state.user.is_admin
    ? h('button', { type: 'button', class: 'icon-btn', 'aria-label': 'Fetch all sources now', title: 'Fetch all sources now', onclick: () => adminRefresh(refreshBtn, () => reload()) }, icon('refresh'))
    : null;
  const fab = h('button', { type: 'button', class: 'fab', 'aria-label': 'New post', onclick: () => openComposer(() => { if (st.mode !== 'latest') setMode('latest'); else reload(); }) }, icon('pencil'));

  const ctx = {
    get mode() { return st.mode; },
    saveScroll: () => { if (feedCache) feedCache.scrollY = window.scrollY; },
  };

  const setMode = (m) => {
    st.mode = m;
    modeLatest.setAttribute('aria-pressed', String(m === 'latest'));
    modeForYou.setAttribute('aria-pressed', String(m === 'foryou'));
    state.user.feed_mode = m;
    api('/api/me/prefs', { method: 'PATCH', body: { feed_mode: m } }).catch(() => {});
    reload();
  };
  modeLatest.onclick = () => st.mode !== 'latest' && setMode('latest');
  modeForYou.onclick = () => st.mode !== 'foryou' && setMode('foryou');
  seenBtn.onclick = () => {
    st.hideSeen = !st.hideSeen;
    state.user.hide_seen = st.hideSeen;
    seenBtn.classList.toggle('on', st.hideSeen);
    seenBtn.replaceChildren(icon(st.hideSeen ? 'eyeOff' : 'eye'));
    api('/api/me/prefs', { method: 'PATCH', body: { hide_seen: st.hideSeen } }).catch(() => {});
    renderChips();
    toast(st.hideSeen ? 'Hiding posts you have already seen' : 'Showing seen posts too', { ms: 1800 });
    reload();
  };

  let sources = [];
  const setShow = (v) => { st.show = v; store.set('feed.show', v); };
  const setSource = (id) => { st.source = id; store.set('feed.source', id); };
  const pickSource = () => {
    // Reddit and YouTube each get their own section; blogs and people's posts below.
    const visible = sources.filter((s) => s.enabled && s.rss_enabled && s.manual !== 'mute');
    const groups = [['reddit', 'Reddit'], ['youtube', 'YouTube'], ['rss', 'Blogs & sites'], ['user', 'People'], ['demo', 'Demo']];
    const row = (s) => h('button', { type: 'button', class: `pick-row${st.source === s.id ? ' on' : ''}`, onclick: () => { closeSheet(); setSource(s.id); renderChips(); reload(); } },
      avatar(s.title, s.icon), h('span', { class: 't' }, s.title), st.source === s.id ? icon('check') : null);
    const sections = groups.map(([kind, label]) => {
      const list = visible.filter((s) => s.kind === kind);
      return list.length ? h('section', { class: 'pick-group' }, h('h4', {}, label, h('span', { class: 'muted' }, ` ${list.length}`)), ...list.map(row)) : null;
    }).filter(Boolean);
    openSheet({
      title: 'Show posts from',
      tall: true,
      body: h('div', {},
        h('button', { type: 'button', class: `pick-row${!st.source ? ' on' : ''}`, onclick: () => { closeSheet(); setSource(null); renderChips(); reload(); } },
          h('span', { class: 't' }, h('b', {}, 'All sources')), !st.source ? icon('check') : null),
        ...(sections.length ? sections : [h('p', { class: 'muted' }, 'No sources yet.')])),
    });
  };
  const renderChips = () => {
    const mk = (label, pressed, onclick, ico) => h('button', { type: 'button', class: 'chip', 'aria-pressed': String(pressed), onclick }, ico ? icon(ico) : null, label);
    const showChip = (value, label, ico) => mk(label, st.show === value, () => {
      setShow(st.show === value ? 'all' : value);
      if (st.hideSeen) seenBtn.click(); else { renderChips(); reload(); }
    }, ico);
    const current = sources.find((s) => s.id === st.source);
    chips.replaceChildren(
      mk('All', !st.source && !st.hideSeen && st.show === 'all', () => {
        setSource(null); setShow('all');
        if (st.hideSeen) seenBtn.click(); else { renderChips(); reload(); }
      }),
      mk('Unread', st.hideSeen, () => { if (!st.hideSeen) setShow('all'); seenBtn.click(); }, 'eye'),
      showChip('liked', 'Liked', 'heart'),
      showChip('commented', 'Commented', 'comment'),
      showChip('disliked', 'Disliked', 'dislike'),
      mk(current ? current.title : 'Sources', !!current, pickSource, 'sources'),
    );
  };
  api('/api/sources').then((d) => {
    sources = d.sources;
    if (st.source && !sources.some((s) => s.id === st.source)) setSource(null);
    renderChips();
  }).catch(() => renderChips());
  renderChips();

  const header = h('header', { class: 'topbar' },
    h('div', { class: 'topbar-row' }, h('h1', {}, 'Feed'), h('div', { class: 'segmented', role: 'group', 'aria-label': 'Sort' }, modeLatest, modeForYou), seenBtn, refreshBtn),
    chips);

  const root = h('div', {}, header, ptr, list, sentinel, endNote, fab);
  view.replaceChildren(root);

  // Seen tracking: a card counts as seen once it scrolls up past the top bar.
  const seenObs = new IntersectionObserver((entries) => {
    for (const en of entries) {
      if (!en.isIntersecting && en.boundingClientRect.bottom < (en.rootBounds?.top ?? 0) + 80) {
        const id = Number(en.target.dataset.id);
        if (!en.target.classList.contains('seen')) {
          en.target.classList.add('seen');
          seenQueue.item.add(id);
        }
        seenObs.unobserve(en.target);
      }
    }
  }, { threshold: 0 });

  const load = async () => {
    if (st.loading || st.done) return;
    st.loading = true;
    const gen = st.gen;
    const skel = skeletonCards(list.children.length ? 1 : 3);
    list.append(...skel);
    try {
      const params = new URLSearchParams({ mode: st.mode });
      if (st.cursor) params.set('cursor', st.cursor);
      if (st.source) params.set('source', st.source);
      params.set('show', st.hideSeen ? 'unread' : st.show);
      const d = await api(`/api/feed?${params}`);
      if (gen !== st.gen) return;
      skel.forEach((s) => s.remove());
      for (const it of d.items) {
        if (st.ids.has(it.id)) continue;
        st.ids.add(it.id);
        const c = itemCard(it, ctx);
        list.append(c);
        if (!it.seen) seenObs.observe(c);
      }
      st.cursor = d.cursor;
      st.done = !d.cursor;
      if (st.done) {
        endNote.replaceChildren(...(list.children.length
          ? [st.mode === 'foryou' ? 'You are all caught up. Switch to Latest for older posts.' : 'You reached the end.']
          : [emptyFeed()]));
      } else endNote.replaceChildren();
    } catch (e) {
      skel.forEach((s) => s.remove());
      if (gen === st.gen) endNote.replaceChildren(h('div', { class: 'error-msg' }, e.message), h('button', { class: 'btn small', onclick: () => load() }, 'Retry'));
    } finally {
      if (gen === st.gen) st.loading = false;
    }
    // Keep filling until the sentinel leaves the viewport.
    if (!st.done && gen === st.gen && sentinel.getBoundingClientRect().top < window.innerHeight + 600) load();
  };

  const emptyFeed = () => {
    const filtered = st.hideSeen || st.show !== 'all' || st.source;
    const msg = st.hideSeen ? ['Nothing unread', 'You have seen everything. Turn off "Unread" to see older posts.']
      : { liked: ['No liked posts', 'Posts you like show up here.'], commented: ['No commented posts', 'Posts you comment on show up here.'],
        disliked: ['No disliked posts', 'Posts you dislike show up here. Disliking only lowers a source, it never hides posts.'] }[st.show]
      || (st.source ? ['No posts from this source yet', 'It may still be fetching.'] : ['No posts yet', 'Add a few sources to fill your feed.']);
    return h('div', { class: 'empty' }, h('h3', {}, msg[0]), h('div', {}, msg[1]),
      filtered ? h('button', { class: 'btn', type: 'button', onclick: () => chips.firstChild.click() }, 'Show all posts')
        : h('a', { class: 'btn primary', href: '#/discover' }, icon('compass'), 'Discover sources'));
  };

  const reload = () => {
    st.gen++;
    st.cursor = null; st.done = false; st.loading = false; st.ids.clear();
    seenObs.disconnect();
    list.replaceChildren();
    endNote.replaceChildren();
    window.scrollTo(0, 0);
    load();
  };

  const moreObs = new IntersectionObserver((en) => { if (en[0].isIntersecting) load(); }, { rootMargin: '800px 0px' });
  moreObs.observe(sentinel);

  // Pull to refresh
  let startY = null; let pulling = 0;
  const onStart = (e) => { if (window.scrollY <= 0 && !activeSheet) startY = e.touches[0].clientY; };
  const onMove = (e) => {
    if (startY === null) return;
    pulling = Math.max(0, Math.min(120, (e.touches[0].clientY - startY) * 0.5));
    ptr.classList.add('active');
    ptr.style.height = `${pulling}px`;
    ptr.textContent = pulling > 60 ? 'Release to refresh' : 'Pull to refresh';
  };
  const onEnd = () => {
    if (startY === null) return;
    startY = null;
    ptr.classList.remove('active');
    if (pulling > 60) {
      ptr.textContent = 'Refreshing…'; ptr.style.height = '44px';
      haptic(15);
      reload();
      setTimeout(() => { ptr.style.height = '0'; }, 600);
    } else ptr.style.height = '0';
    pulling = 0;
  };
  const listeners = [['touchstart', onStart], ['touchmove', onMove], ['touchend', onEnd], ['touchcancel', onEnd]];
  const resume = () => listeners.forEach(([n, f]) => window.addEventListener(n, f, { passive: true }));
  const pause = () => {
    listeners.forEach(([n, f]) => window.removeEventListener(n, f));
    flushSeen();
  };
  resume();
  feedCache = { key, el: root, scrollY: 0, resume, pause };
  cleanupView = pause;
  load();
}

async function viewItem(view, id) {
  setTabs('feed');
  const back = h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Back', onclick: () => (history.length > 1 ? history.back() : (location.hash = '#/feed')) }, icon('back'));
  view.replaceChildren(h('header', { class: 'topbar' }, h('div', { class: 'topbar-row' }, back, h('h1', {}, ''))),
    h('div', { class: 'detail' }, ...skeletonCards(1)));
  let item;
  try { item = await api(`/api/items/${id}`); } catch (e) {
    view.replaceChildren(h('div', { class: 'empty' }, h('h3', {}, 'Could not load'), e.message));
    return;
  }
  seenQueue.item.add(item.id);
  const link = safeUrl(item.url);
  const prose = h('div', { class: 'prose' });
  prose.innerHTML = item.content_html || ''; // sanitized server-side (allowlist)
  if (!item.content_html && item.excerpt) prose.textContent = item.excerpt;
  for (const img of $$('img', prose)) img.onerror = () => img.remove();
  const firstImg = $('img', prose);
  const atts = attachmentsView(item.attachments);
  const hero = !firstImg && !atts && item.image && safeUrl(item.image)
    ? h('img', { class: 'hero-img', src: safeUrl(item.image), alt: '', referrerpolicy: 'no-referrer' }) : null;
  if (hero) hero.onerror = () => hero.remove();
  const countEl = h('span', {}, String(item.comments || 0));
  const rb = reactionButtons('item', item, {
    onDislike: (prev) => toast(`You'll see less from ${item.source.title}`, { action: 'Undo', onAction: () => rb.set(prev.my === -1 ? 0 : prev.my, rb.dis) }),
  });
  const delBtn = canDeletePost(item) ? h('button', { class: 'btn small danger', type: 'button', onclick: async () => {
    if (!(await deletePost(item))) return;
    if (feedCache) $(`.card[data-id="${item.id}"]`, feedCache.el)?.remove();
    history.length > 1 ? history.back() : (location.hash = '#/feed');
  } }, icon('trash'), 'Delete') : null;
  const thread = commentThread('item', item.id, { onCount: (n) => { countEl.textContent = String(n); } });
  view.replaceChildren(
    h('header', { class: 'topbar' }, h('div', { class: 'topbar-row' }, back,
      h('div', { class: 'meta', style: { flex: '1' } }, avatar(item.source.title, item.source.icon), h('span', { class: 'src' }, item.source.title)),
      link ? h('a', { class: 'icon-btn', href: link, target: '_blank', rel: 'noopener noreferrer', 'aria-label': 'Open original' }, icon('external')) : null)),
    h('article', { class: 'detail' },
      h('div', { class: 'meta' }, item.author ? h('span', {}, item.author) : null, item.author ? h('span', { class: 'dot' }) : null, h('span', {}, fmtDate(item.published_at))),
      h('h1', {}, item.title),
      h('p', { class: 'why' }, item.why),
      hero, prose, atts,
      h('div', { class: 'row', style: { paddingTop: '6px' } }, askButton('item', item, 'btn small'), priorityButton('item', item, 'btn small')),
      h('div', { class: 'actions', style: { padding: '10px 0' } }, rb.like, rb.dis, delBtn,
        link ? h('a', { class: 'btn small grow', style: { marginLeft: 'auto' }, href: link, target: '_blank', rel: 'noopener noreferrer' }, 'Open original', icon('external')) : null),
      h('div', { class: 'section-title' }, 'Comments (', countEl, ')'),
      thread.list,
      h('div', { class: 'inline-compose' }, ...thread.composer)));
}

/* ============================================================ reels */

const fmtClock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

/** Progress bar at the bottom of a Short: shows playback and can be dragged (or tapped) to seek. */
function scrubber(video) {
  const fill = h('i', {});
  const knob = h('b', {});
  const label = h('span', { class: 'scrub-time' });
  const track = h('div', { class: 'scrub-track' }, fill, knob);
  const el = h('div', { class: 'scrub', role: 'slider', tabindex: '0', 'aria-label': 'Seek', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': '0' }, label, track);
  let dragging = false;
  let wasPlaying = false;
  const paint = (f) => {
    const pct = `${Math.max(0, Math.min(1, f)) * 100}%`;
    fill.style.width = pct; knob.style.left = pct;
    el.setAttribute('aria-valuenow', String(Math.round(f * 100)));
    if (video.duration) {
      label.textContent = `${fmtClock(f * video.duration)} / ${fmtClock(video.duration)}`;
      el.setAttribute('aria-valuetext', label.textContent);
    }
  };
  video.addEventListener('timeupdate', () => { if (!dragging && video.duration) paint(video.currentTime / video.duration); });
  const fraction = (e) => {
    const r = track.getBoundingClientRect();
    return Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
  };
  const seek = (f) => { if (video.duration) video.currentTime = f * video.duration; paint(f); };
  el.addEventListener('pointerdown', (e) => {
    if (!video.duration) return;
    e.preventDefault(); e.stopPropagation();
    dragging = true; wasPlaying = !video.paused;
    video.pause();
    el.setPointerCapture(e.pointerId);
    el.classList.add('active');
    seek(fraction(e));
  });
  el.addEventListener('pointermove', (e) => { if (dragging) { e.preventDefault(); seek(fraction(e)); } });
  const end = (e) => {
    if (!dragging) return;
    dragging = false;
    el.classList.remove('active');
    try { el.releasePointerCapture(e.pointerId); } catch { /* already released */ }
    if (wasPlaying) video.play().catch(() => {});
  };
  el.addEventListener('pointerup', end);
  el.addEventListener('pointercancel', end);
  el.addEventListener('click', (e) => e.stopPropagation());
  el.addEventListener('keydown', (e) => {
    if (!video.duration) return;
    const step = { ArrowRight: 5, ArrowLeft: -5, ArrowUp: 5, ArrowDown: -5 }[e.key];
    if (step === undefined) return;
    e.preventDefault(); e.stopPropagation();
    seek(Math.max(0, Math.min(video.duration, video.currentTime + step)) / video.duration);
  });
  return el;
}

function viewReels(view) {
  setTabs('reels');
  document.body.classList.add('reels-mode');
  const muted = { value: store.get('reels.muted', state.user.muted !== false) };
  const reels = h('div', { class: 'reels', tabindex: '-1' });
  const muteTop = h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Toggle sound' });
  const top = h('div', { class: 'reels-top' }, h('h1', {}, 'Reels'), muteTop,
    h('a', { class: 'icon-btn', href: '#/past', 'aria-label': 'Past Shorts' }, icon('history')));
  view.replaceChildren(reels, top);

  const slides = []; // {el, video, data, srcSet}
  const exclude = new Set();
  let active = -1;
  let loading = false;
  let ended = false;
  let seenTimer = null;
  let userPaused = false;

  const paintMute = () => {
    const ic = icon(muted.value ? 'mute' : 'volume');
    muteTop.replaceChildren(ic);
    for (const s of slides) {
      s.video.muted = muted.value;
      const b = $('.mute-btn', s.el);
      if (b) b.replaceChildren(icon(muted.value ? 'mute' : 'volume'), h('span', {}, muted.value ? 'Muted' : 'Sound'));
    }
  };
  const toggleMute = () => {
    muted.value = !muted.value;
    store.set('reels.muted', muted.value);
    state.user.muted = muted.value;
    api('/api/me/prefs', { method: 'PATCH', body: { muted: muted.value } }).catch(() => {});
    paintMute();
    haptic(8);
    const cur = slides[active];
    if (cur && !muted.value && cur.video.paused && !userPaused) cur.video.play().catch(() => {});
  };
  muteTop.onclick = toggleMute;

  const setSrc = (s, preload) => {
    if (!s.srcSet && s.data.video) {
      s.video.preload = preload;
      s.video.src = s.data.video;
      s.srcSet = true;
    } else if (s.srcSet) s.video.preload = preload;
  };
  const dropSrc = (s) => {
    if (!s.srcSet) return;
    s.video.pause();
    s.video.removeAttribute('src');
    s.video.load(); // releases the decoder + buffered data
    s.srcSet = false;
  };

  // Paused: show a big play icon until playback resumes.
  const flashIndicator = (s, playing) => {
    const ind = $('.play-ind', s.el);
    if (playing) { ind.classList.remove('show'); return; }
    ind.replaceChildren(icon('play'));
    ind.classList.add('show');
  };

  const playActive = () => {
    const s = slides[active];
    if (!s) return;
    s.video.muted = muted.value;
    const p = s.video.play();
    p?.catch((err) => {
      if (err.name === 'NotAllowedError' && !muted.value) {
        // Autoplay with sound was blocked: fall back to muted.
        muted.value = true; paintMute();
        s.video.play().catch(() => {});
        toast('Tap the speaker icon to turn sound on', { ms: 2500 });
      }
    });
  };

  const setActive = (i) => {
    if (i === active || !slides[i]) return;
    active = i;
    userPaused = false;
    clearTimeout(seenTimer);
    slides.forEach((s, j) => {
      if (j === i) setSrc(s, 'auto');
      else if (j === i + 1) setSrc(s, 'auto'); // preload only the next one
      else dropSrc(s);
      if (j !== i) { s.video.pause(); $('.play-ind', s.el).classList.remove('show'); }
    });
    playActive();
    const cur = slides[i];
    if (!cur.data.seen) {
      seenTimer = setTimeout(() => { cur.data.seen = true; seenQueue.short.add(cur.data.id); }, 1500);
    }
    if (i >= slides.length - 3) load();
  };

  const observer = new IntersectionObserver((entries) => {
    for (const en of entries) {
      if (en.isIntersecting && en.intersectionRatio >= 0.6) setActive(Number(en.target.dataset.index));
    }
  }, { root: reels, threshold: [0.6] });

  const goTo = (i) => {
    const s = slides[i];
    if (s) s.el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const makeSlide = (d) => {
    const index = slides.length;
    const video = h('video', { playsinline: true, 'webkit-playsinline': true, loop: true, muted: true, preload: 'none', disablepictureinpicture: true, poster: d.thumb || null });
    video.muted = muted.value;
    const scrub = scrubber(video);
    video.addEventListener('error', async () => {
      if (!video.getAttribute('src')) return;
      const errEl = $('.info .err', el);
      try {
        const r = await fetch(d.video, { headers: { Range: 'bytes=0-0' }, credentials: 'same-origin' });
        errEl.textContent = r.status === 404 ? 'This Short just expired. It is in Past Shorts.' : 'This browser cannot play this video.';
      } catch { errEl.textContent = 'Could not load this video. Check your connection.'; }
      errEl.hidden = false;
    });
    const countEl = h('span', {}, d.comments ? String(d.comments) : 'Chat');
    const rb = reactionButtons('short', d, {
      cls: '', showCounts: false,
      onDislike: (prev) => {
        toast('Got it, fewer like this', { action: 'Undo', onAction: () => rb.set(prev.my === -1 ? 0 : prev.my, rb.dis) });
        setTimeout(() => goTo(index + 1), 250);
      },
    });
    rb.like.append(h('span', { class: 'cnt' }, 'Like'));
    rb.dis.append(h('span', {}, 'Nope'));
    const tap = h('div', { class: 'tap' });
    tap.addEventListener('click', () => {
      if (video.paused) { userPaused = false; video.play().catch(() => {}); flashIndicator(slide, true); } else { userPaused = true; video.pause(); flashIndicator(slide, false); }
    });
    const yt = safeUrl(d.url);
    const el = h('section', { class: 'slide', dataset: { index }, 'aria-label': d.title || 'Short' },
      d.thumb ? h('img', { class: 'poster', src: d.thumb, alt: '' }) : null,
      video, tap, h('div', { class: 'shade' }),
      h('div', { class: 'play-ind' }),
      h('div', { class: 'info' },
        h('div', { class: 'channel' }, avatar(d.channel, d.icon), h('span', {}, d.channel)),
        h('div', { class: 'title' }, d.title),
        h('div', { class: 'why' }, d.why),
        h('div', { class: 'err', hidden: true })),
      h('div', { class: 'rail' }, rb.like, rb.dis,
        h('button', { type: 'button', 'aria-label': 'Comments', onclick: () => openComments('short', d.id, { title: d.title || 'Comments', onCount: (n) => { d.comments = n; countEl.textContent = n ? String(n) : 'Chat'; } }) }, icon('comment'), countEl),
        state.ai ? h('button', { type: 'button', 'aria-label': 'Ask AI', onclick: () => openAsk('short', d) }, icon('sparkle'), h('span', {}, 'Ask')) : null,
        h('button', { type: 'button', class: 'mute-btn', 'aria-label': 'Toggle sound', onclick: toggleMute }, icon(muted.value ? 'mute' : 'volume'), h('span', {}, muted.value ? 'Muted' : 'Sound')),
        yt ? h('a', { href: yt, target: '_blank', rel: 'noopener noreferrer', 'aria-label': 'Open on YouTube', onclick: () => video.pause() }, icon('external'), h('span', {}, 'YouTube')) : null),
      scrub);
    const slide = { el, video, data: d, srcSet: false };
    slides.push(slide);
    reels.append(el);
    observer.observe(el);
  };

  const load = async () => {
    if (loading) return;
    loading = true;
    try {
      const d = await api('/api/reels/next', { method: 'POST', body: { exclude: [...exclude].slice(-4000), n: 6 } });
      if (d.reset) exclude.clear();
      for (const it of d.items) { exclude.add(it.id); makeSlide(it); }
      if (!slides.length) {
        ended = true;
        reels.replaceChildren(h('div', { class: 'reels-empty' }, h('div', {},
          h('h3', {}, 'No Shorts yet'),
          h('p', {}, 'Add a YouTube channel and its newest Shorts will be downloaded within a few minutes.'),
          h('a', { class: 'btn primary', href: '#/discover' }, icon('compass'), 'Find channels'), ' ',
          h('a', { class: 'btn', href: '#/past' }, 'Past Shorts'))));
      }
    } catch (e) {
      toastErr(e);
    } finally { loading = false; }
  };

  const onKey = (e) => {
    if (activeSheet || e.target.closest?.('input, textarea')) return;
    if (e.key === 'ArrowDown' || e.key === 'j') { e.preventDefault(); goTo(active + 1); }
    else if (e.key === 'ArrowUp' || e.key === 'k') { e.preventDefault(); goTo(active - 1); }
    else if (e.key === 'm') toggleMute();
    else if (e.key === ' ') { e.preventDefault(); $('.tap', slides[active]?.el)?.click(); }
  };
  document.addEventListener('keydown', onKey);
  const onVis = () => {
    const s = slides[active];
    if (!s) return;
    if (document.visibilityState === 'hidden') s.video.pause(); else if (!userPaused && !ended) playActive();
  };
  document.addEventListener('visibilitychange', onVis);
  paintMute();
  load();

  cleanupView = () => {
    observer.disconnect();
    clearTimeout(seenTimer);
    document.removeEventListener('keydown', onKey);
    document.removeEventListener('visibilitychange', onVis);
    slides.forEach(dropSrc);
    flushSeen();
    document.body.classList.remove('reels-mode');
  };
}

/* ============================================================ past shorts */

function viewPast(view) {
  setTabs('menu');
  const list = h('div', { class: 'list' });
  const sentinel = h('div', { class: 'sentinel' });
  const end = h('div', { class: 'end' });
  view.replaceChildren(
    h('header', { class: 'topbar' }, h('div', { class: 'topbar-row' },
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Back', onclick: () => history.back() }, icon('back')),
      h('h1', {}, 'Past Shorts'))),
    h('p', { class: 'page muted small', style: { margin: 0 } }, 'Video files are removed after the retention period. Titles, comments and reactions are kept forever.'),
    list, sentinel, end);
  let cursor = null; let done = false; let loading = false;
  const load = async () => {
    if (loading || done) return;
    loading = true;
    const sk = skeletonCards(list.children.length ? 1 : 2);
    list.append(...sk);
    try {
      const d = await api(`/api/shorts/past${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`);
      sk.forEach((s) => s.remove());
      for (const it of d.items) list.append(pastCard(it));
      cursor = d.cursor; done = !cursor;
      if (done) end.replaceChildren(list.children.length ? 'That is everything.' : h('div', { class: 'empty' }, h('h3', {}, 'No past Shorts yet'), `Shorts move here when their video file expires.`));
    } catch (e) { sk.forEach((s) => s.remove()); end.replaceChildren(h('div', { class: 'error-msg' }, e.message)); } finally { loading = false; }
  };
  const obs = new IntersectionObserver((en) => { if (en[0].isIntersecting) load(); }, { rootMargin: '600px 0px' });
  obs.observe(sentinel);
  cleanupView = () => obs.disconnect();
}

function pastCard(d, { priority = false } = {}) {
  const yt = safeUrl(d.url);
  const cnt = h('span', {}, d.comments ? String(d.comments) : '');
  const rb = reactionButtons('short', d, {});
  const thumb = d.thumb ? h('img', { src: d.thumb, alt: '', loading: 'lazy' }) : h('div', { class: 'ph' });
  return h('article', { class: 'card past' }, thumb,
    h('div', { class: 't' },
      h('div', { class: 'meta' }, h('span', { class: 'src' }, d.channel)),
      h('b', {}, d.title || '(untitled)'),
      h('div', { class: 'muted small' }, d.status === 'expired'
        ? `Published ${d.published_at ? timeAgo(d.published_at) : '—'} · expired ${timeAgo(d.expired_at)}`
        : d.status === 'available' ? 'Short · still in Reels' : 'Short'),
      h('div', { class: 'actions' }, rb.like, rb.dis,
        h('button', { type: 'button', class: 'act', 'aria-label': 'Comments', onclick: () => openComments('short', d.id, { title: d.title, onCount: (n) => { cnt.textContent = n ? String(n) : ''; } }) }, icon('comment'), cnt),
        askButton('short', d), priority ? priorityButton('short', d) : null,
        yt ? h('a', { class: 'act', href: yt, target: '_blank', rel: 'noopener noreferrer', 'aria-label': 'Open on YouTube' }, icon('external')) : null)));
}

/* ============================================================ menu */

$('#menu-btn').addEventListener('click', () => {
  const link = (href, ic, label) => h('a', { href, onclick: () => closeSheet() }, icon(ic), label);
  openSheet({
    title: 'Local DS',
    body: h('div', { class: 'menu-list' },
      link('#/activity', 'heart', 'Your activity'),
      link('#/sources', 'sources', 'Sources'),
      link('#/discover', 'compass', 'Discover'),
      link('#/past', 'history', 'Past Shorts'),
      link('#/account', 'user', 'Account'),
      state.user?.is_admin ? link('#/admin', 'shield', 'Admin') : null),
  });
});

/* ============================================================ sources */

function statusBadge(s) {
  if (!s.enabled) return h('span', { class: 'badge' }, 'Disabled');
  if (s.status === 'ok') return h('span', { class: 'badge ok' }, 'OK');
  if (s.status === 'new') return h('span', { class: 'badge' }, 'Pending');
  if (s.status === 'rate_limited') return h('span', { class: 'badge warn' }, 'Rate limited');
  if (s.status === 'blocked') return h('span', { class: 'badge warn' }, 'Blocked');
  return h('span', { class: 'badge err' }, 'Error');
}

function viewSources(view) {
  setTabs('menu');
  const input = h('input', { class: 'input', placeholder: 'URL, r/subreddit, @youtube or feed', autocapitalize: 'none', spellcheck: 'false', 'aria-label': 'Source', enterkeyhint: 'go' });
  const alsoRss = h('input', { type: 'checkbox', checked: true });
  const err = h('div', { class: 'error-msg' });
  const btn = h('button', { class: 'btn primary', type: 'submit' }, icon('plus'), 'Add');
  const list = h('div', { class: 'list', style: { padding: '0' } });
  const form = h('form', { class: 'panel', onsubmit: async (e) => {
    e.preventDefault();
    err.textContent = '';
    const v = input.value.trim();
    if (!v) return;
    btn.disabled = true; btn.replaceChildren(h('span', { class: 'spinner', style: { width: '18px', height: '18px', borderWidth: '2px' } }), 'Adding…');
    try {
      const r = await api('/api/sources', { method: 'POST', body: { input: v, also_rss: alsoRss.checked } });
      input.value = '';
      toast(r.created ? `Added ${r.source.title}` : `${r.source.title} is already added`);
      feedCache = null;
      refresh();
    } catch (ex) { err.textContent = ex.message; } finally { btn.disabled = false; btn.replaceChildren(icon('plus'), 'Add'); }
  } },
  h('h3', {}, 'Add a source'),
  h('div', { class: 'row', style: { flexWrap: 'nowrap' } }, input, btn),
  h('label', { class: 'check' }, alsoRss, 'For YouTube: also show regular videos in the Feed tab'),
  h('div', { class: 'muted small' }, 'Paste a website (feed is auto-detected), an RSS/Atom URL, a subreddit like ', h('b', {}, 'selfhosted'), ', or a YouTube channel like ', h('b', {}, '@JeffGeerling'), '.'),
  err);

  view.replaceChildren(
    h('header', { class: 'topbar' }, h('div', { class: 'topbar-row' }, h('h1', {}, 'Sources'),
      h('a', { class: 'btn small', href: '#/discover' }, icon('compass'), 'Discover'))),
    h('div', { class: 'page' }, form, list));

  let timer = null;
  const refresh = async () => {
    clearTimeout(timer);
    try {
      const d = await api('/api/sources');
      list.replaceChildren(...(d.sources.length ? d.sources.map(sourceCard) : [h('div', { class: 'empty' }, h('h3', {}, 'No sources yet'), 'Add one above or browse Discover.')]));
      if (d.sources.some((s) => s.status === 'new')) timer = setTimeout(refresh, 5000);
    } catch (e) { list.replaceChildren(h('div', { class: 'error-msg' }, e.message)); }
  };

  const sourceCard = (s) => {
    const patch = async (body) => {
      try { await api(`/api/sources/${s.id}`, { method: 'PATCH', body }); feedCache = null; refresh(); } catch (e) { toastErr(e); }
    };
    const enabled = h('input', { type: 'checkbox', checked: s.enabled, 'aria-label': 'Enabled', onchange: (e) => patch({ enabled: e.target.checked }) });
    const kindLabel = { reddit: 'Reddit', youtube: 'YouTube', rss: 'RSS', demo: 'Demo', user: 'Posts' }[s.kind] || s.kind;
    let errText = null;
    if (s.last_error && s.enabled) {
      errText = s.last_error + (s.backoff_until ? ` Next try ${new Date(s.backoff_until * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}.` : '');
    }
    const counts = [s.item_count ? `${s.item_count} posts` : null, s.kind === 'youtube' ? `${s.shorts_available} Shorts on disk` : null].filter(Boolean).join(' · ');
    return h('div', { class: 'card src-card' },
      h('div', { class: 'src-head' }, avatar(s.title, s.icon),
        h('div', { class: 't' }, h('b', {}, s.title),
          h('span', { class: 'muted small' }, kindLabel, ' · ', s.kind === 'user' ? 'posted in Local DS' : s.last_fetched ? `fetched ${timeAgo(s.last_fetched)} ago` : 'not fetched yet')),
        statusBadge(s),
        h('label', { class: 'toggle' }, enabled, h('span', {}))),
      h('div', { class: 'share', title: `${s.share}% of your feed` }, h('i', { style: { width: `${Math.min(100, s.share * 2)}%` } })),
      h('div', { class: 'muted small' }, s.manual === 'mute' ? 'Muted for you' : `${s.share}% of your feed · weight ${s.weight.toFixed(2)}x`, counts ? ` · ${counts}` : ''),
      h('div', { class: 'why', style: { marginTop: '4px' } }, s.why),
      errText ? h('div', { class: 'src-err' }, errText) : null,
      h('div', { class: 'src-actions' },
        h('button', { class: 'btn small', type: 'button', 'aria-pressed': String(s.manual === 'boost'), onclick: () => patch({ manual: s.manual === 'boost' ? 'none' : 'boost' }) }, s.manual === 'boost' ? 'Unboost' : 'Boost'),
        h('button', { class: 'btn small', type: 'button', onclick: () => patch({ manual: s.manual === 'mute' ? 'none' : 'mute' }) }, s.manual === 'mute' ? 'Unmute' : 'Mute'),
        h('button', { class: 'btn small', type: 'button', onclick: async () => {
          try { await api(`/api/sources/${s.id}/reset`, { method: 'POST' }); toast('Weight reset to 1.0'); refresh(); } catch (e) { toastErr(e); }
        } }, 'Reset'),
        s.kind !== 'demo' && s.kind !== 'user' ? h('button', { class: 'btn small', type: 'button', 'aria-label': 'Refresh now', onclick: async () => {
          try { await api(`/api/sources/${s.id}/refresh`, { method: 'POST' }); toast('Refreshing in the background'); setTimeout(refresh, 4000); } catch (e) { toastErr(e); }
        } }, icon('refresh')) : null,
        s.kind === 'youtube' ? h('button', { class: 'btn small', type: 'button', onclick: () => patch({ rss_enabled: !s.rss_enabled }) }, s.rss_enabled ? 'Hide videos in Feed' : 'Show videos in Feed') : null,
        state.user.is_admin ? h('button', { class: 'btn small danger', type: 'button', onclick: async () => {
          if (!confirm(`Remove ${s.title}? Posts with comments or reactions are kept.`)) return;
          try { await api(`/api/sources/${s.id}`, { method: 'DELETE' }); feedCache = null; toast('Source removed'); refresh(); } catch (e) { toastErr(e); }
        } }, icon('trash')) : null));
  };
  refresh();
  cleanupView = () => clearTimeout(timer);
}

/* ============================================================ discover */

function discoverRow(item, onAdded) {
  const added = { value: !!item.added };
  const btn = h('button', { class: `btn small${added.value ? '' : ' primary'}`, type: 'button', disabled: added.value });
  const paint = () => btn.replaceChildren(...(added.value ? [icon('check'), 'Added'] : [icon('plus'), 'Add']));
  paint();
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    btn.replaceChildren(h('span', { class: 'spinner', style: { width: '16px', height: '16px', borderWidth: '2px' } }));
    try {
      const r = await api('/api/sources', { method: 'POST', body: { input: item.input, topics: item.topics || null } });
      added.value = true; paint();
      feedCache = null;
      haptic(12);
      toast(r.created ? `Added ${r.source.title}` : `${r.source.title} was already added`);
      onAdded?.();
    } catch (e) { btn.disabled = false; paint(); toastErr(e); }
  });
  const kindLabel = { reddit: 'Reddit', youtube: 'YouTube', rss: 'Blog / RSS' }[item.kind] || item.kind;
  return h('div', { class: 'disc-item' }, avatar(item.title),
    h('div', { class: 't' }, h('b', {}, item.title), h('span', {}, item.reason || item.subtitle || `${kindLabel} · ${(item.topics || []).join(', ')}`)),
    btn);
}

function viewDiscover(view) {
  setTabs('menu');
  // The switch filters everything on the page: search, Suggested and the starter lists.
  let kind = 'all';
  const q = h('input', { class: 'input', type: 'search', 'aria-label': 'Search', enterkeyhint: 'search' });
  const kinds = [['all', 'All'], ['youtube', 'YouTube'], ['reddit', 'Reddit']];
  const kindBtns = kinds.map(([k, label]) => h('button', { type: 'button', 'aria-pressed': String(k === kind), onclick: () => setKind(k) }, label));
  const results = h('div', {});
  const suggested = h('div', {}, h('div', { class: 'muted small' }, 'Loading…'));
  const starter = h('div', {});
  let suggestedItems = null;
  let starterItems = null;
  let affinity = {};
  const matches = (i) => kind === 'all' || i.kind === kind;
  const searchKind = async (k, text, signal) => {
    const d = await api(`/api/discover/search?kind=${k}&q=${encodeURIComponent(text)}`, { signal });
    return { items: d.items, error: d.error };
  };
  let ctrl = null;
  const search = async () => {
    const text = q.value.trim();
    if (text.length < 2) { ctrl?.abort(); results.replaceChildren(); return; }
    ctrl?.abort(); ctrl = new AbortController();
    const signal = ctrl.signal;
    const msg = { all: 'Searching YouTube and Reddit (takes a few seconds)…', youtube: 'Searching YouTube (takes a few seconds)…', reddit: 'Searching Reddit…' }[kind];
    results.replaceChildren(h('div', { class: 'muted small', style: { padding: '10px 0' } }, msg));
    try {
      const parts = await Promise.all((kind === 'all' ? ['reddit', 'youtube'] : [kind]).map((k) => searchKind(k, text, signal)));
      const items = parts.flatMap((r) => r.items);
      const error = parts.map((r) => r.error).filter(Boolean).join(' · ');
      results.replaceChildren(...(items.length ? items.map((i) => discoverRow(i)) : [h('div', { class: 'muted small' }, error || 'No results')]),
        ...(items.length && error ? [h('div', { class: 'muted small' }, error)] : []));
    } catch (e) { if (e.name !== 'AbortError') results.replaceChildren(h('div', { class: 'error-msg' }, e.message)); }
  };
  const paintSuggested = () => {
    if (!suggestedItems) return;
    const items = suggestedItems.slice(0, 8);
    suggested.replaceChildren(...(items.length ? items.map((i) => discoverRow(i, loadSuggested))
      : [h('div', { class: 'muted small' }, { all: 'You have added everything we know about!', youtube: 'You have added every channel we know about!', reddit: 'You have added every subreddit we know about!' }[kind])]));
  };
  const paintStarter = () => {
    if (!starterItems) return;
    const groups = new Map();
    for (const it of starterItems.filter(matches)) {
      const g = it.topics[0];
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g).push(it);
    }
    const names = { tech: 'Tech', homelab: 'Homelab & self-hosting', pc: 'PC & gaming', science: 'Science', '3dprinting': 'Making & 3D printing', maker: 'Making & 3D printing', humor: 'Humor', news: 'News', food: 'Food', gaming: 'Gaming' };
    // Topics you like, comment on (and don't dislike) come first.
    const ordered = [...groups.entries()].sort(([a], [b]) => (affinity[b] || 0) - (affinity[a] || 0));
    starter.replaceChildren(...ordered.map(([g, items]) => h('div', { class: 'panel' },
      h('h3', {}, names[g] || g), ...items.map((i) => discoverRow(i, loadSuggested)))));
  };
  const setKind = (k) => {
    kind = k;
    kindBtns.forEach((b, i) => b.setAttribute('aria-pressed', String(kinds[i][0] === k)));
    q.placeholder = { all: 'Search channels and subreddits', youtube: 'Search YouTube channels', reddit: 'Search subreddits' }[k];
    search();
    loadSuggested();
    paintStarter();
  };

  view.replaceChildren(
    h('header', { class: 'topbar' }, h('div', { class: 'topbar-row' }, h('h1', {}, 'Discover'),
      h('a', { class: 'btn small', href: '#/sources' }, 'Sources'))),
    h('div', { class: 'page' },
      h('form', { class: 'panel', onsubmit: (e) => { e.preventDefault(); q.blur(); search(); } },
        h('div', { class: 'row', style: { flexWrap: 'nowrap', marginBottom: '10px' } }, q,
          h('button', { class: 'icon-btn', type: 'submit', 'aria-label': 'Search' }, icon('search'))),
        h('div', { class: 'segmented wide', role: 'group', 'aria-label': 'Show' }, ...kindBtns),
        results),
      h('div', { class: 'panel' }, h('h3', {}, 'Suggested for you'),
        h('p', { class: 'muted small', style: { margin: '0 0 6px' } }, 'Ranked by the topics of the sources you keep and the posts you like.'),
        suggested),
      starter));
  // Suggestions are ranked on the server from your likes, dislikes and comments, separately per kind.
  let sugCtrl = null;
  const loadSuggested = () => {
    sugCtrl?.abort(); sugCtrl = new AbortController();
    const qs = kind === 'all' ? '' : `?kind=${kind}`;
    return api(`/api/discover/suggested${qs}`, { signal: sugCtrl.signal }).then((d) => { suggestedItems = d.items; paintSuggested(); })
      .catch((e) => { if (e.name !== 'AbortError') suggested.replaceChildren(h('div', { class: 'error-msg' }, e.message)); });
  };
  setKind(kind);
  api('/api/discover/starter').then((d) => { starterItems = d.items; affinity = d.affinity || {}; paintStarter(); }).catch(toastErr);
}

/* ============================================================ account & admin */

function viewAccount(view) {
  setTabs('menu');
  const err = h('div', { class: 'error-msg' });
  const cur = h('input', { class: 'input', type: 'password', autocomplete: 'current-password', required: true, id: 'pw-cur' });
  const nw = h('input', { class: 'input', type: 'password', autocomplete: 'new-password', required: true, minlength: '8', id: 'pw-new' });
  view.replaceChildren(
    h('header', { class: 'topbar' }, h('div', { class: 'topbar-row' }, h('h1', {}, 'Account'))),
    h('div', { class: 'page' },
      h('div', { class: 'panel' }, h('h3', {}, state.user.username),
        h('div', { class: 'muted small' }, state.user.is_admin ? 'Administrator' : 'Member', ` · Local DS ${state.version}`),
        h('div', { class: 'row', style: { marginTop: '12px' } },
          state.user.is_admin ? h('a', { class: 'btn small', href: '#/admin' }, icon('shield'), 'Admin') : null,
          h('button', { class: 'btn small danger', type: 'button', onclick: async () => {
            try { await api('/api/logout', { method: 'POST' }); } catch { /* ignore */ }
            state.user = null; feedCache = null; location.hash = '#/feed'; render();
          } }, 'Log out'))),
      h('a', { class: 'panel link-panel', href: '#/activity' }, icon('heart'),
        h('div', {}, h('b', {}, 'Your activity'), h('div', { class: 'muted small' }, 'Everything you liked, disliked or commented on'))),
      appearancePanel(),
      h('form', { class: 'panel', onsubmit: async (e) => {
        e.preventDefault(); err.textContent = '';
        try {
          await api('/api/account/password', { method: 'POST', body: { current: cur.value, new: nw.value } });
          cur.value = ''; nw.value = '';
          toast('Password changed. Other devices were logged out.');
        } catch (ex) { err.textContent = ex.message; }
      } },
      h('h3', {}, 'Change password'),
      h('div', { class: 'field' }, h('label', { for: 'pw-cur' }, 'Current password'), cur),
      h('div', { class: 'field' }, h('label', { for: 'pw-new' }, 'New password (8+ characters)'), nw),
      err, h('button', { class: 'btn primary', type: 'submit' }, 'Change password')),
      h('div', { class: 'panel' }, h('h3', {}, 'Install the app'),
        h('p', { class: 'muted small', style: { margin: 0 } }, 'iPhone: Safari → Share → Add to Home Screen. Android: Chrome menu → Install app.'))));
}

function appearancePanel() {
  const save = (key, value) => {
    state.user[key] = value;
    applyTheme(state.user);
    paint();
    api('/api/me/prefs', { method: 'PATCH', body: { [key]: value } }).catch(toastErr);
  };
  const themeRow = h('div', { class: 'segmented wide', role: 'group', 'aria-label': 'Theme' });
  const accentRow = h('div', { class: 'swatches', role: 'group', 'aria-label': 'Color' });
  const layoutRow = h('div', { class: 'layout-picks', role: 'group', 'aria-label': 'Feed layout' });
  const paint = () => {
    themeRow.replaceChildren(...THEMES.map(([v, label]) => h('button', { type: 'button', 'aria-pressed': String(state.user.theme === v), onclick: () => save('theme', v) }, label)));
    accentRow.replaceChildren(...ACCENTS.map(([v, label]) => h('button', { type: 'button', class: 'swatch', dataset: { accent: v }, 'aria-label': label, title: label, 'aria-pressed': String(state.user.accent === v), onclick: () => save('accent', v) }, state.user.accent === v ? icon('check') : '')));
    layoutRow.replaceChildren(...LAYOUTS.map(([v, label, desc]) => h('button', { type: 'button', class: 'layout-pick', dataset: { layout: v }, 'aria-pressed': String(state.user.layout === v), onclick: () => save('layout', v) },
      h('span', { class: 'lp-preview', 'aria-hidden': 'true' }, h('i'), h('i'), h('i')), h('b', {}, label), h('span', { class: 'muted small' }, desc))));
  };
  paint();
  return h('div', { class: 'panel' }, h('h3', {}, 'Appearance'),
    h('div', { class: 'field' }, h('label', {}, 'Theme'), themeRow),
    h('div', { class: 'field' }, h('label', {}, 'Color'), accentRow),
    h('div', { class: 'field', style: { marginBottom: 0 } }, h('label', {}, 'Feed layout'), layoutRow));
}

/* ============================================================ activity */

function viewActivity(view) {
  setTabs('menu');
  const kinds = [['liked', 'Liked'], ['disliked', 'Disliked'], ['commented', 'Commented'], ['priority', 'Priority list']];
  const f = { kind: 'liked', q: '', type: 'all', source: '', priority: 'any', sort: 'recent', ...store.get('activity.filters', {}) };
  const save = () => store.set('activity.filters', { ...f, q: '', source: '' });
  const tabs = h('div', { class: 'chips', role: 'toolbar', 'aria-label': 'Show' });
  const list = h('div', { class: 'list' });
  const sentinel = h('div', { class: 'sentinel' });
  const end = h('div', { class: 'end' });
  const count = h('div', { class: 'muted small' });
  const ctx = { mode: 'latest', activity: true, saveScroll: () => {} };
  let cursor = null; let done = false; let loading = false; let gen = 0; let searchTimer = null;

  const select = (label, key, options) => {
    const el = h('select', { class: 'input', 'aria-label': label, onchange: () => { f[key] = el.value; save(); reset(); } },
      ...options.map(([v, l]) => h('option', { value: v }, l)));
    el.value = f[key];
    return el;
  };
  const typeSel = select('Type', 'type', [['all', 'Posts and Shorts'], ['item', 'Posts only'], ['short', 'Shorts only']]);
  const prioSel = select('Priority filter', 'priority', [['any', 'Any priority'], ['set', 'Has a priority'], ['high', 'High'], ['medium', 'Medium'], ['low', 'Low'], ['none', 'No priority']]);
  const sortSel = select('Sort', 'sort', [['recent', 'Newest first'], ['oldest', 'Oldest first'], ['priority', 'By priority'], ['popular', 'Most liked & discussed']]);
  const sourceSel = select('Source', 'source', [['', 'All sources']]);
  const search = h('input', { class: 'input', type: 'search', placeholder: 'Search titles and sources', 'aria-label': 'Search', enterkeyhint: 'search',
    oninput: () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { f.q = search.value.trim(); reset(); }, 300); } });

  const paintTabs = () => tabs.replaceChildren(...kinds.map(([v, label]) => h('button', { type: 'button', class: 'chip', 'aria-pressed': String(f.kind === v),
    onclick: () => {
      if (f.kind === v) return;
      f.kind = v;
      if (v === 'priority' && f.sort === 'recent') { f.sort = 'priority'; sortSel.value = 'priority'; }
      save(); paintTabs(); reset();
    } }, v === 'priority' ? icon('flag') : null, label)));

  const load = async () => {
    if (loading || done) return;
    loading = true;
    const g = gen;
    const sk = skeletonCards(list.children.length ? 1 : 2);
    list.append(...sk);
    try {
      const params = new URLSearchParams({ kind: f.kind, type: f.type, priority: f.priority, sort: f.sort });
      if (f.q) params.set('q', f.q);
      if (f.source) params.set('source', f.source);
      if (cursor) params.set('cursor', cursor);
      const d = await api(`/api/me/activity?${params}`);
      if (g !== gen) return;
      sk.forEach((s) => s.remove());
      if (d.sources) {
        sourceSel.replaceChildren(h('option', { value: '' }, 'All sources'),
          ...d.sources.map((s) => h('option', { value: String(s.id) }, `${s.title} (${s.count})`)));
        sourceSel.value = d.sources.some((s) => String(s.id) === f.source) ? f.source : '';
        count.textContent = `${d.total} ${d.total === 1 ? 'result' : 'results'}`;
      }
      for (const it of d.items) list.append(it.type === 'item' ? itemCard(it, ctx) : pastCard(it, { priority: true }));
      cursor = d.cursor; done = !cursor;
      const filtered = f.q || f.source || f.type !== 'all' || f.priority !== 'any';
      const empty = filtered ? 'Nothing matches these filters'
        : { liked: 'Nothing liked yet', disliked: 'Nothing disliked yet', commented: 'No comments yet', priority: 'Your priority list is empty' }[f.kind];
      const hint = f.kind === 'priority' && !filtered ? 'Tap the flag on any post here, or in the reader view, to add it.' : 'Posts and Shorts you react to or comment on are saved here.';
      if (done) end.replaceChildren(list.children.length ? 'That is everything.' : h('div', { class: 'empty' }, h('h3', {}, empty), hint));
    } catch (e) { sk.forEach((s) => s.remove()); if (g === gen) end.replaceChildren(h('div', { class: 'error-msg' }, e.message)); } finally { if (g === gen) loading = false; }
    if (!done && g === gen && sentinel.getBoundingClientRect().top < window.innerHeight + 600) load();
  };
  const reset = () => { gen++; cursor = null; done = false; loading = false; list.replaceChildren(); end.replaceChildren(); load(); };
  paintTabs();
  view.replaceChildren(
    h('header', { class: 'topbar' }, h('div', { class: 'topbar-row' },
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Back', onclick: () => history.back() }, icon('back')),
      h('h1', {}, 'Your activity')), tabs),
    h('div', { class: 'activity-filters' }, search, h('div', { class: 'filter-grid' }, typeSel, sourceSel, prioSel, sortSel), count),
    list, sentinel, end);
  const obs = new IntersectionObserver((en) => { if (en[0].isIntersecting) load(); }, { rootMargin: '600px 0px' });
  obs.observe(sentinel);
  cleanupView = () => { obs.disconnect(); clearTimeout(searchTimer); };
}

/* ============================================================ admin */

function aiPanel(settings) {
  const result = h('div', { class: 'muted small', style: { marginTop: '8px' } });
  const test = h('button', { class: 'btn small', type: 'button', onclick: async () => {
    test.disabled = true; result.textContent = 'Testing…';
    try {
      const r = await api('/api/admin/ai/test', { method: 'POST' });
      result.replaceChildren(r.ok ? h('span', { class: 'ok-msg' }, `Connected. ${r.models.length} model(s) on the server.`) : h('span', { class: 'error-msg' }, r.error));
    } catch (e) { result.replaceChildren(h('span', { class: 'error-msg' }, e.message)); } finally { test.disabled = false; }
  } }, 'Test connection');
  return h('div', { class: 'panel' }, h('h3', {}, 'Ask AI'),
    settings.llm_model
      ? h('dl', { class: 'kv' }, h('dt', {}, 'Server'), h('dd', {}, settings.llm_base_url), h('dt', {}, 'Model'), h('dd', {}, settings.llm_model))
      : h('p', { class: 'muted small', style: { marginTop: 0 } }, 'Not configured. Set the server URL and model under Settings → Ask AI below (any OpenAI-compatible server: Ollama, llama.cpp, LM Studio, vLLM).'),
    test, result);
}

function settingInput(f) {
  const id = `set-${f.key}`;
  let input;
  if (f.kind === 'bool') {
    input = h('input', { type: 'checkbox', id, 'aria-label': f.label });
    input.checked = !!f.value;
  } else if (f.kind === 'choice') {
    const choices = f.choices.includes(String(f.value)) ? f.choices : [String(f.value), ...f.choices];
    input = h('select', { class: 'input', id }, ...choices.map((c) => h('option', { value: c }, c)));
    input.value = String(f.value);
  } else if (f.kind === 'int' || f.kind === 'float') {
    input = h('input', { class: 'input', id, type: 'number', inputmode: f.kind === 'int' ? 'numeric' : 'decimal', step: f.kind === 'int' ? '1' : 'any', min: f.min ?? null, max: f.max ?? null });
    input.value = String(f.value);
  } else if (f.kind === 'secret') {
    input = h('input', { class: 'input', id, type: 'password', autocomplete: 'off', placeholder: f.is_set ? 'Set (type to replace)' : 'Not set' });
  } else {
    input = h('input', { class: 'input', id, type: 'text', autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false', inputmode: f.kind === 'url' ? 'url' : null });
    input.value = f.value ?? '';
  }
  const read = () => {
    if (f.kind === 'bool') return input.checked;
    if (f.kind === 'int' || f.kind === 'float') return input.value === '' ? null : Number(input.value);
    return input.value.trim();
  };
  const dirty = () => {
    if (f.kind === 'secret') return input.value !== '';
    if (f.kind === 'int' || f.kind === 'float') return input.value !== '' && Number(input.value) !== Number(f.value);
    return read() !== (f.kind === 'bool' ? !!f.value : String(f.value ?? ''));
  };
  return { f, id, input, read, dirty };
}

function settingsPanel(onChange) {
  const body = h('div', {}, h('div', { class: 'muted small' }, 'Loading…'));
  const render = (d) => {
    const fmtDefault = (f) => (f.kind === 'secret' ? (f.default ? 'set in .env' : 'not set')
      : f.kind === 'bool' ? (f.default ? 'on' : 'off') : f.default === '' ? 'empty' : String(f.default));
    const groups = Object.entries(d.groups).map(([g, title], gi) => {
      const rows = d.fields.filter((f) => f.group === g).map(settingInput);
      const err = h('div', { class: 'error-msg' });
      const save = async (values) => {
        err.textContent = '';
        try {
          const r = await api('/api/admin/settings', { method: 'PATCH', body: { values } });
          state.ai = !!r.ai;
          toast(r.changed.length ? 'Saved. Changes apply right away.' : 'Nothing changed');
          render(r); onChange?.();
        } catch (e) { err.textContent = e.message; }
      };
      const fieldEl = (r) => {
        const { f } = r;
        const reset = f.overridden ? h('button', { class: 'btn small', type: 'button', onclick: () => save({ [f.key]: null }) }, 'Reset') : null;
        const meta = h('div', { class: 'setting-help' },
          f.help ? h('div', {}, f.help) : null,
          h('div', {}, f.overridden ? `Changed here · .env/default: ${fmtDefault(f)}` : 'From .env/default'));
        if (f.kind === 'bool') {
          return h('div', { class: 'setting' }, h('div', { class: 'setting-line' },
            h('label', { for: r.id, class: 'setting-label' }, f.label), reset, h('label', { class: 'toggle' }, r.input, h('span', {}))), meta);
        }
        const clear = f.kind === 'secret' && f.is_set ? h('button', { class: 'btn small', type: 'button', onclick: () => save({ [f.key]: '' }) }, 'Clear') : null;
        return h('div', { class: 'setting' }, h('div', { class: 'setting-line' }, h('label', { for: r.id, class: 'setting-label' }, f.label), clear, reset), r.input, meta);
      };
      const extra = g === 'reddit' ? h('p', { class: 'muted small' }, 'Sent as User-Agent: ', h('code', {}, d.reddit_user_agent)) : null;
      return h('details', { class: 'settings-group', open: gi === 0 ? true : null }, h('summary', {}, title),
        extra, ...rows.map(fieldEl), err,
        h('button', { class: 'btn primary', type: 'button', onclick: () => {
          const values = Object.fromEntries(rows.filter((r) => r.dirty()).map((r) => [r.f.key, r.read()]));
          if (!Object.keys(values).length) { toast('Nothing changed'); return; }
          save(values);
        } }, 'Save'));
    });
    body.replaceChildren(...groups);
  };
  api('/api/admin/settings').then(render).catch((e) => body.replaceChildren(h('div', { class: 'error-msg' }, e.message)));
  return h('div', { class: 'panel' }, h('h3', {}, 'Settings'),
    h('p', { class: 'muted small', style: { marginTop: 0 } }, 'Saved settings override .env and apply immediately. Reset goes back to the .env value. Data folder, secret key and scheduler on/off stay in .env.'),
    body);
}

async function viewAdmin(view) {
  setTabs('menu');
  if (!state.user.is_admin) { location.hash = '#/account'; return; }
  const body = h('div', { class: 'page' }, ...skeletonCards(2));
  view.replaceChildren(h('header', { class: 'topbar' }, h('div', { class: 'topbar-row' },
    h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Back', onclick: () => history.back() }, icon('back')),
    h('h1', {}, 'Admin'))), body);
  let settingsEl = null;
  const load = async () => {
    let d;
    try { d = await api('/api/admin/status'); } catch (e) { body.replaceChildren(h('div', { class: 'error-msg' }, e.message)); return; }
    const used = d.disk.disk_total - d.disk.disk_free;
    const pct = d.disk.disk_total ? (used / d.disk.disk_total) * 100 : 0;
    const lowDisk = d.disk.disk_free < d.disk.min_free_bytes;
    const inviteOut = h('div', {});
    settingsEl ||= settingsPanel(() => setTimeout(load, 300));
    const jobRow = (name, label) => {
      const j = d.jobs[name] || {};
      return h('div', { class: 'disc-item' }, h('div', { class: 't' }, h('b', {}, label),
        h('span', {}, j.running ? 'Running…' : j.last_run ? `${timeAgo(j.last_run)} ago · ${j.took}s · ${j.ok ? 'ok' : `failed: ${j.error}`}` : 'Not run since start')),
      h('button', { class: 'btn small', type: 'button', onclick: async () => {
        try { await api(`/api/admin/jobs/${name}`, { method: 'POST' }); toast(`${label} started`); setTimeout(load, 2500); } catch (e) { toastErr(e); }
      } }, 'Run'));
    };
    body.replaceChildren(
      h('div', { class: 'panel' }, h('h3', {}, 'Storage (/data)'),
        h('div', { class: 'bar' }, h('i', { style: { width: `${pct}%`, background: lowDisk ? 'var(--err)' : '' } })),
        h('dl', { class: 'kv', style: { marginTop: '10px' } },
          h('dt', {}, 'Disk'), h('dd', {}, `${fmtBytes(used)} used of ${fmtBytes(d.disk.disk_total)} (${fmtBytes(d.disk.disk_free)} free)`),
          h('dt', {}, 'Local DS'), h('dd', {}, `${fmtBytes(d.disk.data_bytes)} total, videos ${fmtBytes(d.disk.videos_bytes)}, thumbnails ${fmtBytes(d.disk.thumbs_bytes)}`),
          h('dt', {}, 'Min free'), h('dd', {}, `${fmtBytes(d.disk.min_free_bytes)}${lowDisk ? ' — downloads paused' : ''}`),
          h('dt', {}, 'Shorts'), h('dd', {}, Object.entries(d.shorts).map(([k, v]) => `${v} ${k}`).join(', ') || 'none'),
          h('dt', {}, 'Retention'), h('dd', {}, `${d.settings.retention_days} days, thumbnails ${d.settings.keep_thumbnails ? 'kept' : 'deleted'}`),
          h('dt', {}, 'Encoding'), h('dd', {}, `max ${d.settings.max_height}p, hwaccel ${d.settings.hwaccel}${d.settings.vaapi_device ? ` (${d.settings.vaapi_device})` : ' (software)'}`),
          h('dt', {}, 'Data'), h('dd', {}, `${d.items} posts, ${d.comments} comments, ${d.reactions} reactions`))),
      h('div', { class: 'panel' }, h('h3', {}, 'Jobs'),
        h('dl', { class: 'kv' }, h('dt', {}, 'Version'), h('dd', {}, d.version), h('dt', {}, 'yt-dlp'), h('dd', {}, d.ytdlp_version), h('dt', {}, 'Shorts'), h('dd', {}, d.shorts_status)),
        jobRow('rss', 'Refresh feeds'), jobRow('shorts', 'Fetch Shorts'), jobRow('cleanup', 'Cleanup + reconcile'),
        jobRow('weights', 'Recompute weights'), jobRow('ytdlp_update', 'Update yt-dlp'), jobRow('icons', 'Fetch source pictures')),
      aiPanel(d.settings),
      settingsEl,
      h('div', { class: 'panel' }, h('h3', {}, 'Invite a friend'),
        h('p', { class: 'muted small', style: { marginTop: 0 } }, 'Single-use link, valid for 3 days.'),
        h('button', { class: 'btn primary', type: 'button', onclick: async () => {
          try {
            const r = await api('/api/admin/invites', { method: 'POST', body: { hours: 72 } });
            const inp = h('input', { class: 'input', readonly: true, value: r.url });
            const copyBtn = h('button', { class: 'btn', type: 'button', onclick: async () => {
              try { await navigator.clipboard.writeText(r.url); toast('Copied'); } catch { inp.select(); }
            } }, 'Copy');
            const shareBtn = navigator.share ? h('button', { class: 'btn', type: 'button', onclick: () => navigator.share({ title: 'Local DS invite', url: r.url }).catch(() => {}) }, 'Share') : null;
            inviteOut.replaceChildren(h('div', { class: 'copy-box' }, inp, copyBtn, shareBtn));
          } catch (e) { toastErr(e); }
        } }, 'Create invite link'),
        inviteOut,
        ...d.invites.map((i) => h('div', { class: 'disc-item' }, h('div', { class: 't' },
          h('b', {}, i.used_by ? `Used by ${i.used_by}` : i.expires_at < Date.now() / 1000 ? 'Expired' : 'Open invite'),
          h('span', {}, `created ${timeAgo(i.created_at)} ago`)),
        !i.used_by && i.expires_at > Date.now() / 1000 ? h('button', { class: 'btn small danger', type: 'button', onclick: async () => {
          await api(`/api/admin/invites/${i.id}`, { method: 'DELETE' }).catch(toastErr); load();
        } }, 'Revoke') : null))),
      h('div', { class: 'panel' }, h('h3', {}, 'Users'),
        ...d.users.map((u) => h('div', { class: 'disc-item' }, avatar(u.username),
          h('div', { class: 't' }, h('b', {}, u.username), h('span', {}, `${u.is_admin ? 'Admin' : 'Member'} · joined ${timeAgo(u.created_at)} ago`)),
          u.id !== state.user.id ? h('button', { class: 'btn small danger', type: 'button', onclick: async () => {
            if (!confirm(`Delete ${u.username}? Their comments stay, their reactions are removed.`)) return;
            await api(`/api/admin/users/${u.id}`, { method: 'DELETE' }).catch(toastErr); load();
          } }, 'Delete') : null))));
  };
  load();
}

/* ============================================================ boot */

async function boot() {
  try {
    const s = await api('/api/state');
    Object.assign(state, { user: s.user, csrf: s.csrf, setupNeeded: s.setup_needed, version: s.version, ai: !!s.ai });
  } catch (e) {
    $('#view').replaceChildren(h('div', { class: 'empty' }, h('h3', {}, 'Cannot reach the server'), e.message,
      h('div', {}, h('button', { class: 'btn', onclick: () => location.reload() }, 'Retry'))));
    return;
  }
  render();
}

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {}));
}
boot();
