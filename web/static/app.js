"use strict";

const TYPE_ORDER = ["book", "audiobook", "comicbook", "series", "authors"];
const TYPE_LABEL = { book: "Книги", audiobook: "Аудиокниги", comicbook: "Комиксы", series: "Серии", authors: "Авторы" };
const TYPE_BADGE = { book: "EPUB", audiobook: "Аудио", comicbook: "Комикс", series: "Серия", authors: "Автор" };
const TYPE_PH = { book: "📚", audiobook: "🎧", comicbook: "🎨", series: "📀", authors: "👤" };
const DOWNLOADABLE = new Set(["book", "audiobook", "comicbook"]);
const OAUTH_URL = "https://oauth.yandex.ru/authorize?response_type=token&client_id=4483e97bab6e486a9822973109a14d05";

const $ = (id) => document.getElementById(id);
const el = {
  topbar: $("topbar"), gate: $("gate"), app: $("app"), empty: $("empty"),
  results: $("results"), more: $("more-btn"),
  searchForm: $("search-form"), searchInput: $("search-input"),
  loginForm: $("login-form"), tokenInput: $("token-input"), loginBtn: $("login-btn"), loginErr: $("login-err"),
  logoutBtn: $("logout-btn"), oauthLink: $("oauth-link"),
  overlay: $("overlay"), overlayText: $("overlay-text"), toast: $("toast"),
};

let state = { q: "", cursor: null, accum: {} };
let toastTimer = null;

// --- Утилиты ------------------------------------------------------------------
function show(node, on) { node.hidden = !on; }

function toast(msg) {
  el.toast.textContent = msg;
  show(el.toast, true);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => show(el.toast, false), 3500);
}

function showOverlay(text) { el.overlayText.textContent = text; show(el.overlay, true); }
function hideOverlay() { show(el.overlay, false); }

async function api(path, opts) {
  const r = await fetch(path, opts);
  let data = null;
  try { data = await r.json(); } catch (_) { /* нет тела */ }
  return { r, data };
}

// --- Авторизация --------------------------------------------------------------
function showAuthed(authed) {
  show(el.gate, !authed);
  show(el.topbar, authed);
  show(el.app, authed);
  if (authed) el.searchInput.focus();
}

async function refreshMe() {
  let authed = false;
  try {
    const { data } = await api("/api/me");
    authed = !!(data && data.authed);
  } catch (_) { authed = false; }  // при сбое показываем экран входа, не пустоту
  showAuthed(authed);
}

function extractToken(raw) {
  raw = (raw || "").trim();
  const m = raw.match(/access_token=([^&\s]+)/);
  return m ? decodeURIComponent(m[1]) : raw;
}

async function login(raw) {
  const token = extractToken(raw);
  if (!token) { showErr("Введите токен"); return; }
  el.loginBtn.disabled = true;
  showErr("");
  const { r, data } = await api("/api/login", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token }),
  });
  el.loginBtn.disabled = false;
  if (r.ok) {
    el.tokenInput.value = "";
    await refreshMe();
  } else {
    showErr((data && data.detail) || "Не удалось войти");
  }
}

function showErr(msg) { el.loginErr.textContent = msg; show(el.loginErr, !!msg); }

async function logout() {
  await api("/api/logout", { method: "POST" });
  state = { q: "", cursor: null, accum: {} };
  el.results.innerHTML = "";
  show(el.empty, true);
  show(el.more, false);
  await refreshMe();
}

function sessionExpired() {
  showAuthed(false);
  showErr("Сессия истекла, войдите снова");
}

// --- Рендер карточек ----------------------------------------------------------
function card(item) {
  const b = document.createElement("button");
  b.className = "card";
  b.type = "button";
  const cover = document.createElement("div");
  cover.className = "cover";
  if (item.cover_url) {
    const img = document.createElement("img");
    img.loading = "lazy";
    img.alt = "";
    img.src = item.cover_url;
    img.onerror = () => { cover.innerHTML = `<div class="ph">${TYPE_PH[item.content_type] || "📖"}</div>`; addBadge(); };
    cover.appendChild(img);
  } else {
    cover.innerHTML = `<div class="ph">${TYPE_PH[item.content_type] || "📖"}</div>`;
  }
  function addBadge() {
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = TYPE_BADGE[item.content_type] || "";
    cover.appendChild(badge);
  }
  addBadge();
  const title = document.createElement("div");
  title.className = "title";
  title.textContent = item.title || "Без названия";
  const author = document.createElement("div");
  author.className = "author";
  author.textContent = (item.authors && item.authors[0]) || "";
  b.append(cover, title, author);
  b.addEventListener("click", () => onCardClick(item));
  return b;
}

