"""Páginas legales de la web pública (25-10-2026): Aviso legal, Privacidad y Fuentes.

Decisiones de David: pie mínimo (ontoca.com · Hecho en Barcelona, hola@ontoca.com y estas tres
páginas); responsable «Numhaus»; fuentes, lo mínimo que piden las licencias (no se nombran
ticketeras, agregadores ni agendas de sala); correo de las alertas con Brevo.

Cada página lleva los tres idiomas; /legal.js enseña el que corresponde (?lang= o el guardado por
la app, brollant-lang). Sin JavaScript se ve el castellano.
"""
import html

CONTACT = 'hola@ontoca.com'
OWNER = 'Numhaus'
LANGS = ('es', 'ca', 'en')
MAIL = f'<a href="mailto:{CONTACT}">{CONTACT}</a>'

FOOTER_LINKS = {
    'es': ('Hecho en Barcelona', 'Aviso legal', 'Privacidad', 'Fuentes'),
    'ca': ('Fet a Barcelona', 'Avís legal', 'Privacitat', 'Fonts'),
    'en': ('Made in Barcelona', 'Legal notice', 'Privacy', 'Sources'),
}
PATHS = ('/aviso-legal', '/privacidad', '/creditos')
BACK = {'es': '← Volver a la agenda', 'ca': "← Tornar a l'agenda", 'en': '← Back to the listings'}

AVISO = {
    'es': ('Aviso legal', f'''
<p>Ontoca (ontoca.com) es una agenda cultural de Barcelona sin fines comerciales, gestionada por {OWNER}. Contacto: {MAIL}.</p>
<p>Ontoca no organiza los actos ni vende entradas. La información se recoge de fuentes públicas y de las webs de los organizadores, y puede cambiar: confirma fecha, hora y precio con el organizador antes de ir.</p>
<p>Los textos e imágenes de las fichas pertenecen a sus titulares y se muestran con enlace a su origen. Si eres titular y quieres que retiremos o corrijamos algo, escribe a {MAIL} con el enlace de la ficha y lo haremos sin demora.</p>
<p>Algunas descripciones se muestran con traducción automática, señalada en la propia ficha junto al texto original.</p>'''),
    'ca': ('Avís legal', f'''
<p>Ontoca (ontoca.com) és una agenda cultural de Barcelona sense finalitat comercial, gestionada per {OWNER}. Contacte: {MAIL}.</p>
<p>Ontoca no organitza els actes ni ven entrades. La informació es recull de fonts públiques i de les webs dels organitzadors, i pot canviar: confirma data, hora i preu amb l'organitzador abans d'anar-hi.</p>
<p>Els textos i les imatges de les fitxes pertanyen als seus titulars i es mostren amb enllaç a l'origen. Si n'ets titular i vols que retirem o corregim alguna cosa, escriu a {MAIL} amb l'enllaç de la fitxa i ho farem sense demora.</p>
<p>Algunes descripcions es mostren amb traducció automàtica, indicada a la mateixa fitxa al costat del text original.</p>'''),
    'en': ('Legal notice', f'''
<p>Ontoca (ontoca.com) is a non-commercial cultural listings site for Barcelona, run by {OWNER}. Contact: {MAIL}.</p>
<p>Ontoca does not organise events or sell tickets. Information is collected from public sources and from organisers' websites, and may change: check the date, time and price with the organiser before you go.</p>
<p>Texts and images in the listings belong to their owners and are shown with a link to their source. If you own any of them and want us to remove or correct something, write to {MAIL} with the link to the listing and we will do so promptly.</p>
<p>Some descriptions are shown with machine translation, marked as such next to the original text.</p>'''),
}

