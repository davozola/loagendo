"""Local media registry: references are safe; files require explicit rights."""
from __future__ import annotations
import hashlib
import datetime as dt
import json
import urllib.request
from urllib.parse import urlsplit
from pathlib import Path
from src.network import tls_context


def is_event_image(url, alt=' ', content_type=''):
    """Return false for page chrome accidentally discovered as an event image.

    Detail pages from GuiaBCN include the municipality logo in their regular
    ``img`` tags.  Keeping that reference is useful for auditability, but it
    must never become the event's representative image.
    """
    candidate=(f'{url or ""} {alt or ""}').lower()
    page_chrome=(
        'favicon', 'brand/banner', 'assets/images/brand/',
        'ico-ajuntament', 'ico-iris', 'ico-tramits', 'ico-agenda',
        'ico-comshiva', 'ico-difusio', 'ico-planol', 'ico-premsa', 'sprite',
    )
    path=(url or '').lower().split('?',1)[0]
    filename=path.rsplit('/',1)[-1]
    is_logo=filename.startswith('logo') or (alt or '').strip().lower().startswith('logo')
    return not is_logo and not any(mark in candidate for mark in page_chrome) and not (
        path.endswith('.svg') or content_type == 'image/svg+xml'
    )


REGISTRY_PATH=Path(__file__).resolve().parents[1]/'docs'/'source_registry.json'


def source_rights_policy(source, registry_path=REGISTRY_PATH):
    """'authorized' when the source registry records an editorial decision that
    its images may be used; 'unknown' otherwise. The decision and its basis
    live in docs/source_registry.json, next to the data licence."""
    try: registry=json.loads(Path(registry_path).read_text(encoding='utf-8'))
    except (OSError,json.JSONDecodeError): registry={}
    entry=registry.get(source) or _wildcard_entry(registry,source) or {}
    return 'authorized' if entry.get('image_reuse_confirmed') is True else 'unknown'


def _wildcard_entry(registry, source):
    """'venue_*' covers every venue_<slug> source; 'ticketing_*' every ticketing/aggregator one."""
    if source.startswith('venue_'):
        try:
            from src.venue_feeds import load_venues
            kind={('venue_'+v['slug']):v.get('type','') for v in load_venues()}.get(source,'')
        except Exception: kind=''
        return registry.get('aggregator_*') if kind=='aggregator' else registry.get('ticketing_*') if kind=='ticketing' else registry.get('venue_*')
    return None


def apply_rights_policy(conn, registry_path=REGISTRY_PATH):
    """Raise archived assets to the registry's current policy. Idempotent and
    logged; never downgrades an asset an editor set explicitly."""
    conn.execute('''CREATE TABLE IF NOT EXISTS media_rights_log(
      seq INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, assets INTEGER NOT NULL,
      new_status TEXT NOT NULL, basis TEXT NOT NULL, applied_at TEXT NOT NULL)''')
    try: registry=json.loads(Path(registry_path).read_text(encoding='utf-8'))
    except (OSError,json.JSONDecodeError): return {}
    applied={}
    sources=[r[0] for r in conn.execute("SELECT DISTINCT source FROM media_assets WHERE rights_status='unknown'")]
    for source in sources:
        entry=registry.get(source) or _wildcard_entry(registry,source) or {}
        if entry.get('image_reuse_confirmed') is not True: continue
        changed=conn.execute("UPDATE media_assets SET rights_status='authorized' WHERE source=? AND rights_status='unknown'",(source,)).rowcount
        if changed:
            conn.execute('INSERT INTO media_rights_log(source,assets,new_status,basis,applied_at) VALUES(?,?,?,?,?)',
                         (source,changed,'authorized',str(entry.get('image_reuse_basis') or 'source_registry.image_reuse_confirmed'),dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')))
            applied[source]=changed
    conn.commit()
    return applied


def register(conn, source, record_id, url, *, alt='', credit='', rights_status=None):
    if rights_status is None: rights_status=source_rights_policy(source)
    if rights_status not in ('unknown','authorized','blocked'):
        raise ValueError('Estado de derechos no permitido')
    conn.execute('''INSERT INTO media_assets(source,id,original_url,alt_text,credit,rights_status)
      VALUES(?,?,?,?,?,?) ON CONFLICT(source,id,original_url) DO UPDATE SET alt_text=excluded.alt_text,credit=excluded.credit,rights_status=excluded.rights_status''',
      (source,record_id,url,alt,credit,rights_status))


def _download(conn, asset_id, directory):
    row=conn.execute('SELECT original_url FROM media_assets WHERE asset_id=?',(asset_id,)).fetchone()
    if not row: raise LookupError('Imagen no encontrada')
    url=row[0]; parsed=urlsplit(url)
    if parsed.scheme not in ('http','https') or not parsed.netloc: raise ValueError('URL de imagen no permitida')
    request=urllib.request.Request(url,headers={'Accept':'image/avif,image/webp,image/*','User-Agent':'Loagendo/1.3 local preview'})
    with urllib.request.urlopen(request,timeout=20,context=tls_context()) as response:  # nosec B310: URL is recorded from an event source
        content=response.read(10_000_000)
        content_type=response.headers.get_content_type()
    if not content_type.startswith('image/') or len(content)>10_000_000: raise ValueError('Contenido de imagen no permitido')
    extension={'image/jpeg':'jpg','image/png':'png','image/webp':'webp','image/gif':'gif','image/avif':'avif'}.get(content_type,'img')
    digest=hashlib.sha256(content).hexdigest(); path=Path(directory)/f'{digest}.{extension}'; path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists(): path.write_bytes(content)
    conn.execute('UPDATE media_assets SET sha256=?,local_path=?,content_type=?,download_failed_at=NULL,download_error=NULL WHERE asset_id=?',(digest,str(path),content_type,asset_id)); conn.commit()
    return path


def download_authorized(conn, asset_id, directory):
    row=conn.execute('SELECT rights_status FROM media_assets WHERE asset_id=?',(asset_id,)).fetchone()
    if not row: raise LookupError('Imagen no encontrada')
    if row[0]!='authorized': raise PermissionError('Los derechos de imagen no están autorizados')
    return _download(conn,asset_id,directory)


TRANSIENT_DOWNLOAD_ERRORS = ('CERTIFICATE_VERIFY_FAILED', 'timed out', 'Connection reset', 'Remote end closed', 'HTTP Error 5', 'Tunnel connection failed', 'Temporary failure in name resolution')
RETRY_TRANSIENT_AFTER_DAYS = 1


def retry_transient_download_failures(conn, older_than_days=RETRY_TRANSIENT_AFTER_DAYS, source=None):
    """Clear download failures caused by the network rather than by the asset
    (TLS trust, timeouts, 5xx) so the next media job tries them again; the
    error text is kept in download_error until a retry overwrites it. A 404 or
    a non-image answer stays failed: retrying would only repeat it."""
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=older_than_days)).isoformat(timespec='seconds')
    clause = ' OR '.join("download_error LIKE ?" for _ in TRANSIENT_DOWNLOAD_ERRORS)
    params = [f'%{e}%' for e in TRANSIENT_DOWNLOAD_ERRORS] + [cutoff]
    query = f"UPDATE media_assets SET download_failed_at=NULL WHERE local_path IS NULL AND download_failed_at IS NOT NULL AND download_failed_at<=? AND ({clause})"
    params = [cutoff] + params[:-1]
    if source: query += ' AND source=?'; params.append(source)
    cur = conn.execute(query, params); conn.commit()
    return cur.rowcount


