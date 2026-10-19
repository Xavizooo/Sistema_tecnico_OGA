/* Búsqueda local de lectura. Nunca modifica equipos, referencias ni archivos. */
(() => {
  'use strict';
  const source = document.getElementById('bibSearchCatalog');
  if (!source) return;
  const catalog = JSON.parse(source.textContent), $ = id => document.getElementById(id);
  const query = $('bibQuery'), equipo = $('bibEquipo'), pdfOnly = $('bibPdfOnly');
  const refs = catalog.references, PAGE_SIZE = 24;
  let selections = { ...catalog.initial_selections }, limit = PAGE_SIZE, current = [], timer;
  const stopWords = new Set(['de', 'del', 'la', 'las', 'el', 'los', 'para', 'con', 'en', 'un', 'una', 'y', 'por', 'tipo', 'aisi']);
  function normalize(value) {
    return String(value ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
      .replace(/([a-z])(\d)/g, '$1 $2').replace(/(\d)([a-z])/g, '$1 $2')
      .replace(/\b(?:acero\s+)?(?:inoxidable|inox)\b/g, 'inox').replace(/\bstainless(?:\s+steel)?\b/g, 'inox');
  }
  function words(value) { return normalize(value).match(/[a-z0-9]+(?:[.,][0-9]+)?/g) || []; }
  function tokens(value) { return words(value).filter(w => !stopWords.has(w)); }
  const indexed = refs.map(ref => ({
    ref, words: words([ref.referencia_codigo, ref.equipo_codigo, ref.equipo_nombre,
    ...ref.selecciones.flatMap(s => [s.caracteristica, s.codigo, s.texto])].join(' '))
  }));
  function distance(a, b, max) {
    if (Math.abs(a.length - b.length) > max) return max + 1;
    let last = Array.from({ length: b.length + 1 }, (_, i) => i);
    for (let i = 1; i <= a.length; i++) {
      const row = [i];
      for (let j = 1; j <= b.length; j++) row[j] = Math.min(row[j - 1] + 1, last[j] + 1, last[j - 1] + (a[i - 1] !== b[j - 1]));
      if (Math.min(...row) > max) return max + 1;
      last = row;
    }
    return last[b.length];
  }
  function matchesToken(token, options) {
    if (/^\d+(?:[.,]\d+)?$/.test(token)) return options.includes(token);
    if (options.some(word => word.startsWith(token))) return true;
    // Tolerancia limitada a palabras; las medidas y números se comparan sin aproximar.
    if (token.length < 5 || !/^[a-z]+$/.test(token)) return false;
    const max = token.length >= 8 ? 2 : 1;
    return options.some(word => /^[a-z]+$/.test(word) && distance(token, word, max) <= max);
  }
  function textResults() {
    const wanted = tokens(query.value);
    const raw = query.value.trim().toLowerCase();
    const codeQuery = /^[a-z0-9_.-]+$/.test(raw) && /[a-z]/.test(raw) && /[0-9]/.test(raw);
    return indexed.filter(item => (!equipo.value || item.ref.equipo_codigo === equipo.value)
      && (!pdfOnly.checked || item.ref.has_planos) && ((codeQuery && item.ref.referencia_codigo.toLowerCase().startsWith(raw)) || wanted.every(t => matchesToken(t, item.words)))).map(item => item.ref);
  }
  function selectionMatches(ref, selected, ignore = null) {
    const values = Object.fromEntries(ref.selecciones.map(s => [String(s.orden), String(s.codigo).toUpperCase()]));
    return Object.entries(selected).every(([order, code]) => !code || order === ignore || values[order] === String(code).toUpperCase());
  }
  function node(tag, className, text) {
    const el = document.createElement(tag); if (className) el.className = className; if (text !== undefined) el.textContent = text; return el;
  }
  function fallback(message) {
    const box = node('span', 'bib-thumb-fallback');
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.setAttribute('viewBox', '0 0 40 40'); svg.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS(svg.namespaceURI, 'path'); path.setAttribute('d', 'M10 4h14l7 7v25H10z M24 4v8h7 M15 19h11 M15 25h11 M15 30h7'); svg.append(path);
    box.append(svg, node('span', '', message)); return box;
  }
  function image(ref, lazy = true) {
    const box = node('span', 'bib-thumb-fallback', 'Cargando miniatura…');
    const img = node('img'); img.alt = 'Primera página del plano ' + ref.referencia_codigo;
    img.loading = lazy ? 'lazy' : 'eager'; img.decoding = 'async'; img.src = ref.thumbnail_url;
    img.addEventListener('load', () => box.remove(), { once: true });
    img.addEventListener('error', () => { img.replaceWith(fallback('Miniatura no disponible')); box.remove(); }, { once: true });
    return [box, img];
  }
  let closeActivePreview = null;
  function showPreview(ref) {
    if (closeActivePreview) closeActivePreview();
    const trigger = document.activeElement;
    const host = document.createElement('div');
    host.id = 'ogaBibPreviewV3';
    host.style.cssText = 'position:fixed;inset:0;z-index:2147483647;display:block;isolation:isolate;';
    // Aislamiento real: los estilos y controladores globales no entran al visor.
    const shadow = host.attachShadow({ mode: 'open' });
    const style = document.createElement('style');
    style.textContent = `
      :host{font-family:var(--oga-font,Arial,sans-serif);color:#243446;font-size:14px;line-height:1.45}
      *{box-sizing:border-box} [hidden]{display:none!important}
      .shade{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;padding:16px;background:#182d4f88;backdrop-filter:blur(3px)}
      .panel{width:min(1040px,100%);max-height:94vh;overflow:auto;background:#fff;border-radius:14px;padding:24px;box-shadow:0 20px 80px #10274755}
      header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}h2{margin:0;color:#203b60;font-size:20px}p{margin:4px 0 0;color:#718298;font-size:12px}
      button,a{font:inherit;cursor:pointer}button:focus-visible,a:focus-visible{outline:2px solid #285da9;outline-offset:3px}
      .cross{border:0;background:none;color:#8190a4;font-size:27px;line-height:1;padding:3px 6px;border-radius:5px}
      .picture{height:min(56vh,560px);display:flex;align-items:center;justify-content:center;border:1px solid #e8edf5;border-radius:9px;padding:12px;margin:15px 0;position:relative}
      .picture img{width:100%;height:100%;object-fit:contain}.picture>span{position:absolute;font-size:12px;color:#718298}
      .bib-thumb-fallback{display:flex;flex-direction:column;gap:8px;align-items:center;color:#718298}.bib-thumb-fallback svg{height:34px;width:34px;stroke:#a7b4c8;fill:none;stroke-width:1.4}
      .specs{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:20px}.spec{font-size:11px;padding:4px 7px;background:#f4f6fa;border:1px solid #e8ecf3;border-radius:5px;color:#5b6d84;overflow-wrap:anywhere}
      footer{display:flex;justify-content:flex-end;flex-wrap:wrap;gap:8px;border-top:1px solid #edf0f5;padding-top:16px}
      .action{border:1px solid #dce3eb;background:#f6f8fa;border-radius:7px;padding:8px 12px;color:#37495e;text-decoration:none;display:inline-flex;align-items:center;font-size:12px}
      .primary{background:#285da9;border-color:#285da9;color:#fff}.action:disabled{opacity:.5;cursor:default}
      @media(max-width:720px){.shade{padding:10px}.panel{padding:16px}h2{font-size:17px}footer{justify-content:flex-start}}
    `;
    const shade = node('div', 'shade'), panel = node('section', 'panel');
    panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-modal', 'true');
    panel.setAttribute('aria-labelledby', 'preview-title'); panel.setAttribute('aria-describedby', 'preview-subtitle');
    const header = node('header'), heading = node('div');
    const title = node('h2', '', ref.referencia_codigo); title.id = 'preview-title';
    const subtitle = node('p', '', ref.equipo_nombre); subtitle.id = 'preview-subtitle';
    heading.append(title, subtitle);
    const cross = node('button', 'cross', '×'); cross.type = 'button'; cross.setAttribute('aria-label', 'Cerrar vista previa');
    header.append(heading, cross);
    const picture = node('div', 'picture');
    if (ref.has_planos && ref.thumbnail_url) picture.append(...image(ref, false));
    else picture.append(fallback('Esta referencia no tiene plano PDF'));
    const specs = node('div', 'specs');
    ref.selecciones.forEach(s => specs.append(node('span', 'spec', (s.caracteristica ? s.caracteristica + ': ' : '') + (s.texto || s.codigo))));
    const footer = node('footer'), closeButton = node('button', 'action', 'Cerrar'); closeButton.type = 'button';
    const download = node('button', 'action', 'Descargar archivos'); download.type = 'button';
    download.disabled = ![ref.has_planos, ref.has_modelo3d, ref.has_lista_materiales, ref.has_ficha_tecnica].some(Boolean);
    const pdf = node('a', 'action primary', 'Abrir PDF completo'); pdf.target = '_blank'; pdf.rel = 'noopener'; pdf.hidden = !ref.has_planos;
    if (ref.has_planos) pdf.href = ref.preview_url;
    footer.append(closeButton, download, pdf); panel.append(header, picture, specs, footer); shade.append(panel); shadow.append(style, shade);
    const previousOverflow = document.body.style.overflow;
    let opened = true;
    function close() {
      if (!opened) return;
      opened = false;
      host.remove();
      document.body.style.overflow = previousOverflow;
      if (closeActivePreview === close) closeActivePreview = null;
      if (trigger?.isConnected) trigger.focus({ preventScroll: true });
    }
    closeActivePreview = close;
    cross.addEventListener('click', close); closeButton.addEventListener('click', close);
    shade.addEventListener('click', event => { if (event.target === shade) close(); });
    download.addEventListener('click', () => { close(); openDownloadModal(ref); });
    shadow.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); }
      if (event.key === 'Tab') {
        const targets = [cross, closeButton, download, pdf].filter(el => !el.disabled && !el.hidden);
        const first = targets[0], last = targets[targets.length - 1], active = shadow.activeElement;
        if (event.shiftKey && (active === first || !targets.includes(active))) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && (active === last || !targets.includes(active))) { event.preventDefault(); first.focus(); }
      }
    });
    document.body.append(host); document.body.style.overflow = 'hidden'; cross.focus({ preventScroll: true });
  }
  function cards(rows) {
    const grid = $('bibResults'); grid.replaceChildren();
    const fragment = document.createDocumentFragment();
    rows.slice(0, limit).forEach(ref => {
      const card = node('article', 'bib-reference-card'); card.dataset.reference = ref.referencia_codigo;
      const thumb = node('button', 'bib-thumbnail'); thumb.type = 'button'; thumb.setAttribute('aria-label', 'Vista previa de ' + ref.referencia_codigo);
      if (ref.has_planos && ref.thumbnail_url) thumb.append(...image(ref), node('span', 'bib-page-mark', 'PDF · PÁGINA 1'));
      else thumb.append(fallback('Sin plano PDF'));
      thumb.addEventListener('click', () => showPreview(ref));
      const body = node('div', 'bib-card-body'); body.append(node('h3', 'bib-card-code', ref.referencia_codigo), node('p', 'bib-card-equipo', ref.equipo_nombre));
      const specs = node('div', 'bib-card-specs');
      ref.selecciones.slice(0, 5).forEach(s => { const badge = node('span', 'bib-spec', s.texto || s.codigo); badge.title = (s.caracteristica ? s.caracteristica + ': ' : '') + (s.texto || s.codigo); specs.append(badge); });
      if (ref.selecciones.length > 5) specs.append(node('span', 'bib-spec', '+' + (ref.selecciones.length - 5)));
      body.append(specs);
      const bottom = node('div', 'bib-card-bottom'), buttons = node('div', 'bib-card-actions');
      const preview = node('button', '', 'Vista previa'); preview.type = 'button'; preview.addEventListener('click', () => showPreview(ref));
      const download = node('button', '', 'Archivos'); download.type = 'button'; download.addEventListener('click', () => openDownloadModal(ref));
      buttons.append(preview, download); bottom.append(node('span', 'bib-card-cost', formatMoneyJs(ref.costo)), buttons); body.append(bottom);
      card.append(thumb, body); fragment.append(card);
    });
    grid.append(fragment); $('bibEmpty').hidden = rows.length > 0;
    $('bibLoadMore').hidden = rows.length <= limit;
    $('bibLoadMore').textContent = 'Mostrar más referencias (' + Math.max(0, rows.length - limit) + ' restantes)';
    $('bibResultCount').textContent = rows.length + (rows.length === 1 ? ' referencia encontrada' : ' referencias encontradas')
      + (rows.length > limit ? ' · mostrando ' + limit : '');
  }
  function facetPanel(base) {
    const codes = [...new Set(base.map(ref => ref.equipo_codigo))];
    const active = equipo.value || (codes.length === 1 ? codes[0] : '');
    const chars = catalog.characteristics[active] || [], holder = $('bibFacets'); holder.replaceChildren();
    $('bibFacetNote').hidden = chars.length > 0;
    $('bibDetailFilters').hidden = chars.length === 0;
    chars.forEach(c => {
      const group = node('div', 'bib-facet'), id = 'bibFacet-' + c.orden;
      const label = node('label', 'bib-filter-label', c.nombre); label.htmlFor = id;
      const select = node('select'); select.id = id; select.dataset.order = c.orden; select.setAttribute('aria-label', c.nombre);
      const other = base.filter(ref => selectionMatches(ref, selections, c.orden));
      select.append(new Option('Cualquier opción', ''));
      c.subcaracteristicas.forEach(s => {
        const code = String(s.codigo || '').toUpperCase(); if (!code) return;
        const count = other.filter(ref => ref.selecciones.some(item => String(item.orden) === c.orden && String(item.codigo).toUpperCase() === code)).length;
        const option = new Option((s.texto || code) + ' (' + count + ')', code);
        option.disabled = count === 0 && selections[c.orden] !== code; select.append(option);
      });
      select.value = selections[c.orden] || '';
      select.addEventListener('change', () => {
        // Las posiciones de características son locales al equipo.
        equipo.value = active; selections[c.orden] = select.value; limit = PAGE_SIZE; refresh();
      });
      group.append(label, select); holder.append(group);
    });
  }
  function chips() {
    const holder = $('bibChips'); holder.replaceChildren();
    function add(text, remove) { const chip = node('span', 'bib-chip', text), button = node('button', '', '×'); button.type = 'button'; button.setAttribute('aria-label', 'Quitar filtro ' + text); button.addEventListener('click', () => { remove(); limit = PAGE_SIZE; refresh(); }); chip.append(button); holder.append(chip); }
    if (query.value.trim()) add(query.value.trim(), () => { query.value = ''; });
    if (equipo.value) add(equipo.selectedOptions[0].textContent.split(' · ')[0], () => { equipo.value = ''; selections = {}; });
    if (pdfOnly.checked) add('Con plano PDF', () => { pdfOnly.checked = false; });
    (catalog.characteristics[equipo.value] || []).forEach(c => {
      const code = selections[c.orden]; if (!code) return;
      const sub = c.subcaracteristicas.find(s => String(s.codigo).toUpperCase() === code);
      add(c.nombre + ': ' + (sub?.texto || code), () => { delete selections[c.orden]; });
    });
  }
  function updateURL() {
    const url = new URL(window.location.href);['q', 'equipo', 'pdf', 'ref'].forEach(key => url.searchParams.delete(key));
    Array.from(url.searchParams.keys()).filter(key => key.startsWith('sel_')).forEach(key => url.searchParams.delete(key));
    if (query.value.trim()) url.searchParams.set('q', query.value.trim());
    if (equipo.value) url.searchParams.set('equipo', equipo.value);
    if (pdfOnly.checked) url.searchParams.set('pdf', '1');
    Object.entries(selections).forEach(([order, code]) => { if (code) url.searchParams.set('sel_' + order, code); });
    window.history.replaceState(null, '', url);
  }
  function refresh() { const base = textResults(); current = base.filter(ref => selectionMatches(ref, selections)); facetPanel(base); chips(); cards(current); updateURL(); }
  function clear() { clearTimeout(timer); query.value = ''; equipo.value = ''; selections = {}; pdfOnly.checked = false; limit = PAGE_SIZE; refresh(); query.focus(); }
  query.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => { limit = PAGE_SIZE; refresh(); }, 140); });
  equipo.addEventListener('change', () => { selections = {}; limit = PAGE_SIZE; refresh(); });
  pdfOnly.addEventListener('change', () => { limit = PAGE_SIZE; refresh(); });
  $('bibClear').addEventListener('click', clear); $('bibEmptyClear').addEventListener('click', clear);
  $('bibLoadMore').addEventListener('click', () => { limit += PAGE_SIZE; cards(current); });
  const mobile = window.matchMedia('(max-width:720px)');
  $('bibDetailFilters').open = !mobile.matches;
  mobile.addEventListener('change', event => { $('bibDetailFilters').open = !event.matches; });
  pdfOnly.checked = new URL(window.location.href).searchParams.get('pdf') === '1';
  const initialRef = refs.find(ref => ref.referencia_codigo === catalog.initial_reference);
  if (initialRef && !equipo.value) equipo.value = initialRef.equipo_codigo;
  refresh(); if (initialRef) showPreview(initialRef);
})();
