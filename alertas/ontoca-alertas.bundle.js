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
var CHANS = { familia: "En familia", barrio: "Vida de barrio", aire: "Al aire libre", galerias: "Arte y galer\xEDas", festivales: "Festivales" };
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
    body: JSON.stringify({
      sender: { name: "Ontoca", email: sender(env) },
      replyTo: { email: sender(env) },
      to: [{ email: to }],
      subject,
      htmlContent: html,
      textContent: text,
      headers: headers || {},
      tags: ["alertas"]
    })
  });
  if (!res.ok) throw new Error(`Brevo ${res.status}: ${(await res.text()).slice(0, 200)}`);
  return true;
}
var shell = (inner, footer) => `<!doctype html><html lang="es"><body style="margin:0;background:#fff;color:#000;font-family:Helvetica,Arial,sans-serif">
<div style="max-width:600px;margin:0 auto;padding:24px 16px"><div style="font-size:26px;font-weight:700;letter-spacing:-1px;margin-bottom:20px">ontoca<span style="color:#097C87">.</span></div>
${inner}<div style="border-top:1px solid #000;margin-top:28px;padding-top:12px;font-size:12px;color:#444;line-height:1.5">${footer}</div></div></body></html>`;
var when = (item) => {
  const fmt = (d) => {
    const [y, m, dd] = d.split("-").map(Number);
    return `${dd}/${m}`;
  };
  const date = item.a === item.b || !item.b ? fmt(item.a) : `del ${fmt(item.a)} al ${fmt(item.b)}`;
  return item.tm ? `${date} \xB7 ${item.tm}` : date;
};
var ficha = (env, key) => {
  const [s, ...rest] = key.split(":");
  return `${site(env)}/e/${encodeURIComponent(s)}/${encodeURIComponent(rest.join(":"))}`;
};
function digestMail(env, { groups, manageUrl, unsubscribeUrl }) {
  const total = groups.reduce((n, g) => n + g.items.length, 0);
  const subject = total === 1 ? `1 plan nuevo en Ontoca: ${groups[0].items[0].t}`.slice(0, 120) : `${total} planes nuevos para tus b\xFAsquedas en Ontoca`;
  const blocks = groups.map((g) => {
    const shown = g.items.slice(0, MAX_ITEMS_PER_SEARCH), more = g.items.length - shown.length;
    return `<h2 style="font-size:18px;margin:24px 0 8px;border-bottom:1px solid #000;padding-bottom:6px">${esc(g.label)}</h2>` + shown.map((i) => `<p style="margin:0 0 12px;line-height:1.4"><a href="${esc(ficha(env, i.k))}" style="color:#000;font-weight:700;font-size:16px">${esc(i.t)}</a><br><span style="font-size:14px;color:#444">${esc([when(i), i.v, i.fr ? "Gratis" : ""].filter(Boolean).join(" \xB7 "))}</span></p>`).join("") + `<p style="margin:4px 0 0;font-size:14px"><a href="${esc(g.url)}" style="color:#097C87">${more > 0 ? `Ver ${more} m\xE1s y toda la b\xFAsqueda` : "Ver la b\xFAsqueda en Ontoca"}</a></p>`;
  }).join("");
  const html = shell(
    `<p style="font-size:16px;margin:0">Planes nuevos en la agenda de Barcelona desde tu \xFAltimo aviso.</p>${blocks}`,
    `Recibes este correo porque pediste avisos en Ontoca. <a href="${esc(manageUrl)}" style="color:#444">Gestionar mis avisos</a> \xB7 <a href="${esc(unsubscribeUrl)}" style="color:#444">Darme de baja</a> \xB7 <a href="${site(env)}/privacidad" style="color:#444">Privacidad</a>`
  );
  const text = "Planes nuevos en Ontoca desde tu \xFAltimo aviso.\n\n" + groups.map((g) => `${g.label}
` + g.items.slice(0, MAX_ITEMS_PER_SEARCH).map((i) => `- ${i.t} (${[when(i), i.v].filter(Boolean).join(" \xB7 ")})
  ${ficha(env, i.k)}`).join("\n") + `
  Ver la b\xFAsqueda: ${g.url}`).join("\n\n") + `

Gestionar mis avisos: ${manageUrl}
Darme de baja: ${unsubscribeUrl}`;
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
  const { results: due } = await d.prepare(`SELECT id, email, token, freq, last_sent_at FROM subscribers WHERE confirmed_at IS NOT NULL
      AND ((freq='semanal' AND last_sent_at<?) OR (freq<>'semanal' AND last_sent_at<?)) ORDER BY last_sent_at LIMIT ?`).bind(slotW, slotB, room).all();
  if (!due.length) return { status: "nadie pendiente", sentToday };
  const res = await (env.FETCH || fetch)(`${site(env)}/data/alertas/nuevos.json?v=${Date.now()}`, { cf: { cacheTtl: 0 } });
  if (!res.ok) return { status: `sin novedades publicadas (${res.status})` };
  const feed = (await res.json()).items || [];
  const ids = due.map((s) => s.id);
  const { results: searches } = await d.prepare(`SELECT subscriber_id, filters, label FROM searches WHERE status='active'
      AND subscriber_id IN (${ids.map(() => "?").join(",")}) ORDER BY id`).bind(...ids).all();
  const updates = [];
  let sent = 0, checked = 0, error = "";
  for (const sub of due) {
    const since = Date.parse(sub.last_sent_at || 0) || 0;
    const fresh = feed.filter((i) => Date.parse(i.fs) > since && (i.b || i.a) >= m.day), seen = /* @__PURE__ */ new Set();
    const groups = searches.filter((s) => s.subscriber_id === sub.id).map((s) => {
      const f = cleanFilters(JSON.parse(s.filters));
      const items = fresh.filter((i) => !seen.has(i.k) && matches(i, f));
      items.forEach((i) => seen.add(i.k));
      return { label: s.label, url: searchUrl(env, f), items };
    }).filter((g) => g.items.length);
    if (groups.length) {
      const manageUrl = `${site(env)}/alertas/gestionar?t=${sub.token}`, unsubscribeUrl = `${site(env)}/alertas/baja?t=${sub.token}`;
      const mail = digestMail(env, { groups, manageUrl, unsubscribeUrl });
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
