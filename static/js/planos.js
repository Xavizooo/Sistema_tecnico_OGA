let lastResult = null;
const bodies = { EN: el('tbodyEN'), PF: el('tbodyPF'), PZ: el('tbodyPZ'), FRAME: el('tbodyFRAME'), LM: el('tbodyLM'), ESTANDAR: el('tbodySTD') };
function el(id) { return document.getElementById(id) }
function toast(msg) { const t = el('toast'); t.textContent = msg; t.classList.remove('hidden'); setTimeout(() => t.classList.add('hidden'), 3500) }
function dot(ok) { return `<span class="dot ${ok ? 'ok' : ''}"></span>` }
function fmt(v, d = 3) { if (v === null || v === undefined || v === '') return ''; let n = Number(v); return isNaN(n) ? v : n.toFixed(d) }
function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[character]);
}
function naturalCompare(a, b) { return String(a || '').localeCompare(String(b || ''), 'es', { numeric: true, sensitivity: 'base' }) }
function clearTables() { Object.values(bodies).forEach(b => b.innerHTML = ''); el('tbodyLaminaGroup').innerHTML = ''; el('downloadCurrent').classList.add('hidden') }
const pdfObjectUrls = {};
function showNativePdf(file, containerId, openButtonId) {
  if (pdfObjectUrls[containerId]) URL.revokeObjectURL(pdfObjectUrls[containerId]);
  const url = URL.createObjectURL(file);
  pdfObjectUrls[containerId] = url;
  const container = el(containerId);
  container.classList.add('has-pdf');
  container.innerHTML = `<iframe class="native-pdf-frame" src="${url}#page=1&zoom=page-width" title="Visor PDF"></iframe>`;
  const openButton = el(openButtonId);
  openButton.classList.remove('hidden');
  openButton.onclick = () => window.open(url, '_blank');
}
function clearNativePdf(containerId, openButtonId) {
  if (pdfObjectUrls[containerId]) {
    URL.revokeObjectURL(pdfObjectUrls[containerId]);
    delete pdfObjectUrls[containerId];
  }
  const container = el(containerId);
  container.classList.remove('has-pdf');
  container.innerHTML = '<div>Seleccione un PDF para abrirlo con el visor tradicional del navegador.</div>';
  const openButton = el(openButtonId);
  openButton.classList.add('hidden');
  openButton.onclick = null;
}
function rowItem(it) {
  const missing = it.requiere_plano && !it.tiene_plano;
  const text = (it.codigo + ' ' + (it.descripcion || '')).toLowerCase();
  if (it.tipo === 'LM') return `<tr class="${missing ? 'row-missing' : ''}" data-text="${esc(text)}"><td>${esc(it.codigo)}</td><td>${dot(it.tiene_plano)}</td><td>${esc(it.cantidad)}</td><td>${esc(it.espesor || '')}</td><td class="area">${esc(fmt(it.area_m2_total))}</td></tr>`;
  if (it.tipo === 'ESTANDAR') return `<tr data-text="${esc(text)}"><td>${esc(it.codigo)}</td><td>${esc(it.descripcion || '')}</td><td>${esc(it.cantidad || '')}</td></tr>`;
  if (it.tipo === 'FRAME') return `<tr class="${missing ? 'row-missing' : ''}" data-text="${esc(text)}"><td>${esc(it.codigo)}</td><td>${esc(it.descripcion || '')}</td><td>${dot(it.tiene_plano)}</td><td>${esc(it.hoja_plano || '')}</td></tr>`;
  return `<tr class="${missing ? 'row-missing' : ''}" data-text="${esc(text)}"><td>${esc(it.codigo)}</td><td>${dot(it.tiene_plano)}</td><td>${esc(it.hoja_plano || '')}</td></tr>`;
}
function renderResult(result) {
  lastResult = result; clearTables();
  const sorted = [...result.items].sort((a, b) => naturalCompare(a.codigo, b.codigo) || naturalCompare(a.descripcion, b.descripcion));
  sorted.forEach(it => { let key = bodies[it.tipo] ? it.tipo : 'FRAME'; if (bodies[key]) bodies[key].insertAdjacentHTML('beforeend', rowItem(it)); });
  renderLaminaGroup(result.lamina_resumen); el('downloadCurrent').classList.remove('hidden'); toast('Revision terminada y Excel guardado');
}
function renderLaminaGroup(rows) { let b = el('tbodyLaminaGroup'); b.innerHTML = '';[...rows].sort((a, b) => naturalCompare(a.espesor, b.espesor)).forEach(r => b.insertAdjacentHTML('beforeend', `<tr><td>${esc(r.espesor)}</td><td>${esc(r.espesor)}</td><td class="area">${esc(fmt(r.area_m2_total))}</td></tr>`)); }
el('pdfInput').addEventListener('change', async e => { const f = e.target.files[0]; if (!f) return; const fd = new FormData(); fd.append('pdf', f); el('fileName').textContent = f.name; showNativePdf(f, 'viewer', 'openPdfTab'); const res = await fetch('/planos/upload', { method: 'POST', body: fd }); const data = await res.json(); if (!data.ok) toast(data.error || 'Error cargando PDF'); else toast('PDF cargado') });
el('reviewBtn').addEventListener('click', async () => { document.body.classList.add('loading'); try { const res = await fetch('/planos/review', { method: 'POST' }); const data = await res.json(); if (!data.ok) toast(data.error || 'Error al revisar'); else renderResult(data.result) } catch (e) { toast('Error: ' + e.message) } finally { document.body.classList.remove('loading') } });
el('clearBtn').addEventListener('click', async () => { await fetch('/planos/clear', { method: 'POST' }); clearTables(); el('fileName').textContent = '(Ningún plano cargado)'; clearNativePdf('viewer', 'openPdfTab'); el('pdfInput').value = ''; toast('Pantalla limpia. El historial no se borra.') });
document.querySelectorAll('.table-search[data-filter]').forEach(inp => inp.addEventListener('input', e => { const key = e.target.dataset.filter; const q = e.target.value.toLowerCase(); bodies[key].querySelectorAll('tr').forEach(tr => tr.style.display = (tr.dataset.text || '').includes(q) ? '' : 'none') }));
async function deleteReport(name) { if (!confirm('Eliminar este Excel de planos revisados?')) return; const res = await fetch('/planos/delete/report/' + encodeURIComponent(name), { method: 'POST' }); const data = await res.json(); if (!data.ok) toast(data.error || 'No se pudo eliminar'); else { toast('Archivo eliminado'); loadHistory(); } }
async function loadHistory() {
  const res = await fetch('/planos/history');
  const data = await res.json();
  const body = el('historyBody');
  body.innerHTML = '';
  (data.files || []).forEach(f => body.insertAdjacentHTML('beforeend', `<tr><td>${esc(f.name)}</td><td>${esc(f.mtime)}</td><td>${esc(Math.round(f.size / 1024))} KB</td><td><a class="btn success small" href="/planos/download/report/${encodeURIComponent(f.name)}">DESCARGAR</a></td><td><button class="btn danger small" type="button" data-delete-report="${esc(f.name)}">ELIMINAR</button></td></tr>`));
  body.querySelectorAll('[data-delete-report]').forEach(button => {
    button.addEventListener('click', () => deleteReport(button.dataset.deleteReport));
  });
}
function showView(name) { ['Revisor', 'Historial', 'Distribucion'].forEach(v => { el('view' + v).classList.toggle('hidden', v !== name); el('tab' + v).classList.toggle('active', v === name) }); if (name === 'Historial') loadHistory(); }
el('tabHistorial').addEventListener('click', () => showView('Historial')); el('tabRevisor').addEventListener('click', () => showView('Revisor')); el('tabDistribucion').addEventListener('click', () => showView('Distribucion'));

