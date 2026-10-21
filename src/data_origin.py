"""De dónde salen los datos de cada ficha (21-10-2026).

Orden de preferencia (David: «idealmente, de la fuente oficial»):
  centro       la web o el feed del propio centro (agenda leída con reglas o IA, conector propio);
  web_oficial  la página oficial del acto, leída para corregir lo que da un agregador;
  red_publica  la red pública que organiza sus actos y los publica en la agenda municipal
               (centres cívics, casals, bibliotecas, museos municipales);
  agenda       una agenda pública que recoge actos de otros (Ajuntament, Generalitat, GRAF);
  eventbrite   Eventbrite (a menudo lo publica el propio organizador);
  directorio   un directorio de conciertos o una ticketera (Songkick, conciertos.club, DICE…).
"""
from __future__ import annotations

import re

OWN_WEB = {"web_auditori", "web_cccb", "web_macba", "web_teatre_lliure"}
PUBLIC_NETWORK_SOURCES = {"web_centres_civics", "diba_bibliotecas"}
AGGREGATORS = {"opendatabcn_agenda", "guiabcn", "generalitat", "diba_turismo", "web_graf"}
MUNICIPAL = re.compile(r"centre c[ií]vic|casal|bibliotec|espai jove|espai de gent gran|casa de la cultura|ludoteca|centre cultural|muhba|"
                       r"museu d.hist[oò]ria de barcelona|museu del disseny|disseny hub|museu de ci[eè]ncies naturals|museu etnol[oò]gic|museu picasso|"
                       r"virreina|arxiu|fabra i coats|ateneu municipal|punt d.informaci|aula ambiental|seu del districte|cotxeres|la capella", re.I)
RANK = ("centro", "web_oficial", "red_publica", "agenda", "eventbrite", "directorio")


def of_source(source, venue=""):
    from src.dedupe import first_party
    if source in OWN_WEB or first_party(source): return "centro"
    if source in PUBLIC_NETWORK_SOURCES: return "red_publica"
    if source in ("opendatabcn_agenda", "guiabcn") and MUNICIPAL.search(venue or ""): return "red_publica"
    if source in AGGREGATORS: return "agenda"
    if source == "venue_eventbrite": return "eventbrite"
    return "directorio"


def best(origins):
    origins = [o for o in origins if o in RANK]
    return min(origins, key=RANK.index) if origins else "directorio"
