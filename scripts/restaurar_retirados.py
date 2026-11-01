"""Vuelve a publicar los actos vigentes de una agenda leída con IA que se retiraron por no verse en la página
(1-11-2026, Fundació Miró: una lectura a medias retiró 19 actos de noviembre a febrero).

Sin --aplicar solo enseña qué haría. Cada acto recupera la elegibilidad con la que entró (raw_json.normalized) y
queda anotado en source_record_retirements. No toca los excluidos por reglas (los que ya entraron como «exclude»).
No se ejecuta si el motor está en marcha.

    python3 scripts/restaurar_retirados.py venue_ia_fundacio_miro
    python3 scripts/restaurar_retirados.py venue_ia_fundacio_miro --aplicar
    python3 scripts/restaurar_retirados.py todas --visto-desde 2026-10-25 [--aplicar]

«todas»: las agendas activas de config/agendas_ia.json. --visto-desde: solo los actos que la sala tenía en su página
desde esa fecha (última vez observados, source_record_versions); lo retirado hace más tiempo se deja como está.
"""
import argparse, datetime as dt, json, re, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB = ROOT / 'reports' / 'loagendo_v12.sqlite3'


def last_seen(conn, source):
    return dict(conn.execute('SELECT external_id, MAX(observed_at) FROM source_record_versions WHERE source=? GROUP BY external_id', (source,)))


CANCELLED = re.compile(r'\b(cancelad|cancel·lat|anul·lat|anulad|ajornat|aplazad|suspès|suspendid|sold out|esgotat|agotad)', re.I)


def _key(title):
    import unicodedata
    t = unicodedata.normalize('NFKD', title or '').encode('ascii', 'ignore').decode().lower()
    return ' '.join(re.findall(r'[a-z0-9]+', t))


def candidates(conn, source, today, since=None):
    out = []
    seen = last_seen(conn, source) if since else {}
    # Ya publicado con otra ficha de la misma sala (mismo título y día): no se duplica.
    alive = {(_key(t), sd) for t, sd in conn.execute("SELECT title,start_date FROM source_records WHERE source=? AND end_date>=? AND eligibility<>'exclude'", (source, today))}
    for rid, title, start, end, raw in conn.execute("SELECT id,title,start_date,end_date,raw_json FROM source_records WHERE source=? AND end_date>=? "
                                                     "AND eligibility='exclude' ORDER BY start_date", (source, today)):
        try: original = (json.loads(raw).get('normalized') or {}).get('eligibility')
        except ValueError: original = None
        # Un «título» sin ninguna palabra de 4 letras no es un acto («de les 18.12 a les 17.48», un horario leído como título).
        if not re.search(r'[^\W\d_]{4,}', title or '') or '#' in (title or ''): continue   # «#titulo-2#»: plantilla de la web
        if since and (seen.get(rid) or '') < since: continue
        if (_key(title), start) in alive or CANCELLED.search(title or ''): continue
        if original and original != 'exclude': out.append((rid, title, start, end, original))
    return out


PENDING = ROOT / 'config' / 'restauraciones_pendientes.json'


def sources_for(name):
    if name != 'todas': return [name]
    from src.ai_agenda import load_agendas
    return ['venue_ia_' + a['slug'] for a in load_agendas() if a.get('activa') and not a.get('descartada')]


def find(conn, name, since=None, today=None):
    today = today or dt.date.today().isoformat()
    return [(source, *r) for source in sources_for(name) for r in candidates(conn, source, today, since)]


def apply(conn, rows, reason='restaurado: retirado por una lectura a medias de la página'):
    from src.ai_agenda import initialize
    initialize(conn)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    with conn:
        for source, rid, title, start, end, original in rows:
            conn.execute("UPDATE source_records SET eligibility=? WHERE source=? AND id=?", (original, source, rid))
            conn.execute('INSERT INTO source_record_retirements(source,id,run_id,retired_at,previous_eligibility,reason,restored_at) VALUES(?,?,?,?,?,?,?)',
                         (source, rid, None, '', original, reason, now))
    try:
        from mvp import catalog; catalog.invalidate_cache()
    except Exception: pass
    return len(rows)


def run_pending(conn):
    """Lo llama el motor al empezar cada pasada, con el candado puesto: aplica el encargo y deja el fichero como .hecho."""
    if not PENDING.exists(): return None
    order = json.loads(PENDING.read_text())
    rows = find(conn, order.get('fuente', 'todas'), order.get('visto_desde'))
    done = apply(conn, rows, order.get('motivo') or 'restaurado por encargo: retirado por una lectura a medias de la página')
    by_source = {}
    for r in rows: by_source[r[0]] = by_source.get(r[0], 0) + 1
    result = {**order, 'aplicado': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), 'restaurados': done, 'por_fuente': by_source}
    PENDING.with_suffix('.hecho.json').write_text(json.dumps(result, ensure_ascii=False, indent=1))
    PENDING.unlink()
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('source'); ap.add_argument('--aplicar', action='store_true'); ap.add_argument('--visto-desde')
    ap.add_argument('--encargar', action='store_true', help='que lo aplique el motor al empezar su próxima pasada')
    args = ap.parse_args()
    if args.encargar:
        PENDING.write_text(json.dumps({'fuente': args.source, 'visto_desde': args.visto_desde,
                                       'pedido': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}, ensure_ascii=False, indent=1))
        print(f'Encargado en {PENDING.relative_to(ROOT)}: el motor lo aplica al empezar su próxima pasada.'); return
    # La vista previa lee sin bloquear (immutable), así no molesta al motor; aplicar exige que el motor esté parado.
    conn = sqlite3.connect(DB, timeout=30) if args.aplicar else sqlite3.connect(f'file:{DB}?immutable=1', uri=True)
    if args.aplicar and conn.execute("SELECT 1 FROM sqlite_master WHERE name='automation_locks'").fetchone() and \
       conn.execute("SELECT held_at FROM automation_locks WHERE name='engine'").fetchone():
        sys.exit('El motor está en marcha: espera a que acabe la pasada y vuelve a lanzarlo.')
    rows = find(conn, args.source, args.visto_desde)
    current = None
    for source, rid, title, start, end, original in rows:
        if source != current: print(f'== {source}'); current = source
        print(f'   {start}..{end}  {original:8} {title[:70]}')
    print(f'{len(rows)} actos retirados por no verse en la página que siguen vigentes.')
    if not args.aplicar:
        print('Vista previa: añade --aplicar para volver a publicarlos, o --encargar para que lo haga el motor.'); return
    print(f'Restaurados {apply(conn, rows)}. Saldrán en la web con la próxima publicación.')


if __name__ == '__main__':
    main()
