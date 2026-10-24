"""Actos aplazados o cancelados (24-10-2026): que no salgan como vigentes en ninguna ficha.

Caso: Dani Martín en el Palau Sant Jordi (23 y 24-10-2026). GuiaBCN lo marcaba «Acte ajornat»
(código 3, «Ajornat. Properament es comunicaran les noves dates»), pero la ficha publicada era la de
Open Data BCN (mismo id, con «event_status: ok» aún) y las de Conciertos.Club; Ontoca lo destacaba.

Fuentes del estado (solo lo que la fuente dice, con su cita):
  · GuiaBCN: ``api_item.status.item.code`` 2 «Acte suspès», 3 «Acte ajornat», y las marcas del
    título («*Ajornat», «*Suspès», «*Cancel·lada», «**Anul·lat**»);
  · Open Data BCN: ``event_status`` distinto de «ok» («deferred» = aplazado);
  · schema.org de salas y ticketeras: ``eventStatus`` EventCancelled / EventPostponed;
  · Eventbrite: estado «canceled» de su API.
El estado pasa a las demás fichas del mismo acto: mismo día (dentro del periodo del aviso), mismo
recinto y título que contiene las mismas palabras propias («Dani Martín» ⊂ «Concert "Dani Martin",
dins la gira…»). Esas fichas no se publican (``moved_to``) y nada se borra; la evidencia queda en
la ficha (``event_status``).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
import unicodedata

TITLE_MARK = re.compile(r"\*+\s*(ajornat|ajornada|aplazad[oa]|suspès|suspes|suspesa|suspendid[oa]|cancel·lat|cancel·lada|cancel.lat|cancel.lada|cancelad[oa]|anul·lat|anul·lada|anulad[oa])\b\**", re.I)
POSTPONED = {'ajornat', 'ajornada', 'aplazado', 'aplazada'}
STOP = {'concert', 'concierto', 'concerts', 'conciertos', 'gira', 'tour', 'dins', 'dentro', 'amb', 'con', 'live', 'presenta', 'presents', 'espectacle',
        'espectaculo', 'festival', 'the', 'and', 'del', 'dels', 'les', 'las', 'los', 'els', 'una', 'per', 'para', 'barcelona', 'world', 'entrades', 'entradas',
        'teatre', 'teatro', 'sala', 'palau', 'sant', 'jordi', 'club', 'anos', 'anys', 'aniversari', 'aniversario', 'edicio', 'edicion', 'ajornat', 'suspes', 'cancel',
        # Géneros y formatos: no identifican un acto por sí solos («Taller» no es «Taller 'Modelat amb Fusion 360'»).
        'taller', 'tallers', 'xerrada', 'xerrades', 'charla', 'visita', 'visites', 'visitas', 'curs', 'curso', 'lectura', 'mostra', 'fira', 'feria', 'familiar',
        'infantil', 'cia', 'companyia', 'carrec', 'cargo', 'exposicio', 'exposicion', 'presentacio', 'presentacion', 'sessio', 'sesion', 'jornada', 'jornades',
        'activitat', 'actividad', 'dansa', 'danza', 'musica', 'cinema', 'cine', 'projeccio', 'concert', 'recital', 'nit', 'noche', 'dia', 'festa', 'fiesta'}
_CACHE = {'stamp': None, 'map': {}}


def _fold(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(text or '').lower()) if not unicodedata.combining(c))


def words(title):
    t = TITLE_MARK.sub(' ', str(title or ''))
    return {w for w in re.findall(r"[a-z0-9]+", _fold(t)) if len(w) >= 3 and w not in STOP and not w.isdigit()}


def _label(text):
    t = _fold(text)
    if any(w in t for w in ('ajorn', 'aplaz', 'deferred', 'postpon')): return 'aplazado'
    return 'cancelado'


def anchors(conn, today):
    """[(source, id, estado, evidencia, inicio, fin, palabras, recintos)] de las fichas cuya fuente dice que el acto
    está aplazado o cancelado y que aún no ha pasado."""
    out = []
    rows = conn.execute("""SELECT source,id,title,substr(start_date,1,10),substr(end_date,1,10),raw_json FROM source_records
        WHERE end_date>=? AND (
          (source='guiabcn' AND (json_extract(raw_json,'$.api_item.status.item.code') IN ('2','3') OR title LIKE '%*%'))
          OR (source='opendatabcn_agenda' AND COALESCE(json_extract(raw_json,'$.event_status'),'ok') NOT IN ('ok',''))
          OR (raw_json LIKE '%EventCancelled%' OR raw_json LIKE '%EventPostponed%'))""", (today,)).fetchall()
    for source, rid, title, start, end, raw_text in rows:
        try: raw = json.loads(raw_text)
        except ValueError: continue
        state = evidence = ''
        if source == 'guiabcn':
            item = (raw.get('api_item') or {})
            status = ((item.get('status') or {}).get('item') or {})
            mark = TITLE_MARK.search(title or '')
            if str(status.get('code')) in ('2', '3'):
                state = 'aplazado' if str(status.get('code')) == '3' else 'cancelado'
                evidence = f"Ajuntament de Barcelona (GuiaBCN): «{status.get('name') or ''}»" + (f" · «{item['warning']}»" if item.get('warning') else '')
            elif mark:
                state = 'aplazado' if _fold(mark.group(1)) in POSTPONED else 'cancelado'
                evidence = f"Ajuntament de Barcelona (GuiaBCN), en el título: «{mark.group(0).strip()}»"
        elif source == 'opendatabcn_agenda':
            st = raw.get('event_status')
            if st and st != 'ok':
                state = _label(f"{st} {raw.get('event_status_name') or ''}")
                evidence = f"Ajuntament de Barcelona (Open Data BCN): «{raw.get('event_status_name') or st}»"
        else:
            st = str(((raw.get('item') or {}).get('eventStatus')) or '')
            if 'Cancelled' in st or 'Postponed' in st:
                state = 'aplazado' if 'Postponed' in st else 'cancelado'
                evidence = f"La fuente lo publica como {'aplazado' if state == 'aplazado' else 'cancelado'} (schema.org {st.split('/')[-1]})"
        if not state: continue
        venues = {_fold(v) for (v,) in conn.execute('SELECT venue FROM source_venues WHERE source=? AND id=?', (source, rid)) if v}
        out.append((source, rid, state, evidence, start, end, words(title), venues))
    return out


def _same_venue(a, b):
    if not a or not b: return False
    wa = {w for v in a for w in re.findall(r"[a-z0-9]+", v) if len(w) >= 3}
    wb = {w for v in b for w in re.findall(r"[a-z0-9]+", v) if len(w) >= 3}
    small, big = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    return bool(small) and len(small & big) >= max(1, min(2, len(small)))


def compute(conn, today=None):
    """{(source, id): {'estado', 'evidencia', 'origen'}} para las fichas del aviso y las del mismo acto."""
    today = (today or dt.date.today()).isoformat()
    out = {}
    for source, rid, state, evidence, start, end, wanted, venues in anchors(conn, today):
        info = {'estado': state, 'evidencia': evidence, 'origen': f'{source}:{rid}'}
        out[(source, rid)] = info
        if not wanted: continue
        # Las demás fichas del mismo acto: algún día dentro del periodo del aviso, mismo recinto y título.
        for s, i, title in conn.execute("""SELECT source,id,title FROM source_records WHERE NOT (source=? AND id=?)
                AND substr(start_date,1,10)<=? AND substr(end_date,1,10)>=? AND eligibility<>'exclude'""", (source, rid, end, start)).fetchall():
            if (s, i) in out: continue
            have = words(title)
            if not have: continue
            small, big = (have, wanted) if len(have) <= len(wanted) else (wanted, have)
            if not small <= big: continue
            other = {_fold(v) for (v,) in conn.execute('SELECT venue FROM source_venues WHERE source=? AND id=?', (s, i)) if v}
            if (s == 'opendatabcn_agenda' and source == 'guiabcn' and i == rid) or _same_venue(venues, other):
                out[(s, i)] = info
    return out


def statuses(conn):
    """compute() con caché: se recalcula cuando cambian las fichas de las fuentes."""
    try:
        stamp = conn.execute("SELECT COUNT(*), MAX(raw_sha256), (SELECT MAX(rowid) FROM source_records) FROM source_records WHERE source IN ('guiabcn','opendatabcn_agenda')").fetchone() + (dt.date.today().isoformat(),)
    except sqlite3.DatabaseError:
        return {}
    if stamp != _CACHE['stamp']:
        try: _CACHE.update(stamp=stamp, map=compute(conn))
        except sqlite3.DatabaseError: _CACHE.update(stamp=stamp, map={})
    return _CACHE['map']
