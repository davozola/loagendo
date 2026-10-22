"""Comprobación de los enlaces externos de las fichas antes de publicarlas (22-10-2026).

Una ficha no debe mandar a una página rota: el 22-10-2026 las fichas de evento de graf.cat
devolvían un error 500 de WordPress y la web seguía enlazándolas. Antes de cada publicación se
pide cada enlace secundario de las fichas (``links`` del detalle) y se guarda su estado en
``link_checks``; la exportación deja fuera de la web pública los que están rotos.

Nada se borra: el enlace sigue en los datos de la fuente y en ``link_checks``, y vuelve a la web
en cuanto responde bien. Cada cambio de estado queda en ``link_check_log`` (procedencia e historial).

Qué cuenta como roto (``broken``):
  · HTTP 404 o 410 (la página no existe) y cualquier 5xx (el servidor falla), a la primera;
  · sin respuesta (DNS, conexión, tiempo agotado) dos comprobaciones seguidas, para no ocultar
    un enlace por un fallo pasajero de la red del Mac. Si en una pasada más de la mitad de los
    enlaces no responde, se da por caída la red y esa pasada no anota fallos de conexión.
401, 403, 429 y otros 4xx son ``unverified``: muchas webs (redes sociales, Cloudflare) cortan a los
robots y la página puede estar bien para una persona; se publican.

Se vuelve a comprobar a los 3 días si estaba bien, a las 6 horas si estaba rota y al día si no se
pudo verificar. Cada publicación comprueba como mucho ``MAX_CHECKS`` enlaces y ``TIME_BUDGET``
segundos; lo que no llega a comprobarse se publica (sin estado no se oculta nada).
La verificación TLS es la de ``src.network`` (nunca se desactiva).
"""
from __future__ import annotations

import datetime as dt
import socket
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from src.network import ascii_url, tls_context

USER_AGENT = 'Brollant/1.3 (+https://brollant.com) link check'
TIMEOUT = 12
WORKERS = 8
PER_HOST = 2
MAX_CHECKS = 1500
TIME_BUDGET = 300
TTL = {'ok': dt.timedelta(days=3), 'broken': dt.timedelta(hours=6), 'unverified': dt.timedelta(days=1), 'unreachable': dt.timedelta(hours=6)}
UNREACHABLE_STRIKES = 2
NETWORK_MIN = 10      # con al menos 10 comprobaciones en la pasada…
NETWORK_SHARE = 0.5   # …si más de la mitad no tiene respuesta, la red está caída: no se anota nada


def initialize(conn):
    conn.executescript('''
      CREATE TABLE IF NOT EXISTS link_checks(
        url TEXT PRIMARY KEY, host TEXT NOT NULL, state TEXT NOT NULL, http_status INTEGER, error TEXT,
        consecutive_failures INTEGER NOT NULL DEFAULT 0, first_failed_at TEXT, last_ok_at TEXT, checked_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS link_check_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL, checked_at TEXT NOT NULL, state TEXT NOT NULL, http_status INTEGER, error TEXT);
      CREATE TABLE IF NOT EXISTS link_usage(
        url TEXT NOT NULL, source TEXT NOT NULL, id TEXT NOT NULL, label TEXT, last_seen_at TEXT NOT NULL, PRIMARY KEY(url, source, id));
    ''')


def _now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def classify(http_status=None, error=None):
    """Estado de una respuesta: ok, broken, unverified o unreachable (sin respuesta)."""
    if http_status is None: return 'unreachable'
    if http_status < 400: return 'ok'
    if http_status in (404, 410) or http_status >= 500: return 'broken'
    return 'unverified'


def fetch_status(url, timeout=TIMEOUT):
    """(código HTTP, error) de un GET al enlace, siguiendo redirecciones; no lee el cuerpo."""
    request = urllib.request.Request(ascii_url(url), headers={'User-Agent': USER_AGENT, 'Accept': 'text/html,*/*;q=0.8'})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=tls_context()) as response:
            return response.status, None
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, ValueError) as exc:
        return None, str(getattr(exc, 'reason', exc))[:300]


def _due(row, now):
    if row is None: return True
    state, checked_at = row
    try: last = dt.datetime.fromisoformat(checked_at)
    except (TypeError, ValueError): return True
    return now - last >= TTL.get(state, TTL['unverified'])


def _round_robin(urls):
    by_host = {}
    for u in urls: by_host.setdefault((urlsplit(u).hostname or '').lower(), []).append(u)
    queues = list(by_host.values()); out = []
    for i in range(max((len(q) for q in queues), default=0)): out += [q[i] for q in queues if i < len(q)]
    return out


