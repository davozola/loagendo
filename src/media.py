"""Local media registry: references are safe; files require explicit rights."""
from __future__ import annotations
import hashlib
import urllib.request
from urllib.parse import urlsplit
from pathlib import Path


def register(conn, source, record_id, url, *, alt='', credit='', rights_status='unknown'):
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
    with urllib.request.urlopen(request,timeout=20) as response:  # nosec B310: URL is recorded from an event source
        content=response.read(10_000_000)
        content_type=response.headers.get_content_type()
    if not content_type.startswith('image/') or len(content)>10_000_000: raise ValueError('Contenido de imagen no permitido')
    extension={'image/jpeg':'jpg','image/png':'png','image/webp':'webp','image/gif':'gif','image/avif':'avif'}.get(content_type,'img')
    digest=hashlib.sha256(content).hexdigest(); path=Path(directory)/f'{digest}.{extension}'; path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists(): path.write_bytes(content)
    conn.execute('UPDATE media_assets SET sha256=?,local_path=?,content_type=? WHERE asset_id=?',(digest,str(path),content_type,asset_id)); conn.commit()
    return path


def download_authorized(conn, asset_id, directory):
    row=conn.execute('SELECT rights_status FROM media_assets WHERE asset_id=?',(asset_id,)).fetchone()
    if not row: raise LookupError('Imagen no encontrada')
    if row[0]!='authorized': raise PermissionError('Los derechos de imagen no están autorizados')
    return _download(conn,asset_id,directory)


def download_local_previews(conn, directory, limit=20):
    """Download unverified source references for this local prototype only.

    This never upgrades rights_status: unknown assets remain unsuitable for publication.
    """
    rows=conn.execute('''SELECT asset_id FROM media_assets
      WHERE local_path IS NULL AND rights_status IN ('unknown','authorized')
        AND (lower(original_url) GLOB '*jpg*' OR lower(original_url) GLOB '*jpeg*'
          OR lower(original_url) GLOB '*png*' OR lower(original_url) GLOB '*webp*'
          OR lower(original_url) GLOB '*avif*')
      ORDER BY asset_id LIMIT ?''',(limit,)).fetchall()
    downloaded=failed=0
    for (asset_id,) in rows:
        try:
            _download(conn,asset_id,directory); downloaded+=1
        except Exception:
            failed+=1
    return {'attempted':len(rows),'downloaded':downloaded,'failed':failed,'rights_status':'unknown_or_authorized_unchanged'}
