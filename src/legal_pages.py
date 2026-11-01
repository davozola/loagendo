"""Páginas legales de la web pública (25-10-2026): Aviso legal, Privacidad y Fuentes.

Decisiones de David: pie mínimo (ontoca.com · Hecho en Barcelona, hola@ontoca.com y estas tres
páginas); responsable «Numhaus»; fuentes, lo mínimo que piden las licencias (no se nombran
ticketeras, agregadores ni agendas de sala); correo de las alertas con Brevo.

1-11-2026, 21:51 (David): una página por idioma, cada una con su dirección, como el resto de la web: el catalán en
la raíz (/avis-legal, /privacitat, /fonts-de-dades), el castellano en /es/ y el inglés en /en/, con hreflang entre ellas.
Las direcciones de antes (/aviso-legal, /privacidad, /creditos) redirigen a las castellanas (src/landings.redirects).
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
<p><b>En tu navegador.</b> El idioma y los planes guardados se quedan en tu dispositivo; no nos llegan. Si usas «Cerca de mí», tu ubicación solo se usa en tu dispositivo para calcular distancias: no se envía ni se guarda.</p>
<p><b>Proveedores:</b> Cloudflare (alojamiento, base de datos de los avisos y verificación antispam), Brevo (envío de los correos, UE) y Google (buzón de correo).</p>
<p><b>Cookies:</b> no usamos cookies.</p>
<p><b>Tus derechos.</b> Puedes pedir acceso, rectificación o supresión de tus datos en {MAIL}. También puedes reclamar ante la Agencia Española de Protección de Datos (<a href="https://www.aepd.es" rel="noopener noreferrer" target="_blank">aepd.es</a>).</p>'''),
    'ca': ('Privacitat', f'''
<p><b>Responsable:</b> {OWNER} · {MAIL}.</p>
<p><b>Avisos per correu.</b> Si t'hi subscrius, guardem el teu correu, la freqüència i les cerques que triïs, només per enviar-te els avisos. La base legal és el teu consentiment, que confirmes des d'un correu; les sol·licituds sense confirmar s'esborren al cap de 48 hores. Et pots donar de baixa des de l'enllaç de cada correu i llavors s'esborren les teves dades. Per evitar abusos es guarda durant un dia un resum xifrat de la IP, mai la IP.</p>
<p><b>Si ens escrius</b> a {CONTACT}, fem servir el teu correu només per respondre't.</p>
<p><b>Estadístiques.</b> Mesurem l'ús de la web amb Matomo en un servidor propi, sense galetes, amb la IP anonimitzada i sense mesurar res si el teu navegador demana no ser seguit (Do Not Track o Global Privacy Control).</p>
<p><b>Al teu navegador.</b> L'idioma i els plans desats es queden al teu dispositiu; no ens arriben. Si fas servir «A prop meu», la teva ubicació només s'usa al teu dispositiu per calcular distàncies: no s'envia ni es guarda.</p>
<p><b>Proveïdors:</b> Cloudflare (allotjament, base de dades dels avisos i verificació antispam), Brevo (enviament dels correus, UE) i Google (bústia de correu).</p>
<p><b>Galetes:</b> no fem servir galetes.</p>
<p><b>Els teus drets.</b> Pots demanar l'accés, la rectificació o la supressió de les teves dades a {MAIL}. També pots reclamar davant l'Agència Espanyola de Protecció de Dades (<a href="https://www.aepd.es" rel="noopener noreferrer" target="_blank">aepd.es</a>).</p>'''),
    'en': ('Privacy', f'''
<p><b>Controller:</b> {OWNER} · {MAIL}.</p>
<p><b>Email alerts.</b> If you subscribe, we store your email address, the frequency and the searches you choose, only to send you the alerts. The legal basis is your consent, which you confirm from an email; unconfirmed requests are deleted after 48 hours. You can unsubscribe from the link in every email, and your data is then deleted. To prevent abuse, a hashed summary of your IP is kept for one day, never the IP itself.</p>
<p><b>If you write to us</b> at {CONTACT}, we use your address only to reply.</p>
<p><b>Statistics.</b> We measure use of the site with Matomo on our own server, without cookies, with anonymised IPs and measuring nothing if your browser asks not to be tracked (Do Not Track or Global Privacy Control).</p>
<p><b>In your browser.</b> Your language and saved plans stay on your device; they never reach us. If you use «Near me», your location is only used on your device to work out distances: it is never sent or stored.</p>
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

DESCRIPTIONS = {
    'aviso-legal': {'es': 'Quién gestiona Ontoca y cómo pedir una corrección o retirada.',
                    'ca': 'Qui gestiona Ontoca i com demanar una correcció o una retirada.',
                    'en': 'Who runs Ontoca and how to ask for a correction or removal.'},
    'privacidad': {'es': 'Qué datos trata Ontoca, para qué y cómo ejercer tus derechos.',
                   'ca': 'Quines dades tracta Ontoca, per a què i com exercir els teus drets.',
                   'en': 'What data Ontoca processes, why, and how to exercise your rights.'},
    'creditos': {'es': 'De dónde salen los datos de Ontoca y con qué licencia.',
                 'ca': 'D’on surten les dades d’Ontoca i amb quina llicència.',
                 'en': 'Where Ontoca’s data comes from and under which licence.'}}
PAGES = {'aviso-legal': AVISO, 'privacidad': PRIVACIDAD, 'creditos': FUENTES}
PAGE_PATHS = {'aviso-legal': {'ca': '/avis-legal', 'es': '/es/aviso-legal', 'en': '/en/legal-notice'},
              'privacidad': {'ca': '/privacitat', 'es': '/es/privacidad', 'en': '/en/privacy'},
              'creditos': {'ca': '/fonts-de-dades', 'es': '/es/creditos', 'en': '/en/sources'}}
OLD_PATHS = {'/aviso-legal': '/es/aviso-legal', '/privacidad': '/es/privacidad', '/creditos': '/es/creditos'}
HOME = {'ca': '/', 'es': '/es/', 'en': '/en/'}
LANG_NAMES = {'ca': 'Català', 'es': 'Castellano', 'en': 'English'}


def path_for(slug, lang):
    return PAGE_PATHS[slug][lang]


def file_for(path):
    return path.strip('/') + '.html'


def footer_html(lang='ca'):
    """El pie de las páginas legales, en su idioma (el de la app está en static/index.html)."""
    links = ' · '.join(f'<a href="{PAGE_PATHS[slug][lang]}">{FOOTER_LINKS[lang][i + 1]}</a>' for i, slug in enumerate(('aviso-legal', 'privacidad', 'creditos')))
    return f'<footer><span>ontoca.com · {FOOTER_LINKS[lang][0]}</span><span class="footer-links">{MAIL} · {links}</span></footer>'


def page_html(slug, skin_css='', lang='ca', site_url=''):
    """Una página legal en un idioma, con canonical y hreflang a las otras dos (x-default, la catalana)."""
    title, body = PAGES[slug][lang]
    theme, extra = ('light', f'<link rel="stylesheet" href="{html.escape(skin_css)}">') if skin_css else ('dark', '')
    base = site_url.rstrip('/') if site_url else ''
    seo = ''
    if base:
        seo = (f'<link rel="canonical" href="{html.escape(base + PAGE_PATHS[slug][lang])}">'
               + ''.join(f'<link rel="alternate" hreflang="{l}" href="{html.escape(base + PAGE_PATHS[slug][l])}">' for l in LANGS)
               + f'<link rel="alternate" hreflang="x-default" href="{html.escape(base + PAGE_PATHS[slug]["ca"])}">')
    others = ' · '.join(f'<a href="{PAGE_PATHS[slug][l]}" hreflang="{l}" lang="{l}">{LANG_NAMES[l]}</a>' for l in ('ca', 'es', 'en') if l != lang)
    return (f'<!DOCTYPE html><html lang="{lang}" data-theme="{theme}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{html.escape(title)} · Ontoca</title><meta name="description" content="{html.escape(DESCRIPTIONS[slug][lang])}">{seo}'
            f'<link rel="stylesheet" href="/public.css">{extra}<style>.legal-langs{{font-size:14px}}</style>'
            '<script defer src="/analytics.js"></script></head>'
            f'<body class="credits-page"><header class="site-header"><div class="nav-wrap"><a class="logo" href="{HOME[lang]}">ontoca<span>.</span></a></div></header>'
            f'<main class="credits"><p class="legal-langs">{others}</p><section lang="{lang}"><a class="back" href="{HOME[lang]}">{BACK[lang]}</a>'
            f'<h1>{title}</h1>{body}</section></main>{footer_html(lang)}</body></html>')


def write_all(out, skin_css='', site_url=''):
    """Las nueve páginas (tres por idioma). Devuelve sus direcciones (para el sitemap)."""
    from pathlib import Path
    out = Path(out); paths = []
    for slug in PAGES:
        for lang in LANGS:
            path = PAGE_PATHS[slug][lang]; target = out / file_for(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(page_html(slug, skin_css, lang, site_url), encoding='utf-8')
            paths.append(path)
    for old in OLD_PATHS:   # las de antes (una sola página con los tres idiomas): redirigen
        f = out / file_for(old)
        if f.is_file(): f.unlink()
    return paths
