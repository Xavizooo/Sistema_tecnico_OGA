/* REV15: library-only controllers. All URLs are supplied by Flask. */
'use strict';
const libraryUrls = window.bibliotecaUrls || {};
let libraryModalTrigger = null;
function bUrl(template, replacements = {}) {
  let result = template || '';
  for (const [key, value] of Object.entries(replacements)) result = result.replace(key, encodeURIComponent(String(value)));
  return result;
}
function openModal(id) {
  const el = document.getElementById(id);
  if (!el) return;
  libraryModalTrigger = document.activeElement;
  el.classList.add('show');
  el.setAttribute('role', 'dialog');
  el.setAttribute('aria-modal', 'true');
  const title = el.querySelector('h3');
  if (title) { title.id = `${id}-title`; el.setAttribute('aria-labelledby', title.id); }
  document.body.style.overflow = 'hidden';
  el.querySelector('input:not([type="hidden"]):not([disabled]), select, button')?.focus();
}
function closeModal(id) {
  document.getElementById(id)?.classList.remove('show');
  document.body.style.overflow = '';
  libraryModalTrigger?.focus();
}
window.addEventListener('click', event => {
  document.querySelectorAll('.biblioteca-module .modal.show').forEach(m => { if (event.target === m) closeModal(m.id); });
});
document.addEventListener('keydown', event => {
  const modal = document.querySelector('.biblioteca-module .modal.show');
  if (!modal) return;
  if (event.key === 'Escape') closeModal(modal.id);
  if (event.key === 'Tab') {
    const focusable = Array.from(modal.querySelectorAll('button, input:not([type="hidden"]):not([disabled]), select, a[href]')).filter(x => x.getClientRects().length);
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }
});
function openEditEquipo(e) {
  document.getElementById('formEquipoEditar').action = bUrl(libraryUrls.editEquipo, {'__CODE__': e.codigo});
  document.getElementById('edit-equipo-codigo').value = e.codigo;
  document.getElementById('edit-equipo-nombre').value = e.nombre;
  openModal('modalEquipoEditar');
}
function countRows(id) { return document.getElementById(id)?.querySelectorAll('.sub-row').length || 0; }
function renumberSubRows(id) {
  document.getElementById(id)?.querySelectorAll('.sub-row').forEach((row, index) => {
    row.querySelector('.sub-num').textContent = index + 1;
    row.querySelectorAll('input').forEach(input => {
      input.name = (input.name.startsWith('sub_codigo_') ? 'sub_codigo_' : 'sub_texto_') + (index + 1);
    });
  });
}
function addSubRow(id, codigo = '', texto = '') {
  const list = document.getElementById(id);
  if (!list) return;
  if (countRows(id) >= 50) { alert('Puede crear hasta 50 subcaracter\u00edsticas por caracter\u00edstica.'); return; }
  const index = countRows(id) + 1;
  const row = document.createElement('div'); row.className = 'sub-row';
  const num = document.createElement('span'); num.className = 'sub-num'; num.textContent = index;
  const code = document.createElement('input'); code.name = `sub_codigo_${index}`; code.placeholder = 'C\u00f3digo'; code.value = codigo;
  const text = document.createElement('input'); text.name = `sub_texto_${index}`; text.placeholder = 'Descripci\u00f3n'; text.value = texto;
  const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'remove-sub'; remove.textContent = '\u00d7'; remove.title = 'Quitar subcaracter\u00edstica';
  remove.addEventListener('click', () => removeSubRow(remove));
  row.append(num, code, text, remove); list.append(row);
}
function ensureBaseRows(id, total = 10) { const list = document.getElementById(id); if (list && !list.children.length) for (let i = 0; i < total; i++) addSubRow(id); }
function resetSubList(id) { document.getElementById(id)?.replaceChildren(); }
function removeSubRow(button) { const row = button.closest('.sub-row'); const list = row?.parentElement; row?.remove(); if (list) renumberSubRows(list.id); }
function openEditChar(c) {
  document.getElementById('formCaracteristicaEditar').action = bUrl(libraryUrls.editChar, {'__CODE__': c.equipo_codigo, '__ORDER__': c.orden});
  document.getElementById('edit-char-orden').value = c.orden;
  document.getElementById('edit-char-nombre').value = c.nombre;
  document.getElementById('edit-char-color').value = c.grupo_color;
  resetSubList('edit-sub-list');
  (c.subcaracteristicas || []).forEach(s => addSubRow('edit-sub-list', s.codigo || '', s.texto || ''));
  ensureBaseRows('edit-sub-list', 1); openModal('modalCaracteristicaEditar');
}
function openEditReferencia(r) {
  const form = document.getElementById('formReferenciaEditar'); form.reset();
  form.action = bUrl(libraryUrls.editReferencia, {'__CODE__': r.referencia_codigo});
  document.getElementById('edit-ref-code').value = r.referencia_codigo;
  document.getElementById('edit-ref-costo').value = r.costo || '';
  openModal('modalReferenciaEditar');
}
function submitBibliotecaSearch() {
  const form = document.createElement('form'); form.method = 'post'; form.action = libraryUrls.buscarReferencia;
  function hidden(name, value) { const input = document.createElement('input'); input.type = 'hidden'; input.name = name; input.value = value; form.append(input); }
  hidden('_csrf_token', securityToken());
  hidden('equipo_codigo', document.getElementById('biblioteca-equipo-codigo')?.value || '');
  document.querySelectorAll('.biblioteca-module .subchoice:not(.search-subchoice)').forEach(sel => hidden(sel.name, sel.value));
  document.body.append(form); form.submit();
}
function openDownloadModal(r) {
  const el = document.getElementById('download-options'); if (!el) return; el.replaceChildren();
  const items = [['Planos PDF', 'planos', r.planos, r.has_planos], ['Modelo 3D ZIP', 'modelo3d', r.modelo3d, r.has_modelo3d], ['Lista de materiales XLSM', 'lista_materiales', r.lista_materiales, r.has_lista_materiales], ['Ficha t\u00e9cnica DOCX', 'ficha_tecnica', r.ficha_tecnica, r.has_ficha_tecnica]];
  items.forEach(([label, kind, filename, ok]) => {
    const element = document.createElement(ok ? 'a' : 'span');
    element.className = `download-item ${ok ? 'ok' : 'disabled'}`;
    element.textContent = label + (ok ? '' : ' - No disponible');
    if (ok) element.href = bUrl(libraryUrls.download, {'__KIND__': kind, '__FILE__': filename});
    el.append(element);
  });
  openModal('modalDescargar');
}
function changeSearchEquipo(code) { const url = new URL(libraryUrls.buscador, window.location.origin); url.searchParams.set('equipo', code); window.location.assign(url); }
function limpiarBuscador() { changeSearchEquipo(document.getElementById('search-equipo')?.value || ''); }
function getCurrentSearchSelections() { const result = {}; document.querySelectorAll('.search-subchoice').forEach(sel => { result[sel.dataset.orden] = sel.value || ''; }); return result; }
function referenceMatchesSelections(ref, selections) {
  const mapping = {}; (ref.selecciones || []).forEach(s => { mapping[String(s.orden)] = String(s.codigo || '').toUpperCase(); });
  return Object.entries(selections).every(([orden, value]) => !value || mapping[orden] === String(value).toUpperCase());
}
function updateSearchOptionStates() {
  const selections = getCurrentSearchSelections();
  document.querySelectorAll('.search-subchoice').forEach(sel => {
    const order = sel.dataset.orden; const current = sel.value;
    sel.replaceChildren(new Option('Seleccione...', ''));
    (window.searchAllOptions?.[order] || []).forEach(opt => {
      const matches = {...selections, [order]: opt.codigo};
      const option = new Option(`${opt.codigo}. ${opt.texto}`, opt.codigo);
      option.disabled = !window.searchReferences.some(ref => referenceMatchesSelections(ref, matches));
      option.selected = current === String(opt.codigo); sel.append(option);
    });
    if (sel.selectedIndex === -1) sel.value = '';
  });
}
function renderSearchTable(filtered) {
  const ids = new Set(filtered.map(r => r.referencia_codigo));
  document.querySelectorAll('.search-ref-row').forEach(row => { const ref = JSON.parse(row.dataset.ref); row.style.display = ids.has(ref.referencia_codigo) ? '' : 'none'; });
  const count = document.getElementById('search-result-count'); if (count) count.textContent = `${filtered.length} referencia${filtered.length === 1 ? '' : 's'} encontrada${filtered.length === 1 ? '' : 's'}`;
}
function formatMoneyJs(value) {
  const raw = String(value ?? '').trim(); if (!raw) return 'Sin costo';
  // Same convention as the source Excel: numeric values, optionally $ and commas.
  const num = Number(raw.replace(/[$,\s]/g, '')); if (!Number.isFinite(num)) return raw;
  return '$ ' + num.toLocaleString('es-CO', {maximumFractionDigits: 0});
}
function updateSearchPreview(filtered) {
  const box = document.getElementById('search-ref-box'), cost = document.getElementById('search-cost'), status = document.getElementById('search-status');
  const frame = document.getElementById('search-pdf'), wrap = document.getElementById('search-pdf-wrap');
  if (!box || !frame || !wrap || !cost || !status) return;
  const ref = filtered.length === 1 ? filtered[0] : null;
  box.textContent = ref?.referencia_codigo || ''; cost.textContent = formatMoneyJs(ref?.costo);
  status.textContent = ref ? 'Referencia existente' : filtered.length ? 'Selecciona una referencia o aplica m\u00e1s filtros' : 'No hay referencias con estos filtros';
  status.classList.toggle('success-text', !!ref); status.classList.toggle('error-text', !filtered.length);
  if (ref?.has_planos && ref.preview_url) {
    const src = ref.preview_url + '#toolbar=0&navpanes=0&page=1';
    if (frame.getAttribute('src') !== src) frame.src = src;
    frame.classList.remove('hidden-frame'); wrap.classList.remove('empty');
  } else {
    frame.removeAttribute('src'); frame.classList.add('hidden-frame'); wrap.classList.add('empty');
    let message = wrap.querySelector('.pdf-empty-message');
    if (!message) { message = document.createElement('span'); message.className = 'pdf-empty-message'; wrap.append(message); }
    message.textContent = ref ? 'Sin plano PDF para esta referencia' : 'Seleccione una referencia con plano PDF';
  }
}
function updateSearchFilters() {
  if (!window.searchReferences) return;
  updateSearchOptionStates();
  const selected = getCurrentSearchSelections();
  const filtered = window.searchReferences.filter(ref => referenceMatchesSelections(ref, selected));
  renderSearchTable(filtered); updateSearchPreview(filtered);
}
function selectSearchReference(ref) {
  const values = {}; (ref.selecciones || []).forEach(s => { values[String(s.orden)] = String(s.codigo); });
  document.querySelectorAll('.search-subchoice').forEach(sel => { sel.value = values[sel.dataset.orden] || ''; });
  updateSearchFilters(); updateSearchPreview([ref]);
}
window.addEventListener('DOMContentLoaded', () => {
  ensureBaseRows('new-sub-list', 10);
  if (window.searchReferences) updateSearchFilters();
});
