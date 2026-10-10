"""Detail-page enrichment for GuiaBCN records; media stays reference-only."""
from __future__ import annotations
import datetime as dt
import html
import sqlite3
from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from src.media import register

class MetaParser(HTMLParser):
    def __init__(self): super().__init__(); self.meta={}; self.links=[]; self.images=[]
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='meta':
            key=attrs.get('property') or attrs.get('name')
            if key and attrs.get('content'): self.meta[key]=html.unescape(attrs['content'])
        elif tag=='a' and attrs.get('href'): self.links.append(attrs['href'])
        elif tag=='img':
            candidate=attrs.get('src') or attrs.get('data-src') or attrs.get('data-lazy-src')
            if candidate: self.images.append((candidate,attrs.get('alt','')))

def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS source_enrichments (
      source TEXT NOT NULL,id TEXT NOT NULL, fetched_at TEXT NOT NULL, source_url TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '', links_json TEXT NOT NULL DEFAULT '[]', raw_html_sha256 TEXT NOT NULL,
      PRIMARY KEY(source,id), FOREIGN KEY(source,id) REFERENCES source_records(source,id))''')

def enrich(conn, limit=10, timeout=20):
    initialize(conn); rows=conn.execute("""SELECT id,source_url FROM source_records
      WHERE source='guiabcn' AND source_url<>'' AND id NOT LIKE 'G%'
      ORDER BY CASE WHEN end_date>='2026-10-10' THEN 0 ELSE 1 END, start_date, id LIMIT ?""",(limit,)).fetchall(); done=failed=media=0
    import hashlib,json
    for record_id,url in rows:
        try:
            req=Request(url,headers={'Accept':'text/html','User-Agent':'Loagendo/1.3 local enrichment'})
            with urlopen(req,timeout=timeout) as response: content=response.read(2_000_000).decode('utf-8','replace')
            parser=MetaParser();parser.feed(content);description=parser.meta.get('description',''); now=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
            with conn:
                conn.execute('''INSERT INTO source_enrichments VALUES(?,?,?,?,?,?,?) ON CONFLICT(source,id) DO UPDATE SET fetched_at=excluded.fetched_at,source_url=excluded.source_url,description=excluded.description,links_json=excluded.links_json,raw_html_sha256=excluded.raw_html_sha256''',('guiabcn',record_id,now,url,description,json.dumps(parser.links[:20]),hashlib.sha256(content.encode()).hexdigest()))
                image=parser.meta.get('og:image')
                candidates=[]
                if image: candidates.append((image,parser.meta.get('og:image:alt','')))
                candidates.extend(parser.images)
                seen=set()
                for image,alt in candidates:
                    image=urljoin(url,image)
                    if image in seen or not image.startswith(('https://','http://')): continue
                    seen.add(image); register(conn,'guiabcn',record_id,image,alt=alt,rights_status='unknown');media+=1
            done+=1
        except Exception: failed+=1
    return {'attempted':len(rows),'enriched':done,'failed':failed,'media_references':media}
