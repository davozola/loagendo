'use strict';
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeurl = s => { try { const u = new URL(s); return ['http:','https:'].includes(u.protocol) ? u.href : null } catch (_) { return null } };
// Clasificación pública (19-10-2026, src/taxonomy.py): 8 categorías —cada ficha tiene una sola,
// según su naturaleza— y 5 canales de descubrimiento —colecciones transversales; una ficha puede
// estar en varios—. Se combinan: categorías marcadas (se suman) × canales marcados (se suman).
// Sin tercer nivel: los subtipos y el «Con niños» antiguos pasan a ser el canal «En familia».
const CATS = {musica: ['Música y conciertos', 'Música i concerts', 'Music and concerts'], escena: ['Teatro y danza', 'Teatre i dansa', 'Theatre and dance'], cine: ['Cine', 'Cinema', 'Cinema'],
  arte: ['Arte y exposiciones', 'Art i exposicions', 'Art and exhibitions'], charlas: ['Charlas y visitas', 'Xerrades i visites', 'Talks and visits'], talleres: ['Talleres y experiencias', 'Tallers i experiències', 'Workshops and experiences'],
  fiestas: ['Fiestas y mercados', 'Festes i mercats', 'Festivities and markets'], deporte: ['Deporte', 'Esport', 'Sport']};
const CHANS = {familia: ['En familia', 'En família', 'With family'], barrio: ['Vida de barrio', 'Vida de barri', 'Neighbourhood life'], aire: ['Al aire libre', "A l'aire lliure", 'Outdoors'],
  galerias: ['Arte y galerías', 'Art i galeries', 'Art and galleries'], festivales: ['Festivales y fiestas', 'Festivals i festes', 'Festivals']};
// Enlaces antiguos (?cat=Conciertos, ?kids=1) siguen funcionando.
const LEGACY_CAT = {Conciertos: 'musica', 'Música': 'musica', Teatro: 'escena', Cine: 'cine', Exposiciones: 'arte', Talleres: 'talleres', Deporte: 'deporte'};
const LEGACY_CHAN = {Familia: 'familia', Barrio: 'barrio'};
const byLang = pair => pair[LANG === 'ca' ? 1 : LANG === 'en' ? 2 : 0] ?? pair[0];
const catName = c => CATS[c] ? byLang(CATS[c]) : CATS[LEGACY_CAT[c]] ? byLang(CATS[LEGACY_CAT[c]]) : t(c || '');
const chanName = c => CHANS[c] ? byLang(CHANS[c]) : c;
const catMatch = (e, cats) => !cats || !cats.length || cats.includes(e.public_category);
const chanMatch = (e, chans) => !chans || !chans.length || chans.some(c => (e.channels || []).includes(c));
// Idioma en que se hace la actividad (23-10-2026): solo lo declaran algunas fuentes (Open Data BCN).
const ACT_LANGS = {en: ['En inglés', 'En anglès', 'In English'], es: ['En castellano', 'En castellà', 'In Spanish'], ca: ['En catalán', 'En català', 'In Catalan'], other: ['Más idiomas', 'Més idiomes', 'Other languages']};
const langMatch = (e, langs) => !langs || !langs.length || langs.some(l => l === 'other' ? (e.languages || []).some(x => ['fr', 'it', 'other'].includes(x)) : (e.languages || []).includes(l));
// Franjas de edad del canal «En familia» (20-10-2026). La edad sale de la fuente (título o texto) o
// del texto leído por IA con cita comprobada; si nadie la dice, la ficha es «Edad no indicada».
const AGE_BANDS = {'0-3': [0, 3], '4-6': [4, 6], '7-12': [7, 12], '13-17': [13, 17], nd: null};
const AGE_LABEL = {'0-3': ['0–3 años', '0–3 anys', 'Ages 0–3'], '4-6': ['4–6 años', '4–6 anys', 'Ages 4–6'], '7-12': ['7–12 años', '7–12 anys', 'Ages 7–12'], '13-17': ['13–17 años', '13–17 anys', 'Ages 13–17'], nd: ['Edad no indicada', 'Edat no indicada', 'Age not stated']};
const hasAge = e => e.age_min !== null && e.age_min !== undefined;
const ageMatch = (e, bands) => !bands || !bands.length || bands.some(b => b === 'nd' ? !hasAge(e) : hasAge(e) && e.age_min <= AGE_BANDS[b][1] && (e.age_max ?? 99) >= AGE_BANDS[b][0]);
const ageText = e => !hasAge(e) ? '' : e.age_max === null || e.age_max === undefined ? L(`Desde ${e.age_min} años`, `A partir de ${e.age_min} anys`, `From age ${e.age_min}`) : e.age_min === 0 && e.age_max <= 1 ? L('Bebés', 'Nadons', 'Babies') : L(`${e.age_min}–${e.age_max} años`, `${e.age_min}–${e.age_max} anys`, `Ages ${e.age_min}–${e.age_max}`);
const FORMATS = {one_shot:'Actos y funciones',workshop:'Talleres',course:'Cursos',program:'Ciclos y programas',festival:'Festivales',exhibition:'Exposiciones',ongoing:'Actividades continuadas'};
const PAGE = 50;
const params = new URLSearchParams(location.search);

/* ---------- idioma ----------
   La interfaz se muestra en castellano o catalán; el contenido de cada ficha
   (título, descripción, horarios) se deja en el idioma en que lo publica la
   fuente, nunca se traduce automáticamente. */
// Preferencias del navegador: nombre nuevo (brollant-*) y, si no existe, el de Loagendo, para no perder eventos guardados.
function pref(key) { try { return localStorage.getItem('brollant-' + key) ?? localStorage.getItem('loagendo-' + key) } catch (_) { return null } }
const LANG = (() => { const q = params.get('lang'); let saved = ''; try { saved = pref('lang') || '' } catch (_) {} return ['es','ca','en'].includes(q) ? q : ['es','ca','en'].includes(saved) ? saved : 'es' })();
const CA = {'Fin de semana': 'Cap de setmana', 'Vista de la agenda': 'Vista de l’agenda', 'Hecho en Barcelona': 'Fet a Barcelona', 'Aviso legal': 'Avís legal', 'Privacidad': 'Privacitat', 'Fuentes': 'Fonts', 'Este fin de semana': 'Aquest cap de setmana', 
  'Conciertos':'Concerts','Música':'Música','Teatro':'Teatre','Exposiciones':'Exposicions','Cine':'Cinema','Familia':'Família','Talleres':'Tallers','Deporte':'Esport','Barrio':'Barri','Teatro y danza':'Teatre i dansa','Charlas, visitas y barrio':'Xerrades, visites i barri','Talleres y cursos':'Tallers i cursos','Con niños':'Amb canalla','Cartel':'Cartell','Con':'Amb','Público y precio':'Públic i preu','Solo planes para ir con niños':'Només plans per anar amb canalla','Baile':'Ball','Teatro y circo':'Teatre i circ','Temporadas y ciclos':'Temporades i cicles',
  'Actos y funciones':'Actes i funcions','Cursos':'Cursos','Ciclos y programas':'Cicles i programes','Festivales':'Festivals','Actividades continuadas':'Activitats continuades',
  'Arquitectura y diseño':'Arquitectura i disseny','Arte contemporáneo':'Art contemporani','Arte y manualidades':'Art i manualitats','Ciencia y naturaleza':'Ciència i natura','Clásica y ópera':'Clàssica i òpera','Cocina':'Cuina','Coral y tradicional':'Coral i tradicional','Cuerpo y salud':'Cos i salut','Electrónica':'Electrònica','Flamenco y músicas del mundo':'Flamenc i músiques del món','Fotografía':'Fotografia','Historia y patrimonio':'Història i patrimoni','Humanidades y ciencia':'Humanitats i ciència','Idiomas':'Idiomes','Jazz y blues':'Jazz i blues','Música, danza y teatro':'Música, dansa i teatre','Pintura y dibujo':'Pintura i dibuix','Pop y rock':'Pop i rock','Tecnología':'Tecnologia','Sin clasificar':'Sense classificar','Varios distritos':'Diversos districtes',
  'Hoy':'Avui','Fecha':'Data','planes':'plans','guardados':'desats','Todos los días':'Tots els dies','Próximos 7 días':'Propers 7 dies','Periodo de la selección':'Període de la selecció','Tipo de plan':'Tipus de pla','Tipo de plan de la Selección':'Tipus de pla de la Selecció','Planes anteriores':'Plans anteriors','Planes siguientes':'Plans següents','Selección Ontoca':'Selecció Ontoca','Próximos 30 días':'Propers 30 dies','Próximos 3 meses':'Propers 3 mesos','Próximos 6 meses':'Propers 6 mesos','Próximos':'Propers','días':'dies',
  'Varios días':'Diversos dies','Hora no indicada':'Hora no indicada','Gratis':'Gratis','Todo':'Tot','Todos':'Tots','Todos los distritos':'Tots els districtes','Cualquier hora':'Qualsevol hora','Con cursos ya empezados':'Amb cursos ja començats',
  'Limpiar todo':'Esborra-ho tot','Quitar filtro':'Treu el filtre','Ver':'Mostra','más':'més','restantes':'restants','Reintentar':'Torna-ho a provar',
  'Nada con estos filtros este día. Prueba otro día o quita algún filtro.':'Res amb aquests filtres aquest dia. Prova un altre dia o treu algun filtre.',
  'No se pudo cargar la agenda.':'No s\'ha pogut carregar l\'agenda.','No se pudo cargar la selección.':'No s\'ha pogut carregar la selecció.','Aún no hay actividades destacadas para estas fechas.':'Encara no hi ha activitats destacades per a aquestes dates.',
  'No hay ubicaciones geográficas para estos filtros. Prueba otro día o consulta la lista.':'No hi ha ubicacions geogràfiques per a aquests filtres. Prova un altre dia o consulta la llista.','Mapa de actividades geolocalizadas':'Mapa d\'activitats geolocalitzades','lugares con ubicación · pulsa un punto para abrir la ficha':'llocs amb ubicació · prem un punt per obrir la fitxa','Sin recinto identificado':'Sense recinte identificat',
  'Cerrar ficha':'Tanca la fitxa','Ver en la fuente oficial':'Mostra a la font oficial','Web del evento':'Web de l’esdeveniment','Web de la sala':'Web de la sala','Cómo llegar':'Com arribar-hi','Cuándo':'Quan','Dónde':'On','Organiza':'Organitza','Consultar fuente':'Consulta la font','Precio':'Preu','Descubre':'Descobreix','Consultar en la fuente':'Consulta-ho a la font','Contraste':'Contrast','Fecha coincidente en':'Data coincident a','fuentes':'fonts',
  'Horario':'Horari','Horas publicadas':'Hores publicades','las fuentes no coinciden; confirma en la sala':'les fonts no coincideixen; confirma-ho a la sala','Requiere inscripción':'Cal inscripció','Texto de':'Text de','Imagen del equipamiento':'Imatge de l\'equipament','Imagen de la fuente':'Imatge de la font','Más imágenes':'Més imatges','Ubicación':'Ubicació','Mapa de':'Mapa de','la ubicación':'la ubicació','Próximamente en':'Properament a','esta sala':'aquesta sala',
  'Guardado':'Desat','Guardar':'Desa','Compartir':'Comparteix','Añadir al calendario':'Afegeix al calendari','Enlace copiado':'Enllaç copiat','Enlace de la ficha':'Enllaç de la fitxa',
  'Fecha y sala recogidas automáticamente y contrastadas entre fuentes; el detalle, en la web de la sala.':'Data i sala recollides automàticament i contrastades entre fonts; el detall, al web de la sala.','Fuente':'Font','Información recogida automáticamente':'Informació recollida automàticament','confirma horario y precio antes de ir.':'confirma l\'horari i el preu abans d\'anar-hi.',
  // index.html
  'Saltar a la agenda':'Salta a l\'agenda','Agenda':'Agenda','Selección':'Selecció','Barrios':'Barris','Guardados':'Desats','Ver guardados':'Mostra els desats','Cambiar modo claro u oscuro':'Canvia el mode clar o fosc',
  'Qué hacer en Barcelona':'Què fer a Barcelona','Qué hacer en':'Què fer a','Más filtros':'Més filtres','Dónde':'On','Elegir día':'Tria el dia','Otra fecha':'Una altra data','Cuándo':'Quan','hoy.':'avui.','Mil maneras de vivir la ciudad.':'Mil maneres de viure la ciutat.',
  'Selección de la semana':'Selecció de la setmana','Buscar en la agenda':'Cerca a l\'agenda','Artista, sala, barrio, obra…':'Artista, sala, barri, obra…','7 días':'7 dies','30 días':'30 dies','6 meses':'6 mesos','Elegir una fecha concreta':'Tria una data concreta','Días anteriores':'Dies anteriors','Días siguientes':'Dies següents','Días de agenda':'Dies d\'agenda','Periodo':'Període',
  'Filtros':'Filtres','Filtros activos':'Filtres actius','Planes':'Plans','Limpiar':'Esborra','Cerrar filtros':'Tanca els filtres','Qué te apetece':'Què et ve de gust','Categoría':'Categoria','Tipo':'Tipus','Distrito':'Districte','Filtrar por distrito':'Filtra per districte','Formato':'Format','Filtrar por formato':'Filtra per format','Todos los formatos':'Tots els formats','Idioma de la actividad':'Idioma de l\'activitat','Incluir cursos ya empezados':'Inclou cursos ja començats','Solo gratis':'Només gratis','Filtrar por horario':'Filtra per horari','Franja horaria':'Franja horària','Mañana':'Matí','Tarde':'Tarda','Noche':'Nit','Desde':'Des de','Hasta':'Fins a','Hora desde':'Hora des de','Hora hasta':'Hora fins a','Quitar horario':'Treu l\'horari','Vista':'Vista','Modo de vista':'Mode de vista','Lista':'Llista','Mapa':'Mapa','Por sitio':'Per lloc',
  'Los horarios y precios se muestran tal como los publica cada fuente. Confírmalos antes de ir.':'Els horaris i preus es mostren tal com els publica cada font. Confirma\'ls abans d\'anar-hi.','Por distritos':'Per districtes','Próximos 14 días':'Propers 14 dies','Fuentes y créditos':'Fonts i crèdits',
  'Datos: Ajuntament de Barcelona (Open Data BCN, CC BY 4.0), Generalitat de Catalunya, Diputació de Barcelona (CC BY 4.0) y agendas de los equipamientos. Confirma horarios en la fuente.':'Dades: Ajuntament de Barcelona (Open Data BCN, CC BY 4.0), Generalitat de Catalunya, Diputació de Barcelona (CC BY 4.0) i agendes dels equipaments. Confirma els horaris a la font.',
  'Cambiar idioma':'Canvia l\'idioma','mañana.':'demà.','este fin de semana.':'aquest cap de setmana.','esta semana.':'aquesta setmana.','este mes.':'aquest mes.','Exposición':'Exposició','Hoy, lunes':'Avui, dilluns'
};
// Inglés (23-10-2026): mismas claves que CA (el texto en castellano).
const EN = {'Fin de semana': 'Weekend', "Vista de la agenda":"Listings view","Hecho en Barcelona":"Made in Barcelona","Aviso legal":"Legal notice","Privacidad":"Privacy","Fuentes":"Sources","Este fin de semana":"This weekend","Conciertos":"Concerts","Música":"Music","Teatro":"Theatre","Exposiciones":"Exhibitions","Cine":"Cinema","Familia":"Family","Talleres":"Workshops","Deporte":"Sport","Barrio":"Neighbourhood","Teatro y danza":"Theatre and dance","Charlas, visitas y barrio":"Talks, visits and neighbourhood","Talleres y cursos":"Workshops and courses","Con niños":"With kids","Cartel":"Line-up","Con":"With","Público y precio":"Audience and price","Solo planes para ir con niños":"Only plans for kids","Baile":"Dance","Teatro y circo":"Theatre and circus","Temporadas y ciclos":"Seasons and series","Actos y funciones":"Events and shows","Cursos":"Courses","Ciclos y programas":"Series and programmes","Festivales":"Festivals","Actividades continuadas":"Ongoing activities","Arquitectura y diseño":"Architecture and design","Arte contemporáneo":"Contemporary art","Arte y manualidades":"Arts and crafts","Ciencia y naturaleza":"Science and nature","Clásica y ópera":"Classical and opera","Cocina":"Cooking","Coral y tradicional":"Choral and traditional","Cuerpo y salud":"Body and health","Electrónica":"Electronic","Flamenco y músicas del mundo":"Flamenco and world music","Fotografía":"Photography","Historia y patrimonio":"History and heritage","Humanidades y ciencia":"Humanities and science","Idiomas":"Languages","Jazz y blues":"Jazz and blues","Música, danza y teatro":"Music, dance and theatre","Pintura y dibujo":"Painting and drawing","Pop y rock":"Pop and rock","Tecnología":"Technology","Sin clasificar":"Unclassified","Varios distritos":"Several districts","Hoy":"Today","Fecha":"Date","planes":"plans","guardados":"saved","Todos los días":"Every day","Próximos 7 días":"Next 7 days","Periodo de la selección":"Selection period","Tipo de plan":"Type of plan","Tipo de plan de la Selección":"Type of plan in the picks","Planes anteriores":"Previous plans","Planes siguientes":"Next plans","Selección Ontoca":"Ontoca picks","Próximos 30 días":"Next 30 days","Próximos 3 meses":"Next 3 months","Próximos 6 meses":"Next 6 months","Próximos":"Next","días":"days","Varios días":"Several days","Hora no indicada":"Time not stated","Gratis":"Free","Todo":"All","Todos":"All","Todos los distritos":"All districts","Cualquier hora":"Any time","Con cursos ya empezados":"Including courses under way","Limpiar todo":"Clear all","Quitar filtro":"Remove filter","Ver":"See","más":"more","restantes":"remaining","Reintentar":"Try again","Nada con estos filtros este día. Prueba otro día o quita algún filtro.":"Nothing with these filters on this day. Try another day or remove a filter.","No se pudo cargar la agenda.":"The listings could not be loaded.","No se pudo cargar la selección.":"The selection could not be loaded.","Aún no hay actividades destacadas para estas fechas.":"No featured activities for these dates yet.","No hay ubicaciones geográficas para estos filtros. Prueba otro día o consulta la lista.":"No locations for these filters. Try another day or check the list.","Mapa de actividades geolocalizadas":"Map of activities","lugares con ubicación · pulsa un punto para abrir la ficha":"places with a location · tap a point to open it","Sin recinto identificado":"No venue identified","Cerrar ficha":"Close","Ver en la fuente oficial":"See on the official source","Web del evento":"Event website","Web de la sala":"Venue website","Cómo llegar":"Directions","Cuándo":"When","Dónde":"Where","Organiza":"Organiser","Consultar fuente":"Check the source","Precio":"Price","Descubre":"Discover","Consultar en la fuente":"Check with the source","Contraste":"Cross-check","Fecha coincidente en":"Same date on","fuentes":"sources","Horario":"Times","Horas publicadas":"Published times","las fuentes no coinciden; confirma en la sala":"sources disagree; check with the venue","Requiere inscripción":"Registration required","Texto de":"Text by","Imagen del equipamiento":"Venue photo","Imagen de la fuente":"Source image","Más imágenes":"More images","Ubicación":"Location","Mapa de":"Map of","la ubicación":"the location","Próximamente en":"Coming up at","esta sala":"this venue","Guardado":"Saved","Guardar":"Save","Compartir":"Share","Añadir al calendario":"Add to calendar","Enlace copiado":"Link copied","Enlace de la ficha":"Link","Fecha y sala recogidas automáticamente y contrastadas entre fuentes; el detalle, en la web de la sala.":"Date and venue collected automatically and cross-checked between sources; details on the venue’s website.","Fuente":"Source","Información recogida automáticamente":"Information collected automatically","confirma horario y precio antes de ir.":"check times and prices before you go.","Saltar a la agenda":"Skip to the listings","Agenda":"Listings","Selección":"Picks","Barrios":"Neighbourhoods","Guardados":"Saved","Ver guardados":"See saved","Cambiar modo claro u oscuro":"Switch light or dark mode","Qué hacer en Barcelona":"What to do in Barcelona","Qué hacer en":"What to do in","Más filtros":"More filters","Elegir día":"Pick a day","Otra fecha":"Another date","hoy.":"today.","Mil maneras de vivir la ciudad.":"A thousand ways to live the city.","Selección de la semana":"This week’s picks","Buscar en la agenda":"Search the listings","Artista, sala, barrio, obra…":"Artist, venue, neighbourhood, show…","7 días":"7 days","30 días":"30 days","6 meses":"6 months","Elegir una fecha concreta":"Pick a date","Días anteriores":"Previous days","Días siguientes":"Next days","Días de agenda":"Listing days","Periodo":"Period","Filtros":"Filters","Filtros activos":"Active filters","Planes":"Plans","Limpiar":"Clear","Cerrar filtros":"Close filters","Qué te apetece":"What do you fancy","Categoría":"Category","Tipo":"Type","Distrito":"District","Filtrar por distrito":"Filter by district","Formato":"Format","Filtrar por formato":"Filter by format","Todos los formatos":"All formats","Idioma de la actividad":"Language of the activity","Incluir cursos ya empezados":"Include courses under way","Solo gratis":"Free only","Filtrar por horario":"Filter by time","Franja horaria":"Time of day","Mañana":"Morning","Tarde":"Afternoon","Noche":"Evening","Desde":"From","Hasta":"Until","Hora desde":"From time","Hora hasta":"Until time","Quitar horario":"Remove time filter","Vista":"View","Modo de vista":"View mode","Lista":"List","Mapa":"Map","Por sitio":"By venue","Los horarios y precios se muestran tal como los publica cada fuente. Confírmalos antes de ir.":"Times and prices are shown as each source publishes them. Check them before you go.","Por distritos":"By district","Próximos 14 días":"Next 14 days","Fuentes y créditos":"Sources and credits","Datos: Ajuntament de Barcelona (Open Data BCN, CC BY 4.0), Generalitat de Catalunya, Diputació de Barcelona (CC BY 4.0) y agendas de los equipamientos. Confirma horarios en la fuente.":"Data: Barcelona City Council (Open Data BCN, CC BY 4.0), Generalitat de Catalunya, Barcelona Provincial Council (CC BY 4.0) and venue listings. Check times with the source.","Cambiar idioma":"Change language","mañana.":"tomorrow.","este fin de semana.":"this weekend.","esta semana.":"this week.","este mes.":"this month.","Exposición":"Exhibition","Hoy, lunes":"Today, Monday"};
const t = s => LANG === 'ca' ? (CA[s] ?? s) : LANG === 'en' ? (EN[s] ?? s) : s;
const months = LANG === 'en' ? ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'] : LANG === 'ca' ? ['gen','febr','març','abr','maig','juny','jul','ag','set','oct','nov','des'] : ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
const weekdays = LANG === 'en' ? ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'] : LANG === 'ca' ? ['dg','dl','dt','dc','dj','dv','ds'] : ['dom','lun','mar','mié','jue','vie','sáb'];
function translatePage() {
  document.documentElement.lang = LANG;
  document.querySelectorAll('[data-i18n]').forEach(el => { const key = el.dataset.i18n || el.textContent.trim(); if (CA[key] !== undefined) el.textContent = t(key) });
  document.querySelectorAll('[data-i18n-attr]').forEach(el => el.dataset.i18nAttr.split(',').forEach(a => { const v = el.getAttribute(a); if (v && CA[v] !== undefined) el.setAttribute(a, t(v)) }));
  const sw = $('lang'); if (sw) sw.value = LANG;
}
// Búsqueda bilingüe: una palabra encuentra también su equivalente en el otro
// idioma (y sus derivados, por prefijo), sin tocar el texto de las fichas.
const SYN = [['exposicion','exposicio','mostra','muestra'],['taller','tallers'],['nino','nen','infantil','familiar','familia'],['teatro','teatre'],['concierto','concert'],['cine','cinema'],['danza','dansa','baile','ball'],['charla','xerrada','conferencia'],['museo','museu'],['mercado','mercat'],['fiesta','festa'],['barrio','barri'],['gratis','gratuit'],['noche','nit'],['cuento','conte'],['titere','titella'],['circo','circ'],['poesia','poesia'],['libro','llibre'],['fotografia','foto'],['jardin','jardi'],['paseo','passeig','passejada'],['cocina','cuina'],['canto','cant'],['coro','cor '],['mujeres','dones'],['jovenes','joves'],['mayores','gent gran'],['espectaculo','espectacle'],['feria','fira'],['navidad','nadal'],['verano','estiu'],['invierno','hivern'],['primavera','primavera'],['otono','tardor'],['lectura','lectura','club'],['historia','historia'],['ciencia','ciencia'],['pintura','pintura'],['escuela','escola'],['biblioteca','biblioteca'],['centro civico','centre civic'],['visita','visita'],['ruta','ruta','itinerari','itinerario'],['musica','musica'],['opera','opera'],['flamenco','flamenc'],['electronica','electronica'],['juego','joc'],['magia','magia'],['humor','humor','monolog'],['cuentacuentos','contacontes']];
// El buscador mira título, recinto y cartel: un artista encuentra el festival en que toca.
const searchText = e => fold(e.title + ' ' + (e.venue_names || []).join(' ') + ' ' + (e.lineup || []).join(' ') + ' ' + (e.program_titles || e.program?.map(p => p.title) || []).join(' ') + ' ' + (e.festival?.name || ''));
// Artista del cartel que explica el resultado cuando el título no lo dice.
function lineupHit(e) {
  if (!state.query || !e.lineup?.length) return '';
  const q = fold(state.query);
  if (queryMatches(fold(e.title + ' ' + (e.venue_names || []).join(' ')), q)) return '';
  return e.lineup.find(n => queryMatches(fold(n), q)) || '';
}
// Búsqueda que acierta en el programa de un festival con abono (25-10-2026): «Programa: <sesión>».
function programHit(e) {
  const list = e.program_titles?.length ? e.program_titles : (e.program || []).map(p => p.title);
  if (!state.query || !list.length) return '';
  const q = fold(state.query);
  if (queryMatches(fold(e.title + ' ' + (e.venue_names || []).join(' ')), q)) return '';
  return list.find(n => queryMatches(fold(n), q)) || '';
}
// Raíz de palabra (24-10-2026): se quita la terminación de la palabra buscada (raíz de 4
// letras o más) y se aceptan, como palabra entera, las terminaciones de su misma familia:
// «castellers» encuentra «castellera» pero no «castell», «Castelló» ni «castellà»;
// «sardanes», «sardana»; «exposiciones», «exposició»; «castells», «castellera». La coincidencia exacta de antes
// (también dentro de otra palabra) se mantiene. Igual que mvp/catalog.word_stem.
const ENDING_FAMILIES = [['er','ers','era','eres','ero','eros'], ['or','ors','ora','ores'], ['al','als','ales'], ['io','ion','ions','iones'], ['','a','as','e','es','o','os','s']];
const ENDINGS = ENDING_FAMILIES.flat().filter(Boolean).sort((x, y) => y.length - x.length);
// La familia nominal (-a, -es, -s…) acepta también la de oficio: «castells» encuentra «castellera».
const familyOf = x => { const f = ENDING_FAMILIES.find(g => g.includes(x)); return f === ENDING_FAMILIES[4] ? [...f, ...ENDING_FAMILIES[0]] : f };
const wordStem = w => { for (const x of ENDINGS) if (w.endsWith(x) && w.length - x.length >= 4) return [w.slice(0, -x.length), familyOf(x)]; return [w, ['','s','es']] };
const STEM_RE = new Map();
const stemRe = w => {
  if (!STEM_RE.has(w)) { const [st, fam] = wordStem(w); const clean = st.replace(/[^a-z0-9]/g, ''); STEM_RE.set(w, clean.length >= 4 ? new RegExp(`(?:^|[^a-z0-9])${clean}(?:${fam.join('|')})(?![a-z0-9])`) : null) }
  return STEM_RE.get(w);
};
function queryMatches(text, query) {
  return query.split(' ').every(word => {
    const re = stemRe(word); if (re && re.test(text)) return true;
    const alts = new Set([word]);
    for (const g of SYN) if (g.some(m => word.startsWith(m) || m.startsWith(word))) g.forEach(m => alts.add(m));
    return [...alts].some(a => text.includes(a));
  });
}
const iso = d => { const z = new Date(d.getTime() - d.getTimezoneOffset() * 60000); return z.toISOString().slice(0, 10) };
const today = new Intl.DateTimeFormat('en-CA', {timeZone: 'Europe/Madrid'}).format(new Date());  // el día de Barcelona, aunque el dispositivo esté en otra zona
const MAX_DAYS = 183;
const addDays = (v, n) => { const d = new Date(v + 'T12:00:00'); d.setDate(d.getDate() + n); return iso(d) };
const RANGE_LABELS = {finde: t('Este fin de semana'), '7': t('Próximos 7 días'), '30': t('Próximos 30 días'), '90': t('Próximos 3 meses'), '183': t('Próximos 6 meses'), all: t('Todos los días')};
function rangeWindow() {
  // Returns {from,to,label} for the active period, or null in single-day mode.
  // A search without a chosen period looks across the whole public horizon.
  const r = state.range || (state.query ? 'all' : '');
  if (!r) return null;
  if (r === 'finde') {   // de lunes a jueves, viernes a domingo de esa semana; de viernes a domingo, de hoy al domingo (src/landings.py)
    const wd = (new Date(today + 'T12:00:00').getDay() + 6) % 7;
    return {from: wd < 4 ? addDays(today, 4 - wd) : today, to: addDays(today, 6 - wd), label: RANGE_LABELS.finde};
  }
  const n = r === 'all' ? MAX_DAYS : Math.min(Number(r) || 7, MAX_DAYS);
  return {from: today, to: addDays(today, n), label: RANGE_LABELS[r] || `${t('Próximos')} ${n} ${t('días')}`};
}

// Páginas de entrada (/hoy, /fin-de-semana, /con-ninos…, src/landings.py): arrancan con su filtro.
// Solo cuando se llega sin parámetros; la dirección se mantiene mientras el filtro sea ese (syncUrl).
const LANDING = (() => { try { return location.search ? {} : JSON.parse(document.documentElement.dataset.landing || '{}') } catch (_) { return {} } })();
const landingDay = () => LANDING.day === 'today' ? today : LANDING.day === 'tomorrow' ? addDays(today, 1) : (LANDING.day || '');
let state = {
  pickRange: 'auto',   // «Selección Ontoca»: 'auto' (hoy si quedan planes; si no, 7 días), 'today' o 'week'
  pickCat: '',         // tipo de la Selección (28-10-2026, 19:34, David): solo filtra la Selección; '' = «Todo»
  day: params.get('day') || landingDay() || today, cats: [...new Set([...params.getAll('cat'), ...(LANDING.cats || [])].map(c => LEGACY_CAT[c] || c).filter(c => CATS[c]))],
  chans: [...new Set([...params.getAll('ch'), ...(LANDING.chans || []), ...params.getAll('cat').map(c => LEGACY_CHAN[c]), params.get('kids') === '1' ? 'familia' : ''].filter(c => CHANS[c]))], ages: params.getAll('edad').filter(a => a in AGE_BANDS), format: '', district: params.get('district') || '',
  free: params.get('free') === '1', query: params.get('q') || '',
  hourFrom: params.has('from') ? Number(params.get('from')) : null, hourTo: params.has('to') ? Number(params.get('to')) : null,
  view: ['list','map','venue'].includes(params.get('view')) ? params.get('view') : 'list',
  range: params.get('range') || LANDING.range || '',
  // Pestaña de la agenda (25-10-2026): Agenda (por defecto), Exposiciones o Festivales; /exposiciones abre en la suya.
  tab: ['agenda', 'expo'].includes(params.get('vista')) ? params.get('vista') : LANDING.path === '/exposiciones' ? 'expo' : 'agenda',
  fest: params.get('fest') || '', festName: params.get('festname') || '', started: params.get('started') === '1', langs: params.getAll('idioma').filter(l => ACT_LANGS[l]),
  savedOnly: false, saved: [], detail: null, page: 1, items: [], total: 0,
};
const LANDING_Q = LANDING.path ? stateQuery() : null;   // el filtro con que arrancó la página de entrada (syncUrl)
try { state.saved = JSON.parse(pref('saved') || '[]') } catch (_) { state.saved = [] }
let returnFocus = null, agendaRequest = 0;

