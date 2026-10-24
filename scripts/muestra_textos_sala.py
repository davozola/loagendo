"""Muestra del texto completo de las salas, sin guardar nada (25-10-2026).

Uso (en el Mac):  python3 scripts/muestra_textos_sala.py [n_por_sala]
Para cada sala de src/venue_text.RULES lee n páginas de actos vigentes y sus versiones es/en, y
escribe reports/muestra_textos_sala.html con el texto que se importaría, para revisarlo antes de que
el trabajo «textos-sala» lo publique. Respeta robots.txt.
"""
from __future__ import annotations

import html
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import venue_text as vt  # noqa: E402
from src.official_translations import acceptable, alternates, jamboree_url, page_lang, switch_links  # noqa: E402
from src.venue_feeds import fetch, robots_allows  # noqa: E402


def main(n=2):
    conn = sqlite3.connect(f"file:{ROOT / 'reports' / 'loagendo_v12.sqlite3'}?mode=ro", uri=True)
    rows = []
    for source in vt.RULES:
        for rid, title, url in conn.execute("SELECT id,title,source_url FROM source_records WHERE source=? AND end_date>=date('now') AND source_url LIKE 'https://%' ORDER BY start_date LIMIT ?", (source, n)):
            if not robots_allows(url): rows.append((source, title, url, 'robots', '', {})); continue
            st, _, page = fetch(url, 15); text = vt.extract(source, page) if st == 200 else ''
            links = {l: jamboree_url(url, l) for l in ('es', 'en')} if source == 'venue_jamboree' else ((alternates(page, url) or switch_links(page, url)) if page else {})
            versions = {}
            for lang in ('es', 'en'):
                link = links.get(lang)
                if not link or link.rstrip('/') == url.rstrip('/') or page_lang(page) == lang: continue
                st2, _, p2 = fetch(link, 15); t2 = vt.extract(source, p2) if st2 == 200 else ''
                versions[lang] = (link, acceptable(t2, text, lang, page_lang(p2)) if len(t2) >= vt.MIN_TEXT else 'corto', t2)
            rows.append((source, title, url, st, text, versions))
            print(source, st, len(text), {k: v[1] for k, v in versions.items()})
    body = ''.join(f"<section><h2>{html.escape(s)} · {html.escape(t)}</h2><p><a href='{html.escape(u)}'>{html.escape(u)}</a> · HTTP {st} · {len(x)} caracteres</p><pre>{html.escape(x)}</pre>"
                   + ''.join(f"<h3>{l} · {html.escape(v[1])} · <a href='{html.escape(v[0])}'>página</a></h3><pre>{html.escape(v[2])}</pre>" for l, v in vs.items()) + '</section>'
                   for s, t, u, st, x, vs in rows)
    out = ROOT / 'reports' / 'muestra_textos_sala.html'
    out.write_text(f"<!doctype html><meta charset=utf-8><title>Textos de sala</title><style>body{{font:15px system-ui;max-width:900px;margin:2em auto}}pre{{white-space:pre-wrap;background:#f4f4f4;padding:1em}}</style>{body}", encoding='utf-8')
    print('→', out)


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 2)
