'use strict';
const $=id=>document.getElementById(id);
const labels={pending:'Pendiente',needs_evidence:'Pedir evidencia',reviewed:'Revisada',excluded:'Excluida'};
let view='explore',page=1,options={},details=null,latest={};
const fields=['search','date','category','district','source','kind','status','onlySessions'];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const date=s=>{if(!s)return 'Fecha sin verificar';let [y,m,d]=s.split('-');return `${d}/${m}/${y}`};
const short=s=>{if(!s)return 'Lugar sin identificar';return s.length>75?s.slice(0,72)+'…':s};
const safeurl=s=>{try{let u=new URL(s);return ['http:','https:'].includes(u.protocol)?u.href:null}catch(_){return null}};
async function get(path){const r=await fetch(path,{cache:'no-store'});let d=await r.json();if(!r.ok)throw Error(d.error||'Error HTTP');return d}
async function boot(){
 try{options=await get('/api/options');populate('category',options.categories);populate('district',options.districts);populate('source',options.sources);populate('kind',options.kinds);populate('status',Object.fromEntries(Object.entries(labels)));
 let st=await get('/api/stats');$('quickStats').innerHTML=[['Fichas de origen',st.total],['Horas candidatas',st.candidate_occurrences],['Distritos identificados',st.district_known],['Publicadas',st.published]].map(([name,v])=>`<div class="stat"><strong>${v}</strong><span>${esc(name)}</span></div>`).join('');
 fields.forEach(k=>$(k).addEventListener(['search'].includes(k)?'input':'change',()=>{page=1;show()}));
 $('clear').onclick=()=>{fields.forEach(k=>{if(k==='onlySessions')$(k).checked=false;else $(k).value=''});page=1;show()};
 $('viewExplore').onclick=()=>setView('explore');$('viewReview').onclick=()=>setView('review');$('viewMetrics').onclick=()=>setView('metrics');
 $('closePanel').onclick=close; $('overlay').onclick=e=>{if(e.target===$('overlay'))close()};document.addEventListener('keydown',e=>{if(e.key==='Escape')close()});
 await show();
 }catch(e){$('cards').innerHTML=`<div class="empty">No se pudo iniciar: ${esc(e.message)}</div>`}
}
function populate(id,data){for(const [v,label] of Array.isArray(data)?data.map(v=>[v,v]):Object.entries(data)){const opt=document.createElement('option');opt.value=v;opt.textContent=label;$(id).append(opt)}}
function setView(which){view=which;page=1;document.querySelector('.filters').classList.toggle('hidden',which==='metrics');document.querySelector('.shell').classList.toggle('metrics-mode',which==='metrics');['Explore','Review','Metrics'].forEach(s=> $('view'+s).classList.toggle('active',which===s.toLowerCase()));
 $('status').value=which==='review'?'pending':'';$('status').disabled=which==='metrics';show()}
function filters(){const f={query:$('search').value.trim(),date:$('date').value,category:$('category').value,district:$('district').value,source:$('source').value,kind:$('kind').value,status:$('status').value,only_sessions:$('onlySessions').checked?'1':'0',page:String(page),page_size:'24'};
 if(view==='review'&&!f.status)f.status='pending';return new URLSearchParams(f)}
