// Worker «ontoca-alertas» empaquetado (alertas/worker.js + alertas/lib.js) para pegarlo en el panel de Cloudflare. Generado: npx esbuild alertas/worker.js --bundle --format=esm
// alertas/lib.js
var PENDING_HOURS = 48;
var MAX_ITEMS_PER_SEARCH = 10;
var CATS = {
  musica: "M\xFAsica",
  escena: "Teatro y danza",
  cine: "Cine",
  arte: "Arte y exposiciones",
  charlas: "Charlas y visitas",
  talleres: "Talleres",
  fiestas: "Fiestas y mercados",
  deporte: "Deporte"
};
var CHANS = { familia: "En familia", barrio: "Vida de barrio", aire: "Al aire libre", galerias: "Arte y galer\xEDas", festivales: "Festivales y fiestas" };
var site = (env) => String(env.SITE_URL || "https://ontoca.com").replace(/\/$/, "");
var sender = (env) => env.SENDER || "hola@ontoca.com";
var nowIso = () => (/* @__PURE__ */ new Date()).toISOString();
var esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
var fold = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
var SCHEMA = [
  `CREATE TABLE IF NOT EXISTS subscribers (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, token TEXT NOT NULL UNIQUE,
     freq TEXT NOT NULL DEFAULT 'bisemanal', created_at TEXT NOT NULL, confirmed_at TEXT, last_sent_at TEXT)`,
  `CREATE TABLE IF NOT EXISTS searches (id INTEGER PRIMARY KEY, subscriber_id INTEGER NOT NULL, filters TEXT NOT NULL, label TEXT NOT NULL,
     freq TEXT NOT NULL DEFAULT 'bisemanal', status TEXT NOT NULL DEFAULT 'pending', confirm_token TEXT UNIQUE, created_at TEXT NOT NULL, confirmed_at TEXT)`,
  `CREATE INDEX IF NOT EXISTS searches_sub ON searches(subscriber_id)`,
  `CREATE TABLE IF NOT EXISTS signup_log (ip_hash TEXT NOT NULL, at TEXT NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS sends (day TEXT PRIMARY KEY, count INTEGER NOT NULL DEFAULT 0)`,
  `CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)`
];
var schemaReady = null;
async function db(env) {
  if (!env.ALERTAS_DB) throw new Error("Falta la base de datos ALERTAS_DB");
  if (schemaReady !== env.ALERTAS_DB) {
    await env.ALERTAS_DB.batch(SCHEMA.map((q) => env.ALERTAS_DB.prepare(q)));
    schemaReady = env.ALERTAS_DB;
  }
  return env.ALERTAS_DB;
}
function cleanFilters(f) {
  f = f && typeof f === "object" ? f : {};
  const list = (x, ok) => [...new Set((Array.isArray(x) ? x : []).filter((v) => ok[v]))].slice(0, 8);
  return {
    cats: list(f.cats, CATS),
    chans: list(f.chans, CHANS),
    district: String(f.district || "").slice(0, 60),
    free: Boolean(f.free),
    q: String(f.q || "").replace(/\s+/g, " ").trim().slice(0, 80)
  };
}
function searchUrl(env, f) {
  const p = new URLSearchParams();
  f.cats.forEach((c) => p.append("cat", c));
  f.chans.forEach((c) => p.append("ch", c));
  if (f.district) p.set("district", f.district);
  if (f.free) p.set("free", "1");
  if (f.q) p.set("q", f.q);
  p.set("range", "30");
  return `${site(env)}/?${p}`;
}
function matches(item, f) {
  if (f.cats.length && !f.cats.includes(item.pc)) return false;
  if (f.chans.length && !f.chans.some((c) => (item.ch || []).includes(c))) return false;
  if (f.district && item.d !== f.district) return false;
  if (f.free && !item.fr) return false;
  if (f.q) {
    const hay = fold([item.t, item.v, ...item.lu || []].join(" "));
    if (!fold(f.q).split(" ").filter(Boolean).every((w) => hay.includes(w))) return false;
  }
  return true;
}
function madrid(date = /* @__PURE__ */ new Date()) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Madrid",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    weekday: "short"
  }).formatToParts(date).map((p) => [p.type, p.value]));
  return {
    day: `${parts.year}-${parts.month}-${parts.day}`,
    hour: Number(parts.hour),
    minute: Number(parts.minute),
    weekday: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].indexOf(parts.weekday)
  };
}
function eightInMadrid(day) {
  for (const off of [1, 2]) {
    const d = /* @__PURE__ */ new Date(`${day}T${String(8 - off).padStart(2, "0")}:00:00Z`);
    const m = madrid(d);
    if (m.day === day && m.hour === 8) return d;
  }
  return /* @__PURE__ */ new Date(`${day}T07:00:00Z`);
}
var addDays = (day, n) => {
  const d = /* @__PURE__ */ new Date(`${day}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};
function lastSlot(freq, now = /* @__PURE__ */ new Date()) {
  const days = freq === "semanal" ? [0] : [0, 3];
  for (let back = 0; back < 8; back++) {
    const day = addDays(madrid(now).day, -back), wd = madrid(/* @__PURE__ */ new Date(`${day}T12:00:00Z`)).weekday;
    if (!days.includes(wd)) continue;
    const at = eightInMadrid(day);
    if (at <= now) return at;
  }
  return null;
}
async function sendMail(env, { to, subject, html, text, headers }) {
  if (!env.BREVO_API_KEY) throw new Error("Falta BREVO_API_KEY");
  const res = await (env.FETCH || fetch)("https://api.brevo.com/v3/smtp/email", {
    method: "POST",
    headers: { "api-key": env.BREVO_API_KEY, "content-type": "application/json", accept: "application/json" },
    // Sin «headers» vacío ni «tags» (26-10-2026): el alta recibía «Brevo 400»; los correos del Mac, que funcionan,
    // no los mandan. Las cabeceras solo van cuando hay alguna (la baja en un clic de los resúmenes).
    body: JSON.stringify({
      sender: { name: "Ontoca", email: sender(env) },
      replyTo: { email: sender(env) },
      to: [{ email: to }],
      subject,
      htmlContent: html,
      textContent: text,
      ...headers && Object.keys(headers).length ? { headers } : {}
    })
  });
  if (!res.ok) {
    let why = "";
    try {
      const j = await res.json();
      why = [j.code, j.message].filter(Boolean).join(": ");
    } catch (_) {
    }
    throw new Error(`Brevo ${res.status}${why ? " \xB7 " + why.slice(0, 160) : ""}`);
  }
  return true;
}
var C = {
  ink: "#000000",
  paper: "#ffffff",
  text2: "#444444",
  line: "#e3e3e3",
  surface2: "#f4f4f1",
  petrol: "#097C87",
  sand: "#F9D779",
  turq: "#23CED9",
  coral: "#FCA47C",
  sage: "#A1CCA6",
  lilac: "#BBA6EA",
  cobalt: "#3D5BD9"
};
var CAT_COLOR = { musica: C.ink, escena: C.coral, arte: C.sage, charlas: C.turq, fiestas: C.sand, cine: C.lilac, deporte: C.petrol, talleres: C.cobalt };
var FONT = "'Inter Tight','Helvetica Neue',Helvetica,Arial,sans-serif";
var WD = ["lunes", "martes", "mi\xE9rcoles", "jueves", "viernes", "s\xE1bado", "domingo"];
var MON = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
var MON3 = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"];
var ymd = (d) => d.split("-").map(Number);
var wdOf = (day) => madrid(/* @__PURE__ */ new Date(`${day}T12:00:00Z`)).weekday;
function longDate(x) {
  const day = /^\d{4}-\d{2}-\d{2}$/.test(String(x)) ? x : madrid(new Date(x)).day, [, m, d] = ymd(day);
  return `${WD[wdOf(day)]} ${d} de ${MON[m - 1]}`;
}
var shortDate = (x) => {
  const day = /^\d{4}-\d{2}-\d{2}$/.test(String(x)) ? x : madrid(new Date(x)).day, [y, m, d] = ymd(day);
  return `${d}/${m}/${y}`;
};
function nextSlot(freq, now = /* @__PURE__ */ new Date()) {
  const days = freq === "semanal" ? [0] : [0, 3];
  for (let ahead = 0; ahead < 9; ahead++) {
    const day = addDays(madrid(now).day, ahead);
    if (!days.includes(wdOf(day))) continue;
    const at = eightInMadrid(day);
    if (at > now) return at;
  }
  return null;
}
var SEND_TIME = "8:00";
var freqSentence = (freq) => freq === "semanal" ? `los lunes a partir de las ${SEND_TIME}` : `los lunes y los jueves a partir de las ${SEND_TIME}`;
var button = (href, label, dark = true) => `<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="display:inline-table;margin:0 8px 8px 0"><tr>
<td style="background:${dark ? C.ink : C.paper};border:1px solid ${C.ink}"><a href="${esc(href)}" style="display:inline-block;padding:12px 18px;font-family:${FONT};font-size:14px;font-weight:700;color:${dark ? C.paper : C.ink};text-decoration:none">${label}</a></td></tr></table>`;
var strip = () => `<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>${[C.sand, C.turq, C.coral, C.petrol, C.sage, C.lilac, C.cobalt].map((c) => `<td height="6" style="height:6px;line-height:6px;font-size:0;background:${c}">&nbsp;</td>`).join("")}</tr></table>`;
function shell(env, { preheader = "", kicker = "", inner, outro = "", legal }) {
  const s = site(env);
  return `<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light only"><meta name="supported-color-schemes" content="light">
<meta name="format-detection" content="telephone=no,date=no,address=no,email=no,url=no">
<style>a[x-apple-data-detectors],.nolink a{color:inherit!important;text-decoration:none!important;font-size:inherit!important;font-weight:inherit!important;line-height:inherit!important;pointer-events:none}u+#body a{color:inherit;text-decoration:none}</style>
<title>Ontoca</title></head><body id="body" style="margin:0;padding:0;background:${C.surface2};-webkit-text-size-adjust:100%">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent">${esc(preheader)}&#8199;&#65279;&#847;&#8199;&#65279;&#847;&#8199;&#65279;&#847;</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:${C.surface2}"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px;background:${C.paper};border:1px solid ${C.ink}">
<tr><td style="padding:22px 28px 18px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
<td valign="middle"><a href="${s}/" style="text-decoration:none;color:${C.ink}"><img src="${s}/apple-touch-icon.png" width="40" height="40" alt="" style="display:inline-block;vertical-align:middle;border:0;margin:0 8px 0 -6px"><span style="font-family:${FONT};font-size:30px;font-weight:700;letter-spacing:-1.3px;vertical-align:middle;color:${C.ink}">ontoca<span style="color:${C.petrol}">.</span></span></a></td>
<td valign="middle" align="right" style="font-family:${FONT};font-size:12px;line-height:1.4;color:${C.text2};text-transform:uppercase;letter-spacing:.06em">${kicker}</td></tr></table></td></tr>
<tr><td>${strip()}</td></tr>
<tr><td style="padding:28px 28px 8px;font-family:${FONT};color:${C.ink}">${inner}</td></tr>
${outro ? `<tr><td style="padding:8px 28px 28px">${outro}</td></tr>` : ""}
<tr><td style="background:${C.ink};padding:22px 28px;font-family:${FONT};color:${C.paper}">
<div style="font-size:22px;font-weight:700;letter-spacing:-1px">ontoca<span style="color:${C.turq}">.</span></div>
<div style="font-size:14px;margin:2px 0 14px;color:${C.paper}">Mil maneras de vivir la ciudad.</div>
<div style="font-size:13px;line-height:1.6"><a href="${s}/" style="color:${C.paper};text-decoration:underline">ontoca.com</a> \xB7 Hecho en Barcelona \xB7 <a href="mailto:${esc(sender(env))}" style="color:${C.paper};text-decoration:underline">${esc(sender(env))}</a></div>
<div style="font-size:12px;line-height:1.5;color:#bdbdbd;margin-top:10px">${legal}</div></td></tr>
</table></td></tr></table></body></html>`;
}
var when = (item) => {
  const fmt = (d) => {
    const [, m, dd] = ymd(d);
    return `${dd}/${m}`;
  };
  const date = item.a === item.b || !item.b ? fmt(item.a) : `del ${fmt(item.a)} al ${fmt(item.b)}`;
  return item.tm ? `${date} \xB7 ${item.tm}` : date;
};
var ficha = (env, key) => {
  const [s, ...rest] = key.split(":");
  return `${site(env)}/e/${encodeURIComponent(s)}/${encodeURIComponent(rest.join(":"))}`;
};
var noLink = (text) => esc(text).replace(/(\d)/g, "$1&#8288;");
function dateBlock(item, today) {
  const ongoing = item.b && item.a !== item.b && item.a < today, day = ongoing ? item.b : item.a, [, m, d] = ymd(day);
  return `<td width="62" valign="top" style="width:62px;padding:14px 0;font-family:${FONT}">
<div style="width:52px;border:1px solid ${C.ink};text-align:center">
<div style="font-size:10px;font-weight:700;letter-spacing:.06em;background:${C.ink};color:${C.paper};padding:3px 0">${ongoing ? "HASTA" : WD[wdOf(day)].slice(0, 3).toUpperCase()}</div>
<div style="font-size:22px;font-weight:700;line-height:1;padding:6px 0 2px;color:${C.ink}">${d}</div>
<div style="font-size:10px;font-weight:700;letter-spacing:.06em;padding:0 0 5px;color:${C.ink}">${MON3[m - 1]}</div></div></td>`;
}
function itemRow(env, item, today) {
  const cat = CATS[item.pc] || item.tl || "", color = CAT_COLOR[item.pc] || C.paper;
  const meta = [item.a === item.b || !item.b ? item.tm : when(item), item.v, item.d].filter(Boolean).join(" \xB7 ");
  return `<tr>${dateBlock(item, today)}<td valign="top" style="padding:14px 0;border-bottom:1px solid ${C.line};font-family:${FONT}">
<div style="font-size:12px;font-weight:600;color:${C.ink};margin:0 0 4px">${cat ? `<span style="display:inline-block;width:9px;height:9px;border:1px solid ${C.ink};background:${color};margin-right:6px;vertical-align:0"></span>${esc(cat)}` : ""}${item.fr ? `<span style="display:inline-block;margin-left:8px;padding:1px 6px;background:${C.petrol};color:${C.paper};font-size:11px;font-weight:700">Gratis</span>` : ""}</div>
<a href="${esc(ficha(env, item.k))}" style="font-size:17px;line-height:1.25;font-weight:700;color:${C.ink};text-decoration:none">${esc(item.t)}</a>
${meta ? `<div class="nolink" style="font-size:14px;line-height:1.4;color:${C.text2};margin-top:3px">${noLink(meta)}</div>` : ""}</td></tr>`;
}
function digestMail(env, { groups, manageUrl, unsubscribeUrl, freq = "bisemanal", lastSent = null, now = /* @__PURE__ */ new Date() }) {
  const total = groups.reduce((n, g) => n + g.items.length, 0), today = madrid(now).day, next = nextSlot(freq, now);
  const subject = total === 1 ? `1 plan nuevo en Ontoca: ${groups[0].items[0].t}`.slice(0, 120) : groups.length > 1 ? `${total} planes nuevos en tus ${groups.length} b\xFAsquedas de Ontoca` : `${total} planes nuevos para \xAB${groups[0].label}\xBB en Ontoca`;
  const lead = lastSent ? `Planes que han entrado en la agenda de Barcelona desde tu \xFAltimo aviso, del ${longDate(lastSent)}.` : "Tu primer aviso: planes que han entrado en la agenda de Barcelona desde que activaste la b\xFAsqueda.";
  const blocks = groups.map((g) => {
    const shown = g.items.slice(0, MAX_ITEMS_PER_SEARCH), more = g.items.length - shown.length;
    return `<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:26px 0 0">
<tr><td colspan="2" style="padding:0 0 4px;border-bottom:2px solid ${C.ink};font-family:${FONT}">
<span style="display:inline-block;background:${C.ink};color:${C.paper};padding:5px 9px;font-size:15px;font-weight:700">${esc(g.label)}</span>
<span style="font-size:13px;color:${C.text2};margin-left:6px">${g.items.length} ${g.items.length === 1 ? "plan nuevo" : "planes nuevos"}</span>
<div style="font-size:12px;color:${C.text2};margin:6px 0 2px">Captando planes nuevos desde el ${longDate(g.since)} (${shortDate(g.since)})</div></td></tr>
${shown.map((i) => itemRow(env, i, today)).join("")}
<tr><td colspan="2" style="padding:12px 0 0;font-family:${FONT};font-size:14px;font-weight:700"><a href="${esc(g.url)}" style="color:${C.petrol};text-decoration:none">${more > 0 ? `Ver ${more} m\xE1s y toda la b\xFAsqueda \u2192` : "Ver la b\xFAsqueda en Ontoca \u2192"}</a></td></tr></table>`;
  }).join("");
  const headline = `${total === 1 ? "1 plan nuevo" : `${total} planes nuevos`}${groups.length > 1 ? ` en tus ${groups.length} b\xFAsquedas` : ` para \xAB${esc(groups[0].label)}\xBB`}`;
  const inner = `<h1 style="margin:0 0 10px;font-size:32px;line-height:1.05;letter-spacing:-1.2px;font-weight:700">${headline}</h1>
<p style="margin:0;font-size:16px;line-height:1.5;color:${C.text2}">${lead}</p>${blocks}`;
  const sinceLines = groups.map((g) => `\xAB${esc(g.label)}\xBB, desde el ${shortDate(g.since)}`).join("; ");
  const outro = `<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:${C.surface2};border:1px solid ${C.ink}"><tr><td style="padding:20px 22px;font-family:${FONT};color:${C.ink}">
<div style="font-size:17px;font-weight:700;margin:0 0 10px">As\xED funcionan tus avisos</div>
<p style="margin:0 0 8px;font-size:14px;line-height:1.5"><b>Cu\xE1ndo llegan:</b> ${freqSentence(freq)}, solo si hay planes nuevos.${next ? ` El pr\xF3ximo, el ${longDate(next.toISOString())}.` : ""}</p>
<p style="margin:0 0 16px;font-size:14px;line-height:1.5"><b>Qu\xE9 incluyen:</b> solo los planes que entran en la agenda despu\xE9s de activar cada b\xFAsqueda (${sinceLines}). Lo que ya estaba antes lo encuentras en ontoca.com.</p>
${button(manageUrl, "Modificar mis avisos")}${button(unsubscribeUrl, "Cancelar los avisos", false)}</td></tr></table>`;
  const legal = `Recibes este correo porque pediste avisos en ontoca.com. Horarios y precios, tal como los publica cada fuente: conf\xEDrmalos antes de ir. <a href="${site(env)}/privacidad" style="color:#bdbdbd">Privacidad</a>`;
  const html = shell(env, { preheader: groups.map((g) => g.items[0].t).slice(0, 3).join(" \xB7 "), kicker: `Tus avisos<br><b style="color:${C.ink}">${esc(longDate(now.toISOString()))}</b>`, inner, outro, legal });
  const text = `${headline.replace(/&laquo;|&raquo;/g, '"')} en Ontoca. ${lead}

` + groups.map((g) => `${g.label} (captando desde el ${shortDate(g.since)})
` + g.items.slice(0, MAX_ITEMS_PER_SEARCH).map((i) => `- ${i.t} (${[when(i), i.v].filter(Boolean).join(" \xB7 ")})
  ${ficha(env, i.k)}`).join("\n") + `
  Ver la b\xFAsqueda: ${g.url}`).join("\n\n") + `

Tus avisos llegan ${freqSentence(freq)}, solo si hay planes nuevos, y solo con planes que entran en la agenda despu\xE9s de activar cada b\xFAsqueda.

Modificar mis avisos: ${manageUrl}
Cancelar los avisos: ${unsubscribeUrl}`;
  return { subject, html, text, total };
}

// alertas/worker.js
var num = (v, d) => Number.isFinite(Number(v)) && Number(v) > 0 ? Number(v) : d;
async function run(env, now = /* @__PURE__ */ new Date()) {
  const d = await db(env), at = now.toISOString(), m = madrid(now);
  const stale = new Date(now - PENDING_HOURS * 36e5).toISOString(), dayAgo = new Date(now - 864e5).toISOString();
  await d.batch([
    d.prepare("DELETE FROM searches WHERE status='pending' AND created_at<?").bind(stale),
    d.prepare("DELETE FROM subscribers WHERE confirmed_at IS NULL AND created_at<? AND id NOT IN (SELECT subscriber_id FROM searches)").bind(stale),
    d.prepare("DELETE FROM signup_log WHERE at<?").bind(dayAgo)
  ]);
  if (m.hour < 8) return { status: "antes de las 8" };
  const cap = num(env.DAILY_CAP, 280), batch = num(env.BATCH, 20), warnAt = num(env.ALERT_AT, 200);
  const sentToday = (await d.prepare("SELECT count FROM sends WHERE day=?").bind(m.day).first())?.count || 0;
  await capacityWarning(env, d, now, warnAt, cap);
  const room = Math.min(batch, cap - sentToday);
  if (room <= 0) return { status: "tope diario", sentToday };
  const slotB = lastSlot("bisemanal", now)?.toISOString() || "0", slotW = lastSlot("semanal", now)?.toISOString() || "0";
  const { results: due } = await d.prepare(`SELECT id, email, token, freq, confirmed_at, last_sent_at FROM subscribers WHERE confirmed_at IS NOT NULL
      AND ((freq='semanal' AND last_sent_at<?) OR (freq<>'semanal' AND last_sent_at<?)) ORDER BY last_sent_at LIMIT ?`).bind(slotW, slotB, room).all();
  if (!due.length) return { status: "nadie pendiente", sentToday };
  const res = await (env.FETCH || fetch)(`${site(env)}/data/alertas/nuevos.json?v=${Date.now()}`, { cf: { cacheTtl: 0 } });
  if (!res.ok) return { status: `sin novedades publicadas (${res.status})` };
  const feed = (await res.json()).items || [];
  const ids = due.map((s) => s.id);
  const { results: searches } = await d.prepare(`SELECT subscriber_id, filters, label, confirmed_at, created_at FROM searches WHERE status='active'
      AND subscriber_id IN (${ids.map(() => "?").join(",")}) ORDER BY id`).bind(...ids).all();
  const updates = [];
  let sent = 0, checked = 0, error = "";
  for (const sub of due) {
    const since = Date.parse(sub.last_sent_at || 0) || 0;
    const fresh = feed.filter((i) => Date.parse(i.fs) > since && (i.b || i.a) >= m.day), seen = /* @__PURE__ */ new Set();
    const groups = searches.filter((s) => s.subscriber_id === sub.id).map((s) => {
      const f = cleanFilters(JSON.parse(s.filters));
      const from = Math.max(since, Date.parse(s.confirmed_at || s.created_at || 0) || 0);
      const items = fresh.filter((i) => Date.parse(i.fs) > from && !seen.has(i.k) && matches(i, f));
      items.forEach((i) => seen.add(i.k));
      return { label: s.label, url: searchUrl(env, f), items, since: new Date(from || Date.parse(sub.confirmed_at) || now).toISOString() };
    }).filter((g) => g.items.length);
    if (groups.length) {
      const manageUrl = `${site(env)}/alertas/gestionar?t=${sub.token}`, unsubscribeUrl = `${site(env)}/alertas/baja?t=${sub.token}`;
      const first = !sub.last_sent_at || sub.last_sent_at === sub.confirmed_at;
      const mail = digestMail(env, { groups, manageUrl, unsubscribeUrl, freq: sub.freq, lastSent: first ? null : sub.last_sent_at, now });
      try {
        await sendMail(env, {
          to: sub.email,
          subject: mail.subject,
          html: mail.html,
          text: mail.text,
          headers: { "List-Unsubscribe": `<${unsubscribeUrl}>, <mailto:${sender(env)}?subject=baja>`, "List-Unsubscribe-Post": "List-Unsubscribe=One-Click" }
        });
        sent++;
      } catch (err) {
        error = String(err.message || err);
        break;
      }
    } else checked++;
    updates.push(d.prepare("UPDATE subscribers SET last_sent_at=? WHERE id=?").bind(at, sub.id));
  }
  if (sent) updates.push(d.prepare("INSERT INTO sends (day, count) VALUES (?, ?) ON CONFLICT(day) DO UPDATE SET count=count+?").bind(m.day, sent, sent));
  if (updates.length) await d.batch(updates);
  return { status: error ? "error de env\xEDo" : "ok", sent, checked, sentToday: sentToday + sent, error };
}
async function capacityWarning(env, d, now, warnAt, cap) {
  const active = (await d.prepare("SELECT COUNT(*) AS n FROM subscribers WHERE confirmed_at IS NOT NULL").first()).n;
  if (active < warnAt) return;
  const last = (await d.prepare("SELECT value FROM meta WHERE key='capacity_warned_at'").first())?.value || "";
  if (last && now - new Date(last) < 7 * 864e5) return;
  try {
    await sendMail(env, {
      to: sender(env),
      subject: `Ontoca: ${active} suscriptores a las alertas`,
      html: `<p>Hay <b>${active}</b> personas con avisos activos y el tope diario configurado es <b>${cap}</b> correos (plan gratuito de Brevo: 300 al d\xEDa).</p>
<p>Conviene pasar a un plan de pago de Brevo y subir DAILY_CAP en el Worker \xABontoca-alertas\xBB.</p>`,
      text: `Hay ${active} personas con avisos activos y el tope diario es ${cap}. Conviene pasar a un plan de pago de Brevo y subir DAILY_CAP.`
    });
    await d.prepare("INSERT INTO meta (key, value) VALUES ('capacity_warned_at', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value").bind(nowIso()).run();
  } catch (_) {
  }
}
var worker_default = {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(run(env, new Date(event.scheduledTime || Date.now())).then((r) => console.log(JSON.stringify(r))));
  }
};
export {
  worker_default as default,
  run
};
