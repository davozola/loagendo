"""Compacta el historial de versiones (source_record_versions) quitando las copias que solo se diferencian de la
anterior en lo que el iCal cambia en cada descarga (3-11-2026: Open Data BCN guardaba una versión al día de cada acto
porque el iCal trae sello DTSTAMP y UID nuevos, las sesiones en otro orden y sin las que ya pasaron).

Qué se borra: una versión igual a la última conservada del mismo acto, sin contar sellos, UID, orden de sesiones ni
las sesiones que ya habían terminado el día en que se leyó.
Qué se queda siempre: la primera versión de cada acto, toda versión con un cambio real (aunque luego vuelva al
contenido de antes) y la última versión de cada acto (guarda la fecha en que se vio por última vez).

Sin --aplicar solo enseña qué haría (lee sin bloquear). Con --aplicar:
  1. no hace nada si el motor está en marcha, y pone su candado para que no arranque mientras tanto;
  2. hace una copia completa de la base de datos en reports/ (salvo --sin-copia);
  3. borra por tandas y deja constancia en reports/compactar_historial_<fecha>.json;
  4. VACUUM para devolver el espacio al disco; quita el candado.

    python3 scripts/compactar_historial.py
    python3 scripts/compactar_historial.py --aplicar
"""
import argparse, datetime as dt, json, sqlite3, sys, time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.pipeline import sha  # noqa: E402
from src.sync import stable_raw  # noqa: E402

DB = ROOT / 'reports' / 'loagendo_v12.sqlite3'
BATCH = 2000


def redundant(conn):
    """Versiones que repiten la última que se conserva del mismo acto, salvo lo que el iCal cambia en cada descarga
    (sellos, UID, orden y sesiones que ya habían pasado el día en que se leyó la nueva): (id, bytes, fuente)."""
    out, group, versions, kept = [], None, [], None

    def close():
        # La última versión del acto se queda aunque repita: guarda cuándo se vio por última vez.
        out.extend((i, n, s) for i, n, s, same in versions[:-1] if same)

    for vid, source, ext, raw_text, observed in conn.execute(
            'SELECT id,source,external_id,raw_json,observed_at FROM source_record_versions ORDER BY source,external_id,id'):
        if (source, ext) != group:
            close(); group, versions, kept = (source, ext), [], None
        try: raw = json.loads(raw_text)
        except (TypeError, ValueError): raw = None
        since = str(observed or '')[:10].replace('-', '')
        same = raw is not None and kept is not None and sha(stable_raw(kept, since)) == sha(stable_raw(raw, since))
        if not same: kept = raw
        versions.append((vid, len(raw_text or ''), source, same))
    close()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--aplicar', action='store_true'); ap.add_argument('--sin-copia', action='store_true')
    ap.add_argument('--db', default=str(DB))
    args = ap.parse_args(argv)
    db = Path(args.db)
    conn = sqlite3.connect(db, timeout=60) if args.aplicar else sqlite3.connect(f'file:{db}?immutable=1', uri=True)
    locked = False
    if args.aplicar:
        has_locks = conn.execute("SELECT 1 FROM sqlite_master WHERE name='automation_locks'").fetchone()
        if has_locks and conn.execute("SELECT held_at FROM automation_locks WHERE name='engine'").fetchone():
            print('El motor está en marcha: prueba dentro de un rato.'); return 2
        if has_locks:
            with conn: conn.execute("INSERT INTO automation_locks(name,held_at) VALUES ('engine',?)",
                                    (dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),))
            locked = True
    try:
        total = conn.execute('SELECT COUNT(*) FROM source_record_versions').fetchone()[0]
        rows = redundant(conn)
        by_source = Counter(s for _, _, s in rows)
        size = sum(n for _, n, _ in rows)
        print(f'Versiones: {total}. Repetidas (solo cambia lo del iCal): {len(rows)} (~{size / 1e9:.2f} GB de texto).')
        for s, n in by_source.most_common(): print(f'  {s}: {n}')
        if not args.aplicar:
            print('Vista previa: añade --aplicar para compactar (con el motor parado y copia previa).'); return 0
        if not rows: print('Nada que compactar.'); return 0
        stamp = dt.datetime.now().strftime('%Y%m%d-%H%M')
        if not args.sin_copia:
            copy = db.with_name(f'copia-antes-de-compactar-{stamp}.sqlite3')
            print(f'Copia de seguridad en {copy.name}…'); t = time.time()
            dest = sqlite3.connect(copy); conn.backup(dest); dest.close()
            print(f'  hecha en {time.time() - t:.0f} s')
        ids = [i for i, _, _ in rows]
        for k in range(0, len(ids), BATCH):
            chunk = ids[k:k + BATCH]
            with conn: conn.execute(f"DELETE FROM source_record_versions WHERE id IN ({','.join('?' * len(chunk))})", chunk)
        log = db.with_name(f'compactar_historial_{stamp}.json')
        log.write_text(json.dumps({'fecha': stamp, 'versiones_antes': total, 'borradas': len(ids), 'por_fuente': by_source,
                                   'criterio': 'igual a la última conservada del mismo acto salvo DTSTAMP, UID, orden y sesiones ya pasadas; se conservan primera, cambios reales y última',
                                   'ids': ids}, ensure_ascii=False))
        print(f'Borradas {len(ids)} versiones (lista en {log.name}). VACUUM…'); t = time.time()
        conn.execute('VACUUM')
        print(f'  hecho en {time.time() - t:.0f} s. Tamaño ahora: {db.stat().st_size / 1e9:.2f} GB')
        return 0
    finally:
        if locked:
            with conn: conn.execute("DELETE FROM automation_locks WHERE name='engine'")
        conn.close()


if __name__ == '__main__':
    sys.exit(main())