function renderExcelPreview(tbodyId, rows) { const b = el(tbodyId); b.innerHTML = '';[...rows].sort((a, b) => naturalCompare(a.codigo, b.codigo)).forEach(r => b.insertAdjacentHTML('beforeend', `<tr data-text="${esc(String(r.codigo || '').toLowerCase())}"><td>${esc(r.codigo)}</td><td>${esc(fmt(r.cantidad, 0))}</td><td>${esc(r.espesor || '')}</td></tr>`)); }
async function uploadDistExcel(inputId, url, bodyId) { const f = el(inputId).files[0]; if (!f) return; const fd = new FormData(); fd.append('excel', f); const res = await fetch(url, { method: 'POST', body: fd }); const data = await res.json(); if (!data.ok) toast(data.error || 'Error cargando Excel'); else { renderExcelPreview(bodyId, data.rows || []); toast('Excel cargado: ' + data.name); } }
el('distPdfInput').addEventListener('change', async e => { const f = e.target.files[0]; if (!f) return; const fd = new FormData(); fd.append('pdf', f); el('distFileName').textContent = f.name; showNativePdf(f, 'distViewer', 'openDistPdfTab'); const res = await fetch('/planos/dist/upload_pdf', { method: 'POST', body: fd }); const data = await res.json(); if (!data.ok) toast(data.error || 'Error cargando PDF'); else toast('PDF de distribucion cargado') });
el('lmExcelInput').addEventListener('change', () => uploadDistExcel('lmExcelInput', '/planos/dist/upload_lm', 'lmExcelBody'));
el('dxfExcelInput').addEventListener('change', () => uploadDistExcel('dxfExcelInput', '/planos/dist/upload_dxf', 'dxfExcelBody'));
el('distReviewBtn').addEventListener('click', async () => { document.body.classList.add('loading'); try { const res = await fetch('/planos/dist/review', { method: 'POST' }); const data = await res.json(); if (!data.ok) toast(data.error || 'Error al revisar'); else renderDistribution(data.result) } catch (e) { toast('Error: ' + e.message) } finally { document.body.classList.remove('loading') } });
function renderDistribution(result) { const b = el('foundLmBody'); b.innerHTML = ''; (result.rows || []).forEach(r => b.insertAdjacentHTML('beforeend', `<tr class="${r.ok ? '' : 'row-missing'}" data-text="${esc(String(r.codigo || '').toLowerCase())}"><td>${esc(r.codigo)}</td><td>${dot(r.tiene_plano)}</td><td>${esc(r.hoja || '')}</td><td>${esc(fmt(r.cant_lm, 0))}</td><td>${esc(fmt(r.cant_dxf, 0))}</td><td>${esc(r.espesor_lm || '')}</td><td>${esc(r.espesor_dxf || '')}</td><td>${esc(r.diferencia || '')}</td></tr>`)); toast('Revision de distribucion terminada'); }
el('distClearBtn').addEventListener('click', async () => { await fetch('/planos/dist/clear', { method: 'POST' }); el('distFileName').textContent = '(Ningún plano cargado)'; clearNativePdf('distViewer', 'openDistPdfTab');['lmExcelBody', 'dxfExcelBody', 'foundLmBody'].forEach(id => el(id).innerHTML = '');['distPdfInput', 'lmExcelInput', 'dxfExcelInput'].forEach(id => el(id).value = ''); toast('Revision de distribucion limpia'); });
document.querySelectorAll('.table-search[data-dist-filter]').forEach(inp => inp.addEventListener('input', e => { const q = e.target.value.toLowerCase(); el(e.target.dataset.distFilter).querySelectorAll('tr').forEach(tr => tr.style.display = (tr.dataset.text || '').includes(q) ? '' : 'none') }));