const fetchJson = async (path, opts) => { const r = await fetch(path, opts); const d = await r.json(); if (!r.ok) throw Error(d.error || 'Error'); return d };

/* ---------- data layer ----------
   Live mode asks the local server (/api/...). Static mode (data-static="1" on <html>,
   the published site) reads the exported files: one ranked first page per day in
   /data/day/, the compact catalogue in /data/catalog.json for every filtered or
   multi-day query, and detail records sharded by key in /data/detail/. The ranking
   below mirrors mvp/catalog.query_events so both modes order a day the same way. */
const STATIC = document.documentElement.dataset.static === '1';
const store = {catalog: null, loading: null, days: {}, shards: {}, tr: {}};
const fold = s => String(s ?? '').toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '').split(/\s+/).filter(Boolean).join(' ');
function expand(c) {
  return {source: c.s, id: c.i, key: `${c.s}:${c.i}`, title: c.t, source_label: c.sl || '', start: c.a, end: c.b, kind: c.kd, format: c.f, format_label: FORMATS[c.f] || c.f, category: c.c || '', public_category: c.pc,
    district: c.d || null, family_audience: Boolean(c.fa), has_description: Boolean(c.hd), summary: c.su || '', venue_names: c.v || [],
    coordinates: c.g ? {lat: c.g[0], lon: c.g[1]} : null, occurrences: (c.o || []).map(([date, time]) => ({date, time: time || null})), has_candidate: (c.o || []).length > 0,
    is_free: Boolean(c.fr), price_label: c.pl || null, channels: c.ch || [], age_min: c.ag ? c.ag[0] : null, age_max: c.ag ? (c.ag[1] === 99 ? null : c.ag[1]) : null, time: c.tm || null, time_label: c.tl, time_conflicts: c.tc || null, open_days: c.od || null, by_appointment: Boolean(c.oc), schedule_hint: c.tx || '', hours_by_day: c.hb || null, notes_by_day: c.nd || null, lineup: c.lu || [], languages: c.lg || [], featured_date: c.fd || null, series: c.se || '', image: c.mi || '', relevant: Boolean(c.rv), venue_tier: c.vt || 0, promo: Boolean(c.pm), price_short: c.pp || null, open_enrollment: Boolean(c.oe), registration_required: Boolean(c.rr), drop_in: Boolean(c.di), program_titles: c.pg || [], program_first: c.pf || null, program_days: c.pn || null, manual_hours: c.mh || null, sold_out: c.so ? (c.so === 1 ? [] : c.so) : null, confirmations: c.cf || 1, festival: c.fs ? {slug: c.fs[0], name: c.fs[1], umbrella: Boolean(c.fs[2]), fiesta: Boolean(c.fs[3])} : null, milestone: c.ms === 'op' ? {kind: 'opening'} : c.ms === 'cl' ? {kind: 'closing'} : null, media: (c.m || []).map(m => ({url: m.u, alt: m.alt, credit: m.cr, fallback: Boolean(m.fb)})), url: c.u || ''};
}
async function loadCatalog() {
  if (store.catalog) return store.catalog;
  store.loading ||= fetchJson('/data/catalog.json').then(d => { store.catalog = d.items.map(expand); return store.catalog }).catch(err => { store.loading = null; throw err });
  return store.loading;
}
// Selección por tipo (28-10-2026): fichero aparte por día, {w: {categoría: fichas}, t: …}; solo lo pide la Selección.
async function picksFile(day) {
  if (!STATIC) return null;
  store.picks ||= {};
  store.picks[day] ||= fetchJson(`/data/picks/${day}.json`).catch(() => { delete store.picks[day]; return null });
  return store.picks[day];
}
async function dayFile(day) {
  store.days[day] ||= fetchJson(`/data/day/${day}.json`).catch(err => { delete store.days[day]; throw err });
  return store.days[day];
}
async function shardName(k) {
  const bytes = new TextEncoder().encode(k), digest = await crypto.subtle.digest('SHA-1', bytes);
  return Array.from(new Uint8Array(digest).slice(0, 1)).map(b => b.toString(16).padStart(2, '0')).join('');
}
// Traducción automática de la descripción (inglés o castellano; el original suele ser catalán): solo las
// que pasaron la comprobación (src/ai_translate.py). Sin traducción, la ficha enseña el original.
async function translationFor(k) {
  if (!STATIC || !['en', 'es'].includes(LANG)) return null;
  try {
    const name = await shardName(k);
    store.tr[name] ||= fetchJson(`/data/tr/${LANG}/${name}.json`).catch(() => ({}));
    return (await store.tr[name])[k] || null;
  } catch (_) { return null }
}
async function shardFor(k) {
  const name = await shardName(k);
  store.shards[name] ||= fetchJson(`/data/detail/${name}.json`).catch(err => { delete store.shards[name]; throw err });
  return store.shards[name];
}
// La hora de un día concreto: la sesión fechada si la hay; si no, el horario
// oficial de ese día cuando la fuente lo publica por días (GuiaBCN).
// El horario por día: {fecha: etiqueta} desde la API local, o empaquetado
// {etiqueta: [días desde el inicio]} en la web estática.
function unpackByDay(e, packed) {
  if (!packed) return null;
  if (Object.values(packed).every(v => typeof v === 'string')) return packed;
  const out = {}, base = new Date(e.start + 'T12:00:00');
  for (const [label, offsets] of Object.entries(packed)) for (const n of offsets) { const d = new Date(base); d.setDate(d.getDate() + n); out[d.toISOString().slice(0, 10)] = label }
  return out;
}
function hoursByDay(e) { return e._hours || (e._hours = unpackByDay(e, e.hours_by_day)) }
// Actividad de cada día cuando la fuente la da por filas («Dijous: vermut comunitari»).
function noteOfDay(e, day) { return (e._notes || (e._notes = unpackByDay(e, e.notes_by_day) || {}))[day] || '' }
// Entradas agotadas según la fuente (24-10-2026): para todas las fechas o solo para las que nombra el aviso.
const soldOn = (e, day) => { const so = e.sold_out; if (!so) return false; const days = Array.isArray(so) ? so : (so.dias || []); return !days.length || days.includes(day) };
function atDay(e, day) {
  const t = e.occurrences?.find(o => o.date === day && o.time);
  if (t) return {...e, time: t.time};
  const h = hoursByDay(e)?.[day];
  return h ? {...e, time: (h.match(/\b\d{2}:\d{2}\b/) || [h])[0], time_label: h} : e;
}
const shortSpan = e => { const d = (new Date(e.end + 'T12:00:00') - new Date(e.start + 'T12:00:00')) / 86400000; return d > 0 && d < 4 };
const hoursOf = v => (String(v || '').match(/\b(?:[01]\d|2[0-3]):[0-5]\d\b/g) || []).map(x => Number(x.slice(0, 2)));
async function staticEvents(p) {
  const day = p.get('day') || '', from = p.get('date_from') || '', to = p.get('date_to') || '';
  const page = Number(p.get('page') || 1), size = Number(p.get('page_size') || PAGE);
  if (p.get('featured') === '1') { const d = await dayFile(day || today); const list = p.get('featured_days') === '1' ? (d.featured_today || []) : d.featured; return {items: list.map((c, i) => ({...expand(c), featured_score: 100 - i})), total: list.length, ai: Boolean(p.get('featured_days') === '1' ? d.featured_today_ai : d.featured_ai)} }
  const filters = {cat: p.getAll('public_category').filter(Boolean), chans: p.getAll('channel').filter(Boolean), ages: p.getAll('edad').filter(Boolean), langs: p.getAll('idioma').filter(Boolean), format: p.get('format') || '', district: p.get('district') || '', free: p.get('free') === '1', query: fold(p.get('query') || ''),
    hourFrom: p.get('hour_from') ? Number(p.get('hour_from')) : null, hourTo: p.get('hour_to') ? Number(p.get('hour_to')) : null, started: p.get('started') !== '0'};
  const plain = !filters.cat.length && !filters.chans.length && !filters.ages.length && !filters.format && !filters.district && !filters.free && !filters.query && filters.hourFrom === null && filters.hourTo === null && !filters.started;
  const startedCutoff = addDays(today, -7);
  if (day && plain && page === 1 && size <= PAGE) { try { const d = await dayFile(day); return {items: d.items.map(expand), total: d.total, page: 1} } catch (_) {} }
  const all = await loadCatalog(), out = [];
  for (const base of all) {
    let e = base;
    if (day) {
      if (!(e.start <= day && day <= e.end)) continue;
      // Con horario por día, un programa solo sale los días en que hay actividad.
      const byDay = e.start !== e.end ? hoursByDay(e) : null;
      if (byDay && Object.keys(byDay).length && !(day in byDay)) continue;
      e = atDay(e, day);
    } else if (from) {
      if (!(e.start <= to && e.end >= from)) continue;
      // Con horario por día (feria de unos días al mes), solo si alguno de esos días cae en el periodo.
      const byDay = e.start !== e.end ? hoursByDay(e) : null;
      if (byDay && Object.keys(byDay).length) {
        const first = Object.keys(byDay).sort().find(d => from <= d && d <= to);
        if (!first) continue;
        if (!e.occurrences.some(o => from <= o.date && o.date <= to)) { e = {...atDay(e, first), occurrence_date: first}; }
      }
      const inside = e.occurrences.filter(o => from <= o.date && o.date <= to);
      if (inside.length || !e.occurrence_date) e = {...e, occurrence_date: inside[0]?.date || null, time: inside[0]?.time || e.time};
    }
    if (!filters.started && needsSignup(e) && e.start < startedCutoff) continue;  // solo cursos y talleres por sesiones (25-10-2026)
    if (filters.query && !queryMatches(searchText(e), filters.query)) continue;
    if (!catMatch(e, filters.cat) || !chanMatch(e, filters.chans) || !ageMatch(e, filters.ages) || !langMatch(e, filters.langs)) continue;
    if (filters.format && e.format !== filters.format) continue;
    if (filters.free && !e.is_free) continue;
    if (filters.district && e.district !== filters.district) continue;
    if (filters.hourFrom !== null || filters.hourTo !== null) { const hs = hoursOf(e.time); if (!hs.some(h => h >= (filters.hourFrom ?? 0) && h <= (filters.hourTo ?? 23))) continue }
    out.push(e);
  }
  const byTitle = (a, b) => a.title.localeCompare(b.title, 'es', {sensitivity: 'base'});
  if (day) {
    const rank = e => (e.occurrences.some(o => o.date === day) || (shortSpan(e) && e.time)) ? 0 : e.start === e.end && e.end === day ? 1 : e.kind === 'exhibition' ? 2 : e.kind === 'program' ? 3 : 4;
    out.sort((a, b) => { const ra = rank(a), rb = rank(b); if (ra !== rb) return ra - rb; if (ra === 0) { const t = (a.time || '99:99').localeCompare(b.time || '99:99'); if (t) return t } if (ra >= 2) { const d = b.start.localeCompare(a.start); if (d) return d } return byTitle(a, b) });
  } else {
    const rank = e => e.occurrence_date ? 0 : (e.start === e.end || (shortSpan(e) && e.time)) ? 1 : e.kind === 'program' ? 2 : e.kind === 'exhibition' ? 3 : 4;
    const when = e => e.occurrence_date || (e.start > from ? e.start : from);
    const runningBefore = e => !e.occurrence_date && e.start < from;
    out.sort((a, b) => { const ra = runningBefore(a), rb = runningBefore(b); if (ra !== rb) return ra - rb; if (ra) { const d = b.start.localeCompare(a.start); if (d) return d } else { const w = when(a).localeCompare(when(b)); if (w) return w } return rank(a) - rank(b) || byTitle(a, b) });
  }
  return {items: out.slice((page - 1) * size, page * size), total: out.length, page};
}
async function staticDistricts(day) {
  try { return (await dayFile(day)).districts } catch (_) {}
  const all = await loadCatalog(), until = addDays(day, 13), counts = {};
  for (const e of all) if (e.district && e.district !== 'Varios distritos' && e.end >= day && e.start <= until) counts[e.district] = (counts[e.district] || 0) + 1;
  return Object.entries(counts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([name, count]) => ({name, count}));
}
async function staticDetail(source, id, day) {
  const k = `${source}:${id}`, shard = await shardFor(k), e = shard[k];
  if (!e) throw Error('No encontrado');
  // Ficha secundaria de otra (duplicado fusionado, 26-10-2026): se abre la que manda y el guardado pasa a ella.
  if (e.alias_of) {
    if (state.saved.includes(k)) { state.saved = [...new Set(state.saved.map(x => x === k ? e.alias_of : x))]; saveState() }
    const [s, ...rest] = e.alias_of.split(':'); return staticDetail(s, rest.join(':'), day);
  }
  return day ? atDay(e, day) : e;
}
const get = async path => {
  if (!STATIC) return fetchJson(path, {cache: 'no-store'});
  const [route, query] = path.split('?'), p = new URLSearchParams(query || '');
  if (route === '/api/events') return staticEvents(p);
  if (route === '/api/districts') return staticDistricts(p.get('day') || today);
  if (route === '/api/event') return staticDetail(p.get('source'), p.get('id'), p.get('day') || '');
  throw Error('Ruta no disponible en la web estática');
};
const key = e => `${e.source}:${e.id}`;
// Analítica (static/analytics.js, Matomo): si no está cargada, bloqueada o desactivada, no hace nada.
const track = (...args) => { try { window.ontocaAnalytics?.event(...args) } catch (_) {} };
// Versión 2 del estilo (22-10-2026): la misma app en /v2/ con otra hoja de estilo; las direcciones llevan /v2 delante.
const SKIN = document.documentElement.dataset.skin || '', BASE = '';   // la v2 se sirve en la portada (antes en /v2/)
const eventPath = k => { const [source, ...rest] = k.split(':'); return `${BASE}/e/${encodeURIComponent(source)}/${encodeURIComponent(rest.join(':'))}` };
const eventFromPath = () => { const m = location.pathname.match(/^(?:\/v2)?\/e\/([^/]+)\/([^/]+)\/?$/); return m ? `${decodeURIComponent(m[1])}:${decodeURIComponent(m[2])}` : (params.get('evento') || '') };
function labelDate(v) { const d = new Date(v + 'T12:00:00'); return `${d.getDate()} ${months[d.getMonth()]}` }
function labelDay(v) { if (v === today) return t('Hoy'); const d = new Date(v + 'T12:00:00'); return `${weekdays[d.getDay()]} ${d.getDate()} ${months[d.getMonth()]}` }
function timeLabel(e) { return t(e.time_label) || e.time || (e.start !== e.end ? t('Varios días') : t('Hora no indicada')) }
// Sala tocable en la fila (25-10-2026): lleva a sus planes de los próximos 6 meses. Solo si es un sitio concreto.
function rowVenue(e) {
  const site = String(e.venue_names?.[0] || '').split(' · ')[0].trim();
  return site && !MANY_PLACES.test(site) ? `<span class="ev-venue" data-venueq="${esc(site)}" title="${esc(L(`Planes en ${site}`, `Plans a ${site}`, `Plans at ${site}`))}">${esc(venue(e))}</span>` : `<span>${esc(venue(e))}</span>`;
}
// Filtro de festival o fiesta (28-10-2026, David): la Agenda del día con solo sus actos, día a día; si el festival aún no ha
// empezado, su primer día. Nada se pliega ni se esconde dentro del filtro (también la ficha general y lo que no tiene hora).
function goFest(d) {
  hideSheet(); state.detail = null; state.fest = d.fest; state.festName = d.festname || ''; state.festFiesta = d.festfiesta === '1'; state.range = '';
  const from = d.fesfrom || '', to = d.festo || from;
  if (state.day < from || state.day > to) state.day = from > today ? from : today;
  track('filtro', 'festival', state.fest); refresh({scroll: true});
}
function goVenue(site) {
  track('filtro', 'venue', site);
  hideSheet(); state.detail = null; state.query = site; $('searchInput').value = site; state.day = today; state.range = '183'; refresh({scroll: true});
}
function venue(e) { return [e.venue_names?.[0] || e.venues?.[0]?.name, t(e.district)].filter(Boolean).join(' · ') || 'Barcelona' }
// One label per record: the category, then the format when it is not a plain one-off act ("Talleres y experiencias · Cursos").
function catLabel(e) {
  const cat = catName(e.public_category || e.category || '');
  // Sin repetir lo que ya dice la categoría («Talleres y experiencias · Talleres»).
  if (e.format_label && e.format !== 'one_shot' && e.format_label !== 'Actos y funciones' && !fold(cat).includes(fold(t(e.format_label)))) return `${cat} · ${t(e.format_label)}`;
  return cat;
}

// The sheet is a history entry of its own: opening it pushes /e/<source>/<id>,
// so the browser's Back closes the sheet and returns to the list instead of
// leaving the site; Back from a shared link lands on the agenda.
function stateQuery() {
  const p = new URLSearchParams();
  if (state.day !== today) p.set('day', state.day);
  state.cats.forEach(c => p.append('cat', c)); state.chans.forEach(c => p.append('ch', c)); state.ages.forEach(a => p.append('edad', a)); state.langs.forEach(l => p.append('idioma', l)); if (state.format) p.set('format', state.format); if (state.district) p.set('district', state.district);
  if (state.free) p.set('free', '1'); if (state.query) p.set('q', state.query);
  if (state.hourFrom !== null) p.set('from', state.hourFrom); if (state.hourTo !== null) p.set('to', state.hourTo);
  if (state.view !== 'list') p.set('view', state.view); if (state.range) p.set('range', state.range); if (state.started) p.set('started', '1');
  if (state.tab !== 'agenda') p.set('vista', state.tab);
  if (state.fest) { p.set('fest', state.fest); if (state.festName) p.set('festname', state.festName) }
  return p.toString();
}
function syncUrl(push) {
  const q = stateQuery();
  const onLanding = !state.detail && LANDING_Q !== null && q === LANDING_Q;
  const path = state.detail ? eventPath(state.detail) : onLanding ? LANDING.path : BASE + '/', url = onLanding ? path : path + (q ? '?' + q : '');
  if (push) history.pushState({sheet: state.detail, depth: (history.state?.depth || 0) + 1}, '', url); else history.replaceState(history.state, '', url);
}
const detailFromLocation = () => { const m = location.pathname.match(/^(?:\/v2)?\/e\/([^/]+)\/([^/]+)\/?$/); return m ? `${decodeURIComponent(m[1])}:${decodeURIComponent(m[2])}` : '' };
function scrollToId(id) { const el = $(id); if (el) window.scrollTo({top: el.getBoundingClientRect().top + window.scrollY - 84, behavior: 'smooth'}) }
function saveState() { try { localStorage.setItem('brollant-saved', JSON.stringify(state.saved)) } catch (_) {} const c = $('saved').querySelector('.count'); c.textContent = state.saved.length; c.hidden = !state.saved.length }

/* ---------- avisos por correo (alertas/, functions/api/alertas) ---------- */
// Apagados hasta que la publicación los activa (data-alerts="1" y la clave pública de Turnstile).
const ALERTS = document.documentElement.dataset.alerts === '1', TURNSTILE_KEY = document.documentElement.dataset.turnstile || '';
// Los filtros que admite un aviso (los mismos que alertas/lib.js): sin ninguno no se ofrece.
function alertFilters() {
  const f = {cats: state.cats, chans: state.chans, district: state.district || '', free: state.free, q: (state.query || '').trim()};
  return f.cats.length || f.chans.length || f.district || f.free || f.q ? f : null;
}
const alertLabel = f => [...f.cats.map(catName), ...f.chans.map(chanName), f.district ? t(f.district) : '', f.free ? t('Gratis') : '', f.q ? `«${f.q}»` : ''].filter(Boolean).join(' · ');
let turnstileToken = '', turnstileWidget = null;
function loadTurnstile() {
  if (!TURNSTILE_KEY) return;
  const render = () => { try { turnstileWidget = window.turnstile.render('#alertsTurnstile', {sitekey: TURNSTILE_KEY, language: LANG, callback: tok => { turnstileToken = tok }, 'expired-callback': () => { turnstileToken = '' }}) } catch (_) {} };
  if (window.turnstile) { if (turnstileWidget !== null) { try { window.turnstile.reset(turnstileWidget) } catch (_) {} } else render(); return }
  const sc = document.createElement('script'); sc.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'; sc.async = true; sc.onload = render; document.head.append(sc);
}
// Cuándo llegan exactamente los avisos, según la frecuencia elegida (26-10-2026). El primer envío posible se
// calcula en hora de Barcelona como el Worker (alertas/lib.js nextSlot): lunes, o lunes y jueves, a las 8:00.
function nextAlertDay(freq) {
  const days = freq === 'semanal' ? [1] : [1, 4], now = new Date();
  const part = (d, o) => new Intl.DateTimeFormat('en-GB', {timeZone: 'Europe/Madrid', ...o}).format(d);
  for (let ahead = 0; ahead < 9; ahead++) {
    const d = new Date(now.getTime() + ahead * 86400e3), wd = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].indexOf(part(d, {weekday: 'short'}));
    if (!days.includes(wd)) continue;
    if (ahead === 0 && Number(part(now, {hour: '2-digit', hourCycle: 'h23'})) >= 8) continue;
    return d.toLocaleDateString(LANG === 'en' ? 'en-GB' : LANG === 'ca' ? 'ca-ES' : 'es-ES', {timeZone: 'Europe/Madrid', weekday: 'long', day: 'numeric', month: 'long'});
  }
  return '';
}
function alertsWhen() {
  const el = $('alertsWhen'); if (!el) return;
  const freq = document.querySelector('input[name="alertsFreq"]:checked')?.value || 'bisemanal', next = nextAlertDay(freq);
  const days = freq === 'semanal' ? L('los lunes', 'els dilluns', 'on Mondays') : L('los lunes y los jueves', 'els dilluns i els dijous', 'on Mondays and Thursdays');
  el.innerHTML = L(`<b>Cuándo llegan:</b> ${days}, a partir de las 8:00 (hora de Barcelona), y solo si hay planes nuevos; si no, ese día no te escribimos.<br><b>Qué incluyen:</b> solo los planes que entren en la agenda después de confirmar el aviso.${next ? `<br><b>Primer aviso posible:</b> ${next}.` : ''}`,
    `<b>Quan arriben:</b> ${days}, a partir de les 8:00 (hora de Barcelona), i només si hi ha plans nous; si no, aquell dia no t'escrivim.<br><b>Què inclouen:</b> només els plans que entrin a l'agenda després de confirmar l'avís.${next ? `<br><b>Primer avís possible:</b> ${next}.` : ''}`,
    `<b>When:</b> ${days}, from 8:00 (Barcelona time), only if there are new plans; otherwise we don't write.<br><b>What:</b> only plans added to the listings after you confirm.${next ? `<br><b>First possible alert:</b> ${next}.` : ''}`);
}
function openAlerts() {
  const f = alertFilters(); if (!f) return;
  let dlg = $('alertsDialog');
  if (!dlg) {
    dlg = document.createElement('dialog'); dlg.id = 'alertsDialog'; dlg.className = 'alerts-dialog'; dlg.setAttribute('aria-labelledby', 'alertsTitle');
    dlg.innerHTML = `<form id="alertsForm" method="dialog" novalidate>
<div class="alerts-head"><h2 id="alertsTitle">${L('Avisos de novedades', 'Avisos de novetats', 'Email alerts')}</h2><button type="button" class="alerts-close" data-alerts="close" aria-label="${L('Cerrar', 'Tanca', 'Close')}">✕</button></div>
<p class="alerts-lead">${L('Te escribimos solo cuando aparezcan planes nuevos para esta búsqueda:', 'T\'escrivim només quan apareguin plans nous per a aquesta cerca:', 'We only write when new plans appear for this search:')}</p>
<p class="alerts-search" id="alertsSearch"></p>
<label class="alerts-field" for="alertsEmail">${L('Tu correo', 'El teu correu', 'Your email')}</label>
<input id="alertsEmail" type="email" autocomplete="email" required inputmode="email">
<fieldset class="alerts-freq"><legend>${L('¿Cada cuánto?', 'Cada quan?', 'How often?')}</legend>
<label><input type="radio" name="alertsFreq" value="bisemanal" checked> ${L('Lunes y jueves, a las 8:00', 'Dilluns i dijous, a les 8:00', 'Mondays and Thursdays, 8:00')}</label>
<label><input type="radio" name="alertsFreq" value="semanal"> ${L('Solo los lunes, a las 8:00', 'Només els dilluns, a les 8:00', 'Mondays only, 8:00')}</label></fieldset>
<p class="alerts-when" id="alertsWhen"></p>
<label class="alerts-privacy"><input id="alertsPrivacy" type="checkbox" required> <span>${L('Acepto la <a href="/privacidad" target="_blank" rel="noopener">política de privacidad</a>. Puedes darte de baja en cada correo.', 'Accepto la <a href="/privacidad" target="_blank" rel="noopener">política de privacitat</a>. Et pots donar de baixa a cada correu.', 'I accept the <a href="/privacidad" target="_blank" rel="noopener">privacy policy</a>. You can unsubscribe in every email.')}</span></label>
<div id="alertsTurnstile" class="alerts-turnstile"></div>
<p id="alertsMsg" class="alerts-msg" role="status" aria-live="polite"></p>
<button id="alertsSend" class="alerts-send" type="submit">${L('Quiero los avisos', 'Vull els avisos', 'Send me alerts')}</button></form>`;
    document.body.append(dlg);
    dlg.addEventListener('click', ev => { if (ev.target === dlg || ev.target.closest('[data-alerts="close"]')) dlg.close() });
    $('alertsForm').addEventListener('submit', sendAlerts);
    dlg.querySelectorAll('input[name="alertsFreq"]').forEach(r => r.addEventListener('change', alertsWhen));
  }
  alertsWhen();
  $('alertsSearch').textContent = alertLabel(f); $('alertsMsg').textContent = ''; $('alertsMsg').className = 'alerts-msg';
  $('alertsSend').disabled = false; $('alertsForm').hidden = false;
  dlg.showModal(); $('alertsEmail').focus(); loadTurnstile();
}
async function sendAlerts(ev) {
  ev.preventDefault();
  const f = alertFilters(), msg = $('alertsMsg'), btn = $('alertsSend'), email = $('alertsEmail').value.trim();
  const fail = text => { msg.textContent = text; msg.className = 'alerts-msg is-error'; btn.disabled = false };
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return fail(L('Revisa el correo electrónico.', 'Revisa el correu electrònic.', 'Please check your email address.'));
  if (!$('alertsPrivacy').checked) return fail(L('Tienes que aceptar la política de privacidad.', 'Has d\'acceptar la política de privacitat.', 'Please accept the privacy policy.'));
  if (TURNSTILE_KEY && !turnstileToken) return fail(L('Espera un momento a que termine la comprobación antirrobots.', 'Espera un moment que acabi la comprovació antirobots.', 'Please wait for the bot check to finish.'));
  btn.disabled = true; msg.textContent = L('Enviando…', 'Enviant…', 'Sending…'); msg.className = 'alerts-msg';
  try {
    const r = await fetch('/api/alertas/alta', {method: 'POST', headers: {'content-type': 'application/json'},
      body: JSON.stringify({email, freq: document.querySelector('input[name="alertsFreq"]:checked')?.value || 'bisemanal', filters: f, privacy: true, turnstile: turnstileToken})});
    const d = await r.json().catch(() => ({}));
    // Sin JSON (un bloqueo de seguridad de Cloudflare, un error del servidor): se dice el código para poder saber qué pasó.
    if (!r.ok || !d.ok) { turnstileToken = ''; loadTurnstile(); return fail(d.error || `${L('No se ha podido guardar. Prueba más tarde.', 'No s\'ha pogut desar. Prova-ho més tard.', 'Could not save. Please try later.')} (${r.status})`) }
    msg.textContent = L('Listo. Te hemos enviado un correo: confírmalo para empezar a recibir los avisos.', 'Fet. T\'hem enviat un correu: confirma\'l per començar a rebre els avisos.', 'Done. We have sent you an email: confirm it to start getting alerts.');
    msg.className = 'alerts-msg is-ok';
  } catch (_) { fail(L('Sin conexión. Prueba otra vez.', 'Sense connexió. Torna-ho a provar.', 'No connection. Please try again.')) }
}