function sectionBlock(type, items) {
  const sec = document.createElement("section");
  sec.className = "section";
  const h = document.createElement("h2");
  h.textContent = `${TYPE_LABEL[type] || type} · ${items.length}`;
  const grid = document.createElement("div");
  grid.className = "grid";
  items.forEach((it) => grid.appendChild(card(it)));
  sec.append(h, grid);
  return sec;
}

function renderSections(container, sections) {
  container.innerHTML = "";
  let any = false;
  for (const type of TYPE_ORDER) {
    const items = sections[type];
    if (items && items.length) { container.appendChild(sectionBlock(type, items)); any = true; }
  }
  return any;
}

// --- Поиск --------------------------------------------------------------------
function mergeAccum(sections) {
  for (const type of TYPE_ORDER) {
    if (sections[type]) {
      state.accum[type] = (state.accum[type] || []).concat(sections[type]);
    }
  }
}

async function doSearch(q, append) {
  if (!append) state = { q: q, cursor: null, accum: {} };
  let url = `/api/search?q=${encodeURIComponent(state.q)}`;
  if (append && state.cursor) url += `&cursor=${encodeURIComponent(state.cursor)}`;
  const { r, data } = await api(url);
  if (r.status === 401) return sessionExpired();
  if (!r.ok) { toast((data && data.detail) || "Ошибка поиска"); return; }
  mergeAccum(data.sections || {});
  state.cursor = data.cursor || null;
  const any = renderSections(el.results, state.accum);
  show(el.empty, !any);
  show(el.more, !!state.cursor);
}

// --- Переход внутрь серии/автора ----------------------------------------------
async function openCollection(item) {
  showOverlay("Загружаем список…");
  const { r, data } = await api(`/api/items?type=${item.content_type}&uuid=${encodeURIComponent(item.uuid)}`);
  hideOverlay();
  if (r.status === 401) return sessionExpired();
  if (!r.ok) { toast((data && data.detail) || "Не удалось открыть"); return; }
  const items = data.items || [];
  el.results.innerHTML = "";
  const bar = document.createElement("div");
  bar.className = "backbar";
  const back = document.createElement("button");
  back.className = "back-btn";
  back.type = "button";
  back.textContent = "← Назад к результатам";
  back.addEventListener("click", () => {
    const any = renderSections(el.results, state.accum);
    show(el.empty, !any);
    show(el.more, !!state.cursor);  // восстановить пагинацию
  });
  bar.appendChild(back);
  el.results.appendChild(bar);
  show(el.more, false);
  show(el.empty, false);
  const grouped = {};
  items.forEach((it) => { (grouped[it.content_type] = grouped[it.content_type] || []).push(it); });
  const wrap = document.createElement("div");
  if (!renderSections(wrap, grouped)) {
    wrap.innerHTML = `<p class="muted" style="padding:40px;text-align:center">Нет доступных книг</p>`;
  }
  el.results.appendChild(wrap);
}

// --- Клик по карточке ---------------------------------------------------------
function onCardClick(item) {
  if (DOWNLOADABLE.has(item.content_type)) download(item);
  else openCollection(item);
}

// --- Скачивание (prepare → отдача файла браузером) ----------------------------
async function download(item) {
  showOverlay(`Готовим «${item.title || "файл"}»…`);
  const { r, data } = await api("/api/download/prepare", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content_type: item.content_type, uuid: item.uuid }),
  });
  if (r.status === 401) { hideOverlay(); return sessionExpired(); }
  if (!r.ok || !data || !data.id) { hideOverlay(); return toast((data && data.detail) || "Не удалось скачать"); }
  const a = document.createElement("a");
  a.href = `/api/download/file?id=${encodeURIComponent(data.id)}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  hideOverlay();
  toast("Загрузка началась");
}

// --- События ------------------------------------------------------------------
el.oauthLink.href = OAUTH_URL;
el.loginForm.addEventListener("submit", (e) => { e.preventDefault(); login(el.tokenInput.value); });
el.logoutBtn.addEventListener("click", logout);
el.searchForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const q = el.searchInput.value.trim();
  if (q) doSearch(q, false);
});
el.more.addEventListener("click", () => doSearch(state.q, true));

refreshMe();
