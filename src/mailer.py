"""Correo saliente del motor (25-10-2026): avisos y parte diario a hola@ontoca.com por Brevo.

La clave es BREVO_API_KEY en .env (la misma cuenta que las alertas de suscriptores; remitente
hola@ontoca.com ya verificado). Sin clave no se envía nada y quien llama guarda el correo en disco.
TLS siempre verificado (src/network.tls_context)."""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = 'https://api.brevo.com/v3/smtp/email'
SENDER = {'email': 'hola@ontoca.com', 'name': 'Ontoca'}
DEFAULT_TO = 'hola@ontoca.com'


def env_value(name, env_path=None):
    if os.environ.get(name): return os.environ[name].strip()
    path = Path(env_path) if env_path else ROOT / '.env'
    try:
        for line in path.read_text(encoding='utf-8').splitlines():
            key, sep, value = line.partition('=')
            if sep and key.strip() == name: return value.strip().strip('"').strip("'")
    except OSError:
        pass
    return ''


def send(subject, html, text, to=DEFAULT_TO, *, key=None, opener=None, timeout=30):
    """Envía un correo. Devuelve {'status': 'sent'|'skipped'|'failed', ...}; nunca lanza."""
    key = key if key is not None else env_value('BREVO_API_KEY')
    if not key: return {'status': 'skipped', 'reason': 'Falta BREVO_API_KEY en .env'}
    body = json.dumps({'sender': SENDER, 'to': [{'email': to}], 'subject': subject, 'htmlContent': html, 'textContent': text}).encode()
    request = urllib.request.Request(API, data=body, method='POST', headers={'api-key': key, 'content-type': 'application/json', 'accept': 'application/json'})
    try:
        if opener is None:
            from src.network import tls_context
            response = urllib.request.urlopen(request, timeout=timeout, context=tls_context())
        else:
            response = opener(request, timeout)
        with response:
            return {'status': 'sent', 'code': getattr(response, 'status', 200)}
    except Exception as error:  # Brevo caído o clave mal: se reintenta en la siguiente pasada
        return {'status': 'failed', 'error': (type(error).__name__ + ': ' + str(error))[:300]}
