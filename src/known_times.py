"""Última hora conocida de cada acto (23-10-2026).

Cada lectura de una fuente reescribe las sesiones de la ficha (``candidate_occurrences``). Si una
pasada nueva no trae la hora de un día que otra anterior sí traía (la sala cambió la maqueta, la IA
no copió la cita, el listado la quitó), la ficha se quedaba en «Hora por confirmar». Decisión de
David: mostrar la que ya teníamos.

Aquí se guarda, para cada ficha y día, toda hora que alguna lectura haya dado, con su campo de
evidencia y cuándo se vio por primera y última vez. Nada se borra. Al montar la ficha pública, un
día sin hora en la lectura actual toma la última hora conocida de ese mismo día y de esa misma
ficha (``evidence_field='ultima_hora_conocida'``); si la lectura actual da otra hora, manda la
actual. Una ficha que deja de estar en su fuente deja de publicarse por su propio camino: esto no
la resucita.
"""
from __future__ import annotations

import json
import sqlite3

EVIDENCE = 'ultima_hora_conocida'


def initialize(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS known_times (source TEXT NOT NULL, id TEXT NOT NULL, local_date TEXT NOT NULL,
      local_time TEXT NOT NULL, evidence_field TEXT NOT NULL DEFAULT '', first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
      PRIMARY KEY(source, id, local_date, local_time))""")


def remember(conn: sqlite3.Connection, source: str, rid: str, occurrences, observed_at: str) -> int:
    """Guarda las horas de estas sesiones (las que la tengan). Devuelve cuántas filas tocó."""
    rows = [(source, rid, str(o.get('local_date') or o.get('date') or '')[:10], str(o.get('local_time') or o.get('time') or ''),
             str(o.get('evidence_field') or ''), observed_at, observed_at) for o in occurrences or []]
    rows = [r for r in rows if r[2] and len(r[3]) == 5 and r[3] != '00:00']
    if not rows: return 0
    initialize(conn)
    conn.executemany("""INSERT INTO known_times(source,id,local_date,local_time,evidence_field,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(source,id,local_date,local_time) DO UPDATE SET
          last_seen_at=MAX(known_times.last_seen_at, excluded.last_seen_at),
          first_seen_at=MIN(known_times.first_seen_at, excluded.first_seen_at),
          evidence_field=CASE WHEN excluded.last_seen_at>=known_times.last_seen_at THEN excluded.evidence_field ELSE known_times.evidence_field END""", rows)
    return len(rows)


def _latest(by_day: dict) -> dict:
    # De cada día, las horas de la lectura más reciente que dio alguna (varios pases el mismo día se conservan juntos).
    for d, items in by_day.items():
        last = max(x['last_seen_at'] for x in items)
        by_day[d] = sorted([x for x in items if x['last_seen_at'][:10] == last[:10]], key=lambda x: x['time'])
    return by_day


def load(conn: sqlite3.Connection) -> dict:
    """{(source, id): {fecha: [{'time', 'evidence_field', 'last_seen_at'}]}} — las horas de la última lectura que dio alguna."""
    try:
        rows = conn.execute('SELECT source,id,local_date,local_time,evidence_field,last_seen_at FROM known_times').fetchall()
    except sqlite3.DatabaseError:
        return {}
    out: dict = {}
    for s, i, d, t, f, seen in rows:
        out.setdefault((s, i), {}).setdefault(d, []).append({'time': t, 'evidence_field': f, 'last_seen_at': seen})
    for by_day in out.values(): _latest(by_day)
    return out


def for_record(conn: sqlite3.Connection, source: str, rid: str) -> dict:
    try:
        rows = conn.execute('SELECT local_date,local_time,evidence_field,last_seen_at FROM known_times WHERE source=? AND id=?', (source, rid)).fetchall()
    except sqlite3.DatabaseError:
        return {}
    by_day: dict = {}
    for d, t, f, seen in rows: by_day.setdefault(d, []).append({'time': t, 'evidence_field': f, 'last_seen_at': seen})
    return _latest(by_day)


def fill(occurrences: list, known_by_day: dict, start: str, end: str) -> list:
    """Añade a ``occurrences`` (en su sitio) la última hora conocida de cada día del acto que la lectura
    actual deja sin hora. Devuelve las fechas completadas."""
    if not known_by_day: return []
    start, end = str(start or '')[:10], str(end or start or '')[:10]
    timed = {o['date'] for o in occurrences if o.get('time')}
    named = {o['date'] for o in occurrences}
    filled = []
    for day, items in sorted(known_by_day.items()):
        if day in timed or not (start <= day <= end): continue
        # En un acto de varios días solo vale para días que la lectura actual aún nombra (o si no nombra ninguno).
        if start != end and named and day not in named: continue
        occurrences[:] = [o for o in occurrences if o['date'] != day]
        for x in items:
            # Hora rescatada de la página del acto (src/time_rescue.py) o última que dio la lectura de la fuente.
            evidence = 'rescate' if str(x['evidence_field']).startswith('rescate') else EVIDENCE
            occurrences.append({'date': day, 'time': x['time'], 'evidence_field': evidence, 'verified': False,
                                'seen_at': x['last_seen_at'][:10], 'original_evidence': x['evidence_field']})
        filled.append(day)
    if filled: occurrences.sort(key=lambda o: (o['date'], o.get('time') or ''))
    return filled


def backfill(conn: sqlite3.Connection, today=None) -> dict:
    """Recorre el historial (``source_record_versions``) y guarda las horas que dio cada versión.
    Sin red; idempotente. Usa la misma lectura de sesiones que ``rebuild_candidates``."""
    from src.sync import record_from_stored
    from src.pipeline import candidate_sessions
    initialize(conn)
    seen = stored = 0
    current = {(s, i): (st, en, k) for s, i, st, en, k in conn.execute('SELECT source,id,start_date,end_date,kind FROM source_records')}
    with conn:
        for source, rid, raw_text, observed in conn.execute('SELECT source,external_id,raw_json,observed_at FROM source_record_versions ORDER BY observed_at').fetchall():
            seen += 1
            try: raw = json.loads(raw_text)
            except (TypeError, ValueError): continue
            if not isinstance(raw, dict): continue
            row = current.get((source, rid))
            normalized = raw.get('normalized') or {}
            start, end = normalized.get('start') or (row[0] if row else ''), normalized.get('end') or (row[1] if row else '')
            kind = normalized.get('kind') or (row[2] if row else '')
            record = record_from_stored(source, rid, raw, start, end, kind, 'include', today)
            if not record: continue
            try: occ = candidate_sessions(record)
            except Exception: continue
            stored += remember(conn, source, rid, occ, observed or '')
    return {'versions': seen, 'times_stored': stored, 'rows': conn.execute('SELECT COUNT(*) FROM known_times').fetchone()[0]}