def refresh(conn, urls, fetch=fetch_status, *, max_checks=MAX_CHECKS, time_budget=TIME_BUDGET):
    """Comprueba los enlaces que tocan (nuevos o caducados) y guarda su estado. Devuelve un resumen."""
    initialize(conn)
    now = _now()
    urls = sorted({u for u in urls if str(u).startswith(('https://', 'http://'))})
    known = {u: (s, c) for u, s, c in conn.execute('SELECT url,state,checked_at FROM link_checks')}
    # Primero los rotos (para que vuelvan en cuanto se arreglen), luego los nuevos, luego los caducados.
    due = [u for u in urls if _due(known.get(u), now)]
    # Dentro de cada grupo, una web tras otra (y no 12.000 fichas de GuiaBCN seguidas), para que el
    # presupuesto de la pasada llegue a todas las webs enlazadas.
    groups = {}
    for u in due: groups.setdefault(0 if known.get(u, ('',))[0] in ('broken', 'unreachable') else 1 if u not in known else 2, []).append(u)
    due = [u for g in sorted(groups) for u in _round_robin(groups[g])][:max_checks]
    locks, guard, results = {}, threading.Lock(), {}
    deadline = time.monotonic() + time_budget

    def one(url):
        if time.monotonic() > deadline: return
        host = (urlsplit(url).hostname or '').lower()
        with guard: sem = locks.setdefault(host, threading.Semaphore(PER_HOST))
        with sem:
            if time.monotonic() > deadline: return
            results[url] = fetch(url)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool: list(pool.map(one, due))
    # Si casi nada responde, el problema es la red del Mac, no las webs: no se cuenta como fallo.
    no_answer = [u for u, (code, _) in results.items() if code is None]
    network_down = len(results) >= NETWORK_MIN and len(no_answer) > NETWORK_SHARE * len(results)
    if network_down:
        for u in no_answer: results.pop(u)
    changed = 0
    stamp = _now().isoformat()
    with conn:
        for url, (code, error) in results.items():
            prev = conn.execute('SELECT state,consecutive_failures,first_failed_at,last_ok_at FROM link_checks WHERE url=?', (url,)).fetchone()
            prev_state, fails, first_failed, last_ok = prev or (None, 0, None, None)
            raw = classify(code, error)
            if raw == 'ok':
                fails, first_failed, last_ok, state = 0, None, stamp, 'ok'
            elif raw == 'unverified':
                fails, first_failed, state = 0, None, 'unverified'
            else:
                fails = (fails or 0) + 1; first_failed = first_failed or stamp
                state = 'broken' if raw == 'broken' or fails >= UNREACHABLE_STRIKES else 'unreachable'
            conn.execute('''INSERT INTO link_checks(url,host,state,http_status,error,consecutive_failures,first_failed_at,last_ok_at,checked_at)
                VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET state=excluded.state,http_status=excluded.http_status,error=excluded.error,
                consecutive_failures=excluded.consecutive_failures,first_failed_at=excluded.first_failed_at,last_ok_at=excluded.last_ok_at,checked_at=excluded.checked_at''',
                (url, (urlsplit(url).hostname or '').lower(), state, code, error, fails, first_failed, last_ok, stamp))
            if state != prev_state:
                changed += 1
                conn.execute('INSERT INTO link_check_log(url,checked_at,state,http_status,error) VALUES(?,?,?,?,?)', (url, stamp, state, code, error))
    return {'links': len(urls), 'due': len(due), 'checked': len(results), 'state_changes': changed, 'network_down': network_down,
            'skipped': len(due) - len(results)}


def broken(conn, urls=None):
    """Enlaces que la web no debe mostrar ahora mismo (estado ``broken``)."""
    try: rows = conn.execute("SELECT url FROM link_checks WHERE state='broken'").fetchall()
    except Exception: return set()
    out = {r[0] for r in rows}
    return out if urls is None else out & set(urls)


def record_usage(conn, usage):
    """Qué ficha usa cada enlace (para el readiness por fuente). ``usage``: [(url, source, id, label)]."""
    initialize(conn)
    stamp = _now().isoformat()
    with conn:
        conn.executemany('''INSERT INTO link_usage(url,source,id,label,last_seen_at) VALUES(?,?,?,?,?)
            ON CONFLICT(url,source,id) DO UPDATE SET label=excluded.label,last_seen_at=excluded.last_seen_at''', [(u, s, i, l, stamp) for u, s, i, l in usage])
    return stamp


def summary(conn, since=None):
    """Enlaces externos rotos por fuente y por web, para el readiness. ``since``: uso visto desde esa fecha
    (por defecto, el día de la última exportación)."""
    try:
        if since is None:
            last = conn.execute('SELECT MAX(last_seen_at) FROM link_usage').fetchone()[0]
            if not last: return {'checked_links': 0, 'hidden_links': 0, 'by_source': {}, 'by_host': {}}
            since = (dt.datetime.fromisoformat(last) - dt.timedelta(days=1)).isoformat()
        rows = conn.execute('''SELECT u.source,u.url,COALESCE(c.state,'unchecked'),c.host,c.http_status,c.first_failed_at FROM link_usage u
            LEFT JOIN link_checks c ON c.url=u.url WHERE u.last_seen_at>=?''', (since,)).fetchall()
    except Exception:
        return {'checked_links': 0, 'hidden_links': 0, 'by_source': {}, 'by_host': {}}
    by_source, by_host, checked, hidden = {}, {}, set(), set()
    for source, url, state, host, code, since_failed in rows:
        item = by_source.setdefault(source, {'links': 0, 'broken': 0, 'unverified': 0, 'unchecked': 0})
        item['links'] += 1
        if state in ('broken', 'unverified', 'unchecked'): item[state] += 1
        if state != 'unchecked': checked.add(url)
        if state == 'broken':
            hidden.add(url)
            h = by_host.setdefault(host or (urlsplit(url).hostname or ''), {'broken': 0, 'http_status': {}, 'since': since_failed})
            h['broken'] += 1; h['http_status'][str(code or 'sin respuesta')] = h['http_status'].get(str(code or 'sin respuesta'), 0) + 1
            if since_failed and (not h['since'] or since_failed < h['since']): h['since'] = since_failed
    return {'checked_links': len(checked), 'hidden_links': len(hidden), 'by_source': dict(sorted(by_source.items())),
            'by_host': dict(sorted(by_host.items(), key=lambda kv: -kv[1]['broken']))}