PRIVACIDAD = {
    'es': ('Privacidad', f'''
<p><b>Responsable:</b> {OWNER} · {MAIL}.</p>
<p><b>Avisos por correo.</b> Si te suscribes, guardamos tu correo, la frecuencia y las búsquedas que elijas, solo para enviarte los avisos. La base legal es tu consentimiento, que confirmas desde un correo; las solicitudes sin confirmar se borran a las 48 horas. Puedes darte de baja desde el enlace de cada correo y entonces se borran tus datos. Para evitar abusos se guarda durante un día un resumen cifrado de la IP, nunca la IP.</p>
<p><b>Si nos escribes</b> a {CONTACT}, usamos tu correo solo para responderte.</p>
<p><b>Estadísticas.</b> Medimos el uso de la web con Matomo en un servidor propio, sin cookies, con la IP anonimizada y sin medir nada si tu navegador pide no ser seguido (Do Not Track o Global Privacy Control).</p>
<p><b>En tu navegador.</b> El idioma y los planes guardados se quedan en tu dispositivo; no nos llegan.</p>
<p><b>Proveedores:</b> Cloudflare (alojamiento, base de datos de los avisos y verificación antispam), Brevo (envío de los correos, UE) y Google (buzón de correo).</p>
<p><b>Cookies:</b> no usamos cookies.</p>
<p><b>Tus derechos.</b> Puedes pedir acceso, rectificación o supresión de tus datos en {MAIL}. También puedes reclamar ante la Agencia Española de Protección de Datos (<a href="https://www.aepd.es" rel="noopener noreferrer" target="_blank">aepd.es</a>).</p>'''),
    'ca': ('Privacitat', f'''
<p><b>Responsable:</b> {OWNER} · {MAIL}.</p>
<p><b>Avisos per correu.</b> Si t'hi subscrius, guardem el teu correu, la freqüència i les cerques que triïs, només per enviar-te els avisos. La base legal és el teu consentiment, que confirmes des d'un correu; les sol·licituds sense confirmar s'esborren al cap de 48 hores. Et pots donar de baixa des de l'enllaç de cada correu i llavors s'esborren les teves dades. Per evitar abusos es guarda durant un dia un resum xifrat de la IP, mai la IP.</p>
<p><b>Si ens escrius</b> a {CONTACT}, fem servir el teu correu només per respondre't.</p>
<p><b>Estadístiques.</b> Mesurem l'ús de la web amb Matomo en un servidor propi, sense galetes, amb la IP anonimitzada i sense mesurar res si el teu navegador demana no ser seguit (Do Not Track o Global Privacy Control).</p>
<p><b>Al teu navegador.</b> L'idioma i els plans desats es queden al teu dispositiu; no ens arriben.</p>
<p><b>Proveïdors:</b> Cloudflare (allotjament, base de dades dels avisos i verificació antispam), Brevo (enviament dels correus, UE) i Google (bústia de correu).</p>
<p><b>Galetes:</b> no fem servir galetes.</p>
<p><b>Els teus drets.</b> Pots demanar l'accés, la rectificació o la supressió de les teves dades a {MAIL}. També pots reclamar davant l'Agència Espanyola de Protecció de Dades (<a href="https://www.aepd.es" rel="noopener noreferrer" target="_blank">aepd.es</a>).</p>'''),
    'en': ('Privacy', f'''
<p><b>Controller:</b> {OWNER} · {MAIL}.</p>
<p><b>Email alerts.</b> If you subscribe, we store your email address, the frequency and the searches you choose, only to send you the alerts. The legal basis is your consent, which you confirm from an email; unconfirmed requests are deleted after 48 hours. You can unsubscribe from the link in every email, and your data is then deleted. To prevent abuse, a hashed summary of your IP is kept for one day, never the IP itself.</p>
<p><b>If you write to us</b> at {CONTACT}, we use your address only to reply.</p>
<p><b>Statistics.</b> We measure use of the site with Matomo on our own server, without cookies, with anonymised IPs and measuring nothing if your browser asks not to be tracked (Do Not Track or Global Privacy Control).</p>
<p><b>In your browser.</b> Your language and saved plans stay on your device; they never reach us.</p>
<p><b>Providers:</b> Cloudflare (hosting, alerts database and anti-spam check), Brevo (sending the emails, EU) and Google (mailbox).</p>
<p><b>Cookies:</b> we do not use cookies.</p>
<p><b>Your rights.</b> You can ask for access to, correction or deletion of your data at {MAIL}. You can also complain to the Spanish Data Protection Agency (<a href="https://www.aepd.es" rel="noopener noreferrer" target="_blank">aepd.es</a>).</p>'''),
}

_LIC = ('<a href="https://creativecommons.org/licenses/by/4.0/" rel="noopener noreferrer" target="_blank">CC BY 4.0</a>',
        '<a href="https://web.gencat.cat/ca/generalitat/dades-indicadors/dades-obertes/llicencies" rel="noopener noreferrer" target="_blank">',
        '<a href="https://www.openstreetmap.org/copyright" rel="noopener noreferrer" target="_blank">OpenStreetMap</a>')