def download_local_previews(conn, directory, limit=20, source=None):
    """Download image references. Rights come from the source policy (see
    ``apply_rights_policy``); downloading never changes them."""
    today=dt.date.today().isoformat()
    # One preview per record, upcoming and current events first: what the
    # public listing is about to show is what gets fetched first.
    query='''SELECT MIN(m.asset_id) FROM media_assets m
      JOIN source_records r ON r.source=m.source AND r.id=m.id
      WHERE m.local_path IS NULL AND m.download_failed_at IS NULL
        AND m.rights_status IN ('unknown','authorized')
        AND (m.original_url LIKE 'https://%' OR m.original_url LIKE 'http://%')
        AND NOT EXISTS (SELECT 1 FROM media_assets existing
          WHERE existing.source=m.source AND existing.id=m.id AND existing.local_path IS NOT NULL)
    '''
    params=[]
    if source:
        query+=' AND m.source=?\n'; params.append(source)
    query+=''' GROUP BY m.source,m.id
      ORDER BY CASE WHEN r.end_date<? THEN 2 WHEN r.start_date<=? THEN 0 ELSE 1 END, r.start_date, MIN(m.asset_id) LIMIT ?'''
    rows=conn.execute(query,(*params,today,today,limit)).fetchall()
    downloaded=failed=0
    for (asset_id,) in rows:
        try:
            _download(conn,asset_id,directory); downloaded+=1
        except Exception as err:
            conn.execute('UPDATE media_assets SET download_failed_at=?,download_error=? WHERE asset_id=?',
                         (dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),str(err)[:300],asset_id));conn.commit()
            failed+=1
    return {'attempted':len(rows),'downloaded':downloaded,'failed':failed,'rights_status':'unknown_or_authorized_unchanged'}


def ensure_local(conn, asset_id, directory, *, timeout=20):
    """Return the local path of an asset, fetching it on first use when its
    source policy authorises it. Used by the web server so a live site needs
    no manual download step; failures are recorded and not retried per request."""
    row=conn.execute('SELECT local_path,content_type,rights_status,download_failed_at FROM media_assets WHERE asset_id=?',(asset_id,)).fetchone()
    if not row: return None,None
    local_path,content_type,rights,failed_at=row
    if local_path: return local_path,content_type
    if rights!='authorized' or failed_at: return None,None
    try:
        path=_download(conn,asset_id,directory)
    except Exception as err:
        conn.execute('UPDATE media_assets SET download_failed_at=?,download_error=? WHERE asset_id=?',(dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),str(err)[:300],asset_id)); conn.commit()
        return None,None
    row=conn.execute('SELECT local_path,content_type FROM media_assets WHERE asset_id=?',(asset_id,)).fetchone()
    return (row[0],row[1]) if row else (str(path),None)
