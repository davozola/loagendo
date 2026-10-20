"""Recomendación automática «para ir en familia» de las exposiciones (20-10-2026).

Las fuentes casi nunca marcan una exposición como familiar, aunque muchas lo son claramente
(tiburones en CosmoCaixa, animales en el Museu Blau). Aquí la IA valora, SOLO con los datos de la
ficha (título, espacio, texto de la fuente), si es un buen plan con niños: «si», «no» o «dudoso»,
con un motivo breve en castellano y catalán.

Garantías:
  · es una valoración, no un dato de la fuente: la ficha lo dice así («Recomendación automática»)
    y nunca lleva edades (no se deducen);
  · el motivo pasa la misma comprobación que las descripciones (src/ai_describe.check): cada nombre
    y número tiene que estar en los datos; sin lenguaje promocional;
  · solo cuenta «si» con confianza ≥ APPLY y motivo aceptado;
  · en la web pública solo cuando ``config/ia.json`` tiene ``familia_ia_publica: true``, tras revisar
    la muestra de ``scripts/muestra_familia.py``; antes solo se ve en el panel.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPLY = 0.7  # 0,7 por decisión de David (20-10-2026) tras revisar la muestra
MAX_REASON = 160

SYSTEM = """Valoras si una exposición de la agenda cultural de Barcelona (Brollant) es un buen plan para ir en familia con niños y niñas (aprox. 4-12 años).
Decide con SOLO los datos recibidos (título, espacio, texto de la fuente):
- "si": el tema o el formato engancha y se entiende a esas edades: animales, naturaleza, ciencia, cuerpo humano, dinosaurios, espacio, tecnología, juegos y juguetes, cómic e ilustración, deporte, historia contada con objetos, maquetas o reconstrucciones, montajes interactivos, inmersivos o para tocar y experimentar; o el espacio es claramente de divulgación para todos los públicos (museo de ciencia o de ciencias naturales).
- "no": pensada para adultos o especialistas: violencia o guerra mostrada con crudeza, sexualidad, teoría del arte, archivos y documentos, arquitectura o diseño para profesionales, propuestas comerciales.
- "dudoso": todo lo demás o si los datos no bastan. Ante la duda, "dudoso".
motivo_es y motivo_ca: una frase (máximo 160 caracteres) que diga qué tiene la exposición que lo justifica, usando solo lo que dicen los datos. Prohibido: edades concretas, decir que la fuente la recomienda para familias, adjetivos promocionales.
confianza entre 0 y 1: 0.9 o más solo si el tema es inequívocamente infantil o familiar.
Responde con la herramienta valorar_familia, una entrada por ficha (n)."""

TOOL = {'name': 'valorar_familia', 'description': 'Valoración de cada exposición para ir en familia.',
        'input_schema': {'type': 'object', 'required': ['fichas'], 'properties': {'fichas': {'type': 'array', 'items': {
            'type': 'object', 'required': ['n', 'valoracion', 'confianza', 'motivo_es', 'motivo_ca'],
            'properties': {'n': {'type': 'integer'}, 'valoracion': {'type': 'string', 'enum': ['si', 'no', 'dudoso']},
                           'confianza': {'type': 'number'}, 'motivo_es': {'type': 'string'}, 'motivo_ca': {'type': 'string'}}}}}}}


def payload(ev):
    return {'titulo': (ev.get('title') or '')[:200], 'sala': (ev.get('source_venue') or (ev.get('venue_names') or [''])[0] or '')[:100],
            'texto': (ev.get('source_text') or '')[:1500]}


def needs(ev):
    """Exposiciones que aún no están en «En familia» por un motivo de la fuente."""
    return ev.get('format') == 'exhibition' and 'familia' not in (ev.get('channels') or [])


def parse(row, source_payload):
    from src.ai_describe import check
    verdict = row.get('valoracion')
    if verdict not in ('si', 'no', 'dudoso'): return None
    try: conf = max(0.0, min(1.0, float(row.get('confianza'))))
    except (TypeError, ValueError): conf = 0.0
    es, ca = (row.get('motivo_es') or '').strip(), (row.get('motivo_ca') or '').strip()
    problems = []
    if verdict == 'si':
        for lang, text in (('es', es), ('ca', ca)):
            if len(text) > MAX_REASON + 40: problems.append(f'{lang}: largo ({len(text)})')
            problems += [f'{lang}: {p}' for p in check(text, source_payload)]
    answer = {'valoracion': verdict, 'es': es, 'ca': ca, 'ok': not problems, 'problems': problems}
    return json.dumps(answer, ensure_ascii=False), conf, '; '.join(problems)[:300] or es[:300]


def accepted(answer, confidence):
    return answer.get('valoracion') == 'si' and answer.get('ok') and confidence >= APPLY


def public_enabled():
    try: return bool(json.loads((ROOT / 'config' / 'ia.json').read_text()).get('familia_ia_publica'))
    except (OSError, ValueError): return False