async function show(){
 $('metrics').classList.toggle('hidden',view!=='metrics');$('cards').classList.toggle('hidden',view==='metrics');$('pages').classList.toggle('hidden',view==='metrics');$('totalCount').textContent='';
 if(view==='metrics'){ $('sectionTitle').textContent='Indicadores del piloto';$('sectionDesc').textContent='Métricas técnicas, no estimaciones de cobertura.';let s=await get('/api/stats');renderMetrics(s);return;}
 $('sectionTitle').textContent=view==='review'?'Cola de revisión':'Actividades encontradas';
 $('sectionDesc').textContent=view==='review'?'Registra decisiones editoriales. Ninguna revisión publica la actividad.':'Fichas sin publicar de la Generalitat, Diputació y benchmark municipal.';
 try{let d=await get('/api/events?'+filters());latest=d;$('totalCount').textContent=d.total+' fichas';
 $('cards').innerHTML=d.items.length?d.items.map(card).join(''):'<div class="empty">No encontramos registros con esos filtros. Prueba otra fecha o quita el filtro de distrito.</div>';
 document.querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>open(b.getAttribute('data-source'),b.getAttribute('data-id')));
 $('pages').innerHTML=d.pages>1?`<button id="prev" ${page===1?'disabled':''}>← Anterior</button><span> ${page} de ${d.pages} </span><button id="next" ${page>=d.pages?'disabled':''}>Siguiente →</button>`:'';
 if($('prev'))$('prev').onclick=()=>{page--;show()};if($('next'))$('next').onclick=()=>{page++;show()};
 }catch(e){$('cards').innerHTML=`<div class="empty">Error: ${esc(e.message)}</div>`}
}
function card(e){let occ=e.occurrences.filter(x=>!$('date').value||x.date===$('date').value),time=occ.length?`${date(occ[0].date)} · ${occ.map(x=>x.time).join(', ')} (sin verificar)`:'',when=time||((e.start===e.end)?`${date(e.start)} · hora no verificada`:`${date(e.start)} — ${date(e.end)} · intervalo, sin sesiones confirmadas`);
 return `<article class="event"><div class="eventmain"><div class="labels"><span class="pill mint">${esc(e.category)}</span><span class="pill ${e.has_candidate?'blue':'orange'}">${e.has_candidate?'Hora candidata':esc(e.kind_label)}</span>${e.status!=='pending'?`<span class="pill">${esc(labels[e.status])}</span>`:''}</div><h3>${esc(e.title)}</h3><p class="meta"><span class="meta-icon">◷</span>${esc(when)}</p><p class="meta"><span class="meta-icon">⌖</span>${esc(short(e.venue_names.join(' · ')))}</p>${e.district?`<p class="meta"><span class="meta-icon">◇</span>${esc(e.district)}</p>`:''}</div><div class="eventbottom"><span class="origin">${esc(e.source_label)}</span><button type="button" class="detailbtn" data-open="1" data-source="${esc(e.source)}" data-id="${esc(e.id)}">Ver ficha ↗</button></div></article>`}
