import { apiGet, apiPost } from "./api.js";

const appEl = document.getElementById("app");
const tabbar = document.getElementById("tabbar");
const title = document.getElementById("page-title");
const toastEl = document.getElementById("toast");
const btnInstall = document.getElementById("btn-install");

/** Защита от XSS при вставке в innerHTML (данные API / ошибки). */
function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function showToast(msg, ms = 5000) {
  toastEl.textContent = msg;
  toastEl.classList.remove("hidden");
  setTimeout(() => toastEl.classList.add("hidden"), ms);
}

/** OAuth error от WHOOP в query (?oauth_error=) после redirect. */
function consumeOAuthError() {
  const u = new URL(window.location.href);
  const raw = u.searchParams.get("oauth_error");
  if (!raw) return null;
  u.searchParams.delete("oauth_error");
  const qs = u.searchParams.toString();
  window.history.replaceState(null, "", u.pathname + (qs ? `?${qs}` : "") + u.hash);
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

function loadingSkeleton() {
  appEl.innerHTML = `
    <div class="card"><div class="skeleton" style="width:60%"></div><div class="skeleton"></div><div class="skeleton"></div></div>
    <div class="card"><div class="skeleton"></div><div class="skeleton"></div></div>`;
}

function fmtScoreState(st) {
  if (st === "PENDING_SCORE") return "Обработка…";
  if (st === "UNSCORABLE") return "Нет оценки";
  if (st === "SCORED") return "Готово";
  return escapeHtml(st || "—");
}

async function checkAuth() {
  const s = await apiGet("/auth/status");
  return Boolean(s.logged_in);
}

function renderLogin() {
  title.textContent = "WHOOP";
  tabbar.hidden = true;
  appEl.innerHTML = `
    <div class="card center">
      <p class="muted">Подключите WHOOP, чтобы увидеть Recovery, сон и Strain.</p>
      <p class="muted" style="font-size:0.85rem">Данные защищены OAuth 2.0. Логин/пароль WHOOP мы не запрашиваем.</p>
      <a class="btn btn-primary" href="/auth/login" style="display:inline-block;text-align:center;text-decoration:none;margin-top:12px">Подключить WHOOP</a>
    </div>`;
}

function recClass(level) {
  if (level === "warning") return "rec-warn";
  if (level === "ok") return "rec-ok";
  if (level === "info") return "rec-info";
  return "rec-warn";
}

async function renderDashboard() {
  title.textContent = "Главная";
  loadingSkeleton();
  const d = await apiGet("/api/dashboard");
  const r = d.recovery || {};
  const s = d.sleep || {};
  const st = d.strain || {};

  const recHtml = (d.recommendations || [])
    .map(
      (x) =>
        `<div class="${recClass(x.level)}">${escapeHtml(x.text)}</div>`
    )
    .join("");

  const recVal =
    r.score != null ? `${escapeHtml(String(Math.round(r.score)))}%` : "—";
  const sleepVal =
    s.hours != null ? `${escapeHtml(String(s.hours))} ч` : "—";
  const strainVal =
    st.score != null ? escapeHtml(st.score.toFixed(1)) : "—";

  appEl.innerHTML = `
    <div class="card">
      <h2>Recovery</h2>
      <div class="metric-big">${recVal}</div>
      <div class="sub"><span class="badge">${fmtScoreState(r.score_state)}</span> ${escapeHtml(r.message || "")}</div>
    </div>
    <div class="card">
      <h2>Сон</h2>
      <div class="metric-big">${sleepVal}</div>
      <div class="sub"><span class="badge">${fmtScoreState(s.score_state)}</span> ${escapeHtml(s.message || "")}</div>
    </div>
    <div class="card">
      <h2>Strain</h2>
      <div class="metric-big">${strainVal}</div>
      <div class="sub"><span class="badge">${fmtScoreState(st.score_state)}</span> ${escapeHtml(st.message || "")}</div>
    </div>
    <div class="card">
      <h2>Рекомендации</h2>
      ${recHtml || '<p class="muted">Нет активных рекомендаций.</p>'}
    </div>`;
}

async function renderHistory() {
  title.textContent = "История";
  loadingSkeleton();
  const h = await apiGet("/api/history?days=7");

  const block = (label, rows, fmt) => {
    const items = (rows || [])
      .map((x) => {
        const line = fmt(x);
        return `<li><strong>${escapeHtml(x.date || "—")}</strong> — ${line}</li>`;
      })
      .join("");
    return `<div class="card"><h2>${escapeHtml(label)}</h2><ul class="list">${items || '<li class="muted">Нет данных</li>'}</ul></div>`;
  };

  const pag = h.pagination || {};
  const anyTrunc =
    pag.recovery_truncated || pag.sleep_truncated || pag.cycle_truncated;
  const truncNote = anyTrunc
    ? '<p class="muted" style="font-size:0.85rem;margin-top:8px">За период есть ещё события в WHOOP (достигнут предел выборки на экране).</p>'
    : "";

  appEl.innerHTML = `
    ${block(
      "Recovery (7 дней)",
      h.recoveries,
      (x) =>
        x.score_state === "SCORED" && x.recovery_score != null
          ? `${escapeHtml(String(Math.round(x.recovery_score)))}%`
          : fmtScoreState(x.score_state)
    )}
    ${block(
      "Сон (7 дней)",
      h.sleeps,
      (x) =>
        x.score_state === "SCORED" && x.hours != null
          ? `${escapeHtml(String(x.hours))} ч`
          : fmtScoreState(x.score_state)
    )}
    ${block(
      "Strain (7 дней)",
      h.cycles,
      (x) =>
        x.score_state === "SCORED" && x.strain != null
          ? escapeHtml(x.strain.toFixed(1))
          : fmtScoreState(x.score_state)
    )}
    ${truncNote}`;
}

async function renderWorkouts() {
  title.textContent = "Тренировки";
  loadingSkeleton();
  const w = await apiGet("/api/workouts?days=7");
  const rows = (w.workouts || [])
    .map((x) => {
      const strain = x.strain != null ? escapeHtml(x.strain.toFixed(1)) : "—";
      const sport = escapeHtml(x.sport_name || "Активность");
      const st = fmtScoreState(x.score_state);
      const hr =
        x.average_heart_rate != null
          ? ` · средний пульс ${escapeHtml(String(x.average_heart_rate))}`
          : "";
      const dur =
        x.duration_min != null
          ? ` · ${escapeHtml(String(x.duration_min))} мин`
          : "";
      const start = escapeHtml(x.start || "—");
      return `<li><strong>${start}</strong><br/><span class="muted">${sport} · Strain ${strain} · ${st}${hr}${dur}</span></li>`;
    })
    .join("");

  const trunc = w.pagination?.truncated
    ? '<p class="muted" style="font-size:0.85rem;margin-top:8px">Показана часть тренировок (есть ещё страницы в WHOOP).</p>'
    : "";

  appEl.innerHTML = `<div class="card"><h2>Последние тренировки</h2><ul class="list">${rows || '<li class="muted">Нет тренировок</li>'}</ul></div>${trunc}`;
}

async function renderProfile() {
  title.textContent = "Профиль";
  loadingSkeleton();
  const p = await apiGet("/api/profile");
  const nameRaw = [p.first_name, p.last_name].filter(Boolean).join(" ") || "Пользователь";
  const name = escapeHtml(nameRaw);

  appEl.innerHTML = `
    <div class="card">
      <h2>Профиль</h2>
      <p><strong>${name}</strong></p>
      <p class="muted">WHOOP user_id: ${escapeHtml(String(p.whoop_user_id))}</p>
      ${p.email ? `<p class="muted">${escapeHtml(p.email)}</p>` : ""}
    </div>
    <button type="button" class="btn" id="btn-logout">Выйти (сессия)</button>
    <button type="button" class="btn btn-danger" id="btn-disconnect" style="margin-top:10px">Отключить WHOOP</button>
    <p class="muted" style="font-size:0.85rem;margin-top:12px">«Отключить WHOOP» отзывает доступ у WHOOP и удаляет токены на сервере.</p>`;

  document.getElementById("btn-logout").onclick = async () => {
    await apiPost("/auth/logout");
    location.hash = "#/";
    await route();
  };
  document.getElementById("btn-disconnect").onclick = async () => {
    if (!confirm("Отключить интеграцию WHOOP?")) return;
    try {
      await apiPost("/auth/disconnect");
      showToast("WHOOP отключён, локальные данные удалены");
    } catch (e) {
      showToast(e.message);
    }
    location.hash = "#/";
    await route();
  };
}

function setActiveTab() {
  const h = location.hash || "#/";
  document.querySelectorAll(".tabbar a").forEach((a) => {
    a.classList.toggle("active", a.getAttribute("href") === h);
  });
}

async function route() {
  setActiveTab();

  const oauthErr = consumeOAuthError();
  if (oauthErr) {
    showToast(`WHOOP: ${oauthErr}`);
  }

  const loggedIn = await checkAuth();
  if (!loggedIn) {
    renderLogin();
    return;
  }
  tabbar.hidden = false;
  const h = location.hash || "#/";
  try {
    if (h === "#/history") await renderHistory();
    else if (h === "#/workouts") await renderWorkouts();
    else if (h === "#/profile") await renderProfile();
    else await renderDashboard();
  } catch (e) {
    appEl.innerHTML = `<div class="card"><p class="muted">Ошибка загрузки</p><p>${escapeHtml(e.message)}</p><button class="btn" type="button" id="btn-retry">Повторить</button></div>`;
    document.getElementById("btn-retry").onclick = () => route();
    showToast(e.message);
  }
}

window.addEventListener("hashchange", () => route());

/* PWA install + SW */
let deferredPrompt = null;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  deferredPrompt = e;
  btnInstall.hidden = false;
  btnInstall.classList.remove("hidden");
});

btnInstall.addEventListener("click", async () => {
  if (!deferredPrompt) return;
  deferredPrompt.prompt();
  await deferredPrompt.userChoice;
  deferredPrompt = null;
  btnInstall.classList.add("hidden");
});

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}

route();
