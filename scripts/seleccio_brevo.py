"""Prepara Brevo para La Selecció (4-11-2026): atributos IDIOMA y SELECCIO_T, carpeta y tres listas, y las tres plantillas
de doble confirmación (docs/seleccio/confirmacion-*.html, con la etiqueta «optin»). No duplica lo que ya exista (busca por
nombre). Usa BREVO_API_KEY del .env. Al final escribe los números de las listas en config/seleccio.json y enseña los seis
números que van a Cloudflare.

    python3 scripts/seleccio_brevo.py
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.mailer import env_value  # noqa: E402
from src.network import tls_context  # noqa: E402

API = 'https://api.brevo.com/v3'
LISTS = {'ca': 'La Selecció · català', 'es': 'La Selecció · castellano', 'en': 'La Selecció · English'}
SUBJECTS = {'ca': 'Confirma la teva subscripció a La Selecció', 'es': 'Confirma tu suscripción a La Selecció', 'en': 'Confirm your subscription to La Selecció'}
TEMPLATE_NAME = 'La Selecció · confirmación ({})'


def call(method, path, body=None):
    key = env_value('BREVO_API_KEY')
    if not key: sys.exit('Falta BREVO_API_KEY en .env')
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={'api-key': key, 'content-type': 'application/json', 'accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30, context=tls_context()) as r:
            raw = r.read(); return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read(); return e.code, (json.loads(raw) if raw else {})


def attributes():
    _, got = call('GET', '/contacts/attributes')
    have = {a['name'] for a in got.get('attributes', [])}
    for name in ('IDIOMA', 'SELECCIO_T'):
        if name in have: print(f'Atributo {name}: ya existía'); continue
        status, body = call('POST', f'/contacts/attributes/normal/{name}', {'type': 'text'})
        print(f'Atributo {name}:', 'creado' if status in (200, 201, 204) else f'ERROR {status} {body}')


def lists():
    _, folders = call('GET', '/contacts/folders?limit=50')
    folder = next((f for f in folders.get('folders', []) if f['name'] == 'La Selecció'), None)
    if not folder:
        status, folder = call('POST', '/contacts/folders', {'name': 'La Selecció'})
        if status not in (200, 201): sys.exit(f'No se pudo crear la carpeta: {status} {folder}')
    _, got = call('GET', '/contacts/lists?limit=50')
    have = {l['name']: l['id'] for l in got.get('lists', [])}
    ids = {}
    for lang, name in LISTS.items():
        if name in have: ids[lang] = have[name]; print(f'Lista «{name}»: ya existía (n.º {have[name]})'); continue
        status, body = call('POST', '/contacts/lists', {'name': name, 'folderId': folder['id']})
        if status not in (200, 201): sys.exit(f'No se pudo crear la lista {name}: {status} {body}')
        ids[lang] = body['id']; print(f'Lista «{name}»: creada (n.º {body["id"]})')
    return ids


def templates():
    _, got = call('GET', '/smtp/templates?limit=100')
    have = {t['name']: t['id'] for t in got.get('templates', [])}
    ids = {}
    for lang in LISTS:
        name = TEMPLATE_NAME.format(lang)
        if name in have: ids[lang] = have[name]; print(f'Plantilla «{name}»: ya existía (n.º {have[name]})'); continue
        html = (ROOT / 'docs' / 'seleccio' / f'confirmacion-{lang}.html').read_text(encoding='utf-8')
        status, body = call('POST', '/smtp/templates', {'templateName': name, 'subject': SUBJECTS[lang], 'tag': 'optin', 'isActive': True,
                                                        'sender': {'name': 'Ontoca', 'email': 'hola@ontoca.com'}, 'replyTo': 'hola@ontoca.com', 'htmlContent': html})
        if status not in (200, 201): sys.exit(f'No se pudo crear la plantilla {name}: {status} {body}')
        ids[lang] = body['id']; print(f'Plantilla «{name}»: creada (n.º {body["id"]})')
    return ids


def main():
    attributes()
    list_ids, template_ids = lists(), templates()
    path = ROOT / 'config' / 'seleccio.json'
    cfg = json.loads(path.read_text(encoding='utf-8'))
    cfg['lists'] = list_ids
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('\nconfig/seleccio.json actualizado con las listas.')
    print('\nPara Cloudflare (Pages → brollant → Settings → Variables and Secrets, Production):')
    for lang in LISTS: print(f'  SELECCIO_LIST_{lang.upper()} = {list_ids[lang]}')
    for lang in LISTS: print(f'  SELECCIO_DOI_{lang.upper()} = {template_ids[lang]}')


if __name__ == '__main__':
    main()