FUENTES = {
    'es': ('Fuentes', f'''
<p>Datos del Ajuntament de Barcelona (Open Data BCN) y de la Diputació de Barcelona, con licencia {_LIC[0]}, y de la Generalitat de Catalunya, según {_LIC[1]}su licencia de datos abiertos</a>. El resto de la información procede de las webs de los organizadores, enlazadas en cada ficha.</p>
<p>Mapa: © colaboradores de {_LIC[2]}.</p>'''),
    'ca': ('Fonts', f'''
<p>Dades de l'Ajuntament de Barcelona (Open Data BCN) i de la Diputació de Barcelona, amb llicència {_LIC[0]}, i de la Generalitat de Catalunya, segons {_LIC[1]}la seva llicència de dades obertes</a>. La resta de la informació prové de les webs dels organitzadors, enllaçades a cada fitxa.</p>
<p>Mapa: © col·laboradors d'{_LIC[2]}.</p>'''),
    'en': ('Sources', f'''
<p>Data from Barcelona City Council (Open Data BCN) and Barcelona Provincial Council, under {_LIC[0]}, and from the Generalitat de Catalunya, under {_LIC[1]}its open data licence</a>. All other information comes from the organisers' websites, linked in each listing.</p>
<p>Map: © {_LIC[2]} contributors.</p>'''),
}

DESCRIPTIONS = {'aviso-legal': 'Quién gestiona Ontoca y cómo pedir una corrección o retirada.',
                'privacidad': 'Qué datos trata Ontoca, para qué y cómo ejercer tus derechos.',
                'creditos': 'De dónde salen los datos de Ontoca y con qué licencia.'}
PAGES = {'aviso-legal': AVISO, 'privacidad': PRIVACIDAD, 'creditos': FUENTES}

_HIDE = ''.join(f'[data-l="{l}"] [lang]:not([lang="{l}"])' + (',' if i < 2 else '') for i, l in enumerate(LANGS))


def _multi(texts, tag='span'):
    """El mismo texto en los tres idiomas; el CSS enseña solo el activo."""
    return ''.join(f'<{tag} lang="{l}">{texts[l]}</{tag}>' for l in LANGS)


def footer_html():
    """El pie de las páginas legales (el de la app está en static/index.html y se traduce con public.js)."""
    links = ' · '.join(f'<a href="{p}">' + _multi({l: FOOTER_LINKS[l][i + 1] for l in LANGS}) + '</a>' for i, p in enumerate(PATHS))
    return (f'<footer><span>ontoca.com · ' + _multi({l: FOOTER_LINKS[l][0] for l in LANGS}) + '</span>'
            f'<span class="footer-links">{MAIL} · {links}</span></footer>')


def page_html(slug, skin_css=''):
    texts = PAGES[slug]
    theme, extra = ('light', f'<link rel="stylesheet" href="{html.escape(skin_css)}">') if skin_css else ('dark', '')
    titles = ' '.join(f'data-t{l}="{html.escape(texts[l][0])} · Ontoca"' for l in LANGS)
    sections = ''.join(f'<section lang="{l}"><a class="back" href="/">{BACK[l]}</a><h1>{texts[l][0]}</h1>{texts[l][1]}</section>' for l in LANGS)
    langs = ' · '.join(f'<a href="?lang={l}">{l.upper()}</a>' for l in LANGS)
    return (f'<!DOCTYPE html><html lang="es" data-l="es" data-theme="{theme}" {titles}><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{html.escape(texts["es"][0])} · Ontoca</title><meta name="description" content="{html.escape(DESCRIPTIONS[slug])}">'
            f'<link rel="stylesheet" href="/public.css">{extra}<style>{_HIDE}{{display:none}}.legal-langs{{font-size:14px}}</style>'
            '<script src="/legal.js"></script><script defer src="/analytics.js"></script></head>'
            '<body class="credits-page"><header class="site-header"><div class="nav-wrap"><a class="logo" href="/">ontoca<span>.</span></a></div></header>'
            f'<main class="credits"><p class="legal-langs">{langs}</p>{sections}</main>{footer_html()}</body></html>')