/* ---------- filters panel ---------- */
function activeFilterList() {
  const out = [];
  if (state.query) out.push({k: 'query', label: `“${state.query}”`});
  if (state.cats.length) out.push({k: 'cat', label: state.cats.map(catName).join(' + ')});
  if (state.chans.length) out.push({k: 'ch', label: state.chans.map(chanName).join(' + ')});
  if (state.langs.length) out.push({k: 'idioma', label: state.langs.map(l => byLang(ACT_LANGS[l])).join(' + ')});
  if (state.ages.length) out.push({k: 'edad', label: state.ages.map(a => byLang(AGE_LABEL[a])).join(' + ')});
  if (state.format) out.push({k: 'format', label: t(FORMATS[state.format] || state.format)});
  if (state.free) out.push({k: 'free', label: t('Gratis')});
  if (state.hourFrom !== null || state.hourTo !== null) out.push({k: 'hours', label: `${hourLabel(state.hourFrom ?? 0)}–${hourLabel(state.hourTo ?? 23)}`});
  if (state.district) out.push({k: 'district', label: t(state.district)});
  if (state.started) out.push({k: 'started', label: t('Con cursos ya empezados')});
  if (state.range) out.push({k: 'range', label: RANGE_LABELS[state.range] || state.range});
  if (state.fest) out.push({k: 'fest', label: `${festKind({festival: {fiesta: state.festFiesta}})} · ${state.festName || state.fest}`});
  return out;
}
function clearFilter(k) {
  if (k === 'range') state.range = '';
  if (k === 'query') { state.query = ''; $('searchInput').value = '' }
  if (k === 'cat') state.cats = []; if (k === 'ch') { state.chans = []; state.ages = [] } if (k === 'edad') state.ages = []; if (k === 'idioma') state.langs = []; if (k === 'format') state.format = ''; if (k === 'free') state.free = false;
  if (k === 'hours') { state.hourFrom = null; state.hourTo = null } if (k === 'district') state.district = '';
  if (k === 'started') state.started = false
  if (k === 'fest') { state.fest = ''; state.festName = ''; state.festFiesta = false }
}
function renderActive() {
  const list = activeFilterList(), shown = list.filter(f => f.k !== 'range');   // el periodo ya se ve en «Cuándo» (calendario y celda del móvil)
  $('activeFilters').innerHTML = shown.map(f => `<button class="active-chip" type="button" data-clear="${esc(f.k)}" aria-label="${t('Quitar filtro')} ${esc(f.label)}">${esc(f.label)} <span aria-hidden="true">✕</span></button>`).join('') + (shown.length > 1 ? `<button class="linklike" type="button" data-clear="all">${t('Limpiar todo')}</button>` : '');
  if (ALERTS && alertFilters()) $('activeFilters').insertAdjacentHTML('beforeend', `<button class="alert-cta" type="button" data-alerts="open"><svg aria-hidden="true" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"></path><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"></path></svg>${L('Avísame de novedades', 'Avisa\'m de novetats', 'Email me what\'s new')}</button>`);
  // «Más filtros» cuenta solo lo que se elige dentro: el periodo, la búsqueda y la categoría ya se ven fuera (28-10-2026)
  const n = list.filter(f => !['range', 'query', 'cat'].includes(f.k)).length; const badge = $('filterCount'); badge.hidden = !n; badge.textContent = n;
  $('openFilters').classList.toggle('has-filters', n > 0);
}
function chips() {
  // La categoría se elige en la barra rápida de encima de la lista (23-10-2026): fuera de la columna de filtros.
  const catGroup = $('categories')?.closest('fieldset'); if (catGroup) catGroup.hidden = true;
  $('categories').innerHTML = [`<button class="filter-chip ${state.cats.length ? '' : 'active'}" type="button" data-category="" aria-pressed="${!state.cats.length}">${t('Todo')}</button>`]
    .concat(Object.keys(CATS).map(c => `<button class="filter-chip ${state.cats.includes(c) ? 'active' : ''}" type="button" data-category="${esc(c)}" aria-pressed="${state.cats.includes(c)}">${esc(catName(c))}</button>`)).join('');
  // Franjas de edad: solo con «En familia» activo.
  const fam = state.chans.includes('familia'); if (!fam) state.ages = [];
  $('ages').hidden = !fam;
  $('ages').innerHTML = fam ? Object.keys(AGE_BANDS).map(a => `<button class="age-chip${a === 'nd' ? ' age-nd' : ''} ${state.ages.includes(a) ? 'active' : ''}" type="button" data-age="${a}" aria-pressed="${state.ages.includes(a)}">${esc(byLang(AGE_LABEL[a]))}</button>`).join('') : '';
  $('channels').innerHTML = Object.keys(CHANS).map(c => `<button class="channel-chip ch-${c} ${state.chans.includes(c) ? 'active' : ''}" type="button" data-channel="${esc(c)}" aria-pressed="${state.chans.includes(c)}">${esc(chanName(c))}</button>`).join('');
  if ($('actLangs')) $('actLangs').innerHTML = Object.keys(ACT_LANGS).map(l => `<button class="channel-chip ${state.langs.includes(l) ? 'active' : ''}" type="button" data-actlang="${l}" aria-pressed="${state.langs.includes(l)}">${esc(byLang(ACT_LANGS[l]))}</button>`).join('');
  $('formatFilter').value = state.format; $('freeOnly').checked = state.free; $('searchInput').value = state.query;
  ['List','Map','Venue'].forEach(v => $('view' + v).setAttribute('aria-pressed', String(state.view === v.toLowerCase())));
}
function hourLabel(h) { return String(h).padStart(2, '0') + ':00' }
function hours() {
  const from = state.hourFrom ?? 0, to = state.hourTo ?? 23, active = state.hourFrom !== null || state.hourTo !== null;
  $('hourFrom').value = from; $('hourTo').value = to; $('hourFromLabel').textContent = hourLabel(from); $('hourToLabel').textContent = hourLabel(to); $('hourLabel').textContent = active ? `${hourLabel(from)} — ${hourLabel(to)}` : t('Cualquier hora'); $('clearHours').hidden = !active;
  document.querySelectorAll('#hourPresets [data-hours]').forEach(b => b.setAttribute('aria-pressed', String(active && b.dataset.hours === `${from}-${to}`)));
}
function hourMatches(e) {
  if (state.hourFrom === null && state.hourTo === null) return true;
  const hs = String(e.time || '').match(/\b(?:[01]\d|2[0-3]):[0-5]\d\b/g) || [];
  return hs.some(v => { const h = Number(v.slice(0, 2)); return h >= (state.hourFrom ?? 0) && h <= (state.hourTo ?? 23) });
}
function openDrawer(open) {
  const panel = $('filters'); panel.classList.toggle('open', open); $('drawerBackdrop').hidden = !open; $('openFilters').setAttribute('aria-expanded', String(open)); $('whenOpen')?.setAttribute('aria-expanded', String(open && Boolean(state.whenEntry)));
  document.body.classList.toggle('drawer-open', open);
  if (open) $('closeFilters').focus(); else $('openFilters').focus();
}

/* ---------- days ---------- */
function days() {
  // «Cuándo» (28-10-2026, David): «Hoy | Elegir día ▾ | Periodo ▾». «Elegir día» abre el carrusel de días de siempre (fines de
  // semana en color) con «Otra fecha» al final; «Periodo», la lista de fin de semana, 7 días, 30 días y 6 meses.
  const host = $('days'), other = $('pickDate'); host.innerHTML = '';
  const win = rangeWindow();
  for (let i = 0; i < 28; i++) {
    const d = new Date(today + 'T12:00:00'); d.setDate(d.getDate() + i); const value = iso(d), b = document.createElement('button');
    const weekend = d.getDay() === 0 || d.getDay() === 6;
    b.type = 'button'; b.className = 'day' + (value === state.day && !win ? ' active' : '') + (weekend ? ' weekend' : ''); b.dataset.day = value; b.setAttribute('role', 'tab'); b.setAttribute('aria-selected', String(value === state.day && !win));
    b.innerHTML = `<span>${i ? weekdays[d.getDay()] : t('Hoy')}</span><b>${d.getDate()}</b><small>${months[d.getMonth()]}</small>`; host.append(b);
  }
  if (other) host.append(other);
  const mode = win ? 'period' : state.day === today ? 'today' : 'day';
  if (state.dayOpen === undefined) state.dayOpen = mode === 'day';   // al llegar con un día concreto, el carrusel abierto
  const panel = $('daysPanel'); panel.hidden = !state.dayOpen;
  if (state.dayOpen) { const active = host.querySelector('.day.active'); if (active) host.scrollLeft = Math.max(0, active.offsetLeft - host.offsetLeft - 8) }
  const set = (id, on) => { const b = $(id); b.classList.toggle('active', on); b.setAttribute('aria-pressed', String(on)) };
  set('whenToday', mode === 'today'); set('whenDay', mode === 'day'); set('whenPeriod', mode === 'period');
  $('whenDay').setAttribute('aria-expanded', String(Boolean(state.dayOpen)));
  $('whenDayLabel').textContent = mode === 'day' ? labelDay(state.day).replace(/^./, c => c.toUpperCase()) : t('Elegir día');
  const r = state.range || (state.query ? 'all' : '');
  $('whenPeriodLabel').textContent = mode === 'period' ? (PERIOD_SHORT[r] ? byLang(PERIOD_SHORT[r]) : win.label) : t('Periodo');
  $('pickDateLabel').textContent = mode === 'day' && state.day > addDays(today, 27) ? labelDate(state.day) : t('Otra fecha');
  const picker = $('dayPicker'); picker.min = today; picker.max = addDays(today, MAX_DAYS); picker.value = win ? '' : state.day;
  // Móvil (29-10-2026, opción B1): la celda «Cuándo» dice lo que se ve y abre el panel de filtros por el calendario
  const wl = $('whenOpenLabel');
  if (wl) { const d = new Date(state.day + 'T12:00:00'), short = `${weekdays[d.getDay()]} ${d.getDate()} ${months[d.getMonth()]}`;
    wl.textContent = mode === 'period' ? `${PERIOD_SHORT[r] ? byLang(PERIOD_SHORT[r]) : win.label}${r === 'all' ? '' : ` · ${labelDate(win.from)}–${labelDate(win.to)}`}` : mode === 'today' ? `${t('Hoy')}, ${short}` : short.replace(/^./, c => c.toUpperCase()) }
  deskWhen();
}
const PERIOD_SHORT = {finde: ['Finde', 'Cap de set.', 'Weekend'], '7': ['7 días', '7 dies', '7 days'], '30': ['30 días', '30 dies', '30 days'], '90': ['3 meses', '3 mesos', '3 months'], '183': ['6 meses', '6 mesos', '6 months'], all: ['Todo', 'Tot', 'All']};
// Si se entró por la celda «Cuándo» del móvil, al elegir día o periodo se cierra el panel y se ve la lista
function whenDone() { if (state.whenEntry && !DESK.matches && $('filters').classList.contains('open')) { state.whenEntry = false; openDrawer(false); scrollToId('agenda') } }
// Carrusel de categorías: la flecha del borde desaparece al llegar al final
document.addEventListener('scroll', e => { const bar = e.target; if (bar?.classList?.contains('cat-bar')) bar.parentElement?.classList.toggle('at-end', bar.scrollLeft + bar.clientWidth >= bar.scrollWidth - 4) }, true);
function periodMenu(open) {
  const menu = $('periodMenu'), btn = $('whenPeriod');
  if (open) {
    const span = (from, to) => `${labelDate(from)} – ${labelDate(to)}`;
    const wd = (new Date(today + 'T12:00:00').getDay() + 6) % 7, fFrom = wd < 4 ? addDays(today, 4 - wd) : today, fTo = addDays(today, 6 - wd);
    const items = [['finde', t('Fin de semana'), `${labelDay(fFrom)} – ${labelDay(fTo)}`], ['7', t('7 días'), span(today, addDays(today, 7))], ['30', t('30 días'), span(today, addDays(today, 30))], ['183', t('6 meses'), span(today, addDays(today, 183))]];
    menu.innerHTML = items.map(([k, label, range]) => `<button type="button" data-period="${k}" aria-pressed="${state.range === k}"><b>${esc(label)}</b><small>${esc(range)}</small></button>`).join('');
  }
  menu.hidden = !open; btn.setAttribute('aria-expanded', String(open));
}
document.addEventListener('click', e => { if (!$('periodMenu').hidden && !e.target.closest('.when-pop')) periodMenu(false) });

/* ---------- escritorio (29-10-2026, David, variante B1) ----------
   A partir de 961 px: la columna de filtros arranca bajo la Selección con «Cuándo» (periodos y un calendario de cinco
   semanas, fines de semana en coral) y «Dónde» («Cerca de mí» y distrito); sobre la agenda, el buscador, «Qué» como
   pestañas, el título de lo que se ve con Lista/Mapa/Por sitio y, pegadas a la lista, Agenda/Expos. Son los mismos
   controles del móvil, recolocados: al volver a móvil regresan a su sitio. */
const DESK = matchMedia('(min-width: 961px)');
const deskMarks = {};
function deskLayout() {
  // «Cerca de mí» va siempre en «Dónde» del panel de filtros (29-10-2026, David: en móvil también, opción B1)
  const moves = [['searchForm', 'deskTop'], ['typeMini', 'deskTop'], ['nearBox', 'deskNear', true], ['viewSeg', 'deskView']];
  for (const [id, slot, always] of moves) {
    const el = $(id), to = $(slot); if (!el || !to) continue;
    if (!deskMarks[id]) { deskMarks[id] = document.createComment(id); el.before(deskMarks[id]) }
    if (DESK.matches || always) { if (el.parentElement !== to) to.append(el) } else if (el.previousSibling !== deskMarks[id]) deskMarks[id].after(el);
  }
  deskWhen();
}
function deskWhen() {
  const host = $('deskWhen'); if (!host) return;   // también en el panel de filtros del móvil (29-10-2026)
  const win = rangeWindow(), r = state.range || '';
  const chips = [['today', t('Hoy')], ['finde', byLang(PERIOD_SHORT.finde)], ['7', byLang(PERIOD_SHORT['7'])], ['30', byLang(PERIOD_SHORT['30'])], ['183', byLang(PERIOD_SHORT['183'])]];
  const on = k => k === 'today' ? !win && state.day === today : r === k;
  const wd = (new Date(today + 'T12:00:00').getDay() + 6) % 7, first = addDays(today, -wd), last = addDays(today, MAX_DAYS);
  const focus = win ? win.from : state.day;   // que se vea el día o el periodo elegido
  const weeksTo = Math.floor((new Date(focus + 'T12:00:00') - new Date(first + 'T12:00:00')) / 6048e5);
  if (state.calOff === undefined || (!state.calKeep && (weeksTo < state.calOff || weeksTo > state.calOff + 4))) state.calOff = Math.max(0, weeksTo - 1);
  const start = addDays(first, state.calOff * 7), end = addDays(start, 34);
  const md = v => { const d = new Date(v + 'T12:00:00'); return months[d.getMonth()] };
  const dows = L('L M X J V S D', 'Dl Dt Dc Dj Dv Ds Dg', 'M T W T F S S').split(' ');
  let cells = '';
  for (let i = 0; i < 35; i++) {
    const v = addDays(start, i), n = Number(v.slice(8, 10));
    if (v < today || v > last) { cells += `<span class="dw-day out">${n}</span>`; continue }
    const sel = win ? Boolean(state.range) && v >= win.from && v <= win.to : v === state.day;   // una búsqueda sin periodo no pinta todo el calendario
    cells += `<button type="button" class="dw-day${i % 7 >= 5 ? ' we' : ''}${sel ? ' on' : ''}${v === today ? ' today' : ''}" data-day="${v}" aria-pressed="${sel}" aria-label="${esc(labelDay(v))}">${n}</button>`;
  }
  host.innerHTML = `<span class="dw-title">${t('Cuándo')}</span><div class="dw-periods">${chips.map(([k, label]) => `<button type="button" data-period="${k}" aria-pressed="${on(k)}">${esc(label)}</button>`).join('')}</div>`
    + `<div class="dw-nav"><button type="button" data-calnav="-1" aria-label="${L('Semanas anteriores', 'Setmanes anteriors', 'Previous weeks')}"${state.calOff ? '' : ' disabled'}>‹</button><b>${md(start) === md(end) ? md(start) : `${md(start)} – ${md(end)}`}</b><button type="button" data-calnav="1" aria-label="${L('Semanas siguientes', 'Setmanes següents', 'Next weeks')}">›</button></div>`
    + `<div class="dw-grid">${dows.map(d => `<span class="dw-dow">${d}</span>`).join('')}${cells}</div>`;
  const title = $('deskTitle');
  if (title) {
    const d = new Date(state.day + 'T12:00:00'), day = `${weekdaysLong[d.getDay()]} ${d.getDate()} ${months[d.getMonth()]}`;
    title.textContent = state.query ? `«${state.query}»` : win ? `${win.label} · ${labelDate(win.from)} – ${labelDate(win.to)}` : state.day === today ? `${t('Hoy')}, ${day}` : day.replace(/^./, c => c.toUpperCase());
  }
}
DESK.addEventListener('change', () => { deskLayout(); requestAnimationFrame(stick) });

