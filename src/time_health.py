"""Vigilancia de horas por fuente (23-10-2026).

Regla de David: la hora se busca en la fuente; si una fuente que daba horas deja de darlas, lo
normal es que su web haya cambiado o que el conector lea mal, no que la sala haya decidido quitar
las horas. Este módulo lo detecta solo, en cada pasada del motor:

  · guarda una foto diaria por fuente: actos de un día en los próximos 30 días y cuántos tienen
    hora de la propia fuente (``time_coverage``);
  · compara la de hoy con la mediana de las 7 anteriores; si la proporción con hora cae a menos
    de la mitad de lo habitual (con un mínimo de actos y de historial), abre una alerta
    TIME_COVERAGE_DROP en ``source_alerts`` y avisa en el Mac (notificación del sistema);
  · cuando la fuente se recupera, la alerta se cierra sola (``resolved_at``). Nada se borra.

Mientras tanto la web no pierde las horas: la ficha muestra la última que dio la fuente
(src/known_times.py). La alerta es para revisar el conector.
"""
from __future__ import annotations

import datetime as dt
import subprocess
import sys

WINDOW_DAYS = 30
MIN_ACTS = 10          # por debajo, una fuente con pocos actos da proporciones que bailan
MIN_HISTORY = 3        # fotos anteriores necesarias para comparar
MIN_USUAL_SHARE = 0.4  # solo vigila fuentes que de verdad suelen dar hora
DROP_RATIO = 0.5       # alerta si la proporción de hoy es menos de la mitad de la habitual


def initialize(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS time_coverage (source TEXT NOT NULL, day TEXT NOT NULL, acts INTEGER NOT NULL, timed INTEGER NOT NULL,
      measured_at TEXT NOT NULL, PRIMARY KEY(source, day));
    CREATE TABLE IF NOT EXISTS source_alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL,
      first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, resolved_at TEXT, notified_at TEXT);
    CREATE INDEX IF NOT EXISTS source_alerts_open ON source_alerts(source, kind, resolved_at);
    """)


def measure(conn, today=None):
    """{source: (actos, con hora)} de los actos de un día de los próximos 30 días, con hora de la propia fuente
    (sesiones de su lectura; no cuenta la «última hora conocida» ni la de otras agendas)."""
    today = today or dt.date.today()
    rows = conn.execute("""SELECT r.source, COUNT(*),
          SUM(EXISTS (SELECT 1 FROM candidate_occurrences c WHERE c.source=r.source AND c.id=r.id AND c.local_time<>''))
        FROM source_records r
        WHERE r.kind='single' AND r.eligibility<>'exclude' AND substr(r.start_date,1,10) BETWEEN ? AND ?
        GROUP BY r.source""", (today.isoformat(), (today + dt.timedelta(days=WINDOW_DAYS)).isoformat())).fetchall()
    return {s: (n, int(t or 0)) for s, n, t in rows}


def _notify(title, message):
    if sys.platform != "darwin": return False
    script = 'display notification "%s" with title "%s"' % (message.replace('"', "'")[:200], title.replace('"', "'"))
    try:
        subprocess.run(["osascript", "-e", script], timeout=10, check=False, capture_output=True)
        return True
    except Exception:
        return False


def check(conn, today=None, now=None, notify=_notify):
    """Mide, compara con el historial y abre o cierra alertas. Devuelve las alertas abiertas en esta pasada."""
    initialize(conn)
    today = today or dt.date.today()
    now = now or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    opened, still, resolved = [], [], []
    current = measure(conn, today)
    with conn:
        for source, (acts, timed) in current.items():
            conn.execute("""INSERT INTO time_coverage(source,day,acts,timed,measured_at) VALUES(?,?,?,?,?)
                ON CONFLICT(source,day) DO UPDATE SET acts=excluded.acts,timed=excluded.timed,measured_at=excluded.measured_at""",
                         (source, today.isoformat(), acts, timed, now))
        for source, (acts, timed) in current.items():
            history = [t / n for n, t in conn.execute("SELECT acts,timed FROM time_coverage WHERE source=? AND day<? AND acts>=? ORDER BY day DESC LIMIT 7",
                                                      (source, today.isoformat(), MIN_ACTS)).fetchall()]
            share = timed / acts if acts else 0.0
            open_alert = conn.execute("SELECT id FROM source_alerts WHERE source=? AND kind='TIME_COVERAGE_DROP' AND resolved_at IS NULL", (source,)).fetchone()
            usual = sorted(history)[len(history) // 2] if len(history) >= MIN_HISTORY else None
            dropped = usual is not None and acts >= MIN_ACTS and usual >= MIN_USUAL_SHARE and share < usual * DROP_RATIO
            if dropped:
                detail = "%d %% de los actos con hora (%d de %d) frente al %d %% habitual: revisar el conector o la web de la fuente" % (round(share * 100), timed, acts, round(usual * 100))
                if open_alert:
                    conn.execute("UPDATE source_alerts SET last_seen_at=?, detail=? WHERE id=?", (now, detail, open_alert[0])); still.append(source)
                else:
                    aid = conn.execute("INSERT INTO source_alerts(source,kind,detail,first_seen_at,last_seen_at) VALUES(?,?,?,?,?)",
                                       (source, "TIME_COVERAGE_DROP", detail, now, now)).lastrowid
                    opened.append({"source": source, "detail": detail})
                    if notify and notify("Ontoca: %s ha dejado de dar horas" % source, detail):
                        conn.execute("UPDATE source_alerts SET notified_at=? WHERE id=?", (now, aid))
            elif open_alert and usual is not None and share >= usual * DROP_RATIO:
                conn.execute("UPDATE source_alerts SET resolved_at=? WHERE id=?", (now, open_alert[0])); resolved.append(source)
    return {"opened": opened, "still_open": still, "resolved": resolved, "sources": len(current)}


def open_alerts(conn):
    initialize(conn)
    return [dict(zip(("source", "kind", "detail", "first_seen_at", "last_seen_at"), r)) for r in
            conn.execute("SELECT source,kind,detail,first_seen_at,last_seen_at FROM source_alerts WHERE resolved_at IS NULL ORDER BY first_seen_at")]