async function open(source,id){try{details=await get('/api/event?'+new URLSearchParams({source,id}));$('overlay').classList.remove('hidden');document.body.style.overflow='hidden';renderDetail(details);$('closePanel').focus()}catch(e){alert('Error: '+e.message)}}
function close(){$('overlay').classList.add('hidden');document.body.style.overflow='';details=null}
function renderDetail(e){const d=e.venues.length?e.venues.map(v=>`<div class="fact"><small>Recinto</small><strong>${esc(v.name||'Sin nombre')}</strong><span>${esc(v.address||'')}</span></div>`).join(''):'<p>No identificado</p>';
 const links=e.links.length?e.links.map(l=>`<p><a href="${esc(safeurl(l.url)||'#')}" target="_blank" rel="noopener noreferrer">${esc(l.label)} ↗</a> <small>(enlace de fuente, sin verificación actual)</small></p>`).join(''):'<p>La fuente no trae enlace directo; requiere comprobación manual.</p>';
 const occ=e.occurrences.length?e.occurrences.map(o=>`${date(o.date)} · ${o.time} (candidata, no verificada)`).join('; '):'No hay sesiones puntuales verificadas o candidatas';
 $('detail').innerHTML=`<div class="labels" style="margin-top:20px"><span class="pill mint">${esc(e.category)}</span><span class="pill orange">No publicada</span><span class="pill">${esc(e.source_label)}</span></div><h2 id="detailTitle">${esc(e.title)}</h2><div class="detail-grid"><div class="fact"><small>Fechas de origen</small><strong>${date(e.start)} — ${date(e.end)}</strong></div><div class="fact"><small>Tipo de registro</small><strong>${esc(e.kind_label)}</strong></div><div class="fact"><small>Distrito</small><strong>${esc(e.district||'No identificado')}</strong></div><div class="fact"><small>Estado editorial</small><strong>${esc(labels[e.status])}</strong></div></div>
 <section class="detail-section"><h3>Horas / programación</h3><p>${esc(occ)}</p><p><strong>Texto original del horario:</strong> ${esc(e.time_text||'No disponible')}</p><p><strong>Precio:</strong> ${esc(e.price_text||e.source_free_label||'Desconocido')} <small> (sin verificación primaria)</small></p></section>
 <section class="detail-section"><h3>Recintos y descripción</h3><div class="detail-grid">${d}</div>${e.description?`<p>${esc(e.description.slice(0,2500))}</p>`:'<p>Descripción no disponible o no archivada.</p>'}</section>
 <section class="detail-section"><h3>Procedencia y evidencia</h3>${links}<p><strong>ID de origen:</strong> <code>${esc(e.key)}</code></p><p><strong>Nivel de evidencia:</strong> ${esc(e.evidence_level)}</p><p><strong>Organizadores:</strong> ${esc(e.organizers.join(', ')||'No identificados')}</p><p class="msg">Ninguna revisión en este prototipo habilita la publicación automática ni autoriza reutilizar imágenes.</p></section>
 <section class="detail-section"><h3>Alertas de calidad (${e.alerts.length})</h3><div class="alertlist">${e.alerts.map(a=>`<span>${esc(a)}</span>`).join('')||'<span>Sin alertas mecánicas</span>'}</div></section>
 <div class="editor"><h3>Decisión editorial local</h3><p class="msg">Guardar una revisión no confirma horarios ni publica el evento. Se conserva un historial de cambios.</p><label for="reviewStatus">Estado</label><select id="reviewStatus">${Object.entries(labels).map(([v,l])=>`<option value="${v}" ${e.status===v?'selected':''}>${esc(l)}</option>`).join('')}</select><label for="reviewNote">Nota de revisión</label><textarea id="reviewNote" placeholder="Qué comprobaste y qué falta…">${esc(e.review_note)}</textarea><button id="saveReview" class="actionbtn" type="button">Guardar revisión</button><div id="reviewMsg" class="msg" role="status"></div></div>`;
 $('saveReview').onclick=saveReview
}
async function saveReview(){let b=$('saveReview');b.disabled=true;try{let r=await fetch('/api/review',{method:'POST',headers:{'Content-Type':'application/json','X-Loagendo-Local':'1'},body:JSON.stringify({source:details.source,id:details.id,status:$('reviewStatus').value,note:$('reviewNote').value})});let d=await r.json();if(!r.ok)throw Error(d.error);$('reviewMsg').className='msg ok';$('reviewMsg').textContent='Revisión guardada. La actividad sigue sin publicarse.';details.status=d.status;details.review_note=d.note;await show()}catch(e){$('reviewMsg').className='msg error';$('reviewMsg').textContent=e.message}finally{b.disabled=false}}
function renderMetrics(s){const blocks=[['Por fuente',s.sources,options.sources],['Por tipo',s.kinds,options.kinds],['Por estado',s.statuses,labels],['Por categoría (provisional)',s.by_category,{}]]; $('metrics').innerHTML=`<h3>${s.total} fichas · ${s.candidate_occurrences} horas candidatas · 0 publicadas</h3><p class="msg">${s.district_known} registros con distrito explícito y ${s.district_unknown} sin distrito. No mide exhaustividad ni precisión de sesiones. Instantánea de octubre de 2026.</p><div class="metrics-grid">${blocks.map(([title,items,lookups])=>`<div><h3>${esc(title)}</h3><table class="metric-table">${Object.entries(items).sort((a,b)=>b[1]-a[1]).map(([k,v])=>`<tr><td>${esc(lookups[k]||k)}</td><td>${v}</td></tr>`).join('')}</table></div>`).join('')}</div>`}
boot();
