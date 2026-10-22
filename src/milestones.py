"""Inauguraciones y clausuras de exposiciones (22-10-2026).

GRAF y algunas agendas municipales publican la inauguración de una exposición como un acto de un
día («…/marian-brea-opening/», «Inauguració de l'exposició 'Elles per elles'») y, a veces, la
exposición aparte como ficha de varios días. Aquí:
  · se reconoce la inauguración (o la clausura / finissage) por reglas, guardando qué la delata
    (la dirección de la fuente o el título) — nunca se deduce de otra cosa;
  · se relaciona con la exposición del mismo espacio cuando la tenemos (título parecido y fechas
    que cuadran), para que cada ficha diga dónde está la otra. Si no la tenemos, no se inventa.
"""
from __future__ import annotations

import datetime as dt
import re

from src.festivals import fold

OPENING_URL = re.compile(r"[-/](?:opening|inauguracio|inauguracion|vernissatge)(?:-\d+)?/?(?:[?#].*)?$", re.I)
CLOSING_URL = re.compile(r"[-/](?:closing|finissage|clausura|cloenda)(?:-\d+)?/?(?:[?#].*)?$", re.I)
OPENING_TITLE = re.compile(r"\b(?:inauguracio|inauguracion|opening|vernissatge|vernissage|obertura de (?:l'|les )?exposicio)")
CLOSING_TITLE = re.compile(r"\b(?:finissage|clausura de (?:l'|la )?exposicio|cloenda de (?:l'|la )?exposicio)")
LABEL = {"opening": "Inauguración", "closing": "Clausura"}


def milestone_of(title, url, category, start, end):
    """{'kind': 'opening'|'closing', 'evidence': 'url'|'title', 'value': …} o None.

    Solo actos de un día. Por la dirección (GRAF «…-opening/»), en cualquier categoría; por el
    título, solo en Arte y exposiciones: «Espectacle "La inauguració"» o «Gran Opening» de un
    cabaret no son la inauguración de una exposición."""
    if not start or (end or start) != start: return None
    path = str(url or "").split("://", 1)[-1]
    for kind, rx in (("opening", OPENING_URL), ("closing", CLOSING_URL)):
        m = rx.search(path)
        if m: return {"kind": kind, "evidence": "url", "value": str(url)}
    if category != "arte": return None
    t = fold(title)
    for kind, rx in (("opening", OPENING_TITLE), ("closing", CLOSING_TITLE)):
        m = rx.search(t)
        if m: return {"kind": kind, "evidence": "title", "value": m.group(0)}
    return None


STOP = {"de", "del", "la", "el", "les", "els", "los", "las", "i", "y", "a", "en", "the", "of", "and", "exposicio", "exposicion",
        "inauguracio", "inauguracion", "opening", "vernissatge", "finissage", "clausura", "cloenda", "l", "d"}


def _words(title):
    return {w for w in re.split(r"[^a-z0-9]+", fold(title)) if len(w) > 2 and w not in STOP}


def _place(e):
    return fold(((e.get("venue_names") or [""])[0] or "").split(" · ")[0])


def _same_show(a, b):
    wa, wb = _words(a), _words(b)
    if not wa or not wb: return False
    common = len(wa & wb)
    return common >= 2 and common / min(len(wa), len(wb)) >= 0.6


def link(events):
    """{clave del acto: {'key', 'start', 'end'}} y {clave de la exposición: {'key', 'date', 'time', 'kind'}}.

    La exposición tiene que ser del mismo espacio, de varios días, con un título que comparta la
    mayoría de sus palabras, y empezar entre 3 días antes y 7 después de la inauguración (o
    terminar el día de la clausura)."""
    expos = {}
    for e in events:
        if e.get("start") and e.get("end") and e["start"] != e["end"]:
            expos.setdefault(_place(e), []).append(e)
    to_expo, to_act = {}, {}
    for m in events:
        ms = m.get("milestone")
        if not ms or not _place(m): continue
        day = dt.date.fromisoformat(m["start"])
        best = None
        for e in expos.get(_place(m), []):
            if not _same_show(m["title"], e["title"]): continue
            if ms["kind"] == "opening":
                gap = (dt.date.fromisoformat(e["start"]) - day).days
                if not -3 <= gap <= 7: continue
            elif e["end"] != m["start"]: continue
            if best is None or abs((dt.date.fromisoformat(e["start"]) - day).days) < abs((dt.date.fromisoformat(best["start"]) - day).days): best = e
        if best:
            to_expo[m["key"]] = {"key": best["key"], "start": best["start"], "end": best["end"]}
            to_act.setdefault(best["key"], {"key": m["key"], "date": m["start"], "time": m.get("time") or "", "kind": ms["kind"]})
    return to_expo, to_act