/* ---------- selection ---------- */
function pick(e, i) {
  const d = new Date((e.featured_date || e.start) + 'T12:00:00'), free = e.is_free ? `<span class="free">${t('Gratis')}</span>` : '';
  const c = e.public_category || e.category || '', meta = esc(CAT_SHORT[c] ? byLang(CAT_SHORT[c]) : catLabel(e));   // la misma palabra que las fichas de tipo (28-10-2026, David)
  const image = e.media?.[0] ? `<img class="pick-media" src="${esc(e.media[0].url)}" alt="${esc(e.media[0].alt || e.title)}" loading="lazy">` : '<div class="pick-media pick-placeholder" aria-hidden="true"></div>';
  return `<button class="pick-small" type="button" data-open="${esc(key(e))}" data-cat="${esc(e.public_category || e.category || '')}">${image}<span class="pick-meta">${meta}</span>${free}<div><div class="pick-date">${e.kind === 'exhibition' && e.end ? `${L('Hasta el', 'Fins al', 'Until')} ${Number(e.end.slice(8, 10))} ${months[Number(e.end.slice(5, 7)) - 1]}${e.end.slice(0, 4) !== state.day.slice(0, 4) ? ' ' + e.end.slice(0, 4) : ''}` : `${weekdays[d.getDay()]} ${d.getDate()} ${months[d.getMonth()]}${e.time ? ' · ' + esc(e.time) : ''}`}</div><h3 class="pick-title">${esc(e.title)}</h3><p class="pick-summary">${esc((e.summary || '').slice(0, 190))}</p><p class="place">${esc(venue(e))}</p></div></button>`;
}
// «Selección Ontoca» (28-10-2026, David): coherente con el día que se mira. Por defecto, «Hoy» mientras queden al menos
// tres planes destacados de ese día; si no, los próximos 7 días. Nunca lo que ya ha pasado ni títulos de promoción;
// como mucho dos de la misma categoría (si hay con qué llenar) y en orden de fecha y hora.
async function selection() {
  try {
    const now = madridNow();
    // «Lo mejor del fin de semana» (28-10-2026, David): con el periodo Fin de semana, la selección de 7 días del primer día
    // del periodo, solo con lo que cae dentro; sin el conmutador Hoy / 7 días. Con 7 días, 30 días o 6 meses: la de 7 días.
    const win = rangeWindow(), finde = state.range === 'finde' && win, pickDay = finde ? win.from : state.day;
    const fetchPicks = async one => get('/api/events?' + new URLSearchParams({day: pickDay, featured: '1', page_size: '30', public: '1', ...(one ? {featured_days: '1'} : {})}));
    const when = e => e.featured_date || e.start;
    const past = e => when(e) < now.day || (when(e) === now.day && e.time && (minutesOf(String(e.time).padStart(5, '0')) ?? 1e4) < now.min - GRACE);
    const usable = d => d.items.filter(e => !past(e) && !e.promo && !PROMO_TITLE.test(e.title || '') && (!finde || when(e) <= win.to));
    let one = !win && state.pickRange === 'today', d = await fetchPicks(one), list = usable(d);
    if (!win && state.pickRange === 'auto') {
      one = true; d = await fetchPicks(true); list = usable(d);
      if (list.length < 3) { one = false; d = await fetchPicks(false); list = usable(d) }
    }
    const rangeBox = document.querySelector('.pick-range'); if (rangeBox) rangeBox.hidden = Boolean(win);
    document.querySelectorAll('[data-pickrange]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.pickrange === (one ? 'today' : 'week'))));
    // Elegida por la IA (src/ai_select.py): se respeta su orden de preferencia. Si no, las reglas, con imagen y texto primero.
    const complete = list.filter(e => e.media?.length && e.has_description);
    const ranked = d.ai ? list : complete.concat(list.filter(e => !complete.includes(e) && (e.media?.length || e.has_description)));
    // Una semana tiene más donde elegir (28-10-2026, David): «Todo» 10 y cada tipo 8; un día, 7 y 6.
    const size = one ? 7 : 10, perType = one ? 6 : 8;
    // Con IA (28-10-2026): se respeta su elección (ya viene variada, hasta 3 por categoría); sin IA, las reglas con 2 por
    // categoría. En los dos casos, nunca dos del mismo festival, ciclo u obra.
    const chosen = [], perCat = {}, works = new Set(), cap = d.ai ? 3 : 2, work = e => e.festival?.slug || e.series || fold(e.title);
    for (const e of ranked) { const c = e.public_category || ''; if ((perCat[c] || 0) < cap && !works.has(work(e))) { chosen.push(e); perCat[c] = (perCat[c] || 0) + 1; works.add(work(e)) } if (chosen.length === size) break }
    for (const e of ranked) { if (chosen.length >= size) break; if (!chosen.includes(e) && !works.has(work(e))) { chosen.push(e); works.add(work(e)) } }
    const byTime = (a, b) => when(a).localeCompare(when(b)) || String(a.time || '99').localeCompare(String(b.time || '99'));
    // Por tipo (28-10-2026, David): los mejor puntuados de cada categoría con las mismas reglas; el tipo sale con 3 o más
    // planes y enseña hasta 6. «Todo» es la selección de siempre. Un tipo elegido se mantiene al cambiar de día si ese día
    // tiene bastantes; si no, vuelve a «Todo».
    const pf = await picksFile(pickDay), groups = {};
    for (const [c, list] of Object.entries((pf && pf[one ? 't' : 'w']) || {})) {
      const ok = usable({items: list.map(expand)}).slice(0, perType);
      if (ok.length >= 3) groups[c] = ok;
    }
    // «Expos» (28-10-2026, David): las del ranking de la pestaña Expos de ese día, en su orden; las mismas que esa lista marca.
    const expos = ((pf && pf.x) || []).map(expand).filter(e => e.end >= state.day).slice(0, perType);
    if (expos.length >= 3) groups.expos = expos;
    // Tipos de la Selección (28-10-2026, 19:34, David): una fila dentro de la propia Selección que solo la filtra a ella
    // (la Agenda tiene la suya, fija bajo «Filtros»). «Todo», las categorías con 3 o más planes y «Expos».
    if (state.pickCat && !groups[state.pickCat]) state.pickCat = '';
    const cats = Object.keys(CATS).filter(c => groups[c]);
    if (groups.expos) cats.splice(cats.includes('arte') ? cats.indexOf('arte') + 1 : Math.min(cats.length, 4), 0, 'expos');
    const bar = $('pickCats');
    if (bar) {
      bar.hidden = !cats.length;
      bar.innerHTML = cats.length ? `<div class="cat-bar">${[['', t('Todo')], ...cats.map(c => [c, c === 'expos' ? L('Expos', 'Expos', 'Exhibitions') : byLang(CAT_SHORT[c] || CATS[c])])]
        .map(([c, label]) => `<button class="cat-pill${state.pickCat === c ? ' on' : ''}" type="button" data-pickcat="${c}" aria-pressed="${state.pickCat === c}"${c ? ` data-category-color="${c === 'expos' ? 'arte' : c}"` : ''}>${c ? '<i aria-hidden="true"></i>' : ''}${esc(label)}</button>`).join('')}</div>` : '';
      const on = bar.querySelector('.on'), row = bar.querySelector('.cat-bar');
      if (on && row) { const r = on.getBoundingClientRect(), box = row.getBoundingClientRect(); if (r.right > box.right - 24 || r.left < box.left) row.scrollLeft += r.left - box.left - 16 }
    }
    const want = state.pickCat, sel = want ? groups[want] || [] : chosen;
    const items = want === 'expos' ? sel : sel.slice().sort(byTime);
    const end = new Date(pickDay + 'T12:00:00'); end.setDate(end.getDate() + 6);
    $('weekRange').textContent = finde ? `${L('Lo mejor del fin de semana', 'El millor del cap de setmana', 'The best of the weekend')} · ${labelDate(win.from)} – ${labelDate(win.to)}` : win ? `${labelDate(pickDay)} – ${labelDate(iso(end))}` : one ? labelDate(state.day) : `${labelDate(state.day)} – ${labelDate(iso(end))}`;
    $('curated').innerHTML = items.map(pick).join('') || `<div class="empty">${one ? L('Hoy no hay actividades destacadas. Mira los próximos 7 días.', 'Avui no hi ha activitats destacades. Mira els propers 7 dies.', 'No featured activities today. See the next 7 days.') : t('Aún no hay actividades destacadas para estas fechas.')}</div>`;
    $('curated').scrollLeft = 0; pickNav();
  } catch (_) { $('curated').innerHTML = `<div class="empty">${t('No se pudo cargar la selección.')}</div>`; pickNav() }
}
// Carrusel de la Selección (28-10-2026, David): también en escritorio, todas las fichas iguales. Flechas y «1–4 de 7» en
// escritorio; en móvil se desliza con el dedo. Sin paso automático.
function pickNav() {
  const box = $('curated'), cards = box ? [...box.querySelectorAll('button[data-open]')] : [];
  const nav = document.querySelector('.pick-nav'); if (!nav) return;
  if (!cards.length) { nav.hidden = true; return }
  const step = cards.length > 1 ? cards[1].offsetLeft - cards[0].offsetLeft : cards[0].offsetWidth;
  const first = Math.round(box.scrollLeft / (step || 1)), shown = Math.max(1, Math.floor((box.clientWidth + 8) / (step || 1)));
  const last = Math.min(cards.length, first + shown);
  nav.hidden = cards.length <= shown;
  $('pickCount').textContent = `${first + 1}–${last} ${L('de', 'de', 'of')} ${cards.length}`;
  $('pickPrev').disabled = first <= 0; $('pickNext').disabled = last >= cards.length;
}
function pickScroll(dir) {
  const box = $('curated'), cards = box.querySelectorAll('button[data-open]');
  const step = cards.length > 1 ? cards[1].offsetLeft - cards[0].offsetLeft : box.clientWidth;
  box.scrollBy({left: dir * step, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
}

/* ---------- agenda (v3: una sola línea de tiempo) ----------
   Cada ficha se clasifica para el día mirado en un tipo de disponibilidad:
     timed   → «Empiezan a una hora»: hora de inicio de ese día, o temporada/obra con hora propia
               (si la fuente da varias horas de temporada sin decir cuál toca hoy, se coloca en el
               próximo pase y se avisa «confirma el de hoy»)
     wide    → «Horario amplio»: exposiciones, ferias y espacios abiertos 4 h o más
     tbc     → «Hora por confirmar»: pasa ese día (o está en cartel) pero la fuente no da la hora
     (cursos y talleres de más de una semana: el día que empiezan, en la agenda a su hora con «curso
      hasta el…»; antes de ese día no salen; ya no hay bloque «empiezan pronto», 26-10-2026)
     started → talleres y cursos ya en marcha: solo con el filtro «Incluir talleres y cursos ya empezados»
   Los botones de arriba muestran u ocultan cada tipo (por defecto: hora fija y por confirmar);
   cada botón lleva su número, así nada queda oculto sin que se pueda recuperar.
   Color = tipo: violeta (hora fija, punto), turquesa (horario amplio, barra), gris discontinuo
   (por confirmar); ámbar solo para lo inmediato (ahora, en 20 min, cierra pronto, último día). */
// Textos en tres idiomas (23-10-2026: inglés): L(castellano, catalán, inglés).
const L = (es, ca, en) => LANG === 'ca' ? ca : LANG === 'en' ? (en ?? es) : es;
const TZ = 'Europe/Madrid', GRACE = 15, SOON = 60, WIDE_MIN = 240, SHORT_DAYS = 7, COURSE_AHEAD = 30, STEP = 60, PER_DAY = 10, DAY_CHUNK = 7;   // PER_DAY 15 → 10 (28-10-2026, David)
const weekdaysLong = LANG === 'en' ? ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'] : LANG === 'ca' ? ['diumenge','dilluns','dimarts','dimecres','dijous','divendres','dissabte'] : ['domingo','lunes','martes','miércoles','jueves','viernes','sábado'];
function madridNow() {
  const parts = new Intl.DateTimeFormat('en-CA', {timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'}).formatToParts(new Date());
  const g = k => parts.find(x => x.type === k).value;
  return {day: `${g('year')}-${g('month')}-${g('day')}`, min: Number(g('hour')) * 60 + Number(g('minute'))};
}
const clock = m => `${String(Math.floor(m / 60) % 24).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
const minutesOf = s => { const m = /^(\d{1,2}):(\d{2})$/.exec(s || ''); return m ? Number(m[1]) * 60 + Number(m[2]) : null };
function timesIn(s) { return [...new Set((String(s || '').match(/\b(?:[01]?\d|2[0-3]):[0-5]\d\b/g) || []).map(x => x.padStart(5, '0')))].sort() }
// Todos los tramos del día («10:00–13:00 · 16:00–19:00»): abre con el primero, cierra con el último,
// y entre medias está cerrado (ranges).
function rangeIn(s) {
  const ranges = [...String(s || '').matchAll(/\b([01]?\d|2[0-3]):([0-5]\d)\s*[–-]\s*([01]?\d|2[0-3]):([0-5]\d)\b/g)]
    .map(m => ({open: Number(m[1]) * 60 + Number(m[2]), close: Number(m[3]) * 60 + Number(m[4])}))
    // «19:00–00:00», «22:00–03:00»: cierra pasada la medianoche, no a primera hora de ese mismo día.
    .map(r => r.close <= r.open && r.close <= 6 * 60 && r.open >= 12 * 60 ? {...r, close: r.close + 1440} : r).filter(r => r.close > r.open);
  if (!ranges.length) return null;
  return {open: ranges[0].open, close: ranges[ranges.length - 1].close, ranges};
}
// Horario amplio por el tramo continuo más largo, no por la primera apertura y el último cierre (27-10-2026): «10:00–13:00 ·
// 15:30–18:30» son dos sesiones de un curso, no ocho horas y media abierto.
const longest = r => Math.max(...r.ranges.map(x => x.close - x.open));
// Horario amplio = espacio o actividad abierta durante horas (28-10-2026, David): no es una sesión. Una franja larga que
// empieza de noche (una fiesta «23:00–05:00», «00:00–06:00») sí es una sesión con hora de inicio.
const NIGHT_START = 20 * 60;
const isWideRange = r => longest(r) >= WIDE_MIN && !(r.open >= NIGHT_START || r.open < NIGHT_END);
const daysBetween = (a, b) => Math.round((new Date(b + 'T12:00:00') - new Date(a + 'T12:00:00')) / 86400000);
const isCourse = e => e.kind === 'course' || e.format === 'workshop' || e.format === 'course';
// «Exposición» solo para exposiciones: una actividad continuada (ruta, espacio abierto) no lo es (26-10-2026).
const isExhibit = e => e.kind === 'exhibition' || e.format === 'exhibition';
const isOpenFormat = e => e.kind === 'exhibition' || e.format === 'exhibition' || e.format === 'ongoing';
// Programas de barrio, talleres o deporte que duran semanas: actividad periódica (como un taller), no una obra en cartel.
const PERIODIC_CATS = new Set(['charlas', 'talleres', 'deporte']);
const isPeriodic = e => isCourse(e) || (e.format === 'program' && PERIODIC_CATS.has(e.public_category));
// Curso o taller al que hay que apuntarse desde el principio (mvp/catalog.needs_signup): lo único que
// «ya empezados» aparta. Programas, temporadas, inscripción abierta y sesiones sueltas salen sus días (25-10-2026).
const needsSignup = e => isCourse(e) && !e.open_enrollment && !e.drop_in;
const collator = new Intl.Collator('es', {sensitivity: 'base'}), byTitle = (a, b) => collator.compare(a.title, b.title);

// Parte del día sin hora («Matinal», «Tarda»).
const PARTS = {cita: () => L('Con cita previa', 'Amb cita prèvia', 'By appointment'), mañana: () => L('Por la mañana', 'Al matí', 'In the morning'), tarde: () => L('Por la tarde', 'A la tarda', 'In the afternoon'), noche: () => L('Por la noche', 'A la nit', 'In the evening'), 'mañana y tarde': () => L('Mañana y tarde', 'Matí i tarda', 'Morning and afternoon'), programa: () => L('Varias sesiones', 'Diverses sessions', 'Several sessions')};
function availability(e, day) {
  if (isFestHead(e)) return festAvailability(e, day);
  const occ = (e.occurrences || []).filter(o => o.date === day);
  const occTimes = [...new Set(occ.map(o => o.time).filter(Boolean).map(x => String(x).padStart(5, '0')))].sort();
  const label = e.time_label || '', raw = e.base_time ?? e.time ?? '';
  // Exposición vigente no es exposición abierta (27-10-2026, A8): el día que el horario del espacio no abre, no sale como
  // plan de ese día; si atiende con cita previa, sale con esa nota.
  if (isExhibit(e) && e.open_days && e.start !== e.end && !e.open_days.includes((new Date(day + 'T12:00:00').getDay() + 6) % 7))
    return e.by_appointment ? {kind: 'tbc', part: 'cita', until: e.end} : {kind: 'run', until: e.end};
  // Las fuentes dan horas distintas ese día (27-10-2026): no se presenta una como segura; sale en «Hora por confirmar».
  if (e.time_conflicts && e.time_conflicts[day]) return {kind: 'tbc', conflict: e.time_conflicts[day], until: e.end};
  if (occTimes.length) return {kind: 'timed', times: occTimes};
  // Ficha de pocos días con pases fechados (26-10-2026): sin pase ese día, no sale (sin pruebas de que haya algo).
  if (!occ.length && e.start !== e.end && !isExhibit(e) && !hoursByDay(e) && daysBetween(e.start, e.end) <= SHORT_DAYS && (e.occurrences || []).some(o => o.time)) return {kind: 'skip'};
  const part = hoursByDay(e)?.[day];
  if (PARTS[part]) return {kind: 'tbc', part, until: e.end};
  // Días con sesión según la fuente (23-10-2026): si la tabla por días cubre esta fecha y no la nombra,
  // ese día no hay sesión (la «Jamboree Jam Session» de Open Data es los lunes 19 y 26: no sale el viernes 23).
  const hbd = hoursByDay(e), hbDays = hbd ? Object.keys(hbd).sort() : [];
  if (e.start !== e.end && hbDays.length && !(day in hbd) && day <= hbDays[hbDays.length - 1] && (day >= hbDays[0] || hbDays[0] >= today)) { const next = hbDays.find(d => d > day); return {kind: 'run', until: e.end, ...(next ? {next, nextTime: hbd[next]} : {})} }
  if (e.start === e.end) {
    const range = rangeIn(label) || rangeIn(raw);
    // Un día con franja larga (28-10-2026, David): una castañada «15:30–21:00» o una fiesta «12:00–01:00» empieza a
    // una hora; es una sesión, no un espacio abierto. Solo un formato abierto (exposición, feria) es horario amplio.
    if (range) return (isWideRange(range) && isOpenFormat(e)) ? {kind: 'wide', ...range, until: e.end} : {kind: 'timed', times: [clock(range.open)], endsAt: range.close};
    const times = timesIn(raw);
    return times.length ? {kind: 'timed', times} : {kind: 'tbc'};
  }
  if (occ.length) return {kind: 'tbc'};
  const span = daysBetween(e.start, e.end);
  // Horario oficial de ese día (tabla por días de la fuente): manda sobre la etiqueta general.
  const dayHours = hoursByDay(e)?.[day];
  if (dayHours && !(needsSignup(e) && !isOpenFormat(e) && span > SHORT_DAYS)) {
    const r = rangeIn(dayHours), ts = timesIn(dayHours);
    // Una exposición o un espacio con horario de apertura es «horario amplio», aunque cada tramo sea corto.
    if (r) return (isWideRange(r) || isOpenFormat(e)) ? {kind: 'wide', ...r, until: e.end} : {kind: 'timed', times: [clock(r.open)], endsAt: r.close};
    if (ts.length) return {kind: 'timed', times: ts};
  }
  const range = rangeIn(label), times = timesIn(raw);
  // La fuente confirma actividad ese día pero no da la hora.
  const dayKnown = hoursByDay(e)?.[day] === '';
  if (isPeriodic(e) && !isOpenFormat(e)) {
    // Curso o taller de varias semanas (26-10-2026): sale en la agenda el día que empieza, a su hora (o sin hora
    // confirmada), como cualquier plan; antes de ese día no sale. Ya empezado, lo de siempre.
    if (span > SHORT_DAYS && day < e.start) return {kind: 'skip'};
    if (span > SHORT_DAYS && day === e.start) {
      if (times.length || range) return {kind: 'timed', times: range ? [clock(range.open)] : times, courseStart: true, until: e.end, endsAt: range?.close};
      return {kind: 'tbc', courseStart: true, until: e.end};
    }
    if (span > SHORT_DAYS && needsSignup(e)) return {kind: 'started', until: e.end, ...(range || {})};
    if (span <= SHORT_DAYS) {
      if (times.length || range) return {kind: 'timed', times: times.length ? times : [clock(range.open)], confirmDay: true, until: e.end, endsAt: range?.close};
      return {kind: 'tbc', until: e.end};
    }
    // Programa o sesiones sueltas ya en marcha: sigue como una temporada (abajo).
  }
  if (isOpenFormat(e) || (range && isWideRange(range))) return {kind: 'wide', until: e.end, ...(range || {noHours: true})};
  // Temporada de semanas con una hora general pero sin saber qué días hay función (24-10-2026): no se
  // presenta como sesión de ese día («temporada · confirma el pase»): va a «planes sin hora confirmada».
  // Las de pocos días (festivales cortos) siguen con su hora.
  if ((range || times.length) && span > SHORT_DAYS && !dayKnown) return {kind: 'tbc', until: e.end};
  if (range) return {kind: 'timed', times: [clock(range.open)], season: span > SHORT_DAYS, until: e.end, endsAt: range.close};
  // «Temporada · confirma el pase» solo en temporadas largas; unas funciones de pocos días van a su hora (26-10-2026).
  if (times.length) return {kind: 'timed', times, season: span > SHORT_DAYS, until: e.end};
  // Ciclos, temporadas y programas de semanas sin fechas ni hora de sus sesiones: no se sabe si hay
  // algo ese día, así que no salen en la agenda; solo al buscarlos por nombre.
  if (span > SHORT_DAYS && !dayKnown) return {kind: 'run', until: e.end};
  return {kind: 'tbc', run: true, until: e.end};
}
// Sesiones de madrugada (25-10-2026, David): un acto de un día (o que acaba al día siguiente) a las 00:00–05:59
// es la noche de esa fecha («PleaseQuiet», vie 30 · 00:00, es la noche del viernes): va al final del día, cuenta
// como pendiente hasta entonces y, si la fuente lo alarga al día siguiente, no se repite a primera hora de ese día.
const NIGHT_END = 6 * 60;
function nightAware(e, day, a) {
  if (a.kind !== 'timed' || !a.times?.length || !a.times.every(x => (minutesOf(x) ?? 1e4) < NIGHT_END)) return a;
  // También con sesiones fechadas (26-10-2026): DICE da «PleaseQuiet» como sesión del 30 a las 00:00.
  const occ = e.occurrences || [];
  if (occ.length) return occ.some(o => o.date === day) ? {...a, night: true} : a;
  const span = daysBetween(e.start, e.end);
  if (span === 0 && day === e.start) return {...a, night: true};
  if (span === 1) return day === e.start ? {...a, night: true} : day === e.end ? {kind: 'skip'} : a;
  return a;
}
function status(a, now) {
  if (a.kind === 'timed') {
    const mins = a.times.map(minutesOf).map(m => a.night && m !== null && m < NIGHT_END ? m + 1440 : m);
    if (now === null) return {state: 'scheduled', next: mins[0], sort: mins[0], rest: mins.slice(1)};
    const ahead = mins.filter(m => m >= now), recent = mins.filter(m => m < now && now - m < GRACE);
    if (recent.length && !ahead.length && !a.season) return {state: 'started', next: recent[recent.length - 1], sort: now - 1, ago: now - recent[recent.length - 1], rest: []};
    if (!ahead.length) return {state: 'past', next: mins[mins.length - 1], sort: mins[mins.length - 1], rest: []};
    return {state: ahead[0] - now <= SOON ? 'soon' : 'later', next: ahead[0], sort: ahead[0], in: ahead[0] - now, rest: ahead.slice(1), done: mins.length - ahead.length};
  }
  if (a.kind === 'wide' && !a.noHours) {
    if (now === null) return {state: 'scheduled', sort: a.open};
    if (now < a.open) return {state: a.open - now <= SOON ? 'soon' : 'later', sort: a.open, in: a.open - now};
    const parts = a.ranges || [{open: a.open, close: a.close}];
    const current = parts.find(r => r.open <= now && now < r.close);
    if (current) return {state: 'open', sort: now - 2, closesIn: current.close - now, closesAt: current.close};
    const next = parts.find(r => r.open > now);
    if (next) return {state: next.open - now <= SOON ? 'soon' : 'later', sort: next.open, in: next.open - now, opensAt: next.open, reopens: true};
    return {state: 'past', sort: a.close};
  }
  return {state: 'none', sort: 1e4};
}

// De dónde salen los datos de la ficha (src/data_origin.py).
const ORIGIN = {centro: () => L('datos del propio centro', 'dades del mateix centre', 'data from the venue itself'), web_oficial: () => L('datos de la web oficial del acto', "dades de la web oficial de l'acte", 'data from the event’s official website'),
  red_publica: () => L('datos de la red municipal que lo organiza', 'dades de la xarxa municipal que l\'organitza', 'data from the municipal network that organises it'), agenda: () => L('datos de una agenda pública, no del centro', "dades d'una agenda pública, no del centre", 'data from a public listing, not the venue'),
  eventbrite: () => L('publicado en Eventbrite', 'publicat a Eventbrite', 'published on Eventbrite'), directorio: () => L('datos de un directorio de conciertos, no de la sala', "dades d'un directori de concerts, no de la sala", 'data from a concert directory, not the venue')};
/* ---------- botones de tipo ---------- */
const CHIPS = [
  {k: 'fixed', label: () => L('Empiezan a una hora', 'Comencen a una hora', 'Set start time'), short: () => L('Con hora', 'Amb hora', 'Timed'), desc: () => L('Conciertos, funciones, charlas', 'Concerts, funcions, xerrades', 'Concerts, shows, talks'), mark: 'dot'},
  {k: 'wide', label: () => L('Horario amplio', 'Horari ampli', 'Open hours'), short: () => L('Abierto', 'Obert', 'Ongoing'), desc: () => L('Exposiciones, ferias y espacios', 'Exposicions, fires i espais', 'Exhibitions, fairs and venues'), mark: 'bar'},
  {k: 'soon', label: () => L('Talleres y cursos', 'Tallers i cursos', 'Workshops and courses'), short: () => L('Talleres', 'Tallers', 'Workshops'), desc: () => L(`Que empiezan en los próximos ${COURSE_AHEAD} días`, `Que comencen en els propers ${COURSE_AHEAD} dies`, `Starting in the next ${COURSE_AHEAD} days`), mark: ''},
  {k: 'tbc', label: () => L('Hora por confirmar', 'Hora per confirmar', 'Time to be confirmed'), short: () => L('Sin hora', 'Sense hora', 'No time'), desc: () => '', mark: 'dash'},
];
state.show = {fixed: true, wide: true, tbc: true, soon: true};  // sin bloques de tipo: todo se ve, plegado donde toca (23-10-2026)
// «Arte y galerías» vive sobre todo de exposiciones (horario amplio) y de talleres de varias
// sesiones: al entrar en el canal se ven todos los tipos; al salir vuelve la vista de cada uno.
// (Cambios hechos dentro del canal no se guardan como preferencia general.)
// Con el buscador también se ven los cuatro tipos (22-10-2026): quien busca «MIRA» no tiene
// por qué saber si es un concierto con hora o una feria de horario amplio. Al borrar la
// búsqueda vuelve la vista que tenía.
const ALL_TYPES = {fixed: true, wide: true, soon: true, tbc: true};
const CHANNEL_VIEW = {galerias: ALL_TYPES};
let savedShow = null, viewKey = '';
function channelView() { return }
function channelViewOld() {
  // Guardados (22-10-2026): también los cuatro tipos; lo que guardaste se ve siempre, sea del tipo que sea.
  // Con cualquier filtro (categoría, plan, edad, idioma, distrito, formato, gratis u horario) también los cuatro
  // tipos (23-10-2026, David): quien filtra «Teatro en Gràcia» quiere verlo todo, tenga hora fija o no.
  const filtered = state.cats.length || state.chans.length || state.ages.length || state.langs.length || state.district || state.format || state.free || state.hourFrom !== null || state.hourTo !== null;
  const key = state.savedOnly ? 'saved' : String(state.query || '').trim() ? 'search' : state.chans.length === 1 && CHANNEL_VIEW[state.chans[0]] ? state.chans[0] : filtered ? 'filter' : '';
  if (key === viewKey) return;
  if (!key) { if (savedShow) { state.show = savedShow; savedShow = null } }
  else { if (!savedShow) savedShow = {...state.show}; Object.assign(state.show, CHANNEL_VIEW[key] || ALL_TYPES) }
  viewKey = key;
}
channelView();
state.expanded = new Set(); state.limits = {}; state.openDays = new Set(); state.shown = DAY_CHUNK;
// Barra rápida de categorías (23-10-2026, propuesta A + B): un toque elige una categoría (o «Todo»);
// los cuatro bloques de tipo de horario desaparecen y la lista se ordena por su naturaleza.
const CAT_SHORT = {musica: ['Música', 'Música', 'Music'], escena: ['Teatro', 'Teatre', 'Theatre'], cine: ['Cine', 'Cinema', 'Cinema'], arte: ['Arte', 'Art', 'Art'],
  charlas: ['Charlas', 'Xerrades', 'Talks'], talleres: ['Talleres', 'Tallers', 'Workshops'], fiestas: ['Fiestas', 'Festes', 'Festivities'], deporte: ['Deporte', 'Esport', 'Sport']};
const CAT_LANDING = {'': '/', musica: '/conciertos', escena: '/teatro', arte: '/exposiciones'};
// «Cerca de mí» (25-10-2026): la ubicación se pide solo al tocar y se queda en el navegador (ni URL, ni Matomo,
// ni servidor). Ordena por cercanía dentro de cada hora o día, muestra la distancia y permite «a menos de 1 km».
const NEAR_PIN = '<svg aria-hidden="true" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21s-7-6.1-7-11a7 7 0 0 1 14 0c0 4.9-7 11-7 11z"></path><circle cx="12" cy="10" r="2.5"></circle></svg>';
const nearFail = () => L('No hemos podido saber dónde estás. Puedes elegir un distrito en Filtros.', 'No hem pogut saber on ets. Pots triar un districte a Filtres.', 'We could not get your location. You can pick a district in Filters.');
// «Cerca de mí» junto a «Filtros» (28-10-2026, 19:34, David): al tocarlo pide la ubicación y filtra a 1 km; se puede ampliar
// a 3 km o quitar.
function nearHtml() {
  if (!state.near) return `<button type="button" class="near-btn" data-near="toggle" aria-pressed="false">${NEAR_PIN}${state.nearWait ? L('Buscando…', 'Cercant…', 'Locating…') : L('Cerca de mí', 'A prop meu', 'Near me')}</button>`;
  const km = k => `<button type="button" class="near-km${state.nearKm === k ? ' on' : ''}" data-near="km${k}" aria-pressed="${state.nearKm === k}">${k} km</button>`;
  return `<div class="near-on" role="group" aria-label="${L('Distancia', 'Distància', 'Distance')}">${NEAR_PIN}${km(1)}${km(3)}<button type="button" class="near-off" data-near="toggle" aria-label="${L('Quitar Cerca de mí', 'Treure A prop meu', 'Turn off Near me')}">✕</button></div>`;
}
function kmTo(a, b) {
  const r = x => x * Math.PI / 180, dLat = r(b.lat - a.lat), dLon = r(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(r(a.lat)) * Math.cos(r(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(h));
}
const kmText = k => k < 1 ? `${Math.max(100, Math.round(k * 10) * 100)} m` : `${k < 10 ? k.toFixed(1).replace('.', LANG === 'en' ? '.' : ',') : Math.round(k)} km`;
const nearSort = list => state.near ? [...list].sort((a, b) => (a._km ?? 1e9) - (b._km ?? 1e9)) : list;
function catBarHtml(compact = false) {
  const only = state.cats.length === 1 ? state.cats[0] : '';
  // Las categorías con página de entrada (src/landings.py) son enlaces reales, para que Google llegue a ellas
  // desde la portada (25-10-2026); al tocarlas se filtra igual que antes, sin cambiar de página.
  const btn = (c, label) => { const on = c ? only === c : !state.cats.length, href = CAT_LANDING[c];
    const attrs = `class="cat-pill${on ? ' on' : ''}" data-quickcat="${c}" aria-pressed="${on}"${c ? ` data-category-color="${c}"` : ''}`, inner = `${c ? '<i aria-hidden="true"></i>' : ''}${esc(label)}`;
    return href ? `<a href="${href}" ${attrs}>${inner}</a>` : `<button type="button" ${attrs}>${inner}</button>` };
  if (compact) return `<div class="cat-bar cat-bar-mini" role="group" aria-label="${L('Categoría', 'Categoria', 'Category')}">${btn('', t('Todo'))}${Object.keys(CATS).map(c => btn(c, byLang(CAT_SHORT[c]))).join('')}</div>`;
  return `<div class="cat-bar" role="group" aria-label="${L('Categoría', 'Categoria', 'Category')}">${btn('', t('Todo'))}${Object.keys(CATS).map(c => btn(c, byLang(CAT_SHORT[c]))).join('')}</div>`;
}
function chipsHtml(counts) {
  // Una sola barra de categorías para toda la página (28-10-2026, David): entre el titular y la Selección, y filtra a la vez
  // la Selección y la Agenda. En móvil, cuando se pierde de vista, la misma fila (mismo estado) dentro de la barra fija de
  // «Filtros» que ya existía, para cambiar de categoría sin volver arriba.
  // La Agenda tiene su propia fila de categorías, siempre a la vista y fija bajo «Filtros» (28-10-2026, 19:34, David); la de
  // la Selección va dentro de la Selección. «Cerca de mí», al lado de «Filtros».
  const mini = $('typeMini'); if (mini) { mini.innerHTML = catBarHtml(true); mini.hidden = false; const sel = mini.querySelector('.on'), row = mini.querySelector('.cat-bar'); if (sel && row && sel.offsetLeft > row.clientWidth - 40) row.scrollLeft = sel.offsetLeft - 16 }
  const near = $('nearBox'); if (near) near.innerHTML = nearHtml();
  const msg = $('nearMsg'); if (msg) { msg.textContent = state.nearMsg || ''; msg.hidden = !state.nearMsg }
  requestAnimationFrame(stick);
  return '';
}

/* ---------- modelo ---------- */
function bucketOf(e) { const k = e._a.kind; return k === 'timed' ? 'fixed' : k }
function buildModel(items, win) {
  const now = madridNow();
  const decorate = (e, day, nowMin) => { const a = nightAware(e, day, availability(e, day)); return Object.assign(e, {_a: a, _st: status(a, nowMin), _day: day}) };
  const s = {fixed: [], wide: [], wideNoHours: [], tbc: [], run: [], soon: [], started: [], past: [], other: []};
  const place = e => {
    const k = e._a.kind;
    // Sin grupo «Ahora» (28-10-2026, David): lo que ya ha empezado hoy va con lo anterior, accesible arriba.
    if ((k === 'timed' || k === 'wide') && (e._st.state === 'past' || e._st.state === 'started')) s.past.push(e);
    else if (k === 'timed') s.fixed.push(e);
    else if (k === 'wide') (e._a.noHours ? s.wideNoHours : s.wide).push(e);
    else if (k === 'skip') return;
    else if (s[k]) s[k].push(e); else s.other.push(e);
  };
  if (!win) {
    const day = state.day, live = day === now.day, nowMin = live ? now.min : null;
    for (const e of items) { decorate(e, day, nowMin); place(e) }
    const tl = (a, b) => a._st.sort - b._st.sort || byTitle(a, b);
    s.fixed.sort(tl); s.wide.sort(tl); s.past.sort(tl); s.tbc.sort(byTitle); s.run.sort((a, b) => a.end.localeCompare(b.end) || byTitle(a, b)); s.wideNoHours.sort((a, b) => a.end.localeCompare(b.end) || byTitle(a, b));
    s.soon.sort((a, b) => a.start.localeCompare(b.start) || byTitle(a, b)); s.started.sort((a, b) => a.end.localeCompare(b.end) || byTitle(a, b)); s.other.sort(byTitle);
    return {mode: 'day', day, live, now, sections: s, total: items.length};
  }
  // Periodo: cada ficha una sola vez, en su primer día dentro del periodo. Salvo funciones en pocos días sueltos (de 2 a 8,
  // 28-10-2026, David: «En Joan sense por», 31-10, 1, 7 y 8-11, salía solo el primero al buscarla): una fila por día de función.
  const buckets = new Map(), expanded = [];
  for (const e of items) {
    e._onlyDay = undefined;
    const byDayKeys = e.start !== e.end ? Object.keys(hoursByDay(e) || {}).filter(d => timesIn(hoursByDay(e)[d]).length) : [];
    const days = [...new Set([...(e.occurrences || []).filter(o => o.time).map(o => o.date), ...byDayKeys])].filter(d => d >= win.from && d <= win.to).sort();
    if (e.start !== e.end && days.length >= 2 && days.length <= 8) days.forEach((d, i) => expanded.push(i ? Object.assign(Object.create(Object.getPrototypeOf(e)), e, {_onlyDay: d}) : Object.assign(e, {_onlyDay: d})));
    else expanded.push(e);
  }
  for (const e of expanded) {
    // Días con sesión: los de las sesiones y los del horario por días de la fuente (27-10-2026: «Contes a la mà»
    // de GuiaBCN, «20 octubre i 17 novembre», salía hoy «Sin hora» en vez del 17 nov a las 17:30).
    const byDayKeys = e.start !== e.end ? Object.keys(hoursByDay(e) || {}) : [];
    const inside = [...new Set([...(e.occurrences || []).map(o => o.date), ...byDayKeys])].filter(d => d >= win.from && d <= win.to).sort();
    if (!inside.length && byDayKeys.length && byDayKeys.every(d => d < win.from || d > win.to)) continue;   // ninguna sesión en el periodo
    let day = e._onlyDay || inside[0] || (e.start >= win.from && e.start <= win.to ? e.start : null);
    if (!e._onlyDay && day === now.day && inside.length > 1 && status(availability(e, day), now.min).state === 'past') day = inside.find(d => d > now.day) || day;
    if (!day) day = win.from;                      // ya en marcha al empezar el periodo: su primer día es hoy
    decorate(e, day, day === now.day ? now.min : null);
    if (e._a.kind === 'skip') continue;
    if (e._a.kind === 'started' || e._a.kind === 'soon' || (e._a.kind === 'timed' || e._a.kind === 'wide') && (['past', 'started'].includes(e._st.state) || (e._st.state === 'open' && !isExhibit(e)))) { place(e); continue }
    if (!buckets.has(day)) buckets.set(day, []);
    buckets.get(day).push(e);
  }
  const rank = e => ({timed: 0, wide: 1, tbc: 2, run: 3}[e._a.kind] ?? 4);
  for (const list of buckets.values()) list.sort((a, b) => rank(a) - rank(b) || a._st.sort - b._st.sort || byTitle(a, b));
  s.past.sort((a, b) => a._st.sort - b._st.sort || byTitle(a, b)); s.soon.sort((a, b) => a.start.localeCompare(b.start)); s.started.sort((a, b) => a.end.localeCompare(b.end));
  const counts = {fixed: 0, wide: 0, tbc: 0, run: 0};
  for (const list of buckets.values()) for (const e of list) { const b = bucketOf(e); if (counts[b] !== undefined) counts[b]++; else s.other.push(e) }
  return {mode: 'range', win, now, buckets: [...buckets.entries()].sort((a, b) => a[0].localeCompare(b[0])), sections: s, counts, total: items.length};
}

/* ---------- fila ---------- */
// «Último día» (23-10-2026): aparte del «hasta las 21:00» de hoy, para no juntar dos «hasta» distintos.
// «mañana» solo si se mira hoy (28-10-2026: el sábado una feria que cierra el domingo decía «Último día: mañana»).
const lastText = (e, d) => daysBetween(e._day || today, d) <= 0 ? L('Último día', 'Últim dia', 'Last day') : (e._day || today) === today ? L('Último día: mañana', 'Últim dia: demà', 'Last day: tomorrow') : `${L('Último día:', 'Últim dia:', 'Last day:')} ${labelDate(d)}`;
const untilText = (e, d) => { const n = daysBetween(e._day || today, d); return n <= 0 ? L('último día', 'últim dia', 'last day') : n === 1 ? L('hasta mañana', 'fins demà', 'until tomorrow') : `${L('hasta el', 'fins al', 'until')} ${labelDate(d)}` };
function bar(a, st) {
  const from = 8 * 60, span = 16 * 60, pct = m => Math.max(0, Math.min(100, (m - from) / span * 100)).toFixed(1);
  const nowTick = st.state !== 'scheduled' ? `<i class="w-tick" style="left:${pct(madridNow().min)}%"></i>` : '';
  return `<span class="w-bar" aria-hidden="true">${(a.ranges || [a]).map(r => `<i class="w-fill" style="left:${pct(r.open)}%;width:${Math.max(0, Math.min(r.close, from + span) - Math.max(r.open, from)) / span * 100}%"></i>`).join('')}${nowTick}</span>`;
}
function whenCell(e) {
  const a = e._a, st = e._st || {state: 'none'};
  if (a.ranges && a.ranges.length > 1) a.ranges = [...a.ranges].sort((x, y) => x.open - y.open);  // franjas en orden (09:00–13:00 · 16:00–23:00)
  if (a.kind === 'timed') {
    const multi = a.times.length > 1 || a.season;
    let note = '', cls = '';
    if (a.season) { note = L('temporada · confirma el pase', 'temporada · confirma el passi', 'season · check the show time'); cls = 'hint' }
    else if (st.state === 'soon') { note = st.in <= 1 ? L('ahora', 'ara', 'now') : `${L('en', 'd\'aquí a', 'in')} ${st.in} min`; cls = 'urgent' }
    else if (st.state === 'started') { note = `${L('empezó hace', 'va començar fa', 'started')} ${st.ago} min`; cls = 'urgent' }
    else if (a.courseStart) { note = `${L('inicio de curso', 'inici de curs', 'course starts')}${needsSignup(e) ? ' · ' + L('inscripción', 'inscripció', 'sign-up') : ''} · ${untilText(e, a.until)}`; cls = 'hint' }
    else if (a.confirmDay) { note = L('confirma el día', 'confirma el dia', 'check the day'); cls = 'hint' }
    else if (a.endsAt) note = `${L('hasta las', 'fins a les', 'until')} ${clock(a.endsAt)}`;
    else if ((st.rest || []).length) note = `${L('después', 'després', 'later')} ${st.rest.slice(0, 2).map(clock).join(' · ')}${st.rest.length > 2 ? '…' : ''}`;
    return `<div class="when w-timed"><span class="w-line"><i class="${multi ? 'm-dots' : 'm-dot'}" aria-hidden="true"></i><time class="w-big">${(m => m === 1439 ? '00:00' : clock(m))(st.next ?? minutesOf(a.times[0]))}</time></span>${note ? `<span class="w-note ${cls}">${esc(note)}</span>` : ''}</div>`;
  }
  if (a.kind === 'wide') {
    const last = daysBetween(e._day || today, a.until) <= 1;
    if (!a.noHours && a.open === 0 && a.close >= 1439 && !(a.ranges || []).some(r => r.open > 0 || r.close < 1439)) return `<div class="when w-wide"><span class="w-state-wide">${L('Todo el día', 'Tot el dia', 'All day')}</span>${e.start !== e.end ? `<span class="w-note${last ? ' urgent' : ''}">${esc(untilText(e, a.until))}</span>` : ''}</div>`;
    if (a.noHours) return `<div class="when w-wide"><span class="w-state-wide">${a.until && e.start !== e.end ? (isExhibit(e) ? L('Exposición', 'Exposició', 'Exhibition') : L('Varios días', 'Diversos dies', 'Several days')) : L('Todo el día', 'Tot el dia', 'All day')}</span><span class="w-note${last ? ' urgent' : ''}">${esc(untilText(e, a.until))}</span></div>`;
    let main, note = '', cls = '';
    if (st.state === 'open') { main = `<span class="w-state-wide">${L('Abierto', 'Obert', 'Open')}</span>`; if (st.closesIn <= SOON && !isExhibit(e)) { note = `${L('cierra en', 'tanca d\'aquí a', 'closes in')} ${st.closesIn} min`; cls = 'urgent' } else note = `${L('hasta las', 'fins a les', 'until')} ${clock(st.closesAt ?? a.close)}` }
    else if (st.state === 'soon' || st.state === 'later') { main = `<span class="w-mid">${st.reopens ? L('Reabre', 'Reobre', 'Reopens') : L('Abre', 'Obre', 'Opens')} ${clock(st.opensAt ?? a.open)}</span>`; note = (a.ranges || []).length > 1 ? a.ranges.map(r => `${clock(r.open)}–${clock(r.close)}`).join(' · ') : `${L('hasta las', 'fins a les', 'until')} ${clock(a.close)}` }
    else if (st.state === 'past') { main = `<span class="w-mid w-dim">${L('Cerrado ya', 'Ja tancat', 'Closed now')}</span>`; note = `${clock(a.open)}–${clock(a.close)}` }
    else { main = `<span class="w-mid">${(a.ranges || [a]).map(r => `${clock(r.open)}–${clock(r.close)}`).join(' · ')}</span>` }
    const lastNote = e.start !== e.end && last && cls !== 'urgent' && !isExhibit(e) ? `<span class="w-note urgent">${esc(lastText(e, a.until))}</span>` : '';
    return `<div class="when w-wide">${bar(a, st)}${main}${note ? `<span class="w-note ${cls}">${esc(note)}</span>` : ''}${lastNote}</div>`;
  }
  if (a.kind === 'soon') return `<div class="when w-course"><span class="w-kind">${L('Empieza', 'Comença', 'Starts')}</span><span class="w-mid">${esc(e.start === (e._day || today) ? L('hoy', 'avui', 'today') : labelDate(e.start))}</span>${a.open !== undefined ? `<span class="w-note">${clock(a.open)}–${clock(a.close)}</span>` : ''}</div>`;
  if (a.kind === 'started') return `<div class="when w-course"><span class="w-kind">${L('En marcha', 'En marxa', 'Under way')}</span><span class="w-mid">${esc(untilText(e, a.until))}</span></div>`;
  if (a.kind === 'run' && a.next) return `<div class="when w-course"><span class="w-kind">${L('Próxima sesión', 'Propera sessió', 'Next session')}</span><span class="w-mid">${esc(labelDate(a.next))}</span>${a.nextTime && PARTS[a.nextTime] === undefined ? `<span class="w-note">${esc(a.nextTime)}</span>` : ''}</div>`;
  if (a.kind === 'run') return `<div class="when w-course"><span class="w-kind">${L('En programación', 'En programació', 'On the programme')}</span><span class="w-mid">${esc(untilText(e, a.until))}</span></div>`;
  // Horas que no cuadran entre fuentes (27-10-2026): las dos, y que hay que confirmarlo.
  if (a.conflict) return `<div class="when w-tbc"><span class="w-mid">${esc(a.conflict.join(' / '))}</span><span class="w-note">${L('por confirmar', 'per confirmar', 'to be confirmed')}</span></div>`;
  if (a.part === 'cita') return `<div class="when w-tbc"><span class="w-mid">${esc(PARTS.cita())}</span><span class="w-note">${L('ese día, según su horario', 'aquell dia, segons el seu horari', 'that day, per its opening hours')}</span></div>`;
  if (a.part) return `<div class="when w-tbc"><span class="w-mid">${esc(PARTS[a.part]())}</span><span class="w-note">${a.part === 'programa' ? L('horas en su programa', 'hores al seu programa', 'times in its programme') : L('hora por confirmar', 'hora per confirmar', 'time to be confirmed')}</span></div>`;
  const fixedLater = {'Hora por determinar': L('Hora por determinar', 'Hora per determinar', 'Time to be announced'), 'Horario próximamente': L('Horario próximamente', 'Horari properament', 'Times coming soon')}[e.time_label];
  if (fixedLater) return `<div class="when w-tbc"><span class="w-mid">${esc(fixedLater)}</span><span class="w-note">${L('según la fuente', 'segons la font', 'according to the source')}</span></div>`;
  // Texto de horario de la fuente sin horas (26-10-2026): se muestra tal cual en vez de «Hora por confirmar».
  if (e.schedule_hint && !a.courseStart) return `<div class="when w-tbc"><span class="w-mid"><span class="w-long">${L('Horario según la fuente', 'Horari segons la font', 'Times per source')}</span><span class="w-short">${L('Ver horario', 'Veure horari', 'See times')}</span></span><span class="w-note">${esc(e.schedule_hint)}</span></div>`;
  return `<div class="when w-tbc"><span class="w-mid"><span class="w-long">${L('Hora por confirmar', 'Hora per confirmar', 'Time to be confirmed')}</span><span class="w-short">${L('Sin hora', 'Sense hora', 'No time')}</span></span>${a.courseStart ? `<span class="w-note">${esc(`${L('inicio de curso', 'inici de curs', 'course starts')}${needsSignup(e) ? ' · ' + L('inscripción', 'inscripció', 'sign-up') : ''} · ${untilText(e, a.until)}`)}</span>` : a.run ? `<span class="w-note">${esc(`${L('en cartel', 'en cartell', 'showing')} ${untilText(e, a.until)}`)}</span>` : `<span class="w-note w-long">${L('confírmala antes de ir', 'confirma-la abans d\'anar-hi', 'check it before you go')}</span>`}</div>`;
}
// Precio corto en la fila (28-10-2026): solo si la fuente da importes en euros. Uno → «12 €»; varios → «desde 10 €».
function priceShort(e) {
  const f = n => (Number.isInteger(n) ? String(n) : n.toFixed(2).replace('.', ',')) + ' €';
  if (e.price_short) return e.price_short[1] ? `${L('desde', 'des de', 'from')} ${f(e.price_short[0])}` : f(e.price_short[0]);
  const nums = [...String(e.price_label || '').matchAll(/(\d+(?:[.,]\d{1,2})?)\s*(?:€|eur)/gi)].map(m => Number(m[1].replace(',', '.'))).filter(n => n > 0 && n < 1000);
  if (!nums.length) return '';
  const lo = Math.min(...nums);
  return nums.some(n => n !== lo) ? `${L('desde', 'des de', 'from')} ${f(lo)}` : f(lo);
}
const seriesShort = title => String(title || '').replace(/^\s*patis? escolars? oberts?(?: al barri)?\s*[-–:·]\s*/i, '') || title;
function row(e) {
  if (!e._a) Object.assign(e, {_a: availability(e, e.start), _st: {state: 'none'}, _day: e.start});
  const k = key(e), saved = state.saved.includes(k);
  return `<article class="ev k-${e._a.kind} st-${e._st.state}${e._hl ? ' ev-hl' : ''}" data-cat="${esc(e.public_category || e.category || '')}"><button class="ev-main" type="button" data-open="${esc(k)}">${whenCell(e)}${thumb(e)}<span class="ev-body">${hlHead(e)}${msTag(e)}<h3 class="ev-title">${esc(e._inFest ? festShort(e) : e._seriesShort ? seriesShort(e.title) : e.title)}</h3>${festTag(e)}${lineupHit(e) ? `<span class="ev-hit">${t('Con')} ${esc(lineupHit(e))}</span>` : programHit(e) ? `<span class="ev-hit">${esc(L('En el programa', 'Al programa', 'In the programme'))}: ${esc(programHit(e))}</span>` : ''}${noteOfDay(e, e._day) ? `<span class="ev-hit">${esc(labelDay(e._day))}: ${esc(noteOfDay(e, e._day))}</span>` : ''}<span class="ev-cat"><span class="ev-catname">${esc(catLabel(e))}</span>${hasAge(e) ? `<span class="ev-age">${esc(ageText(e))}</span>` : ''}${daysLeft(e)}${e.is_free ? `<span class="ev-free">${t('Gratis')}</span>` : priceShort(e) ? `<span class="ev-price">${esc(priceShort(e))}</span>` : ''}${isPeriodic(e) && e.registration_required && !e.open_enrollment ? `<span class="ev-signup">${L('Inscripción', 'Inscripció', 'Sign-up')}</span>` : ''}${soldOn(e, e._day) ? `<span class="ev-soldout">${L('Agotado', 'Esgotat', 'Sold out')}</span>` : ''}</span><span class="ev-meta">${rowVenue(e)}${state.near && e._km != null ? `<span class="ev-dist">${kmText(e._km)}</span>` : ''}</span></span></button><button class="save ${saved ? 'active' : ''}" type="button" data-save="${esc(k)}" aria-pressed="${saved}" aria-label="${t('Guardar')} ${esc(e.title)}">${saved ? '♥' : '♡'}</button></article>`;
}

/* ---------- render ---------- */
const hourKey = e => String(Math.floor(e._st.sort / 60)).padStart(2, '0');
function groupHead(label, cls = '') { return `<div class="ag-stick${cls}"><span>${esc(label)}</span></div>` }
// Series de fichas casi iguales (p. ej. un patio escolar abierto por escuela): una fila y el resto plegado.
// Destacados (21-10-2026): pocas filas, con motivo visible. «Selección Ontoca» (la de la portada) y
// «Últimos días» (exposiciones y obras que cierran en una semana). Como mucho una de cada diez filas del
// día y nunca dos seguidas.
state.picks = new Set();
// Funciones que la sala publica una a una (cada día una ficha): mismo título y sala → primera y última fecha.
let runsIndex = null;
function runOf(e) {
  if (!store.catalog) return null;  // sin catálogo completo cargado no se puede saber la primera/última función
  if (!runsIndex) {
    runsIndex = new Map();
    for (const x of store.catalog || []) {
      if (x.start !== x.end) continue;
      const k = fold(x.title) + '|' + fold(x.venue_names?.[0] || ''), r = runsIndex.get(k);
      if (r) { r.n++; if (x.start < r.first) r.first = x.start; if (x.start > r.last) r.last = x.start } else runsIndex.set(k, {n: 1, first: x.start, last: x.start});
    }
  }
  const r = runsIndex.get(fold(e.title) + '|' + fold(e.venue_names?.[0] || ''));
  return r && r.n >= 3 ? r : null;
}
function hlReason(e, day) {
  // Selección Ontoca: la de la portada, o lo que anuncian tres fuentes o más.
  if (state.picks.has(key(e)) || (e.confirmations || 1) >= 3) return 'pick';
  if (!e.relevant || !day) return '';  // el resto, solo en salas y centros de referencia
  const cat = e.public_category || e.category;
  const runs = e.start !== e.end, longRun = runs && daysBetween(e.start, e.end) >= 14;
  // Estreno: primer día de una obra o espectáculo con varias funciones.
  const firstDay = (e.occurrences || []).map(o => o.date).sort()[0] || e.start;
  if (runs && cat === 'escena' && e.kind !== 'exhibition' && day === firstDay) return 'premiere';
  const run = !runs && (cat === 'escena' || cat === 'arte') ? runOf(e) : null;
  if (run && day === run.first && run.first > today) return 'premiere';
  if (run && day >= addDays(run.last, -6) && day <= run.last && daysBetween(run.first, run.last) >= 14) return day === run.last ? 'lastday' : 'last';
  // Últimos días: exposiciones y obras que cierran en una semana.
  if (longRun && e.end >= day && daysBetween(day, e.end) <= 6 && (e.kind === 'exhibition' || cat === 'arte' || (cat === 'escena' && e.kind !== 'course'))) return e.end === day ? 'lastday' : 'last';
  // («Solo hoy» se descartó: muchas salas publican cada función como ficha de un día y no podemos asegurar que sea única.)
  return '';
}
const HL_LABEL = {pick: () => L('Selección Ontoca', 'Selecció Ontoca', 'Ontoca pick'), premiere: () => L('Estreno', 'Estrena', 'Premiere'), last: () => L('Últimos días', 'Últims dies', 'Last days'), lastday: () => L('Último día', 'Últim dia', 'Last day'), onlytoday: () => L('Solo hoy', 'Només avui', 'Today only')};
const HL_ORDER = {pick: 0, premiere: 1, lastday: 2, last: 3, onlytoday: 4};
function markHighlights(list, day) {
  list.forEach(e => { e._hl = '' });
  const cands = list.filter(e => !e._inFest && hlReason(e, day)).sort((a, b) => HL_ORDER[hlReason(a, day)] - HL_ORDER[hlReason(b, day)] || (b.confirmations || 1) - (a.confirmations || 1));
  // Por orden de motivo (Selección, Estreno, Último día…), sin dos filas destacadas seguidas.
  const cap = Math.max(1, Math.floor(list.length / 10)), pos = new Map(list.map((e, i) => [e, i]));
  let used = 0;
  for (const e of cands) {
    if (used >= cap) break;
    const i = pos.get(e);
    if (list[i - 1]?._hl || list[i + 1]?._hl) continue;
    e._hl = hlReason(e, day); used++;
  }
}
// Imagen de un destacado que no carga (23-10-2026): fuera el recuadro vacío. Los errores de carga no suben
// por el DOM, así que se escuchan en captura; y nada de onerror en línea, que la CSP de la web no permite.
document.addEventListener('error', ev => {
  const img = ev.target;
  if (img && img.tagName === 'IMG' && img.closest) { const box = img.closest('.hl-img'); if (box) box.remove() }
}, true);
// Miniatura en todas las filas de Expos que tienen imagen (28-10-2026, David): para elegir una exposición es el dato que
// más decide; el 57 % la tienen y solo se veía en 3 de 20.
function thumb(e) {
  return '';   // 29-10-2026 (David): Expos con la misma maquetación que la Agenda, sin miniatura (el texto quedaba comprimido)
  if (!isExhibit(e)) return '';
  const url = (e.media || []).find(x => x.url && !x.fallback)?.url || e.image || state.pickMedia?.[key(e)] || '';
  return url ? `<span class="ev-thumb"><img src="${esc(url)}" alt="" loading="lazy"></span>` : '';
}
function hlHead(e) {
  if (!e._hl) return '';
  const url = (e.media || []).find(x => x.url && !x.fallback)?.url || e.image || state.pickMedia?.[key(e)] || '';
  return `${url && !isExhibit(e) ? `<span class="hl-img"><img src="${esc(url)}" alt="" loading="lazy"></span>` : ''}<span class="hl-tag hl-${e._hl}">${esc(HL_LABEL[e._hl]())}</span>`;
}

// Festival: las actividades del mismo festival en un bloque plegado con su nombre y cuántas hay
// (48h Open House: decenas de edificios el mismo día); con una o dos, filas normales con la etiqueta.
const FEST_FOLD = 3;
// Inauguración o clausura de una exposición (22-10-2026, src/milestones.py).
const MS_LABEL = {opening: () => L('Inauguración', 'Inauguració', 'Opening'), closing: () => L('Clausura', 'Cloenda', 'Closing')};
function msTag(e) { const k = e.milestone?.kind; return MS_LABEL[k] ? `<span class="ms-tag ms-${k}">${esc(MS_LABEL[k]())}</span>` : '' }
// En la ficha: la inauguración dice hasta cuándo sigue la exposición, y la exposición, cuándo se inaugura.
function msLine(e) {
  const k = e.milestone?.kind, link = e.milestone_link, op = e.opening;
  if (MS_LABEL[k]) {
    const more = link ? ` · <button class="linklike" type="button" data-open="${esc(link.key)}">${esc(k === 'opening' ? L(`La exposición sigue hasta el ${labelDate(link.end)}`, `L'exposició continua fins al ${labelDate(link.end)}`, `The exhibition runs until ${labelDate(link.end)}`) : L(`Exposición del ${labelDate(link.start)} al ${labelDate(link.end)}`, `Exposició del ${labelDate(link.start)} al ${labelDate(link.end)}`, `Exhibition from ${labelDate(link.start)} to ${labelDate(link.end)}`))} ›</button>` : '';
    return `<p class="sheet-ms"><span class="ms-tag ms-${k}">${esc(MS_LABEL[k]())}</span>${esc(L(' de la exposición', " de l'exposició", ' of the exhibition'))}${more}</p>`;
  }
  if (op && MS_LABEL[op.kind]) {
    const when = `${labelDay(op.date)}${op.time ? ' · ' + op.time : ''}`;
    return `<p class="sheet-ms"><span class="ms-tag ms-${op.kind}">${esc(MS_LABEL[op.kind]())}</span> ${esc(when)} · <button class="linklike" type="button" data-open="${esc(op.key)}">${esc(L('Ver', 'Mostra', 'See'))} ›</button></p>`;
  }
  return '';
}
function festTag(e) {
  const f = e.festival;
  if (!f && !isFestHead(e)) return '';
  const bare = x => fold(x).replace(/[^a-z0-9]+/g, '');
  // Dentro del desplegable del festival, la primera fila es la ficha general (24-10-2026).
  if (f && f.umbrella && e._inFest) return `<span class="ev-hit ev-fest">${esc(L('Ficha general del festival', 'Fitxa general del festival', 'Festival overview'))}</span>`;
  const name = f && !f.umbrella && !e._inFest && !bare(e.title).includes(bare(f.name)) ? f.name : '';
  // La hora de la ficha general dice qué es: apertura o primera sesión del día (26-10-2026).
  const how = e._a?.festHour === 'primera' ? L('hora de la primera sesión', 'hora de la primera sessió', 'first session time') : e._a?.festHour === 'apertura' ? L('hora de apertura', "hora d'obertura", 'opening time') : '';
  // Ficha general de un festival de abono (28-10-2026, David): una fila al día, a su hora de apertura, con cuántas
  // actuaciones tiene ese día según su programa oficial.
  const n = isFestHead(e) ? e.program_days?.[e._day] : 0, prog = n ? ` · ${n} ${n === 1 ? L('actuación hoy', 'actuació avui', 'show today') : L('actuaciones en el programa', 'actuacions al programa', 'shows in the programme')}` : '';
  // La etiqueta se puede pulsar (28-10-2026, David): filtra la Agenda a ese festival o fiesta y se mantiene al cambiar de día.
  const slug = f?.slug || '', act = slug && !state.fest ? ` data-fest="${esc(slug)}" data-festname="${esc(f.name)}" data-festfiesta="${f.fiesta ? 1 : 0}" data-fesfrom="${esc(e.start)}" data-festo="${esc(e.end)}" role="link" tabindex="0"` : '';
  return `<span class="ev-hit ev-fest${act ? ' is-link' : ''}"${act}><span class="fest-kind">${esc(festKind(e))}</span>${name ? esc(name) : how ? esc(how) : ''}${esc(prog)}${act ? ' <i aria-hidden="true">›</i>' : ''}</span>`;
}
// Dentro del bloque del festival, el título sin el nombre del festival delante («…: Fira de vins» → «Fira de vins»).
function festShort(e) {
  const m = String(e.title).match(/^.{6,120}?["'»”]?\s*:\s+(\S.*)$/);
  return m ? m[1].replace(/^["'«“]|["'»”]$/g, '') : e.title;
}
function festGroup(list) {
  list.forEach(e => { e._inFest = true });
  // Primero la ficha general del festival; luego sus actividades por hora, con las de madrugada (00:00–05:59) al final
  // de la noche, no al principio (MIRA: Arca a la 01:15 va después de Tortoise a las 22:15). 24-10-2026.
  const tm = e => String(e._a?.times?.[0] || e.time || ''), night = t => !t ? '9' : (t < '06:00' ? '2' : '1') + t;
  const general = list.filter(e => e.festival?.umbrella), acts = list.filter(e => !e.festival?.umbrella && !e._festPast), past = list.filter(e => !e.festival?.umbrella && e._festPast);
  acts.sort((a, b) => String(a._day || '').localeCompare(String(b._day || '')) || night(tm(a)).localeCompare(night(tm(b))) || byTitle(a, b));
  const f = (general[0] || list[0]).festival, first = acts.find(e => tm(e));
  const n = acts.length;
  const kind = f.fiesta ? `<span class="fest-kind">${L('Fiesta mayor', 'Festa major', 'Local festival')}</span>` : '';
  const count = n ? `${n.toLocaleString('es-ES')} ${L(n === 1 ? 'actividad' : 'actividades', n === 1 ? 'activitat' : 'activitats', n === 1 ? 'activity' : 'activities')}${first ? ' · ' + L('desde las', 'des de les', 'from') + ' ' + esc(tm(first)) : ''}` : (past.length ? L('Ya ha pasado todo por hoy', 'Ja ha passat tot per avui', 'All over for today') : L('Programa en la ficha general', 'Programa a la fitxa general', 'Programme in the overview'));
  const pastHtml = past.length ? `<details class="ev-more fest-past"><summary>${L('Ya pasado hoy', 'Ja passat avui', 'Already over today')} (${past.length})</summary>${past.map(row).join('')}</details>` : '';
  return `<details class="ev-fest-group"><summary><span class="fest-text"><span class="fest-name">${kind}${esc(f.name)}</span><span class="fest-count">${count}</span></span><i aria-hidden="true">+</i></summary>${[...general, ...acts].map(row).join('')}${pastHtml}</details>`;
}
// Relevancia dentro de una hora o de un día (28-10-2026, David): una señal simple y explicable, sin IA ni ranking
// por prestigio solo. Nivel de la sala (config/venue_prestige.json: referencia 3, consolidada 2, proximidad o sin
// nivel 1), Selección Ontoca, sala relevante, varias fuentes, imagen y descripción propias; los títulos de
// promoción («FREE GUEST LIST», «DOWNLOAD YOUR FREE PASS») restan. La diversidad la pone rankDiverse.
const TIER_PTS = {12: 3, 8: 2};
const PROMO_TITLE = /\b(?:free guest ?list|guest ?list|free pass|download your|free entry list)\b|\|\|/i;
const hasImage = e => Boolean(e.image || (e.media || []).some(m => m.url && !m.fallback));
function relevance(e) {
  let r = TIER_PTS[e.venue_tier] ?? 1;
  if (state.picks.has(key(e))) r += 2;
  if (e.relevant) r += 1;
  if ((e.confirmations || 1) >= 2) r += 0.5;
  if (hasImage(e)) r += 0.5;
  if (e.has_description) r += 0.3;
  if (e._more?.length) r += 2;   // una serie del día reunida en una fila (patios): no se queda detrás de «Ver más»
  if (e.promo || PROMO_TITLE.test(e.title || '')) r -= 2;
  return r;
}
// Los n primeros por relevancia, restando un punto por cada uno ya elegido del mismo grupo (categoría en la Agenda,
// espacio en Expos), y al menos dos de la red de proximidad o de salas sin nivel si las hay: el barrio no queda
// relegado. A igualdad, el orden que traía la lista (la hora). Devuelve el conjunto elegido.
const isLocal = e => !(e.venue_tier >= 8);
// Además (28-10-2026, David), un ajuste suave por espacio: cada sesión ya elegida del mismo sitio resta un punto en la
// misma hora o día (Teatreneu ×8, Jamboree ×2, Palau ×2 ocupaban plazas); no es una cuota, un concierto bueno sigue entrando.
const placeOf = e => fold(String(e.venue_names?.[0] || '').split(/\s+[-·–]\s+/)[0]);
function rankDiverse(list, n, group, score = relevance, penalty = 1, minLocal = 2, local = isLocal, place = null) {
  if (list.length <= n) return new Set(list);
  const pool = list.map(e => ({e, r: score(e)})), out = [], seen = {}, seenPlace = {};
  while (out.length < n && pool.length) {
    let bi = 0, bv = -Infinity;
    pool.forEach((x, i) => { const v = x.r - penalty * (seen[group(x.e)] || 0) - (place ? (seenPlace[place(x.e)] || 0) : 0); if (v > bv) { bv = v; bi = i } });
    const [x] = pool.splice(bi, 1); out.push(x); seen[group(x.e)] = (seen[group(x.e)] || 0) + 1;
    if (place) { const pl = place(x.e); if (pl) seenPlace[pl] = (seenPlace[pl] || 0) + 1 }
  }
  const want = Math.min(minLocal, list.filter(local).length);
  for (let k = out.filter(x => local(x.e)).length; k < want; k++) {
    const add = pool.filter(x => local(x.e)).sort((a, b) => b.r - a.r)[0];
    const drop = out.filter(x => !local(x.e)).sort((a, b) => a.r - b.r)[0];
    if (!add || !drop) break;
    out[out.indexOf(drop)] = add; pool.splice(pool.indexOf(add), 1);
  }
  return new Set(out.map(x => x.e));
}
// Agenda (28-10-2026, David): como mucho diez actividades por hora, las más relevantes y variadas; el resto a un clic
// («Ver N actividades más», se puede volver a plegar). Sin plegar con búsqueda, en Guardados, con «Cerca de mí» o
// cuando los filtros ya dejan una lista manejable. Dentro de la hora, por minuto y luego por relevancia.
// Validación en la web publicada (28-10-2026): no se pliega por 1 a 3 actividades («Ver 3 más» no ayuda) y con filtros
// se deja entero hasta 60 planes del día (con «Música», un jueves: 59).
const HOUR_CAP = 10, HOUR_SLACK = 3, FILTERED_NO_FOLD = 60;
const narrowed = () => Boolean(state.cats.length || state.chans.length || state.district || state.free || state.ages.length || state.langs.length || state.hourFrom !== null || state.hourTo !== null);
const byMinuteThenRelevance = (a, b) => (a._st.sort - b._st.sort) || (relevance(b) - relevance(a)) || byTitle(a, b);
function hourRows(list, id, fold) {
  if (state.near) return seriesFold(nearSort(list));
  if (!fold || list.length <= HOUR_CAP + HOUR_SLACK) return seriesFold([...list].sort(byMinuteThenRelevance));
  const top = rankDiverse(list, HOUR_CAP, e => e.public_category || '', relevance, 1, 3, isLocal, placeOf), open = state.expanded.has(id);
  const first = list.filter(e => top.has(e)).sort(byMinuteThenRelevance), rest = list.filter(e => !top.has(e)).sort(byMinuteThenRelevance);
  const more = open ? `${seriesFold(rest)}<button class="ag-toggle ag-hourless" type="button" data-hourfold="${esc(id)}">${L('Ver menos', 'Mostra’n menys', 'Show fewer')}</button>`
    : `<button class="ag-toggle ag-hourmore" type="button" data-hourfold="${esc(id)}">${L(`Ver ${rest.length} actividades más`, `Mostra ${rest.length} activitats més`, `See ${rest.length} more activities`)}</button>`;
  return seriesFold(first) + more;
}
// Series que se reúnen en una sola fila en todo el día, a la hora de la primera (27-10-2026, David): los patios
// escolares abiertos de un sábado (47) salían repartidos por todas las horas. Sus fichas se ven todas dentro, ordenadas
// por distrito y escuela (cada una con su hora, su dirección y su enlace); el filtro de distrito se aplica antes.
const DAY_SERIES = new Set(['patis-escolars-oberts']);
function gatherSeries(lists) {
  const first = {};
  for (const l of lists) for (const e of l) { e._more = undefined; e._seriesShort = false }
  const out = lists.map(l => l.filter(e => {
    if (!DAY_SERIES.has(e.series)) return true;
    if (!first[e.series]) { first[e.series] = e; e._more = []; return true }
    first[e.series]._more.push(e); return false;
  }));
  const where = e => [t(e.district || ''), e.venue_names?.[0] || ''].join('|');
  for (const e of Object.values(first)) e._more.forEach(x => { x._seriesShort = true });
  for (const e of Object.values(first)) e._more.sort((a, b) => where(a).localeCompare(where(b), 'es') || String(a._a?.times?.[0] || '').localeCompare(String(b._a?.times?.[0] || '')));
  return out;
}
function seriesFold(list) {
  const out = [], seen = {};
  for (const e of list) {
    if (e._more) { out.push(e._more.length ? {first: e, more: e._more, day: true} : e); continue }
    if (!e.series) { out.push(e); continue }
    if (seen[e.series]) { seen[e.series].more.push(e); continue }
    out.push(seen[e.series] = {first: e, more: []});
  }
  return out.map(x => {
    if (!x.first) return row(x);
    if (!x.more.length) return row(x.first);
    // Actividades de un festival: filas normales, sin desplegable (26-10-2026).
    if (String(x.first.series).startsWith('festival:')) return [x.first, ...x.more].map(row).join('');
    const label = x.day ? L(`Ver ${x.more.length} más hoy, por distrito`, `Mostra'n ${x.more.length} més avui, per districte`, `See ${x.more.length} more today, by district`) : `${L('Ver', 'Mostra', 'See')} ${x.more.length} ${L('más de esta serie', 'més d’aquesta sèrie', 'more in this series')}`;
    // Dentro de una serie del día (patios), el nombre de la escuela y un subtítulo por distrito (28-10-2026).
    let lastD = null;
    const inner = x.day ? x.more.map(e => { const d = t(e.district || ''); const head = d && d !== lastD ? `<div class="ag-subhead">${esc(d)}</div>` : ''; lastD = d; return head + row(e) }).join('') : x.more.map(row).join('');
    return `<div class="ev-series">${row(x.first)}<details class="ev-more"><summary>${label}</summary>${inner}</details></div>`;
  }).join('');
}
function rows(list, id) {
  const limit = state.limits[id] || STEP, shown = list.slice(0, limit), left = list.length - shown.length;
  return seriesFold(shown) + (left > 0 ? `<button class="ag-toggle" type="button" data-step="${id}">${L('Ver', 'Mostra', 'See')} ${Math.min(STEP, left)} ${L('más', 'més', 'more')} · ${L('quedan', 'en queden', 'left')} ${left.toLocaleString('es-ES')}</button>` : '');
}
function foldHtml(id, title, list, sub = '') {
  if (!list.length) return '';
  const open = state.expanded.has(id);
  return `<section class="ag-fold${open ? ' open' : ''}" id="ag-${id}"><button class="ag-fold-head" type="button" data-${open ? 'collapse' : 'expand'}="${id}" aria-expanded="${open}"><span>${esc(title)} · <b>${list.length.toLocaleString('es-ES')}</b>${sub ? `<small>${esc(sub)}</small>` : ''}</span><i aria-hidden="true">${open ? '−' : '+'}</i></button>${open ? `<div class="ag-rows">${rows(list, id)}</div>` : ''}</section>`;
}
// Al buscar, en Guardados o en «Arte y galerías» lo que se busca puede estar en cualquier bloque: todos abiertos.
const openAll = () => Boolean(String(state.query || '').trim()) || state.savedOnly || state.chans.includes('galerias');
// Bloque plegable de lista entera (talleres, sin hora): cerrado salvo que se abra o que sea lo principal.
function foldBlock(id, title, list, sub, openByDefault = false, cls = '') {
  if (!list.length) return '';
  const open = state.expanded.has(id) || ((openByDefault || openAll()) && !state.collapsed?.has(id));
  return `<section class="ag-block${open ? ' open' : ''}${cls}" id="ag-${id}"><button class="ag-block-head" type="button" data-block="${id}" aria-expanded="${open}"><span><b>${esc(title)}</b>${sub ? `<small>${esc(sub)}</small>` : ''}</span><em>${open ? L('Plegar', 'Plega', 'Hide') : L('Ver', 'Mostra', 'See')} ${open ? '−' : '›'}</em></button>${open ? `<div class="ag-rows">${rows(list, id)}</div>` : ''}</section>`;
}
// Pestañas Agenda · Exposiciones · Festivales (25-10-2026, David): sustituyen a los bloques de exposiciones y
// festivales. Cada ficha sale en una sola pestaña; la búsqueda y los filtros se aplican a las tres.
// Al buscar (25-10-2026, David) no hay pestañas: se ven las tres a la vez, cada una con su título y su número.
const searching = () => Boolean(String(state.query || '').trim()) && !state.savedOnly;
const TABS = {agenda: ['Agenda', 'Agenda', 'Events'], expo: ['Expos', 'Expos', 'Exhibits']};
// Festivales con FEST_FOLD actividades o más: un desplegable por festival (la regla del antiguo bloque «Festivales»).
// Festivales y fiestas (25-10-2026, David): sin pestaña propia. La ficha del festival va en la Agenda: arriba
// («Festivales y fiestas hoy») si está abierto ahora o no da horario; a su hora de apertura si abre más tarde.
// Sus actos con entrada propia salen a su hora, cada uno con la etiqueta del festival.
// Festivales y fiestas (26-10-2026, simplificación definitiva de David): sin pestaña ni desplegables. La ficha general
// es una ficha más de la Agenda; sus actividades con ficha propia salen a su hora con la etiqueta del festival.
// Una exposición con nombre de festival (World Press Photo, Drap-Art) sigue siendo exposición.
const isFestHead = e => (Boolean(e.festival?.umbrella) || (!e.festival && e.format === 'festival' && e.start !== e.end)) && e.kind !== 'exhibition' && e.format !== 'exhibition';
const SEASON_DAYS = 31;   // temporada o ciclo largo: sin hora de ese día no sale cada día, solo al buscar
// Hora de la ficha general ese día, solo de la fuente y solo de ese día (nunca del intervalo de fechas ni de otro día):
// el horario por días de la fuente (apertura), una sesión fechada de la propia ficha (apertura), la primera sesión de
// ese día en su programa oficial (primera sesión) o la hora puesta a mano por David (con su tipo).
function festSlot(e, day) {
  const man = e.manual_hours?.[day];
  if (man?.time) return {time: man.time, how: man.kind === 'primera' ? 'primera' : 'apertura'};
  const dh = hoursByDay(e)?.[day];
  if (dh) { const r = rangeIn(dh), ts = timesIn(dh); if (r) return {time: clock(r.open), how: 'apertura', endsAt: r.close}; if (ts.length) return {time: ts[0], how: 'apertura'} }
  const occ = (e.occurrences || []).filter(o => o.date === day && o.time).map(o => String(o.time).padStart(5, '0')).sort();
  if (occ.length) return {time: occ[0], how: 'apertura'};
  // La primera sesión del programa oficial ya no da fila (28-10-2026, David): un festival de abono sale a la hora de
  // apertura que da la fuente; sin ella, no sale (su programa sigue en la ficha y en el buscador).
  return null;
}
function festAvailability(e, day) {
  const slot = festSlot(e, day);
  if (slot) return {kind: 'timed', times: [slot.time], festHour: slot.how, ...(slot.endsAt ? {endsAt: slot.endsAt} : {}), until: e.end};
  if (daysBetween(e.start, e.end) > SEASON_DAYS) return {kind: 'run', until: e.end};   // temporada larga: solo al buscar
  return {kind: 'tbc', until: e.end};                                                  // «sin horario confirmado»
}
const festKind = e => e.festival?.fiesta ? L('Fiesta', 'Festa', 'Local festival') : L('Festival', 'Festival', 'Festival');
function tabsHtml(counts) {
  return Object.keys(TABS).map(k => `<button class="period-tab ag-tab${state.tab === k ? ' active' : ''}" type="button" role="tab" aria-selected="${state.tab === k}" data-agtab="${k}">${esc(byLang(TABS[k]))}<span class="ag-tab-n">${counts[k].toLocaleString('es-ES')}</span></button>`).join('');
}
// Sin resultados en la pestaña activa: enlaces a las que sí tienen (así una búsqueda nunca se pierde).
function tabHint(counts) {
  if (searching()) return '';   // al buscar se ven las tres a la vez
  const others = Object.keys(TABS).filter(k => k !== state.tab && counts[k]);
  return others.length ? `<p class="ag-tab-hint">${others.map(k => `<button class="linklike" type="button" data-agtab="${k}">${L('Ver', 'Mostra', 'See')} ${counts[k].toLocaleString('es-ES')} ${L('en', 'a', 'in')} ${esc(byLang(TABS[k]))}</button>`).join(' · ')}</p>` : '';
}
// Exposiciones y espacios abiertos: primero las que terminan antes (último día, luego fecha de fin; decisión
// de David del 25-10-2026) y, a igualdad, la que cierra antes hoy.
// «Selección Ontoca» en Expos (27-10-2026, David): la lista sigue por cierre; en cada tramo de 9 filas se
// destaca como mucho una, la mejor puntuada del tramo (expo_rank del día: peso del espacio, imagen, texto,
// fuentes, recién inaugurada), una por espacio y nunca dos seguidas. La selección de portada va siempre.
function expoHighlights(list) {
  list.forEach(e => { e._hl = '' });
  const rank = state.expoRank || {}, venues = new Set(), venueOf = e => fold(String(e.venue_names?.[0] || '').split(/\s+[-·–]\s+/)[0]);
  for (let from = 0; from < list.length; from += 9) {
    const block = list.slice(from, from + 9).map((e, j) => ({e, i: from + j}))
      .filter(({e, i}) => (state.picks.has(key(e)) || rank[key(e)]) && !venues.has(venueOf(e)) && !list[i - 1]?._hl);
    block.sort((a, b) => (state.picks.has(key(b.e)) - state.picks.has(key(a.e))) || (rank[key(b.e)] || 0) - (rank[key(a.e)] || 0));
    const best = block[0];
    if (best) { best.e._hl = 'pick'; if (venueOf(best.e)) venues.add(venueOf(best.e)) }
  }
}
// Días que le quedan a una exposición (27-10-2026, David): siempre a la vista; con menos de 7, en rojo.
function daysLeft(e) {
  if (!isExhibit(e) || e.start === e.end || !e.end) return '';
  const n = daysBetween(e._day || today, e.end);
  if (n < 0) return '';
  const text = n === 0 ? L('Último día', 'Últim dia', 'Last day') : n === 1 ? ((e._day || today) === today ? L('Cierra mañana', 'Tanca demà', 'Closes tomorrow') : `${L('Cierra el', 'Tanca el', 'Closes on')} ${labelDate(e.end)}`)
    : n <= 60 ? L(`Quedan ${n} días`, `Queden ${n} dies`, `${n} days left`) : `${L('Hasta el', 'Fins al', 'Until')} ${labelDate(e.end)}${e.end.slice(0, 4) !== (e._day || today).slice(0, 4) ? ' ' + e.end.slice(0, 4) : ''}`;
  return `<span class="ev-left${n < 7 ? ' ev-left-soon' : ''}">${esc(text)}</span>`;
}
function wideTab(list, live) {
  const lastDay = e => e.start !== e.end && daysBetween(e._day || today, e._a.until || e.end) <= 0, endOf = e => String(e._a.until || e.end || '9999');
  // Orden de Expos (28-10-2026, David): ya no solo por fecha de cierre (el sábado las 29 primeras eran «último día», 21
  // de centros cívicos y casals, y el MNAC salía el 28). Relevancia de la exposición (nivel del espacio, puesto en la
  // selección de Expos del día, imagen, texto) más la urgencia (último día +1,5; cierra en una semana +0,75), con
  // variedad de espacios y al menos dos de barrio entre las diez primeras; el resto por cierre, como antes.
  const byClose = (a, b) => (lastDay(b) - lastDay(a)) || endOf(a).localeCompare(endOf(b)) || ((a._st.closesIn ?? 1e4) - (b._st.closesIn ?? 1e4)) || byTitle(a, b);
  // Expos por relevancia (28-10-2026, 15:17, David): la urgencia ya no suma puntos (el sábado 7 las tres primeras eran de
  // último día y 10 de 20); se dice con la etiqueta «Último día» / «Cierra mañana» de la fila. Relevancia = las señales de
  // siempre más el puesto en el ranking de Expos del día (expo_rank: espacio, imagen propia, texto, fuentes, recién
  // inaugurada), y en las 20 primeras un espacio solo una vez salvo que no haya otra (penalización, no exclusión), con al
  // menos 4 de barrio o independientes en su sitio natural, no en posiciones fijas. El resto, por relevancia y cierre.
  const rank = state.expoRank || {}, maxRank = Math.max(1, ...Object.values(rank)), left = e => daysBetween(e._day || today, e._a.until || e.end);
  // Un empujón pequeño a lo que cierra (último día +1; esta semana +0,5): una grande en su último día sigue entre las
  // primeras sin que el cierre mande sobre la relevancia.
  const expoScore = e => relevance(e) + (rank[key(e)] ? 1 + 2 * rank[key(e)] / maxRank : 0) + (left(e) <= 0 ? 1 : left(e) <= 7 ? 0.5 : 0);
  const byScore = (a, b) => expoScore(b) - expoScore(a) || byClose(a, b);
  const byClosed = [...list].sort(byScore), place = e => fold(String(e.venue_names?.[0] || '').split(/\s+[-·–]\s+/)[0]);
  // Barrio o independiente en Expos: centros de proximidad (nivel 3) y espacios de arte sin nivel que están en el ranking
  // de Expos (galerías y centros de arte de la lista «exposiciones»); un museo privado sin nivel no cuenta como tal.
  const indie = e => e.venue_tier === 3 || (!e.venue_tier && Boolean(rank[key(e)]));
  const top = state.near ? new Set() : rankDiverse(byClosed, 20, place, expoScore, 1.5, 4, indie);
  const sorted = [...byClosed.filter(e => top.has(e)), ...byClosed.filter(e => !top.has(e))];
  const soonClose = live ? list.filter(e => (e._st.closesIn ?? 1e4) <= 60).length : 0, last = list.filter(lastDay).length;
  const sub = [soonClose ? L(`${soonClose} cierran en menos de una hora`, `${soonClose} tanquen en menys d'una hora`, `${soonClose} close within an hour`) : '', last ? L(`${last} en su último día`, `${last} en el seu últim dia`, `${last} on their last day`) : ''].filter(Boolean).join(' · ');
  if (state.near) sorted.sort((a, b) => (a._km ?? 1e9) - (b._km ?? 1e9));   // con «Cerca de mí», por distancia (a igualdad, el orden de cierre)
  expoHighlights(sorted);
  return (sub ? `<p class="ag-tab-note">${esc(sub)}</p>` : '') + `<div class="ag-rows ag-wide">${rows(sorted, 'wide')}</div>`;
}
// «Abierto ahora» / «Abre hoy» (hoy) o «Durante el día» (otras fechas): cinco filas y el resto a un clic.
const OPEN_FIRST = 5;
// Horario amplio que merece estar en la Agenda (28-10-2026, David): ferias, mercados, fiestas y experiencias temporales con
// recinto propio, fechadas (hasta 6 semanas, o el día nombrado en el horario por días de la fuente). No: lo permanente o de
// meses, talleres, juegos, visitas, congresos, jornadas y actividades de centros cívicos, casals y bibliotecas.
const DAY_PLAN_MAX = 42;
const isDayPlan = (e, day) => daysBetween(e.start, e.end) <= DAY_PLAN_MAX || (hoursByDay(e) && day in hoursByDay(e) && Object.keys(hoursByDay(e)).length <= 12);
const WIDE_SKIP_TITLE = /\b(?:taller|tallers|curs|curso|joc|juego|congr\w*|jornad\w*|campus|trobada|activitat comunitaria|espai d.aprenentatge|visita|visites|audioguia|street escape|concurs)\b/;
// Además, una propuesta concreta (28-10-2026, 10:45, David): el título dice que es una feria, un mercado, una fiesta o un festival.
// Una temporada temática dentro del horario normal de un recinto («Halloween al Tibidabo», «Castaween al Paradox Museum»,
// «Creepy Halloween Family al Poble Espanyol») es la visita de siempre con decorado: no entra. Se decide por lo que es la
// propuesta según su título, nunca por el tipo de recinto (28-10-2026, 11:11: una feria en un centro cívico vale igual).
// La palabra tiene que ser el núcleo del título: al principio (tras ordinal, comillas o «Tots Sants 2026:»), justo tras «:»,
// o «market/fair/fest» al final («Residu Zero Market»). «Taller … de la Festa Major» o «Concurs de cartell de la Festa» no.
const WIDE_EVENT_WORD = '(?:fira|fires|feria|ferias|fair|mercat|mercats|mercado|mercados|market|mercadillo|encants|festa|festes|fiesta|fiestas|festival)';
const WIDE_EVENT = new RegExp(`(?:^|:\\s*)(?:\\d+\\s*[a-z]{0,2}\\.?\\s+|[ivxlc]+\\s+)?["'«“]?\\s*${WIDE_EVENT_WORD}\\b|\\b(?:market|fair|fest)\\s*$`);
const isStrongWide = (e, day) => { const t = fold(e.title).replace(/^tots sants \d{4}:\s*/, ''); return !isExhibit(e) && !e._a.noHours && isDayPlan(e, day)
  && WIDE_EVENT.test(t) && !WIDE_SKIP_TITLE.test(t) };
// Recordatorio de la tarde (28-10-2026, David): una feria abierta desde antes de las 15:00 vuelve a aparecer a las 15:00 como
// línea corta («Sigue abierta hasta las 20:00»), si el tramo que cubre las 15:00 cierra a una hora fiable a las 17:00 o después.
// Misma ficha, no cuenta en los totales ni ocupa sitio en la hora. Pasada la apertura desaparece la fila; pasadas las 15:00,
// el recordatorio. Se ven 3 y el resto con «Ver más».
const REMIND_AT = 15 * 60, REMIND_SHOW = 3;
function remindLine(e) {
  return `<button class="ag-remind" type="button" data-open="${esc(key(e))}"><span>${esc(L('Sigue abierta hasta las', 'Segueix oberta fins a les', 'Still open until'))} ${clock(e._remindClose ?? e._a.close)}</span><b>${esc(e.title)}</b><i aria-hidden="true">›</i></button>`;
}
function renderDay(m) {
  const s = m.sections, show = state.show, live = m.live;
  const counts = {fixed: s.fixed.length, wide: s.wide.length + s.wideNoHours.length, tbc: s.tbc.length, soon: s.soon.length};
  const hourOf = e => hourKey(e), seasonLast = e => e._a.season ? 1 : 0;
  // La Agenda es cronológica y solo de sesiones con hora de inicio (28-10-2026, David). Un horario de apertura no convierte
  // nada en plan del día: ferias, mercados, espacios y «parades de castanyes» con horario amplio se tratan pero no se
  // enseñan; solo al buscar, en Guardados o dentro del filtro de un festival. Las exposiciones tienen su pestaña.
  let timeline = [...s.fixed].sort((a, b) => Number(hourOf(a)) - Number(hourOf(b)) || seasonLast(a) - seasonLast(b) || a._st.sort - b._st.sort || byTitle(a, b));
  let html = chipsHtml(counts), current = null, groups = '';
  const wideAllDay = [...s.wide, ...s.wideNoHours], wideList = wideAllDay.filter(isExhibit);
  // «Durante el día» (28-10-2026, David): bloque reducido con ferias, mercados y experiencias de horario amplio que son
  // planes de estos días (fechados: hasta 6 semanas, o un día concreto en el horario por días de la fuente). Lo permanente
  // o de meses (audioguías, parades de castanyes, espacios de aprendizaje, campus) no sale; se puede buscar.
  // Horario amplio fuerte (isStrongWide): una fila a su hora de apertura; si ya está abierta hoy, en «En curso». El resto no se enseña.
  const strong = wideAllDay.filter(e => isStrongWide(e, state.day) && e._st.state !== 'past');
  // Solo lo que está por venir (28-10-2026, 10:45, David): sin «En curso» ni «Anteriores». Lo ya abierto hoy no tiene fila;
  // si aún no son las 15:00, le queda el recordatorio.
  timeline = [...timeline, ...strong.filter(e => e._st.state !== 'open')].sort((a, b) => Number(hourOf(a)) - Number(hourOf(b)) || seasonLast(a) - seasonLast(b) || a._st.sort - b._st.sort || byTitle(a, b));
  let tbcList = [...s.tbc, ...wideAllDay.filter(e => !isExhibit(e) && !strong.includes(e))].sort(byTitle);
  [timeline, tbcList] = gatherSeries([timeline, tbcList]);
  const fests = festStrip(timeline, state.day); timeline = fests.rest;
  // Abierta a las 15:00 de verdad: el tramo que la cubre (un horario partido «09:00–13:30 · 16:00–17:30» no vale) y 2 h por delante.
  const span15 = e => (e._a.ranges || [{open: e._a.open, close: e._a.close}]).find(r => r.open <= REMIND_AT && r.close - REMIND_AT >= 120 && r.close <= 1440);
  const remindable = live && m.now.min >= REMIND_AT ? [] : strong.filter(e => e._a.close != null && e._a.open < REMIND_AT && span15(e));
  const reminders = remindable.sort((a, b) => relevance(b) - relevance(a) || byTitle(a, b));
  reminders.forEach(e => { e._remindClose = span15(e).close });
  markHighlights(timeline, state.day);
  // Planes sin hora (28-10-2026, David): se tratan pero no se enseñan en la Agenda; solo al buscar, en Guardados o en el
  // filtro de un festival (ahí se ve todo lo suyo, también su ficha general). La Agenda es lo que tiene hora con confianza alta.
  const showTbc = searching() || state.savedOnly || Boolean(state.fest);
  const tabCounts = {agenda: timeline.length + remindable.filter(e => !timeline.includes(e)).length + (showTbc ? tbcList.length : 0), expo: wideList.length};
  const foldHours = !searching() && !state.savedOnly && !state.fest && !(narrowed() && timeline.length <= FILTERED_NO_FOLD);
  // Hoy la Agenda empieza en la hora actual (28-10-2026, David): lo anterior, ya empezado o acabado, queda arriba plegado.
  const plans = n => `${n.toLocaleString('es-ES')} ${n === 1 ? L('plan', 'pla', 'plan') : L('planes', 'plans', 'plans')}`;
  let bucket = [];
  const flush = () => { if (current !== null) groups += hourRows(bucket, `h:${state.day}:${current}`, foldHours) + '</div>'; bucket = [] };
  const headOf = (h, n) => groupHead(`${Number(h) >= 24 ? `${String(Number(h) - 24).padStart(2, '0')} h · ${L('madrugada', 'matinada', 'after midnight')}` : `${h} h`} · ${plans(n)}`);
  const perHour = {}; for (const e of timeline) perHour[hourOf(e)] = (perHour[hourOf(e)] || 0) + 1 + (e._more ? e._more.length : 0);
  const rid = `r:${state.day}`, ropen = state.expanded.has(rid), rleft = reminders.length - REMIND_SHOW;
  const remindHtml = reminders.length ? `<div class="ag-reminders">${(ropen ? reminders : reminders.slice(0, REMIND_SHOW)).map(remindLine).join('')}${rleft > 0 ? `<button class="ag-toggle ${ropen ? 'ag-hourless' : 'ag-hourmore'}" type="button" data-hourfold="${esc(rid)}">${ropen ? L('Ver menos', 'Mostra’n menys', 'Show fewer') : L(`Ver ${rleft} más que siguen abiertas`, `Mostra'n ${rleft} més que segueixen obertes`, `See ${rleft} more still open`)}</button>` : ''}</div>` : '';
  let reminded = !remindHtml;
  const openReminders = () => { flush(); groups += `<div class="ag-group">${groupHead(perHour['15'] ? `15 h · ${plans(perHour['15'])}` : '15 h')}${remindHtml}`; current = '15'; reminded = true };
  for (const e of timeline) {
    const h = hourOf(e);
    if (!reminded && Number(h) >= 15) { if (h === '15') { if (current !== '15') openReminders() } else { openReminders(); flush(); current = null } }
    if (h !== current) { flush(); groups += `<div class="ag-group">${headOf(h, perHour[h])}`; current = h }
    bucket.push(e);
  }
  if (!reminded) openReminders();
  flush();
  if (state.query && s.run.length) groups += `<div class="ag-group" id="ag-run">${groupHead(L('Ciclos y temporadas sin fechas de sesión', 'Cicles i temporades sense dates de sessió', 'Series and seasons without session dates'))}${rows(s.run, 'run')}</div>`;
  if (state.started && s.started.length) groups += `<div class="ag-group" id="ag-started">${groupHead(L('Talleres y cursos ya empezados', 'Tallers i cursos ja començats', 'Workshops and courses already under way'))}${rows(s.started, 'started')}</div>`;
  if (!groups) groups = `<div class="empty">${live ? L('Por hoy ya no queda nada con estos filtros. Mira mañana o quita algún filtro.', 'Per avui ja no queda res amb aquests filtres. Mira demà o treu algun filtre.', 'Nothing left today with these filters. Look at tomorrow or remove a filter.') : t('Nada con estos filtros este día. Prueba otro día o quita algún filtro.')}${tabHint(tabCounts)}</div>`;
  // Lo ya acabado o empezado sin hora de fin fiable no se enseña (28-10-2026, David: su valor es marginal).
  html += fests.html + `<div class="ag-timeline">${groups}</div>`;
  if (showTbc) html += foldBlock('tbc', L(`${tbcList.length} planes sin hora de inicio`, `${tbcList.length} plans sense hora d'inici`, `${tbcList.length} plans without a start time`), tbcList, L('Espacios y ferias de horario amplio, festivales en varios espacios y actos sin hora publicada', "Espais i fires d'horari ampli, festivals en diversos espais i actes sense hora publicada", 'Open-hours venues and fairs, festivals across venues and events with no published time'), false, ' is-tbc');
  html += foldHtml('other', L('Otras actividades', 'Altres activitats', 'Other activities'), s.other, L('Sin tipo claro; las revisaremos', 'Sense tipus clar; les revisarem', 'No clear type; we will review them'));
  return {html: {agenda: html, expo: wideTab(wideList, live)}, counts: tabCounts};
}
// Fichas generales de festival (28-10-2026, David): no son una sesión a una hora; van en su propia línea al principio del
// día («Festivales hoy: Mozilla Festival · Mostra de cinema emergent»), cada una abre su ficha con el programa.
function festStrip(list, day) {
  const heads = list.filter(e => isFestHead(e) && !state.fest);
  if (!heads.length) return {html: '', rest: list};
  // Plegados en una línea y, al abrir, filas iguales con el nombre (28-10-2026, 19:34, David).
  const rows = heads.map(e => `<button type="button" class="ag-festrow" data-open="${esc(key(e))}"><span>${esc(e.festival?.name || e.title)}</span><i aria-hidden="true">›</i></button>`).join('');
  const label = day === today ? L('Festivales hoy', 'Festivals avui', 'Festivals today') : L('Festivales', 'Festivals', 'Festivals');
  return {html: `<details class="ag-fests"><summary>${esc(label)} <b>${heads.length}</b></summary><div class="ag-festrows">${rows}</div></details>`, rest: list.filter(e => !heads.includes(e))};
}
function dayHeading(d) {
  const date = new Date(d + 'T12:00:00'), rel = d === today ? L('Hoy', 'Avui', 'Today') : d === addDays(today, 1) ? L('Mañana', 'Demà', 'Tomorrow') : '';
  const weekend = date.getDay() === 0 || date.getDay() === 6;
  return `<div class="ag-stick ag-daystick${weekend ? ' is-weekend' : ''}"><span>${rel ? `<b>${rel}</b> · ` : ''}${esc(`${weekdaysLong[date.getDay()]} ${date.getDate()} ${months[date.getMonth()]}`)}</span>${weekend ? `<em>${L('fin de semana', 'cap de setmana', 'weekend')}</em>` : ''}</div>`;
}
function renderRange(m) {
  const show = state.show, s = m.sections;
  // Solo sesiones con hora de inicio (28-10-2026, David): ni «sin hora» ni horario amplio, salvo al buscar, en Guardados o en el filtro de un festival.
  const visible = e => (e._a.kind !== 'wide' || !isExhibit(e)) && (e._a.kind !== 'run' || Boolean(state.query)) && (Boolean(state.query) || state.savedOnly || Boolean(state.fest) || (e._a.kind !== 'tbc' && (e._a.kind !== 'wide' || isStrongWide(e, e._day))));
  const counts = {...m.counts, soon: s.soon.length};
  const seenWide = new Set(), wideAll = [];
  for (const [, l] of m.buckets) for (const e of l) if (e._a.kind === 'wide' && isExhibit(e) && !seenWide.has(key(e))) { seenWide.add(key(e)); wideAll.push(e) }
  const buckets = m.buckets.map(([d, l]) => [d, l.filter(visible)]).filter(([, l]) => l.length);
  const tabCounts = {agenda: buckets.reduce((n, [, l]) => n + l.length, 0), expo: wideAll.length};
  const days = buckets.slice(0, state.shown).map(([d, dayList]) => {
    const [list0] = gatherSeries([nearSort(dayList)]);
    const fests = festStrip(list0, d), list = fests.rest;
    const all = state.openDays.has(d) || list.length <= PER_DAY + 3, top = all || state.near ? null : rankDiverse(list, PER_DAY, e => e.public_category || '', relevance, 1, 4, isLocal, placeOf);
    const shown = all ? list : state.near ? list.slice(0, PER_DAY) : list.filter(e => top.has(e));
    markHighlights(shown, d);
    return `<div class="ag-group ag-day" id="day-${d}">${dayHeading(d)}${fests.html}${seriesFold(shown)}${all ? '' : `<button class="ag-toggle ag-dayall" type="button" data-dayall="${d}">${L('Ver las', 'Mostra les', 'See all')} ${list.length.toLocaleString('es-ES')} ${L('de este día', 'd\'aquest dia', 'on this day')}</button>`}</div>`;
  }).join('');
  const rest = buckets.slice(state.shown).reduce((n, [, l]) => n + l.length, 0);
  let html = chipsHtml(counts) + `<div class="ag-timeline">${days || `<div class="empty">${t('Nada con estos filtros este día. Prueba otro día o quita algún filtro.')}${tabHint(tabCounts)}</div>`}</div>`;
  if (rest) html += `<button class="ag-toggle ag-moredays" type="button" data-moredays="1">${L('Ver más días', 'Mostra més dies', 'See more days')} · ${rest.toLocaleString('es-ES')} ${L('actividades más', 'activitats més', 'more activities')}</button>`;
  if (state.started && s.started.length) html += `<div class="ag-group" id="ag-started">${groupHead(L('Talleres y cursos ya empezados', 'Tallers i cursos ja començats', 'Workshops and courses already under way'))}${rows(s.started, 'started')}</div>`;
  html += foldHtml('other', L('Otras actividades', 'Altres activitats', 'Other activities'), s.other);
  return {html: {agenda: html, expo: wideTab(wideAll, false), }, counts: tabCounts};
}
function venueView(items) {
  const groups = {};
  for (const e of items) { const name = e.venue_names?.[0] || t('Sin recinto identificado'); (groups[name] ??= []).push(e) }
  return `<div class="venue-groups">${Object.entries(groups).sort((a, b) => a[0].localeCompare(b[0])).map(([name, events]) => `<details><summary><span>${esc(name)}</span><b>${events.length}</b></summary><div>${seriesFold(events)}</div></details>`).join('')}</div>`;
}
function renderAgenda() {
  for (const e of state.items) e._km = state.near && e.coordinates && onePlace(e) ? kmTo(state.near, e.coordinates) : null;
  const host = $('agendaList'), items = state.near && state.nearKm ? state.items.filter(e => e._km != null && e._km <= state.nearKm) : state.items, win = state.savedOnly ? {from: today, to: addDays(today, MAX_DAYS)} : rangeWindow();
  const model = state.model = buildModel(items, win);
  document.getElementById('seoLista')?.remove();   // la lista en HTML de las páginas de entrada (src/landings.py): ya está la de la app
  // El filtro «Formato» se solapa con los botones de tipo: se retira y su apartado queda solo para los talleres ya empezados.
  const fmt = $('formatFilter'), group = fmt?.closest('fieldset');
  if (group && !group.dataset.v3) {
    group.dataset.v3 = '1'; fmt.hidden = true; fmt.value = '';
    // Sin el desplegable, el apartado solo serviría para los talleres ya empezados, que no son
    // información útil (22-10-2026): se oculta entero.
    group.hidden = true;
  }
  // Con «Arte» como única categoría se abre Exposiciones, como antes el bloque (25-10-2026).
  const catsKey = state.cats.join(',');
  if (catsKey !== state.catsKey) { if (state.catsKey !== undefined && catsKey === 'arte') state.tab = 'expo'; state.catsKey = catsKey }
  let tabs = $('agTabs');
  if (!tabs) { tabs = document.createElement('div'); tabs.id = 'agTabs'; tabs.className = 'period-tabs ag-tabs'; tabs.setAttribute('role', 'tablist'); host.before(tabs) }
  tabs.hidden = true;
  let tabCounts = null;
  if (!items.length) host.innerHTML = `<div class="empty">${t('Nada con estos filtros este día. Prueba otro día o quita algún filtro.')}</div>`;
  else if (state.view === 'map') { const s = model.sections, located = [...s.fixed, ...(model.buckets || []).flatMap(([, l]) => l), ...s.wide].filter(onePlace).slice(0, 600); host.innerHTML = mapView(located); hydrateMap(located) }
  else if (state.view === 'venue') host.innerHTML = venueView(items.filter(e => !['started'].includes(e._a?.kind)));
  else {
    const r = model.mode === 'day' ? renderDay(model) : renderRange(model); tabCounts = state.tabCounts = r.counts;
    tabs.innerHTML = tabsHtml(r.counts); tabs.hidden = searching();
    const parts = Object.keys(TABS).filter(k => r.counts[k]);
    if (searching()) host.innerHTML = parts.length ? parts.map(k => `<section class="ag-part" id="ag-part-${k}"><h3 class="ag-part-head">${esc(byLang(TABS[k]))} <span>${r.counts[k].toLocaleString('es-ES')}</span></h3>${r.html[k]}</section>`).join('') : r.html.agenda;
    else host.innerHTML = r.counts[state.tab] || state.tab === 'agenda' ? r.html[state.tab]
      : `<div class="empty">${state.tab === 'expo' ? L('No hay exposiciones con estos filtros.', 'No hi ha exposicions amb aquests filtres.', 'No exhibitions with these filters.') : ''}${tabHint(r.counts)}</div>`;
  }
  $('agendaMore').innerHTML = '';
  // Sumatorio = suma exacta de los tres botones del día (hora fija + horario amplio + por confirmar).
  const s = model.sections, count = model.mode === 'day' ? s.fixed.length + s.wide.length + s.wideNoHours.length + s.tbc.length : (model.counts.fixed + model.counts.wide + model.counts.tbc), n = count.toLocaleString('es-ES');
  // Búsqueda interna (Matomo trackSiteSearch): con los resultados ya pintados; analytics.js espera a que el término se estabilice.
  if (state.query && !state.savedOnly) { try { window.ontocaAnalytics?.search(state.query, count, state.cats.length === 1 ? state.cats[0] : false) } catch (_) {} }
  // Cabecera con los mismos números que las pestañas (28-10-2026: decía «116 planes» con «Agenda 35» debajo, porque
  // sumaba las exposiciones): planes de la Agenda y, aparte, exposiciones abiertas.
  const ag = tabCounts ? tabCounts.agenda.toLocaleString('es-ES') : n, ex = tabCounts?.expo ? ` · ${tabCounts.expo.toLocaleString('es-ES')} ${L('exposiciones', 'exposicions', 'exhibitions')}` : '';
  const lead = model.mode === 'day' && model.live ? `<b>${ag} ${L('planes disponibles hoy', 'plans disponibles avui', 'plans available today')}</b> ${L('desde las', 'des de les', 'from')} ${clock(model.now.min)}${ex}`
    : model.mode === 'day' ? `<b>${ag} ${L('planes', 'plans', 'plans')}</b> · ${esc(labelDay(state.day))}${ex}` : `<b>${ag} ${L('planes', 'plans', 'plans')}</b> · ${esc(win.label)}${ex}`;
  const extra = [state.cats.map(catName).join(' + '), state.chans.map(chanName).join(' + '), state.ages.map(a => byLang(AGE_LABEL[a])).join(' + '), state.query ? `“${state.query}”` : ''].filter(Boolean).map(esc).join(' · ');
  $('agendaCount').innerHTML = state.savedOnly ? `<b>${items.length}</b> ${t('guardados')}` : lead + (extra ? ` · ${extra}` : '');
  stick(); mountFilterUi();
}
// Móvil: pie fijo en el panel de filtros («Ver N planes» cierra y deja claro que ya están aplicados)
// (la barra de filtros fija hace de acceso permanente; ya no hay botón flotante).
function mountFilterUi() {
  if (!$('filtersFoot')) {
    const foot = document.createElement('div'); foot.id = 'filtersFoot'; foot.className = 'filters-foot';
    foot.innerHTML = `<button id="filtersClear" class="filters-clear" type="button">${L('Limpiar', 'Esborra', 'Clear')}</button><button id="filtersApply" class="filters-apply" type="button"></button>`;
    $('filters').append(foot);
  }
  const n = state.tabCounts ? state.tabCounts.agenda + (state.tabCounts.expo || 0) : state.model ? (state.model.mode === 'day' ? state.model.sections.fixed.length + state.model.sections.wide.length + state.model.sections.wideNoHours.length + state.model.sections.tbc.length : state.model.counts.fixed + state.model.counts.wide + state.model.counts.tbc) : 0;
  $('filtersApply').textContent = `${L('Ver', 'Mostra', 'See')} ${n.toLocaleString('es-ES')} ${L('planes', 'plans', 'plans')}`;
}
$('curated')?.addEventListener('scroll', () => requestAnimationFrame(pickNav), {passive: true});
window.addEventListener('resize', () => requestAnimationFrame(pickNav));
// --stick: cabecera; --agtop: cabecera + barra de filtros fija (móvil), donde se pegan las pestañas; --daytop: debajo de las pestañas.
function stick() {
  const root = document.documentElement.style, h = document.querySelector('.site-header'), hh = h ? h.getBoundingClientRect().height : 0;
  const bar = $('filterBar'), fb = bar && getComputedStyle(bar).position === 'sticky' ? bar.getBoundingClientRect().height : 0;
  const tabs = $('agTabs'), th = tabs && !tabs.hidden ? tabs.getBoundingClientRect().height : 0;
  root.setProperty('--stick', hh + 'px'); root.setProperty('--agtop', hh + fb + 'px'); root.setProperty('--daytop', hh + fb + th + 'px');
}
window.addEventListener('resize', () => requestAnimationFrame(stick), {passive: true});
function stableRender() {
  const rowsEls = [...document.querySelectorAll('#agendaList .ev')], top = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--stick')) || 0;
  const anchor = rowsEls.find(r => r.getBoundingClientRect().bottom > top + 40), k = anchor?.querySelector('[data-open]')?.dataset.open, y = anchor?.getBoundingClientRect().top;
  renderAgenda();
  if (k) { const again = document.querySelector(`#agendaList [data-open="${CSS.escape(k)}"]`)?.closest('.ev'); if (again) window.scrollBy(0, again.getBoundingClientRect().top - y) }
}
let liveMinute = null;
setInterval(() => {
  const now = madridNow(); if (now.min === liveMinute) return; liveMinute = now.min;
  if (state.model && !state.savedOnly && state.view === 'list' && (state.model.mode === 'range' || state.model.live) && $('overlay').hidden) stableRender();
}, 20000);

function collectStatic(all, win, p) {
  const filters = {cat: p.cats, chans: p.chans, ages: p.ages, langs: p.langs, format: p.format, district: p.district, free: p.free, query: fold(p.query || ''), hourFrom: p.hourFrom, hourTo: p.hourTo};
  const from = win ? win.from : state.day, to = win ? win.to : state.day, ahead = addDays(from, COURSE_AHEAD);
  const out = [];
  for (const base of all) {
    const active = base.start <= to && base.end >= from;
    const upcomingCourse = !active && isPeriodic(base) && !isOpenFormat(base) && base.start > to && base.start <= ahead && daysBetween(base.start, base.end) > SHORT_DAYS;
    if (!active && !upcomingCourse) continue;
    if (filters.query && !queryMatches(searchText(base), filters.query)) continue;
    if (p.fest && base.festival?.slug !== p.fest) continue;   // etiqueta de festival o fiesta pulsada (28-10-2026)
    if (!catMatch(base, filters.cat) || !chanMatch(base, filters.chans) || !ageMatch(base, filters.ages) || !langMatch(base, filters.langs)) continue;
    if (filters.format && base.format !== filters.format) continue;
    if (filters.free && !base.is_free) continue;
    if (filters.district && base.district !== filters.district) continue;
    const e = {...base, base_time: base.time};
    if (filters.hourFrom !== null || filters.hourTo !== null) {
      const inRange = x => { const h = Number(String(x).slice(0, 2)); return h >= (filters.hourFrom ?? 0) && h <= (filters.hourTo ?? 23) };
      const inWindow = o => win || o.date === state.day;
      const occ = (e.occurrences || []).filter(o => inWindow(o) && o.time);
      if (occ.length) {
        if (!occ.some(o => inRange(o.time))) continue;
        // Varios pases: se muestra el primero dentro de la franja elegida, no el primero del día.
        e.occurrences = (e.occurrences || []).filter(o => !o.time || !inWindow(o) || inRange(o.time));
        const first = e.occurrences.find(o => inWindow(o) && o.time);
        if (first && !win) { e.time = first.time; e.base_time = first.time }
      } else {
        const label = String(e.time_label || '') + ' ' + String(e.time || ''), ts = timesIn(label);
        if (!ts.some(inRange)) continue;
        // Pases en texto («20:30 · 22:30»): el primero de la franja. Un horario de apertura («12:00–21:00») no se toca.
        if (ts.length > 1 && !/[–-]/.test(label)) { const kept = ts.filter(inRange); e.time = kept[0]; e.base_time = kept.join(' · ') }
      }
    }
    out.push(e);
  }
  return out;
}
async function agenda(append = false) {
  const host = $('agendaList'), request = ++agendaRequest; host.setAttribute('aria-busy', 'true');
  if (!append) { state.shown = DAY_CHUNK; state.limits = {}; state.openDays = new Set() }
  try {
    if (state.savedOnly) {
      const items = await Promise.all(state.saved.map(async k => { const [source, ...id] = k.split(':'); try { return await get('/api/event?' + new URLSearchParams({source, id: id.join(':')})) } catch (_) { return null } }));
      state.items = items.filter(Boolean).filter(hourMatches).map(e => ({...e, base_time: e.time})); state.total = state.items.length;
    } else {
      const win = rangeWindow();
      if (STATIC) {
        if (!store.catalog) host.innerHTML ||= `<div class="ag-loading">${L('Cargando la agenda…', 'Carregant l\'agenda…', 'Loading the listings…')}</div>`;
        const all = await loadCatalog();
        if (request !== agendaRequest) return;
        state.items = collectStatic(all, win, state);
        // Selección Ontoca de ese día (la de la portada): se destaca también en la lista.
        try { const df = await dayFile(win ? today : state.day); state.picks = new Set([...(df.featured || []).map(c => `${c.s}:${c.i}`), ...(df.highlight || [])]); state.expoRank = df.expo_rank || {}; state.pickMedia = Object.fromEntries([...(df.featured || []), ].filter(c => c.m?.[0]?.u && !c.m[0].fb).map(c => [`${c.s}:${c.i}`, c.m[0].u])); Object.assign(state.pickMedia, df.highlight_media || {}) } catch (_) { state.picks = new Set(); state.expoRank = {} }
        if (request !== agendaRequest) return;
      } else {
        const p = new URLSearchParams({...(win ? {date_from: win.from, date_to: win.to} : {day: state.day}), public_category: state.cats.length === 1 ? state.cats[0] : '', channel: state.chans.length === 1 ? state.chans[0] : '', format: state.format, district: state.district, free: state.free ? '1' : '', query: state.query, hour_from: state.hourFrom ?? '', hour_to: state.hourTo ?? '', started: '1', page: '1', page_size: '5000', public: '1'});
        const d = await get('/api/events?' + p);
        if (request !== agendaRequest) return;
        state.items = d.items.filter(e => catMatch(e, state.cats) && chanMatch(e, state.chans) && ageMatch(e, state.ages) && langMatch(e, state.langs) && (!state.fest || e.festival?.slug === state.fest)).map(e => ({...e, base_time: e.time}));
      }
      state.total = state.items.length;
    }
    renderAgenda();
  } catch (_) { host.innerHTML = `<div class="empty">${t('No se pudo cargar la agenda.')} <button id="retry" class="linklike" type="button">${t('Reintentar')}</button></div>` }
  finally { host.removeAttribute('aria-busy') }
}

function mapView(items) {
  const located = items.filter(e => e.coordinates && Number.isFinite(e.coordinates.lat) && Number.isFinite(e.coordinates.lon));
  if (!located.length) return `<div class="empty">${t('No hay ubicaciones geográficas para estos filtros. Prueba otro día o consulta la lista.')}</div>`;
  return `<div class="event-map" role="group" aria-label="${t('Mapa de actividades geolocalizadas')}"><div id="eventMap" class="map-canvas"></div><div class="map-note">${located.length} ${t('lugares con ubicación · pulsa un punto para abrir la ficha')}</div></div>`;
}
function hydrateMap(items) {
  const canvas = $('eventMap'), located = items.filter(e => e.coordinates && Number.isFinite(e.coordinates.lat) && Number.isFinite(e.coordinates.lon));
  if (!canvas || !window.L || !located.length) return;
  const map = window.L.map(canvas, {scrollWheelZoom: true, zoomControl: true, attributionControl: true});
  window.L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19, attribution: '© OpenStreetMap contributors'}).addTo(map);
  const bounds = [];
  for (const event of located) {
    const point = [event.coordinates.lat, event.coordinates.lon], name = event.venue_names?.[0] || event.title;
    window.L.circleMarker(point, {radius: 8, color: '#ffffff', weight: 2, fillColor: '#b7a9ff', fillOpacity: 1}).addTo(map).bindTooltip(esc(name), {direction: 'top', offset: [0, -7]}).on('click', () => openDetail(key(event), canvas, {origin: 'mapa'}));
    bounds.push(point);
  }
  if (bounds.length === 1) map.setView(bounds[0], 15); else map.fitBounds(bounds, {padding: [34, 34], maxZoom: 15});
}
function sortItems(items) { return items.sort((a, b) => Boolean(b.time) - Boolean(a.time) || String(a.time || '').localeCompare(String(b.time || '')) || b.start.localeCompare(a.start)) }
async function loadDistricts() {
  try {
    const rows = await get('/api/districts?day=' + state.day);
    // 23-10-2026: el bloque «Por distritos» ya no está en la página; solo se rellena el desplegable del panel.
    if ($('districts')) $('districts').innerHTML = rows.map(x => `<button class="district ${state.district === x.name ? 'active' : ''}" type="button" data-district="${esc(x.name)}"><b>${esc(t(x.name))}</b><span>${x.count}</span></button>`).join('');
    $('districtFilter').innerHTML = `<option value="">${t('Todos los distritos')}</option>${[...rows].sort((x, y) => collator.compare(t(x.name), t(y.name))).map(x => `<option value="${esc(x.name)}" ${state.district === x.name ? 'selected' : ''}>${esc(t(x.name))}</option>`).join('')}`;
  } catch (_) { if ($('districts')) $('districts').innerHTML = '' }
}

