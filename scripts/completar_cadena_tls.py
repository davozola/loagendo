#!/usr/bin/env python3
"""Completa la cadena TLS de un servidor que no envía su certificado intermedio.

Uso (en el Mac, desde la carpeta del proyecto):
    python3 scripts/completar_cadena_tls.py www.auditori.cat

Hace lo mismo que un navegador con un servidor mal configurado (AIA fetching):
1. Lee el certificado del servidor con `openssl s_client` solo para saber qué
   intermedio falta (dirección «CA Issuers»). No se confía en nada de esa lectura.
2. Descarga ese intermedio de la autoridad emisora.
3. Comprueba que, añadiéndolo, la conexión verifica con la validación COMPLETA
   de src.network.tls_context (hostname y cadena hasta una raíz de confianza).
4. Solo si la comprobación pasa, lo añade a config/extra-ca.pem.
Nunca desactiva la verificación ni guarda nada que no haya verificado.
"""
from __future__ import annotations

import re, socket, ssl, subprocess, sys, tempfile, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.network import EXTRA_CA, tls_context  # noqa: E402


def verifies(host, extra_pem=None):
    context = tls_context()
    if extra_pem:
        context.load_verify_locations(cadata=extra_pem)
    try:
        with socket.create_connection((host, 443), timeout=20) as raw:
            with context.wrap_socket(raw, server_hostname=host):
                return True, ''
    except ssl.SSLError as err:
        return False, str(err)


def leaf_pem(host):
    out = subprocess.run(['openssl', 's_client', '-connect', f'{host}:443', '-servername', host, '-showcerts'],
                         input=b'', capture_output=True, timeout=30).stdout.decode('latin-1')
    certs = re.findall(r'-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----', out, re.S)
    if not certs: raise SystemExit(f'No se pudo leer el certificado de {host}.')
    return certs[0]


def issuer_url(pem):
    text = subprocess.run(['openssl', 'x509', '-noout', '-text'], input=pem.encode(), capture_output=True, timeout=30).stdout.decode()
    match = re.search(r'CA Issuers - URI:(\S+)', text)
    if not match: raise SystemExit('El certificado no indica dónde obtener su emisor (sin «CA Issuers»).')
    return match.group(1)


def to_pem(data):
    if b'-----BEGIN CERTIFICATE-----' in data: return data.decode()
    with tempfile.NamedTemporaryFile(suffix='.der') as der:
        der.write(data); der.flush()
        out = subprocess.run(['openssl', 'x509', '-inform', 'DER', '-in', der.name], capture_output=True, timeout=30)
    if out.returncode: raise SystemExit('Lo descargado no es un certificado válido.')
    return out.stdout.decode()


def main(host):
    ok, error = verifies(host)
    if ok:
        print(f'{host}: la conexión ya verifica. No hace falta nada.'); return 0
    print(f'{host}: no verifica ({error}). Busco el intermedio que falta…')
    url = issuer_url(leaf_pem(host))
    print(f'Emisor publicado en: {url}')
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Brollant/1.3 (+https://brollant.com)'}), timeout=30) as response:  # nosec B310: URL del propio certificado; el contenido se verifica abajo
        intermediate = to_pem(response.read(200_000))
    ok, error = verifies(host, intermediate)
    if not ok:
        print(f'Con ese intermedio sigue sin verificar ({error}). No se guarda nada.'); return 1
    existing = EXTRA_CA.read_text() if EXTRA_CA.is_file() else ''
    if intermediate.strip() not in existing:
        EXTRA_CA.parent.mkdir(parents=True, exist_ok=True)
        with EXTRA_CA.open('a') as f: f.write(f'\n# {host} — intermedio de {url}\n{intermediate.strip()}\n')
    print(f'Listo: {host} verifica con la validación completa. Intermedio guardado en {EXTRA_CA.relative_to(ROOT)}.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else 'www.auditori.cat'))
