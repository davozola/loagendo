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
        # Contenida en su periodo: un festival que dura meses no se aplaza porque se aplace uno de sus conciertos.
        for s, i, title in conn.execute("""SELECT source,id,title FROM source_records WHERE NOT (source=? AND id=?)
                AND substr(start_date,1,10)>=? AND substr(end_date,1,10)<=? AND eligibility<>'exclude'""", (source, rid, start, end)).fetchall():
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


# ---------- entradas agotadas (24-10-2026) ----------
SOLD = re.compile(r"\b(?:entrades|entradas|localitats|localidades|places|plazas|tickets?)\s+(?:exhaurides|esgotades|agotadas|esgotats|exhaurits)\b|\bsold[\s-]?out\b|\bexhaurit\b|\bcomplet\b|\bagotado\b|\bexhaurides\b|\besgotat\b", re.I)
MONTH_N = {'gener': 1, 'enero': 1, 'febrer': 2, 'febrero': 2, 'marc': 3, 'marzo': 3, 'abril': 4, 'maig': 5, 'mayo': 5, 'juny': 6, 'junio': 6, 'juliol': 7, 'julio': 7,
           'agost': 8, 'agosto': 8, 'setembre': 9, 'septiembre': 9, 'octubre': 10, 'novembre': 11, 'noviembre': 11, 'desembre': 12, 'diciembre': 12}
DATE_IN = re.compile(r"\b((?:\d{1,2}(?:\s*,\s*|\s+i\s+|\s+y\s+))*\d{1,2})\s+(?:de\s+|d')\s*(" + "|".join(MONTH_N) + r")\b")
_SOLD_CACHE = {'stamp': None, 'map': {}}


def _days_in(text, start, end):
    """Días de la ficha que nombra el aviso («pel concert del 24 d'octubre»); vacío = todos."""
    out = set()
    for ds, mo in DATE_IN.findall(_fold(text)):
      for d in re.findall(r"\d{1,2}", ds):
        for year in {start[:4], end[:4]}:
            try: day = dt.date(int(year), MONTH_N[mo], int(d)).isoformat()
            except ValueError: continue
            if start <= day <= end: out.add(day)
    return sorted(out)


def sold_anchors(conn, today):
    rows = conn.execute("""SELECT source,id,title,substr(start_date,1,10),substr(end_date,1,10),raw_json FROM source_records
        WHERE end_date>=? AND eligibility<>'exclude' AND (
          (source='opendatabcn_agenda' AND raw_json LIKE '%"type": "public"%')
          OR (source='guiabcn' AND json_extract(raw_json,'$.api_item.warning') IS NOT NULL)
          OR raw_json LIKE '%SoldOut%')""", (today,)).fetchall()
    out = []
    for source, rid, title, start, end, raw_text in rows:
        try: raw = json.loads(raw_text)
        except ValueError: continue
        texts = []
        if source == 'opendatabcn_agenda':
            texts = [re.sub(r'<[^>]+>', ' ', str(w.get('text') or '')) for w in raw.get('warnings') or [] if isinstance(w, dict) and w.get('type') == 'public']
        elif source == 'guiabcn':
            texts = [str((raw.get('api_item') or {}).get('warning') or '')]
        hits = [' '.join(t.split()) for t in texts if SOLD.search(t)]
        if hits:
            origin = 'Ajuntament de Barcelona'
        else:
            offers = (raw.get('item') or {}).get('offers')
            offers = offers if isinstance(offers, list) else [offers] if offers else []
            avail = [str(o.get('availability') or '') for o in offers if isinstance(o, dict)]
            if avail and all(a.endswith('SoldOut') for a in avail):
                hits = ['SoldOut (schema.org)']; origin = (raw.get('loagendo') or {}).get('source_label') or source
        if not hits: continue
        venues = {_fold(v) for (v,) in conn.execute('SELECT venue FROM source_venues WHERE source=? AND id=?', (source, rid)) if v}
        days = sorted({d for h in hits for d in _days_in(h, start, end)})
        out.append((source, rid, {'texto': hits[0], 'origen': origin, 'dias': days}, start, end, words(title), venues))
    return out


def compute_sold_out(conn, today=None):
    """{(source, id): {'texto', 'origen', 'dias'}}: la fuente dice que no quedan entradas (para todos los días de
    la ficha o para los que nombra). Pasa a las fichas del mismo acto como compute()."""
    today = (today or dt.date.today()).isoformat()
    out = {}
    for source, rid, info, start, end, wanted, venues in sold_anchors(conn, today):
        out[(source, rid)] = info
        if not wanted: continue
        lo, hi = (info['dias'][0], info['dias'][-1]) if info['dias'] else (start, end)
        for s, i, title, a, b in conn.execute("""SELECT source,id,title,substr(start_date,1,10),substr(end_date,1,10) FROM source_records WHERE NOT (source=? AND id=?)
                AND substr(start_date,1,10)<=? AND substr(end_date,1,10)>=? AND substr(start_date,1,10)>=? AND substr(end_date,1,10)<=?
                AND eligibility<>'exclude'""", (source, rid, hi, lo, start, end)).fetchall():
            if (s, i) in out: continue
            have = words(title)
            if not have: continue
            small, big = (have, wanted) if len(have) <= len(wanted) else (wanted, have)
            if not small <= big: continue
            other = {_fold(v) for (v,) in conn.execute('SELECT venue FROM source_venues WHERE source=? AND id=?', (s, i)) if v}
            if (s == 'opendatabcn_agenda' and source == 'guiabcn' and i == rid) or _same_venue(venues, other):
                days = [d for d in info['dias'] if a <= d <= b] if info['dias'] else []
                if info['dias'] and not days: continue
                out[(s, i)] = {**info, 'dias': days}
    return out


def sold_out(conn):
    try:
        stamp = conn.execute("SELECT COUNT(*), MAX(raw_sha256), (SELECT MAX(rowid) FROM source_records) FROM source_records WHERE source IN ('guiabcn','opendatabcn_agenda')").fetchone() + (dt.date.today().isoformat(),)
    except sqlite3.DatabaseError:
        return {}
    if stamp != _SOLD_CACHE['stamp']:
        try: _SOLD_CACHE.update(stamp=stamp, map=compute_sold_out(conn))
        except sqlite3.DatabaseError: _SOLD_CACHE.update(stamp=stamp, map={})
    return _SOLD_CACHE['map']