/* ---------- detail ---------- */
// «23:59» es como Xceed escribe «medianoche».
// «00:00–23:59» (fachadas, espacios al aire libre: «Cada dia de 00.00 h a 23.59 h») es todo el día.
const showTime = v => String(v || '').replace(/\b0?0[:.]00\s*[–-]\s*23[:.]59\b/g, L('todo el día', 'tot el dia', 'all day')).replace(/\b23:59\b/g, L('medianoche', 'mitjanit', 'midnight'));
// «Forma parte de 48h Open House BCN · Ver todo el festival»; en la ficha del festival, cuántas actividades tiene.
function festLine(e) {
  const f = e.festival || (store.catalog || []).find(x => x.key === e.key)?.festival;
  // Hora de ese día y de dónde sale (apertura o primera sesión; si es manual, con su fuente). 26-10-2026.
  const d = e.start === e.end ? e.start : state.day, slot = isFestHead(e) ? festSlot(e, d) : null, man = e.manual_hours?.[d];
  const hourLine = slot ? `<p class="sheet-fest-hour">${esc(slot.how === 'primera' ? L('Primera sesión de ese día', "Primera sessió d'aquell dia", 'First session that day') : L('Apertura ese día', 'Obertura aquell dia', 'Opening that day'))}: <b>${esc(slot.time)}</b>${man?.source && safeurl(man.source) ? ` · <a href="${esc(safeurl(man.source))}" target="_blank" rel="noopener noreferrer">${esc(L('fuente', 'font', 'source'))} ↗</a>` : ''}</p>` : '';
  if (!f) return isFestHead(e) ? `<p class="sheet-fest"><span class="fest-kind">${esc(festKind(e))}</span></p>${hourLine}` : '';
  const n = festSessions(f.slug);
  // Ficha del festival con sesiones recuperadas (28-10-2026, David): «12 sesiones · Ver programa». Sin fila sin hora en la Agenda.
  const label = f.umbrella ? L(`${n} ${n === 1 ? 'sesión' : 'sesiones'} · Ver programa`, `${n} ${n === 1 ? 'sessió' : 'sessions'} · Mostra el programa`, `${n} ${n === 1 ? 'session' : 'sessions'} · See programme`) : L('Ver todo el festival', 'Mostra tot el festival', 'See the whole festival');
  return `<p class="sheet-fest"><span class="fest-kind">${esc(festKind({festival: f}))}</span>${f.umbrella ? '' : L('Forma parte de', 'Forma part de', 'Part of') + ' '}<b>${esc(f.name)}</b>${n ? ` · <button class="linklike" type="button" data-fest="${esc(f.slug)}" data-festname="${esc(f.name)}" data-festfiesta="${f.fiesta ? 1 : 0}" data-fesfrom="${esc(e.start)}" data-festo="${esc(e.end)}">${label}</button>` : ''}</p>${hourLine}`;
}
// Sesiones con fecha de un festival en el catálogo (sus actos con ficha propia).
const festSessions = slug => (store.catalog || []).filter(x => x.festival?.slug === slug && !x.festival.umbrella).length;
function detailWhen(e) {
  const day = e.start === e.end ? e.start : state.day;
  // Ficha general de un festival con sesiones: en vez de «Hora no indicada», «Varias sesiones» (28-10-2026).
  if (e.festival?.umbrella && !e.time && !Object.keys(hoursByDay(e) || {}).length && festSessions(e.festival.slug) > 1)
    return `${e.start === e.end ? labelDay(e.start) : `${labelDate(e.start)} – ${labelDate(e.end)}`} · ${L('Varias sesiones', 'Diverses sessions', 'Several sessions')}`;
  const when = e.start === e.end ? labelDay(e.start) : `${labelDate(e.start)} – ${labelDate(e.end)}`;
  // Funciones en días sueltos con su hora (28-10-2026, David: «En Joan sense por», 31-10, 1, 7 y 8-11, solo se veía un día):
  // hasta 8 días, todos con sus horas, venga de donde venga la ficha.
  const sessions = Object.entries(hoursByDay(e) || {}).filter(([d, h]) => d >= today && timesIn(h).length).sort((a, b) => a[0].localeCompare(b[0]));
  if (e.start !== e.end && sessions.length >= 2 && sessions.length <= 8) return sessions.map(([d, h]) => `${labelDay(d)} ${timesIn(h).join(L(' y ', ' i ', ' and '))}`).join(' · ');
  // Horario oficial del día («09:00–18:00»); si cambia según el día, se dice de qué día es.
  const byDay = hoursByDay(e) || {}, rawDay = e.occurrence_date ? null : byDay[day], dayHours = PARTS[rawDay] ? PARTS[rawDay]().toLowerCase() : rawDay;
  const t = dayHours || (e.time ? e.time : (e.time_label && !/^(Hora no indicada|Varios días|Exposición)$/.test(e.time_label) ? e.time_label : ''));
  if (e.start !== e.end && dayHours && new Set(Object.values(byDay)).size > 1) return `${when} · ${labelDay(day)} ${dayHours}`;
  // Programa de días sueltos (una feria tres días al mes): se dicen los próximos días, no «10 abr – 21 dic».
  const days = Object.keys(byDay).sort(), span = (new Date(e.end + 'T12:00:00') - new Date(e.start + 'T12:00:00')) / 86400000 + 1;
  if (e.start !== e.end && days.length && days.length < span) {
    if (!e.occurrence_date && byDay[day]) return `${labelDay(day)}${t ? ' · ' + showTime(t) : ''}`;
    const next = days.filter(d => d >= today).slice(0, 3);
    if (next.length) return `${L('Próximos días', 'Propers dies', 'Upcoming days')}: ${next.map(labelDay).join(', ')}${t ? ' · ' + showTime(t) : ''}`;
  }
  if (e.occurrence_date) return `${labelDay(e.occurrence_date)}${t ? ' · ' + showTime(t) : ''}`;
  return t ? `${when} · ${showTime(t)}` : when;
}
// Lugar que no es un sitio («Diferents espais», «Diversos centres cívics», «Recorregut: …», 22-10-2026).
const MANY_PLACES = /^(?:diferents|diferentes|diversos|diversas|diverses|varis|varies|varios|varias|distints|distintos|m[uú]ltiples|recorregut|recorrido)\b/i;
const onePlace = e => !MANY_PLACES.test(String(e.venue_names?.[0] || '').trim());
// Precio en la ficha (22-10-2026): si la fuente da varias tarifas («Entrada 1 dia: 50 € · Abonament 2 dies: 95 €»),
// la caja ocupa toda la fila y cada tarifa va en su línea. El texto es el de la fuente, solo partido por «·».
function priceFact(e) {
  const text = e.is_free ? t('Gratis') : String(e.price_text || e.price_label || L('Consultar precio', 'Consultar preu', 'Check price'));
  const parts = text.split(/\s+·\s+/).map(x => x.trim()).filter(Boolean);
  if (text.length <= 32 && parts.length < 2) return `<div><small>${t('Precio')}</small><b>${esc(text)}</b></div>`;
  return `<div class="fact-wide"><small>${t('Precio')}</small><ul class="fact-lines">${parts.map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>`;
}
// Crédito de la imagen (22-10-2026): quien tiene la imagen, no el agregador que la recoge. GRAF publica
// la imagen que manda cada espacio → el espacio; las fuentes municipales → el Ajuntament (CC BY en Open Data);
// la foto del equipamiento conserva su crédito y su enlace al original. La fuente sigue en los datos y en Créditos.
function imageCredit(e, m) {
  const c = m.credit || {}, attr = String(c.attribution || c || '');
  if (!attr && !c.source) return '';
  if (m.fallback) return `© ${attr}`;
  let who = attr.split(' — ')[0].replace(/\s*\([^)]*\)/g, '').trim();
  if (c.source === 'web_graf') who = e.organizers?.[0] || String(e.venue_names?.[0] || '').split(' · ')[0] || who;
  else if (c.source === 'opendatabcn_agenda' || c.source === 'guiabcn') who = 'Ajuntament de Barcelona';
  return who ? `${L('Imagen', 'Imatge', 'Image')}: ${who}` : '';
}
// «Horario» solo si dice algo que «Cuándo» no dice (22-10-2026): «18:00» o «18:00–21:00» ya están arriba;
// «Divendres i dissabte · de 17.30 h a 05.30 h» o «sessions a les 18 i a les 20» sí se muestran.
function scheduleExtra(e) {
  const text = String(e.time_text || '').trim(); if (!text) return '';
  const when = detailWhen(e), clocks = text.match(/\b\d{1,2}[:.]\d{2}\b/g) || [];
  const rest = text.replace(/\b\d{1,2}[:.]\d{2}\b/g, '').replace(/[\s·–\-—,;/h]+/g, '');
  return !rest && clocks.length && clocks.every(c => when.includes(c.replace('.', ':').padStart(5, '0'))) ? '' : text;
}
async function openDetail(k, focus, opts = {}) {
  const [source, ...rest] = k.split(':'), id = rest.join(':');
  try {
    const e = await get('/api/event?' + new URLSearchParams({source, id, day: state.day}));
    // El mismo acto tiene su propia ficha en el día que se está mirando (otra fecha de la misma página del
    // acto, 24-10-2026): se abre esa, no la de otro día.
    const sameDay = !opts.sibling && state.day && e.other_days && e.other_days[state.day];
    if (sameDay && sameDay !== k && !(e.start <= state.day && state.day <= e.end)) return openDetail(sameDay, focus, {...opts, sibling: true});
    returnFocus = focus || document.activeElement; state.detail = k; syncUrl(opts.push !== false);
    // Página vista de la ficha (navegación sin recarga): solo al abrirla de verdad; analytics.js no repite la misma ruta.
    if (opts.push !== false) { try { window.ontocaAnalytics?.pageview(location.href, `${e.title} · Ontoca`) } catch (_) {} }
    if (opts.origin) {
      track('ficha', 'event_open', k);
      if (opts.origin === 'seleccion') track('seleccion', 'featured_click', k);
      else if (opts.origin === 'destacado') track('seleccion', 'highlight_click', k);
    }
    document.getElementById('seoFicha')?.remove();   // la ficha en HTML de /e/* (functions/e): ya está la de la app
    // One descriptive block: the source's own text when it exists (paragraphs
    // kept), otherwise a single factual sentence built from the record.
    // Textos que no describen el plan (28-10-2026, David): avisos de transporte («Transport públic per al concert…»,
    // «TMB habilitarà…») y notas de venta («Mayores de 16 años…»). Si la descripción empieza así, no se enseña como tal.
    const NOT_DESC = /^(?:transport p[úu]blic|tmb |mobilitat|servei especial|mayores de \d|majors de \d|menores de \d|menors de \d|abono|abonament|compra tus entradas|compra les teves entrades)/i;
    const text = NOT_DESC.test((e.description || '').trim()) ? '' : (e.description || '').trim();
    const para = s => s.slice(0, 3000).split(/\n\s*\n|\n/).map(p => p.trim()).filter(Boolean).map(p => `<p>${esc(p)}</p>`).join('');
    // Sin texto de la fuente, nada en su lugar (27-10-2026, auditoría conjunta A4): la frase hecha con los datos («Proyección en
    // Cinemes Girona el martes…») repetía lo que ya dicen Cuándo, Dónde y Precio. Sigue sirviendo para buscadores y para compartir.
    const paragraphs = text ? para(text) : '';
    const tr = text ? await translationFor(k) : null;
    // Descripción breve automática (IA) encima del texto original, para comparar; nunca lo sustituye.
    // Resumen y recomendación escritos por IA: fuera de la ficha pública hasta evaluarlos (22-10-2026).
    const brief = '';
    // Con traducción: se dice que es automática y el original queda a un clic (24-10-2026).
    const description = tr ? `${brief}<section class="sheet-copy"><div class="tr-note">${tr.o ? L('Texto de la web oficial', 'Text del web oficial', 'Text from the official website') : L('Traducción automática', 'Traducció automàtica', 'Machine translation')} · <button type="button" class="tr-toggle" data-trtoggle aria-expanded="false">${L('Ver original', "Veure l'original", 'Show original')}</button></div><div class="tr-text" lang="${LANG}">${para(tr.t)}</div><div class="tr-orig" hidden>${paragraphs}</div></section>`
      : (paragraphs ? `${brief}<section class="sheet-copy">${paragraphs}</section>` : '');
    // Descripciones largas (28-10-2026, David): seis líneas y «Leer más».
    const clampDesc = html => html && String(text || '').length > 420 ? html.replace('<section class="sheet-copy">', '<section class="sheet-copy sheet-copy-clamp">') + `<button type="button" class="linklike sheet-more" data-readmore>${esc(L('Leer más', 'Llegir més', 'Read more'))}</button>` : html;
    const conflict = e.time_conflicts && (e.time_conflicts[e.occurrence_date || state.day] || e.time_conflicts[e.start]);
    // Hora que dio una lectura anterior de la fuente y la actual ya no trae (23-10-2026): se dice.
    const carried = (e.occurrences || []).find(o => o.evidence_field === 'ultima_hora_conocida' && o.date === (e.occurrence_date || state.day));
    const carriedNote = carried ? L(`La fuente publicó esta hora${carried.seen_at ? ' el ' + labelDate(carried.seen_at) : ''} y ahora no la muestra: confírmala`, `La font va publicar aquesta hora${carried.seen_at ? ' el ' + labelDate(carried.seen_at) : ''} i ara no la mostra: confirma-la`, `The source published this time${carried.seen_at ? ' on ' + labelDate(carried.seen_at) : ''} and no longer shows it: please check`) : '';
    // Hora de otra agenda del mismo acto, porque la sala no la publica (23-10-2026): sin nombrar el agregador.
    const borrowed = (e.occurrences || []).find(o => o.evidence_field === 'otra_fuente' && o.date === (e.occurrence_date || state.day));
    const borrowedNote = borrowed ? L('La sala no publica la hora; esta sale de otra agenda: confírmala', 'La sala no publica l\'hora; aquesta surt d\'una altra agenda: confirma-la', 'The venue does not publish the time; this one comes from another listing: please check') : '';
    // Hora leída en la página del propio acto porque el listado de la fuente dejó de darla (src/time_rescue.py).
    const rescued = (e.occurrences || []).find(o => o.evidence_field === 'rescate' && o.date === (e.occurrence_date || state.day));
    const rescuedNote = rescued ? L('Hora leída en la página del acto: confírmala antes de ir', "Hora llegida a la pàgina de l'acte: confirma-la abans d'anar-hi", 'Time read from the event page: please check before you go') : '';
    const scheduleBits = [carriedNote, borrowedNote, rescuedNote, conflict ? L(`Las fuentes dan horas distintas (${conflict.join(' y ')}): confírmalo en la sala`, `Les fonts donen hores diferents (${conflict.join(' i ')}): confirma-ho a la sala`, `Sources give different times (${conflict.join(' and ')}): check with the venue`) : '', e.schedule_days, scheduleExtra(e), e.schedule_note, e.registration_required ? t('Requiere inscripción') : '', e.open_enrollment ? L('Inscripción abierta', 'Inscripció oberta', 'Registration open') : '', e.venue_unconfirmed ? L(`Esta fecha aún no aparece en la agenda de ${e.venue_unconfirmed}: confírmala antes de ir`, `Aquesta data encara no surt a l'agenda de ${e.venue_unconfirmed}: confirma-la abans d'anar-hi`, `This date is not yet on ${e.venue_unconfirmed}’s listings: check it before you go`) : ''].filter(Boolean);
    const schedule = scheduleBits.length ? `<p class="sheet-schedule"><span>${t('Horario')}</span>${esc(showTime(scheduleBits.join(' · ')))}</p>` : '';
    // Cartel: con hora por artista si la fuente la publica; si no, solo los nombres.
    const timed = (e.lineup_times || []).filter(x => x.name && x.time).sort((a, b) => a.time.localeCompare(b.time));
    const names = e.lineup || [];
    const lineup = timed.length ? `<p class="sheet-schedule sheet-lineup"><span>${t('Cartel')}</span>${timed.map(x => `${esc(x.time)} ${esc(x.name)}`).join(' · ')}${names.length > timed.length ? ` · ${esc(names.filter(n => !timed.some(x => x.name === n)).join(' · '))}` : ''}</p>`
      : names.length > 1 || (names.length === 1 && fold(names[0]) !== fold(e.title)) ? `<p class="sheet-schedule sheet-lineup"><span>${t('Cartel')}</span>${esc(names.join(' · '))}</p>` : '';
    // Programa de un festival con abono (25-10-2026): por días y horas, con la sala; plegado si es largo.
    const progDays = {};
    for (const p of e.program || []) (progDays[p.date] ||= []).push(p);
    const progHtml = Object.entries(progDays).map(([d, l]) => `<h4>${esc(labelDay(d))}</h4><ul>${l.map(p => `<li>${p.time ? `<b>${esc(p.time)}</b> ` : ''}${esc(p.title)}${p.room ? ` <small>· ${esc(p.room)}</small>` : ''}</li>`).join('')}</ul>`).join('');
    const program = e.program?.length ? `<details class="sheet-program"${e.program.length <= 12 ? ' open' : ''}><summary>${esc(L('Programa', 'Programa', 'Programme'))} · ${e.program.length} ${esc(L('actividades', 'activitats', 'activities'))} · ${esc(L('con la entrada del festival', "amb l'entrada del festival", 'with the festival ticket'))}</summary>${progHtml}</details>` : '';
    const cover = e.media?.[0] ? `<figure class="detail-hero"><img src="${esc(e.media[0].url)}" alt="${esc(e.media[0].alt || e.title)}" loading="eager"><figcaption>${e.media[0].fallback ? `<span class="venue-photo-tag">${t('Imagen del equipamiento')}</span>` : ''}${[e.media[0].alt && fold(e.media[0].alt) !== fold(e.title) ? esc(e.media[0].alt) : '', esc(imageCredit(e, e.media[0]))].filter(Boolean).join(' · ')}${e.media[0].fallback && safeurl(e.media[0].credit?.original_url) ? ` · <a href="${esc(safeurl(e.media[0].credit.original_url))}" target="_blank" rel="noopener noreferrer">original ↗</a>` : ''}</figcaption></figure>` : `<div class="detail-poster"><span>Ontoca · ${esc(catName(e.public_category || e.category))}</span><strong>${esc(e.title)}</strong></div>`;
    const gallery = e.media?.length > 1 ? `<section class="sheet-gallery"><h3>${t('Más imágenes')}</h3><div>${e.media.slice(1, 7).map(m => `<figure><img src="${esc(m.url)}" alt="${esc(m.alt || e.title)}" loading="lazy"></figure>`).join('')}</div></section>` : '';
    const site = String(e.venue_names?.[0] || e.venues?.[0]?.name || '').split(' · ')[0];
    // «Diferents espais», «Diversos centres cívics», «Recorregut: …» no son un espacio (22-10-2026):
    // sin «Más planes en…», sin mapa y sin «Cómo llegar», porque el punto de la fuente no es el sitio del acto.
    const manyPlaces = MANY_PLACES.test(site.trim());
    const realSite = site && !manyPlaces;
    // «Cómo llegar»: ruta en Google Maps hasta las coordenadas del lugar (en el móvil abre la app).
    const osm = e.coordinates && !manyPlaces ? `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(e.coordinates.lat + ',' + e.coordinates.lon)}` : '';
    // Lugar (28-10-2026, David): dirección y «Cómo llegar» siempre a la vista; el mapa, al tocar «Ver mapa» (ocupaba 380 px
    // antes de los botones de entradas). Sin coordenadas, solo el nombre del sitio.
    const map = e.coordinates && !manyPlaces ? `<section class="sheet-place sheet-place-folded"><div class="sheet-place-caption"><div><b>${esc(e.venue_names?.[0] || e.venues?.[0]?.name || t('Ubicación'))}</b><small>${esc(e.venues?.[0]?.address || t(e.district) || 'Barcelona')}</small></div><span><button type="button" class="linklike" data-showmap>${esc(L('Ver mapa', 'Veure mapa', 'Show map'))}</button> · <a target="_blank" rel="noopener noreferrer" href="${esc(osm)}">${t('Cómo llegar')} ↗</a></span></div><div id="sheetMap" class="sheet-map" role="img" aria-label="${t('Mapa de')} ${esc(e.venues?.[0]?.name || t('la ubicación'))}" hidden></div></section>` : '';
    // Más planes del mismo espacio: un enlace que abre la agenda filtrada por la sala (30 días), no una lista en la ficha.
    const upcoming = realSite ? `<p class="sheet-venue-link"><button class="linklike" type="button" data-venueq="${esc(site)}">${esc(L(`Todos los planes en ${site} (6 meses)`, `Tots els plans a ${site} (6 mesos)`, `All plans at ${site} (6 months)`))} ›</button></p>` : '';
    const all = sheetLinks(e), main = all[0] || null;
    // Botones junto a los datos (28-10-2026, David): entradas o web oficial y guardar, sin pasar el mapa ni la descripción
    // («Entradas» estaba a 1.859 px en la ficha de Jungle).
    const actions = `<div class="sheet-cta sheet-cta-main sheet-actions-top">${main ? `<a class="source-link" data-lk="${esc(main.kind)}" target="_blank" rel="noopener noreferrer" href="${esc(main.url)}">${esc(main.label)} ↗</a>` : ''}<button class="save-link" type="button" data-save="${esc(k)}">${state.saved.includes(k) ? '♥ ' + t('Guardado') : '♡ ' + t('Guardar')}</button></div>`;
    // Debajo, el resto en el mismo orden (sin repetir tipo salvo entradas/inscripciones distintas), y la fuente al final.
    // La ficha de la fuente (GRAF, GuiaBCN…) solo sale si no tenemos la página concreta del acto (22-10-2026).
    const hasEventPage = all.some(x => x.kind === 'evento');
    // (Nombres propios: «source» y «rest» ya son el origen y el id del acto, arriba; repetirlos aquí rompía la ficha.)
    const others = all.slice(1), useful = others.filter(x => x.kind !== 'fuente' && x.kind !== 'social').slice(0, 3), social = others.filter(x => x.kind === 'social').slice(0, 1), sourceLink = hasEventPage ? [] : others.filter(x => x.kind === 'fuente').slice(0, 1);
    const links = [...useful, ...social, ...sourceLink].map(x => `<a class="sheet-link${x.kind === 'fuente' ? ' sheet-link-source' : ''}" data-lk="${esc(x.kind)}" target="_blank" rel="noopener noreferrer" href="${esc(x.url)}">${esc(x.kind === 'sala' || x.kind === 'fuente' || x.kind === 'social' ? x.label : x.label + ' · ' + urlHost(x.url))} ↗</a>`).join('');
    $('sheet').innerHTML = `<div class="sheet-top"><span data-cat="${esc(e.public_category || e.category || '')}">${esc(catName(e.public_category || e.category))}${(e.channels || []).map(c => ' · ' + esc(chanName(c))).join('')}${e.is_free ? ' · ' + t('Gratis') : ''}${soldOn(e, e.occurrence_date || state.day) ? ' · ' + L('Entradas agotadas', 'Entrades esgotades', 'Sold out') : ''}</span><button class="close" type="button" aria-label="${t('Cerrar ficha')}">✕</button></div><h2 id="detailTitle">${esc(e.title)}</h2>${msLine(e)}${festLine(e)}${cover}<div class="facts"><div><small>${t('Cuándo')}</small><b>${esc(detailWhen(e))}</b></div><div><small>${t('Dónde')}</small><b>${esc(e.venue_names?.[0] || e.venues?.[0]?.name || 'Barcelona')}</b>${e.district ? `<small>${esc(t(e.district))}</small>` : ''}</div>${organizerBox(e)}${priceFact(e)}${hasAge(e) ? `<div><small>${esc(L('Edad', 'Edat', 'Age'))}</small><b>${esc(ageText(e))}</b></div>` : ''}</div>${actions}${schedule}${lineup}${program}${clampDesc(description)}${map}${gallery}${upcoming}${links ? `<div class="sheet-links">${links}</div>` : ''}<div class="sheet-actions"><button class="save-link" type="button" data-save="${esc(k)}">${state.saved.includes(k) ? '♥ ' + t('Guardado') : '♡ ' + t('Guardar')}</button><button class="save-link share-link" type="button" data-share="${esc(k)}">⇪ ${t('Compartir')}</button>${calendarMenu(k, e)}</div><p class="sheet-note">${e.presentation === 'venue_link_only' ? L('El detalle, en la web de la sala. Confírmalo antes de ir.', "El detall, al web de la sala. Confirma-ho abans d'anar-hi.", 'Details on the venue’s website. Check before you go.') : L('Confirma en la web oficial antes de ir.', "Confirma-ho al web oficial abans d'anar-hi.", 'Check the official website before you go.')}</p>`;
    $('overlay').hidden = false; document.body.style.overflow = 'hidden'; document.querySelector('.sheet .close').focus();
    $('sheet').scrollTop = 0; state.sheetEvent = e;
    // Algún dato muy largo (horario de varios días, lugar u organizador con nombre largo): dos cajas por fila, no cuatro estrechas.
    const facts = document.querySelector('#sheet .facts'); if (facts && [...facts.querySelectorAll(':scope > div:not(.fact-wide) > b')].some(b => b.textContent.length > 45)) facts.classList.add('facts-long');
  } catch (_) {}
}
// Sin organizador declarado pero con la web oficial que publica la ficha (en
// GuiaBCN suele ser la de quien lo organiza): se muestra «Web» con su dominio.
// Nombre corto y público de la fuente: «MACBA · agenda directa» → «MACBA»; «… (agenda cultural)» sin paréntesis.
function sourceName(e) { return String(e.source_label || 'la fuente').split(' · ')[0].replace(/\s*\([^)]*\)/g, '').trim() || 'la fuente' }
// Botón principal: lo más cerca posible de la fuente original. 1) entradas o web de la sala (catálogo);
// 2) la página oficial del acto que leímos; 3) la web del evento que da la agenda, si es una página concreta
// (no solo la portada de un dominio); 4) si no, la ficha de la fuente que lo recoge.
// Etiquetas de enlace que pone el catálogo en castellano («En GRAF», «Ficha en GuiaBCN»): en catalán, «A GRAF», «Fitxa a GuiaBCN».
function linkLabel(label) {
  return L(label, String(label || '').replace(/^Ficha en /, 'Fitxa a ').replace(/^En /, 'A '), String(label || '').replace(/^Ficha en /, 'Listing on ').replace(/^En /, 'On '));
}
// Enlaces de la ficha (22-10-2026): el botón lleva a lo más cercano al acto, por este orden:
// 1) su web propia (una página concreta, no la portada de un dominio), 2) inscripciones,
// 3) entradas, 4) web de la sala u organizador (y las portadas). La ficha de la fuente que lo
// recoge solo es el botón si no hay nada de eso; si no, queda como enlace pequeño al final.
const LINK_RANK = {evento: 0, inscripcion: 1, entradas: 2, sala: 3, social: 4, fuente: 5};
const LINK_NAME = {evento: () => L('Web del evento', "Web de l'esdeveniment", 'Event website'), inscripcion: () => L('Inscripción', 'Inscripció', 'Registration'), entradas: () => L('Entradas', 'Entrades', 'Tickets'), sala: () => L('Web de la sala', 'Web de la sala', 'Venue website')};
const urlHost = u => { try { return new URL(u).hostname.replace(/^www\./, '') } catch (_) { return '' } };
// Portada de un dominio («auditori.cat/ca/»); las webs de una sola página con rutas tras «#/» (h2o.es/#/ca/exposicion/438) no lo son.
const isHome = u => { try { const x = new URL(u), path = (x.pathname + (x.hash.startsWith('#/') ? x.hash.slice(1) : '')).replace(/\/+/g, '/'); return path.replace(/^\/(?:ca|es|en|cat|esp|eng)(?=\/|$)/, '').replace(/\/+$/, '').length <= 1 } catch (_) { return true } };
// Páginas genéricas del Ajuntament (la del distrito, «ajuntament.barcelona.cat/sants-montjuic»): no dicen nada del acto.
const isCityPortal = u => { try { const x = new URL(u); return /(^|\.)barcelona\.cat$/.test(x.hostname) && !/guia\.barcelona/.test(x.hostname) && x.pathname.split('/').filter(Boolean).length <= 2 } catch (_) { return false } };
function linkKind(l, e) {
  const label = String(l.label || ''), u = safeurl(l.url) || '';
  if (!u) return '';
  if (/whatsapp|drive\.google|docs\.google|geoportal|seuelectronica|safelinks|open\.spotify|linktr\.ee/i.test(u) || isCityPortal(u)) return '';
  if (u === safeurl(e.url)) return e.data_origin === 'centro' ? 'evento' : 'fuente';  // si la fuente es el propio centro, su página es la del acto
  if (/^(Página de la fuente|Ficha en |En |Butlletí)/.test(label)) return 'fuente';
  if (/^(Facebook|Instagram|YouTube|LinkedIn)/.test(label) || /facebook\.com|instagram\.com|youtube\.com|linkedin\.com/i.test(u)) return 'social';
  if (/^Inscripci/.test(label) || /inscripcions|inscripcionscc|\/\/reserva\.|registre_cursos/i.test(u)) return 'inscripcion';
  if (/^(Entradas|Venta de entradas)/.test(label) || /ticket|\/\/entrades\.|\/\/entradas\.|entradium|entrapolis|koobin|weeztix|fourvenues|passline|vivaticket|admit-one|codetickets/i.test(u)) return 'entradas';
  if (/^(Web de la sala|Web del organizador)/.test(label)) return 'sala';
  return isHome(u) ? 'sala' : 'evento';
}
function sheetLinks(e) {
  const own = safeurl(e.url), list = [];
  // Ficha de una sala solo con su web o sus entradas (política de la fuente): ese es el enlace.
  if (own && e.link_label) list.push({url: own, kind: e.link_label === 'Entradas' ? 'entradas' : 'sala', label: t(e.link_label)});
  const official = safeurl(e.official_page?.url);
  if (official) list.push({url: official, kind: isHome(official) ? 'sala' : 'evento'});
  for (const l of e.links || []) { const kind = linkKind(l, e); if (kind) list.push({url: safeurl(l.url), kind, label: kind === 'social' || (kind === 'fuente' && l.label !== 'Página de la fuente') ? linkLabel(l.label) : kind === 'fuente' ? L(`Ficha en ${sourceName(e)}`, `Fitxa a ${sourceName(e)}`, `Listing on ${sourceName(e)}`) : ''}) }
  // La página de la fuente: si la fuente es el propio centro, esa página ya es la del acto.
  if (own && !e.link_label) list.push({url: own, kind: e.data_origin === 'centro' ? 'evento' : 'fuente', label: e.data_origin === 'centro' ? '' : L(`Ficha en ${sourceName(e)}`, `Fitxa a ${sourceName(e)}`, `Listing on ${sourceName(e)}`)});
  const seen = new Set(), key = u => u.split('#')[0].replace(/^http:/, 'https:').replace('://www.', '://').replace(/\/+$/, '');
  const out = list.filter(x => x.url && !seen.has(key(x.url)) && seen.add(key(x.url))).sort((a, b) => LINK_RANK[a.kind] - LINK_RANK[b.kind]);
  for (const x of out) if (!x.label) x.label = x.kind === 'sala' && isHome(x.url) ? urlHost(x.url) : LINK_NAME[x.kind]();
  return out;
}
function mainLink(e) { const first = sheetLinks(e)[0]; return first ? {url: first.url, label: first.label} : null }
function organizerBox(e) {
  if (e.organizers?.length) return `<div><small>${t('Organiza')}</small><b>${esc(e.organizers.join(' · '))}</b></div>`;
  const web = (e.links || []).find(l => l.label === 'Web del evento' && safeurl(l.url));
  if (web) { const host = new URL(safeurl(web.url)).hostname.replace(/^www\./, ''); return `<div><small>${t('Web')}</small><b><a href="${esc(safeurl(web.url))}" target="_blank" rel="noopener noreferrer">${esc(host)} ↗</a></b></div>` }
  return '';  // sin organizador conocido, la caja no sale
}
let sheetMap = null;
function mountSheetMap(e) {
  if (sheetMap) { try { sheetMap.remove() } catch (_) {} sheetMap = null }
  const el = $('sheetMap'); if (!el || !window.L || !e.coordinates) return;
  const point = [e.coordinates.lat, e.coordinates.lon];
  sheetMap = window.L.map(el, {zoomControl: false, dragging: false, scrollWheelZoom: false, doubleClickZoom: false, touchZoom: false, boxZoom: false, keyboard: false, attributionControl: true}).setView(point, 15);
  window.L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19, attribution: '© OpenStreetMap'}).addTo(sheetMap);
  window.L.circleMarker(point, {radius: 9, color: '#ffffff', weight: 3, fillColor: '#6d5bd0', fillOpacity: 1}).addTo(sheetMap);
  setTimeout(() => sheetMap && sheetMap.invalidateSize(), 60);
}
// Añadir al calendario (22-10-2026): iPhone (.ics que Safari abre con «Añadir al calendario») y
// Google Calendar. Lo sirve functions/cal/[[path]].js con el hueco ya calculado al exportar
// (src/publish_static.py, calendar_days): el día que se mira y solo la hora que publica la fuente.
// Solo en la web publicada: el servidor local no tiene esa función.
function calendarMenu(k, e) {
  if (!STATIC) return '';
  const day = e.occurrence_date || (e.start === e.end ? e.start : state.day);
  const base = eventPath(k).replace(/^(?:\/v2)?\/e\//, '/cal/') + '?d=' + encodeURIComponent(day);
  const apple = `<a class="sheet-link" data-cal="ics" data-k="${esc(k)}" href="${esc(base)}">iPhone</a>`, gcal = `<a class="sheet-link" data-cal="google" data-k="${esc(k)}" target="_blank" rel="noopener noreferrer" href="${esc(base + '&g=1')}">Google Calendar ↗</a>`;
  const ios = /iPhone|iPad|iPod|Macintosh/.test(navigator.userAgent) && 'ontouchend' in document;
  return `<details class="cal-menu"><summary class="save-link">▦ ${t('Añadir al calendario')}</summary><div class="cal-options">${ios ? apple + gcal : gcal + apple}</div></details>`;
}
async function shareEvent(k) {
  const url = location.origin + eventPath(k), title = $('detailTitle')?.textContent || 'Ontoca';
  // En WhatsApp el enlace ya trae foto, título, cuándo y dónde (vista previa); el texto lo resume por si no carga.
  const when = document.querySelector('.facts > div:first-child b')?.textContent || '', where = document.querySelector('.facts > div:nth-child(2) b')?.textContent || '';
  const text = [title, [when, where].filter(Boolean).join(' · ')].filter(Boolean).join('\n');
  try { if (navigator.share) { await navigator.share({title, text, url}); track('nativo', 'event_share', k); return } } catch (_) { return }  // cancelado: no cuenta
  try { await navigator.clipboard.writeText(url); track('copiar', 'event_share', k); const b = document.querySelector('[data-share]'); if (b) { b.textContent = '✓ ' + t('Enlace copiado'); setTimeout(() => { b.textContent = '⇪ ' + t('Compartir') }, 1800) } } catch (_) { track('manual', 'event_share', k); prompt(t('Enlace de la ficha'), url) }
}
function hideSheet() { if ($('overlay').hidden) return false; $('overlay').hidden = true; document.body.style.overflow = ''; state.detail = null; if (sheetMap) { try { sheetMap.remove() } catch (_) {} sheetMap = null } returnFocus?.focus(); return true }
function closeSheet() { if (!hideSheet()) return; const depth = history.state?.depth || 0; if (depth) history.go(-depth); else syncUrl() }  // closing skips every sheet opened in a row (sala → evento → …) and lands on the list
window.addEventListener('popstate', () => { const k = detailFromLocation(); if (k) { if (k !== state.detail) openDetail(k, null, {push: false}) } else hideSheet() });
function toggleSave(k) { track('ficha', state.saved.includes(k) ? 'event_unsave' : 'event_save', k); state.saved = state.saved.includes(k) ? state.saved.filter(x => x !== k) : [...state.saved, k]; saveState(); renderAgenda(); if (!$('overlay').hidden) document.querySelectorAll(`#sheet [data-save="${CSS.escape(k)}"]`).forEach(b => { b.textContent = (state.saved.includes(k) ? '♥ ' + t('Guardado') : '♡ ' + t('Guardar')) }) }   // sin reabrir la ficha: no vuelve arriba (28-10-2026)

/* ---------- orchestration ---------- */
async function refresh({scroll = false} = {}) {
  channelView(); syncUrl(); days(); chips(); hours(); renderActive();
  if (scroll) scrollToId('agenda');
  await Promise.all([agenda(), selection(), loadDistricts()]);
}
let searchTimer = null;
document.addEventListener('click', e => {
  const vq = e.target.closest('.ev-venue[data-venueq]'); if (vq) { e.preventDefault(); goVenue(vq.dataset.venueq); return }
  const fq = e.target.closest('.ev-fest[data-fest]'); if (fq) { e.preventDefault(); e.stopPropagation(); goFest(fq.dataset); return }
  const button = e.target.closest('button,a[href^="#"],a[data-quickcat],a[data-period]'); if (!button) return;
  if (button.matches('a[data-quickcat],a[data-period]')) { if (e.metaKey || e.ctrlKey || e.shiftKey || e.button) return; e.preventDefault() }   // enlace para buscadores; en la app, filtro
  if (button.matches('a[href^="#"]') && !button.classList.contains('skip')) { e.preventDefault(); scrollToId(button.getAttribute('href').slice(1)); return }
  if (button.id === 'theme') { const light = document.documentElement.dataset.theme === 'light'; document.documentElement.dataset.theme = light ? 'dark' : 'light'; try { localStorage.setItem('brollant-theme', document.documentElement.dataset.theme) } catch (_) {} return }
  if (button.id === 'saved') { state.savedOnly = !state.savedOnly; button.classList.toggle('active', state.savedOnly); button.setAttribute('aria-pressed', String(state.savedOnly)); channelView(); scrollToId('agenda'); agenda(); return }
  if (button.dataset.hours) { const [f, t] = button.dataset.hours.split('-').map(Number); const same = state.hourFrom === f && state.hourTo === t; track('filtro', 'filter_hours', button.dataset.hours, same ? 0 : 1); state.hourFrom = same ? null : f; state.hourTo = same ? null : t; refresh(); return }
  if (button.id === 'whenOpen') { state.whenEntry = true; openDrawer(true); $('filters').scrollTop = 0; return }
  if (button.id === 'openFilters' || button.id === 'fabFilters') { state.whenEntry = false; openDrawer(true); return }
  if (button.id === 'filtersApply') { openDrawer(false); scrollToId('agenda'); return }
  if (button.id === 'filtersClear') { track('filtro', 'filter_clear', 'todos'); ['query','cat','ch','edad','idioma','format','free','hours','district','started','fest'].forEach(clearFilter); refresh(); return }
  if (button.id === 'closeFilters') { openDrawer(false); return }
  if (button.dataset.alerts === 'open') { openAlerts(); return }
  if (button.id === 'clearAll' || button.dataset.clear === 'all') { track('filtro', 'filter_clear', 'todos'); ['query','cat','ch','edad','format','free','hours','district','fest'].forEach(clearFilter); refresh(); return }
  if (button.dataset.clear) { track('filtro', 'filter_clear', button.dataset.clear); clearFilter(button.dataset.clear); refresh(); return }
  if (button.id === 'viewList' || button.id === 'viewMap' || button.id === 'viewVenue') { const v = button.id.replace('view', '').toLowerCase(); if (v !== state.view) track('vista', 'view_change', v); state.view = button.id.replace('view', '').toLowerCase(); chips(); syncUrl(); agenda(); return }
  if (button.id === 'loadMore') { state.page += 1; button.disabled = true; agenda(true); return }
  if (button.dataset.expand) { state.expanded.add(button.dataset.expand); renderAgenda(); const sec = $('ag-' + button.dataset.expand); if (sec && sec.getBoundingClientRect().top < 0) sec.scrollIntoView({block: 'start'}); return }
  if (button.dataset.collapse) { delete state.limits[button.dataset.collapse]; state.expanded.delete(button.dataset.collapse); renderAgenda(); const sec = $('ag-' + button.dataset.collapse); if (sec) window.scrollTo({top: sec.getBoundingClientRect().top + window.scrollY - (parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--stick')) || 0) - 8}); return }
  if (button.dataset.moredays) { state.shown += 7; stableRender(); return }
  if (button.dataset.dayall) { state.openDays.add(button.dataset.dayall); stableRender(); return }
  if (button.dataset.venueq) {
    goVenue(button.dataset.venueq); return
  }
  if (button.dataset.fest) { goFest(button.dataset); return }
  if (button.dataset.pickcat !== undefined) { if (button.dataset.pickcat !== state.pickCat) { state.pickCat = button.dataset.pickcat; track('seleccion', 'type_filter', state.pickCat || 'todo'); selection() } return }
  if (button.id === 'pickPrev' || button.id === 'pickNext') { pickScroll(button.id === 'pickNext' ? 1 : -1); return }
  if (button.dataset.showmap !== undefined) { const el = $('sheetMap'); if (el) { el.hidden = false; button.closest('.sheet-place')?.classList.remove('sheet-place-folded'); button.remove(); mountSheetMap(state.sheetEvent) } return }
  if (button.dataset.readmore !== undefined) { button.previousElementSibling?.classList.remove('sheet-copy-clamp'); button.remove(); return }
  if (button.dataset.pickrange) { if (button.dataset.pickrange !== state.pickRange) { state.pickRange = button.dataset.pickrange; track('seleccion', 'range_change', state.pickRange); selection() } return }
  if (button.dataset.near) {
    if (button.dataset.near === 'km1' || button.dataset.near === 'km3') { state.nearKm = Number(button.dataset.near.slice(2)); track('filtro', 'near_km', state.nearKm); renderAgenda(); return }
    if (state.near || state.nearWait) { state.near = null; state.nearKm = 0; state.nearWait = false; state.nearMsg = ''; renderAgenda(); return }
    if (!navigator.geolocation) { state.nearMsg = nearFail(); renderAgenda(); return }
    state.nearWait = true; state.nearMsg = ''; renderAgenda();
    navigator.geolocation.getCurrentPosition(pos => {
      if (!state.nearWait) return;
      state.nearWait = false; state.near = {lat: pos.coords.latitude, lon: pos.coords.longitude}; state.nearKm = 1; track('filtro', 'near_me', 'on'); renderAgenda();
    }, () => { state.nearWait = false; state.nearMsg = nearFail(); renderAgenda() }, {enableHighAccuracy: false, timeout: 10000, maximumAge: 300000});
    return
  }
  if (button.dataset.agtab) {   // pestaña: solo su contenido y vuelta al principio del listado
    if (state.tab !== button.dataset.agtab) { state.tab = button.dataset.agtab; track('filtro', 'agenda_tab', state.tab); syncUrl(); renderAgenda() }
    const top = $('agendaList').getBoundingClientRect().top + window.scrollY - (parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--daytop')) || 0);
    if (window.scrollY > top) window.scrollTo({top}); return
  }
  if (button.dataset.quickcat !== undefined) { const c = button.dataset.quickcat; track('filtro', 'filter_category', c || 'todas', c && !(state.cats.length === 1 && state.cats[0] === c) ? 1 : 0); state.cats = !c || (state.cats.length === 1 && state.cats[0] === c) ? [] : [c]; refresh(); return }
  if (button.dataset.block) {
    const id = button.dataset.block, open = button.getAttribute('aria-expanded') === 'true'; state.collapsed ||= new Set();
    if (open) { state.expanded.delete(id); state.collapsed.add(id); if (id === 'wide') state.expanded.delete('wideAll') } else { state.expanded.add(id); state.collapsed.delete(id) }
    stableRender(); const sec = $('ag-' + id); if (sec && sec.getBoundingClientRect().top < 0) sec.scrollIntoView({block: 'start'}); return
  }
  if (button.dataset.chip) { const k = button.dataset.chip, y = button.getBoundingClientRect().top; if (button.closest('#typeMini')) { state.show[k] = !state.show[k]; if (!savedShow) { try { localStorage.setItem('brollant-show', JSON.stringify(state.show)) } catch (_) {} } stableRender(); return } state.show[k] = !state.show[k]; if (!savedShow) { try { localStorage.setItem('brollant-show', JSON.stringify(state.show)) } catch (_) {} } renderAgenda(); const again = document.querySelector(`#typeTabs [data-chip="${k}"]`); if (again) window.scrollBy(0, again.getBoundingClientRect().top - y); return }
  if (button.dataset.hourfold) { const id = button.dataset.hourfold; if (state.expanded.has(id)) state.expanded.delete(id); else state.expanded.add(id); stableRender(); return }
  if (button.dataset.openall) { state.expanded.add('openAll'); stableRender(); return }
  if (button.dataset.step) { const id = button.dataset.step; state.limits[id] = (state.limits[id] || STEP) + STEP; stableRender(); return }
  if (button.dataset.calnav) { state.calOff = Math.max(0, (state.calOff || 0) + Number(button.dataset.calnav)); state.calKeep = true; deskWhen(); return }
  if (button.id === 'whenDay') { state.dayOpen = !state.dayOpen; periodMenu(false); days(); return }
  if (button.id === 'whenPeriod') { periodMenu($('periodMenu').hidden); return }
  if (button.dataset.day) { track('filtro', 'filter_date', button.dataset.day === today ? 'hoy' : 'dia'); state.day = button.dataset.day; state.range = ''; state.dayOpen = true; state.calKeep = false; whenDone(); refresh(); return }
  if (button.dataset.period !== undefined) { track('filtro', 'filter_date', button.dataset.period === 'today' ? 'hoy' : button.dataset.period ? `${button.dataset.period}_dias` : 'hoy'); if (button.dataset.period === 'today') { state.day = today; state.range = '' } else state.range = button.dataset.period; state.dayOpen = false; state.calKeep = false; periodMenu(false); whenDone(); refresh(); return }
  if (button.dataset.category !== undefined) {
    const c = button.dataset.category; track('filtro', 'filter_category', c || 'todas', c && !state.cats.includes(c) ? 1 : 0);
    state.cats = !c ? [] : state.cats.includes(c) ? state.cats.filter(x => x !== c) : [...state.cats, c];
    refresh(); return
  }
  if (button.dataset.age) { const a = button.dataset.age; track('filtro', 'filter_age', a, state.ages.includes(a) ? 0 : 1); state.ages = state.ages.includes(a) ? state.ages.filter(x => x !== a) : [...state.ages, a]; refresh(); return }
  if (button.dataset.actlang) { const l = button.dataset.actlang; track('filtro', 'filter_language', l, state.langs.includes(l) ? 0 : 1); state.langs = state.langs.includes(l) ? state.langs.filter(x => x !== l) : [...state.langs, l]; refresh(); return }
  if (button.dataset.channel) { const c = button.dataset.channel; track('filtro', 'filter_channel', c, state.chans.includes(c) ? 0 : 1); state.chans = state.chans.includes(c) ? state.chans.filter(x => x !== c) : [...state.chans, c]; if (!state.chans.includes('familia')) state.ages = []; channelView(); refresh(); return }
  if (button.dataset.district) { track('filtro', 'filter_district', button.dataset.district, state.district === button.dataset.district ? 0 : 1); state.district = state.district === button.dataset.district ? '' : button.dataset.district; refresh({scroll: true}); return }
  if (button.dataset.trtoggle !== undefined) {
    const sec = button.closest('.sheet-copy'), orig = button.getAttribute('aria-expanded') !== 'true';
    sec.querySelector('.tr-text').hidden = orig; sec.querySelector('.tr-orig').hidden = !orig; button.setAttribute('aria-expanded', String(orig));
    button.textContent = orig ? L('Ver traducción', 'Veure la traducció', 'Show translation') : L('Ver original', "Veure l'original", 'Show original'); return
  }
  if (button.dataset.save) { toggleSave(button.dataset.save); return }
  if (button.dataset.share) { shareEvent(button.dataset.share); return }
  if (button.dataset.open) {
    const origin = button.closest('#curated') ? 'seleccion' : button.closest('.ev-hl') ? 'destacado' : button.closest('#sheet') ? 'ficha' : 'agenda';
    openDetail(button.dataset.open, button, {origin}); return
  }
  if (button.classList.contains('close') && !button.classList.contains('small')) closeSheet();
  if (button.id === 'retry') agenda();
});
// Conversión (Matomo): clic hacia entradas o inscripción, o hacia la web del organizador/sala/fuente. Un solo evento
// propio por clic; Matomo registra además la salida automáticamente (enableLinkTracking).
document.addEventListener('click', e => {
  const a = e.target.closest?.('#sheet a[data-lk], #sheet a[data-cal]'); if (!a || !state.detail) return;
  if (a.dataset.cal) { track(a.dataset.cal, 'event_calendar', a.dataset.k || state.detail); return }
  track('conversion', ['entradas', 'inscripcion'].includes(a.dataset.lk) ? 'ticket_click' : 'organizer_click', state.detail);
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') { periodMenu(false); closeSheet(); if ($('filters').classList.contains('open')) openDrawer(false) } });
$('overlay').addEventListener('click', e => { if (e.target === $('overlay')) closeSheet() });
$('drawerBackdrop').addEventListener('click', () => openDrawer(false));
$('formatFilter').addEventListener('change', e => { track('filtro', 'filter_format', e.target.value || 'todos', e.target.value ? 1 : 0); state.format = e.target.value; refresh() });
$('lang')?.addEventListener('change', ev => { const next = ev.target.value; try { localStorage.setItem('brollant-lang', next) } catch (_) {} const u = new URL(location.href); u.searchParams.delete('lang'); location.replace(u.href) });
$('districtFilter').addEventListener('change', e => { track('filtro', 'filter_district', e.target.value || 'todos', e.target.value ? 1 : 0); state.district = e.target.value; refresh() });
$('freeOnly').addEventListener('change', e => { track('filtro', 'filter_free', 'gratis', e.target.checked ? 1 : 0); state.free = e.target.checked; refresh() });
// El campo de fecha va invisible encima del botón «Fecha»: en Chrome y Safari de escritorio un clic
// en él no abre el calendario (solo su icono, que no se ve). Se abre explícitamente.
$('dayPicker').addEventListener('click', e => { try { e.target.showPicker() } catch (_) { /* navegador sin showPicker: comportamiento nativo */ } });
$('dayPicker').addEventListener('change', e => { if (!e.target.value) return; track('filtro', 'filter_date', 'fecha_concreta'); state.day = e.target.value; state.range = ''; state.dayOpen = true; refresh() });
$('daysPrev').addEventListener('click', () => { $('days').scrollBy({left: -$('days').clientWidth * 0.8}) });
$('daysNext').addEventListener('click', () => { $('days').scrollBy({left: $('days').clientWidth * 0.8}) });
$('searchInput').addEventListener('input', e => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.query = e.target.value.trim(); channelView(); syncUrl(); days(); renderActive(); agenda() }, 250) });
// Enter keeps the typed text and applies it at once (the form must never submit: that would reload the page without the query).
$('searchForm').addEventListener('submit', e => { e.preventDefault(); clearTimeout(searchTimer); state.query = $('searchInput').value.trim(); channelView(); syncUrl(); days(); renderActive(); agenda(); $('searchInput').blur(); scrollToId('agenda') });
function setHours(changed) {
  let from = Number($('hourFrom').value), to = Number($('hourTo').value);
  if (changed === 'from' && from > to) { to = from; $('hourTo').value = to } if (changed === 'to' && to < from) { from = to; $('hourFrom').value = from }
  state.hourFrom = from; state.hourTo = to; track('filtro', 'filter_hours', `${from}-${to}`, 1); refresh();   // al soltar el control (change), no en cada movimiento
}
$('hourFrom').addEventListener('change', () => setHours('from')); $('hourTo').addEventListener('change', () => setHours('to'));
$('hourFrom').addEventListener('input', e => { $('hourFromLabel').textContent = hourLabel(e.target.value) }); $('hourTo').addEventListener('input', e => { $('hourToLabel').textContent = hourLabel(e.target.value) });
$('clearHours').addEventListener('click', () => { state.hourFrom = null; state.hourTo = null; refresh() });

// Hero: the last word is retyped every few seconds (hoy → mañana → este fin de
// semana → esta semana → este mes), typewriter style. The heading keeps a fixed
// accessible name; the animation stops when the tab is hidden or when the
// visitor prefers reduced motion.
function typeHero() {
  const el = $('heroWord'); if (!el) return;
  const words = ['hoy.', 'mañana.', 'este fin de semana.', 'esta semana.', 'este mes.'].map(t);
  $('heroTitle').setAttribute('aria-label', `${t('Qué hacer en Barcelona')} ${words[0]}`);
  const fit = w => {   // 28-10-2026 (David): todo al mismo tamaño; solo encoge la palabra que no cabe (p. ej. «aquest cap de setmana.» en móvil)
    el.style.fontSize = ''; el.style.lineHeight = ''; el.style.minHeight = '';
    const probe = document.createElement('span'); probe.style.cssText = 'position:absolute;visibility:hidden;white-space:nowrap'; probe.textContent = w; el.append(probe);
    const r = Math.min(1, (el.parentElement.clientWidth - 4) / probe.getBoundingClientRect().width); probe.remove();
    if (r < 1) { const lh = parseFloat(getComputedStyle(el).lineHeight) || 0; el.style.fontSize = (Math.floor(r * 100) / 100) + 'em'; if (lh) { el.style.lineHeight = lh + 'px'; el.style.minHeight = lh + 'px' } }
  };
  fit(el.textContent); window.addEventListener('resize', () => fit(words.find(w => w.startsWith(el.textContent)) || el.textContent), {passive: true});
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const visible = async () => { while (document.hidden) await wait(500) };
  (async () => {
    let i = 0; el.classList.add('typing'); await wait(2600);
    for (;;) {
      await visible();
      const current = el.textContent; for (let n = current.length; n >= 0; n--) { el.textContent = current.slice(0, n); await wait(38) }
      await wait(260); i = (i + 1) % words.length; const next = words[i]; fit(next);  // si no cabe en su línea, se reduce lo justo y la línea conserva su altura
      for (let n = 1; n <= next.length; n++) { el.textContent = next.slice(0, n); await wait(n === next.length ? 0 : 55 + Math.random() * 45) }
      await wait(2600);
    }
  })();
}

(async () => {
  let theme = 'dark'; try { theme = pref('theme') || 'dark' } catch (_) {}
  // v1: oscuro por defecto. v2 (22-10-2026): sigue el modo del sistema. En las dos, el botón sol/luna lo cambia y se recuerda.
  if (SKIN === 'v2') theme = 'light';  // v2 solo en claro (23-10-2026: el oscuro no convenció; los colores siguen con nombre por si se retoma)
  document.documentElement.dataset.theme = theme; translatePage(); typeHero(); deskLayout();
  const initial = eventFromPath();  // read before the first syncUrl rewrites the address
  saveState(); await refresh();
  if (initial) { state.detail = null; syncUrl(); openDetail(initial, null, {origin: 'enlace'}) }  // list entry first, then the sheet: Back shows the agenda
  if (STATIC) { const warm = () => loadCatalog().catch(() => {}); 'requestIdleCallback' in window ? requestIdleCallback(warm) : setTimeout(warm, 800) }
})();
