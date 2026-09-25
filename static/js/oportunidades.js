(() => {
  const app = document.getElementById('odApp');
  if (!app) return;

  const searchInput = document.getElementById('odSearch');
  const clearButton = document.getElementById('odClearSearch');
  const list = document.getElementById('odList');
  const detail = document.getElementById('odDetail');
  const detailBackdrop = document.getElementById('odDetailBackdrop');
  const resultCount = document.getElementById('odResultCount');
  const filterButton = document.getElementById('odAdvancedFilterButton');
  const filterPanel = document.getElementById('odAdvancedFilterPanel');
  const filterRuleList = document.getElementById('odFilterRuleList');
  const filterChips = document.getElementById('odFilterChips');
  const filterCount = document.getElementById('odFilterCount');
  const nearestNotice = document.getElementById('odNearestNotice');
  const projectTableShell = document.getElementById('odProjectTableShell');

  let currentId = Number(document.querySelector('.od-list-row.active')?.dataset.id || 0);
  let debounceTimer = null;
  let requestSerial = 0;
  let currentData = null;
  let technicalOptions = {};
  let filterFields = [];
  let appliedFilters = [];
  let draftFilters = [];
  let nextRuleId = 1;
  const suggestionTimers = new Map();
  const suggestionSerials = new Map();
  const filterPanelSizeKey = 'oga.od.advancedFilter.size.v1';

  function parseJsonScript(id, fallback) {
    try {
      return JSON.parse(document.getElementById(id)?.textContent || JSON.stringify(fallback));
    } catch (error) {
      return fallback;
    }
  }

  technicalOptions = parseJsonScript('odTechnicalOptions', {});
  filterFields = parseJsonScript('odFilterFields', []);
  appliedFilters = parseJsonScript('odInitialFilters', []).map(item => ({
    id: nextRuleId++, key: String(item.key || ''), value: String(item.value || '')
  })).filter(item => item.key && item.value);
  const initialSearchMeta = parseJsonScript('odInitialSearchMeta', {});
  const filterFieldMap = new Map(filterFields.map(field => [field.key, field]));

  const urlForId = (template, id) => template.replace('999999', String(id));
  const openModal = (id) => document.getElementById(id)?.classList.remove('hidden');
  const closeModal = (node) => node?.closest('.od-modal-backdrop')?.classList.add('hidden');

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  }

  function normalizeText(value) {
    return String(value ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
  }

  function cleanFilterPayload(source = appliedFilters) {
    return source
      .map(item => ({key: String(item.key || '').trim(), value: String(item.value || '').trim()}))
      .filter(item => filterFieldMap.has(item.key) && item.value);
  }

  function updateBrowserUrl(q, id) {
    const url = new URL(window.location.href);
    const payload = cleanFilterPayload();
    if (q) url.searchParams.set('q', q); else url.searchParams.delete('q');
    if (payload.length) url.searchParams.set('f', JSON.stringify(payload)); else url.searchParams.delete('f');
    if (id) url.searchParams.set('od', id); else url.searchParams.delete('od');
    history.replaceState({}, '', url);
  }

  function showDetailDrawer() {
    detail?.classList.remove('hidden');
    detailBackdrop?.classList.remove('hidden');
  }

  function closeDetail(updateUrl = true) {
    detail?.classList.add('hidden');
    detailBackdrop?.classList.add('hidden');
    list?.querySelectorAll('.od-list-row').forEach(row => row.classList.remove('active'));
    currentId = 0;
    currentData = null;
    if (updateUrl) updateBrowserUrl(searchInput?.value.trim() || '', 0);
  }

  function closeFilterPanel() {
    filterPanel?.classList.add('hidden');
    filterButton?.setAttribute('aria-expanded', 'false');
    document.querySelectorAll('.od-filter-key-menu').forEach(menu => menu.classList.add('hidden'));
  }

  function restoreFilterPanelSize() {
    if (!filterPanel) return;
    try {
      const saved = JSON.parse(localStorage.getItem(filterPanelSizeKey) || '{}');
      const maxWidth = Math.max(520, window.innerWidth - 42);
      const maxHeight = Math.max(240, Math.floor(window.innerHeight * 0.82));
      if (Number(saved.width) >= 520) filterPanel.style.width = `${Math.min(Number(saved.width), maxWidth)}px`;
      if (Number(saved.height) >= 220) filterPanel.style.height = `${Math.min(Number(saved.height), maxHeight)}px`;
    } catch (error) {
      // Si el navegador bloquea localStorage, el resize sigue funcionando igual.
    }
  }

  function saveFilterPanelSize() {
    if (!filterPanel || filterPanel.classList.contains('hidden')) return;
    try {
      localStorage.setItem(filterPanelSizeKey, JSON.stringify({
        width: Math.round(filterPanel.getBoundingClientRect().width),
        height: Math.round(filterPanel.getBoundingClientRect().height),
      }));
    } catch (error) {
      // Preferencia no persistente; no afecta el filtro.
    }
  }

  if (filterPanel && 'ResizeObserver' in window) {
    let resizeSaveTimer = null;
    const observer = new ResizeObserver(() => {
      clearTimeout(resizeSaveTimer);
      resizeSaveTimer = setTimeout(saveFilterPanelSize, 120);
    });
    observer.observe(filterPanel);
  }

  window.addEventListener('resize', () => {
    if (!filterPanel || filterPanel.classList.contains('hidden')) return;
    const rect = filterPanel.getBoundingClientRect();
    const maxWidth = Math.max(520, window.innerWidth - 42);
    const maxHeight = Math.max(240, Math.floor(window.innerHeight * 0.82));
    if (rect.width > maxWidth) filterPanel.style.width = `${maxWidth}px`;
    if (rect.height > maxHeight) filterPanel.style.height = `${maxHeight}px`;
  });

  document.addEventListener('click', (event) => {
    const close = event.target.closest('[data-close-modal]');
    if (close) closeModal(close);
    if (event.target.classList.contains('od-modal-backdrop')) event.target.classList.add('hidden');

    if (filterPanel && !filterPanel.classList.contains('hidden')) {
      // composedPath conserva la ruta original del clic aunque una regla se
      // vuelva a renderizar al seleccionar una clave. Sin esto, el clic puede
      // parecer externo y cerrar accidentalmente todo el filtro avanzado.
      const eventPath = typeof event.composedPath === 'function' ? event.composedPath() : [];
      const insidePanel = eventPath.includes(filterPanel) || event.target.closest('#odAdvancedFilterPanel');
      const opener = eventPath.includes(filterButton) || event.target.closest('#odAdvancedFilterButton');
      const chip = event.target.closest('.od-filter-chip');
      if (!insidePanel && !opener && !chip) closeFilterPanel();
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    if (filterPanel && !filterPanel.classList.contains('hidden')) {
      closeFilterPanel();
      return;
    }
    const openedModals = document.querySelectorAll('.od-modal-backdrop:not(.hidden)');
    if (openedModals.length) {
      openedModals.forEach(m => m.classList.add('hidden'));
      return;
    }
    if (detail && !detail.classList.contains('hidden')) closeDetail();
  });

  detailBackdrop?.addEventListener('click', () => closeDetail());

  function renderRows(rows, meta = {}) {
    const approximate = Boolean(meta?.approximate);
    const predictive = Boolean(meta?.predictive);
    const suffix = approximate ? ' cercanos' : (predictive ? ' predictivos' : '');
    resultCount.textContent = `${rows.length} resultado${rows.length === 1 ? '' : 's'}${suffix}`;
    if (!rows.length) {
      list.innerHTML = '<div class="od-list-empty"><strong>Sin coincidencias</strong><p>Pruebe otra palabra o quite algún filtro avanzado.</p></div>';
      closeDetail(false);
      return;
    }
    list.innerHTML = rows.map(row => `
      <button class="od-list-row ${Number(row.id) === currentId ? 'active' : ''}" type="button" data-id="${Number(row.id)}" role="row">
        <span class="od-cell-proyecto" data-label="Proyecto"><strong>${escapeHtml(row.proyecto || '—')}</strong></span>
        <span class="od-cell-cliente" data-label="Cliente">${escapeHtml(row.cliente || '—')}</span>
        <span class="od-cell-inicio" data-label="Inicio">${escapeHtml(row.fecha_inicio || '—')}</span>
        <span class="od-cell-material" data-label="Material a Transportar">${escapeHtml(row.material_transportado || '—')}</span>
        <span data-label="Punto de origen">${escapeHtml(row.punto_ingreso || '—')}</span>
        <span data-label="Punto de destino">${escapeHtml(row.punto_destino || '—')}</span>
        <span data-label="Flujo en KG/Hora">${escapeHtml(row.flujo_kg_h || '—')}</span>
        <span data-label="Distancia Horizontal de Transporte (m)">${escapeHtml(row.distancia_horizontal_m || '—')}</span>
        <span data-label="Distancia Vertical de Transporte (m)">${escapeHtml(row.distancia_vertical_m || '—')}</span>
        <span data-label="Cantidad de curvas de tubería x 90 grados">${escapeHtml(row.curvas_90 || '—')}</span>
        <span data-label="Tipo de Industria">${escapeHtml(row.industria || '—')}</span>
        <span class="od-cell-transporte" data-label="Tipo de Transporte">${escapeHtml(row.tipo_transporte || '—')}</span>
        <span data-label="Material de contacto con el producto">${escapeHtml(row.material_contacto || '—')}</span>
      </button>`).join('');

    if (currentId && !rows.some(row => Number(row.id) === currentId)) closeDetail(false);
  }

  function renderFilterChips() {
    const payload = cleanFilterPayload();
    filterCount.textContent = String(payload.length);
    filterCount.classList.toggle('hidden', !payload.length);
    filterChips.innerHTML = payload.map((item, index) => {
      const field = filterFieldMap.get(item.key) || {label: item.key};
      return `<button type="button" class="od-filter-chip" data-filter-index="${index}" title="Editar filtro">
        <span>${escapeHtml(field.label)}</span><i>→</i><strong>${escapeHtml(item.value)}</strong>
        <em class="od-filter-chip-remove" data-remove-filter="${index}" title="Quitar filtro">×</em>
      </button>`;
    }).join('');
  }

  function renderNearestNotice(meta = {}) {
    if (!nearestNotice) return;
    const numericGroups = meta?.approximate && Array.isArray(meta.nearest) ? meta.nearest : [];
    const predictiveGroups = Array.isArray(meta?.predictive_matches) ? meta.predictive_matches : [];
    if (!numericGroups.length && !predictiveGroups.length) {
      nearestNotice.classList.add('hidden');
      nearestNotice.innerHTML = '';
      return;
    }

    const predictiveHtml = predictiveGroups.map(group => {
      const percent = Math.round(Number(group.score || 0) * 100);
      return `<div class="od-nearest-group od-predictive-group"><span><b>${escapeHtml(group.label)}</b>: “${escapeHtml(group.requested)}” se interpretó como <strong>${escapeHtml(group.matched)}</strong>${percent ? ` (${percent}% similar)` : ''}.</span></div>`;
    }).join('');

    const numericHtml = numericGroups.map(group => {
      const values = (group.values || []).map(item =>
        `<button type="button" data-nearest-key="${escapeHtml(group.key)}" data-nearest-value="${escapeHtml(item.value)}">${escapeHtml(item.value)}</button>`
      ).join('');
      return `<div class="od-nearest-group"><span><b>${escapeHtml(group.label)}</b>: no existe ${escapeHtml(group.requested)} exacto.</span><div>${values}</div></div>`;
    }).join('');

    const title = numericGroups.length ? 'Coincidencia aproximada' : 'Coincidencia predictiva';
    const help = numericGroups.length
      ? 'Para números se muestran los proyectos más cercanos; para texto se toleran errores pequeños y palabras incompletas.'
      : 'El filtro tolera errores pequeños, palabras incompletas y texto adicional.';
    nearestNotice.innerHTML = `<strong>${title}</strong><small>${help}</small>${predictiveHtml}${numericHtml}`;
    nearestNotice.classList.remove('hidden');
  }

  async function search() {
    const serial = ++requestSerial;
    const q = searchInput.value.trim();
    const filters = cleanFilterPayload();
    const params = new URLSearchParams();
    if (q) params.set('q', q);
    if (filters.length) params.set('f', JSON.stringify(filters));
    try {
      const response = await fetch(`${app.dataset.searchUrl}?${params.toString()}`, {headers:{'Accept':'application/json'}});
      const data = await response.json();
      if (serial !== requestSerial || !data.ok) return;
      renderRows(data.rows || [], data.meta || {});
      renderNearestNotice(data.meta || {});
      updateBrowserUrl(q, currentId);
    } catch (error) {
      resultCount.textContent = 'No fue posible buscar';
    }
  }

  function scheduleSearch() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(search, 260);
  }

  async function selectOpportunity(id) {
    if (!id) return;
    currentId = id;
    currentData = null;
    list.querySelectorAll('.od-list-row').forEach(row => row.classList.toggle('active', Number(row.dataset.id) === id));
    showDetailDrawer();
    detail.innerHTML = '<div class="od-loading">Cargando oportunidad...</div>';
    try {
      const response = await fetch(urlForId(app.dataset.detailUrlTemplate, id), {headers:{'Accept':'application/json'}});
      const data = await response.json();
      if (!data.ok) throw new Error(data.error || 'No disponible');
      detail.innerHTML = data.html;
      detail.scrollTop = 0;
      updateBrowserUrl(searchInput.value.trim(), id);
    } catch (error) {
      detail.innerHTML = `<div class="od-empty-detail"><strong>No fue posible abrir la OD</strong><p>${escapeHtml(error.message)}</p><button class="btn outline od-js-close-detail" type="button">Cerrar</button></div>`;
    }
  }

  function newDraftRule() {
    return {id: nextRuleId++, key: '', value: ''};
  }

  function groupedKeyOptions() {
    const groups = new Map();
    filterFields.forEach(field => {
      if (!groups.has(field.group)) groups.set(field.group, []);
      groups.get(field.group).push(field);
    });
    return Array.from(groups.entries()).map(([group, fields]) => `
      <div class="od-filter-key-group">
        <small>${escapeHtml(group)}</small>
        ${fields.map(field => `<button type="button" class="od-filter-key-option" data-filter-key="${escapeHtml(field.key)}" data-filter-haystack="${escapeHtml(normalizeText(`${field.label} ${group}`))}">${escapeHtml(field.label)}</button>`).join('')}
      </div>`).join('');
  }

  const keyOptionsHtml = groupedKeyOptions();

  function renderFilterRules() {
    if (!filterRuleList) return;
    if (!draftFilters.length) draftFilters = [newDraftRule()];
    filterRuleList.innerHTML = draftFilters.map((rule, index) => {
      const field = filterFieldMap.get(rule.key);
      const numeric = field?.type === 'number';
      return `${index ? '<div class="od-filter-and"><span>Y</span></div>' : ''}
        <div class="od-filter-rule" data-rule-id="${rule.id}">
          <div class="od-filter-rule-main">
            <button type="button" class="od-filter-key-button ${field ? 'selected' : ''}" data-action="pick-key">
              <span>${escapeHtml(field?.label || 'Seleccionar clave')}</span><b>⌄</b>
            </button>
            <span class="od-filter-arrow">→</span>
            <div class="od-filter-value-wrap">
              <input class="od-filter-value" value="${escapeHtml(rule.value)}" ${field ? '' : 'disabled'} inputmode="${numeric ? 'decimal' : 'text'}" autocomplete="off" placeholder="${numeric ? 'Escriba un número' : 'Escriba; admite texto aproximado'}">
              <div class="od-filter-suggestions hidden"></div>
            </div>
            <button type="button" class="od-filter-remove-rule" data-action="remove-rule" title="Quitar condición">×</button>
          </div>
          <div class="od-filter-key-menu hidden">
            <input class="od-filter-key-search" autocomplete="off" placeholder="Buscar una clave…">
            <div class="od-filter-key-options">${keyOptionsHtml}</div>
          </div>
        </div>`;
    }).join('');
  }

  function openFilterPanel(focusIndex = null) {
    draftFilters = appliedFilters.map(item => ({...item}));
    if (!draftFilters.length) draftFilters = [newDraftRule()];
    renderFilterRules();
    restoreFilterPanelSize();
    filterPanel?.classList.remove('hidden');
    filterButton?.setAttribute('aria-expanded', 'true');
    if (focusIndex !== null && draftFilters[focusIndex]) {
      const row = filterRuleList.querySelector(`[data-rule-id="${draftFilters[focusIndex].id}"]`);
      row?.querySelector('.od-filter-value')?.focus();
    }
  }

  function findDraftRule(ruleId) {
    return draftFilters.find(item => item.id === Number(ruleId));
  }

  function hideRuleMenus(exceptRow = null) {
    filterRuleList?.querySelectorAll('.od-filter-key-menu').forEach(menu => {
      if (!exceptRow || menu.closest('.od-filter-rule') !== exceptRow) menu.classList.add('hidden');
    });
  }

  async function loadSuggestions(ruleId) {
    const rule = findDraftRule(ruleId);
    const field = filterFieldMap.get(rule?.key);
    const row = filterRuleList?.querySelector(`[data-rule-id="${ruleId}"]`);
    const box = row?.querySelector('.od-filter-suggestions');
    if (!rule || !field || !box) return;
    const serial = (suggestionSerials.get(ruleId) || 0) + 1;
    suggestionSerials.set(ruleId, serial);
    const params = new URLSearchParams({field: field.key, q: rule.value || ''});
    try {
      const response = await fetch(`${app.dataset.filterValuesUrl}?${params.toString()}`, {headers:{'Accept':'application/json'}});
      const data = await response.json();
      if (suggestionSerials.get(ruleId) !== serial || !data.ok) return;
      const values = data.values || [];
      if (!values.length) {
        box.classList.add('hidden');
        box.innerHTML = '';
        return;
      }
      box.innerHTML = values.map((item, index) => {
        let helper = '';
        if (field.type === 'number' && item.distance !== null && item.distance !== undefined) {
          helper = `<small>${item.exact ? 'Exacto' : `Δ ${escapeHtml(Number(item.distance).toLocaleString('es-CO', {maximumFractionDigits: 3}))}`}</small>`;
        } else if (field.type !== 'number' && item.predictive && item.score) {
          helper = `<small>${Math.round(Number(item.score) * 100)}% similar</small>`;
        } else if (field.type !== 'number' && index === 0 && rule.value.trim()) {
          helper = '<small>Tab / Enter</small>';
        }
        return `<button type="button" class="${index === 0 ? 'is-primary-suggestion' : ''}" data-suggestion-value="${escapeHtml(item.value)}"><span>${escapeHtml(item.value)}</span>${helper}</button>`;
      }).join('');
      box.classList.remove('hidden');
    } catch (error) {
      box.classList.add('hidden');
    }
  }

  function scheduleSuggestions(ruleId) {
    clearTimeout(suggestionTimers.get(ruleId));
    suggestionTimers.set(ruleId, setTimeout(() => loadSuggestions(ruleId), 180));
  }

  filterButton?.addEventListener('click', () => {
    if (filterPanel.classList.contains('hidden')) openFilterPanel(); else closeFilterPanel();
  });
  document.getElementById('odCloseFilterPanel')?.addEventListener('click', closeFilterPanel);
  document.getElementById('odAddFilterRule')?.addEventListener('click', () => {
    draftFilters.push(newDraftRule());
    renderFilterRules();
    filterRuleList.querySelector('.od-filter-rule:last-child .od-filter-key-button')?.focus();
  });
  document.getElementById('odResetFilters')?.addEventListener('click', () => {
    draftFilters = [newDraftRule()];
    renderFilterRules();
  });
  document.getElementById('odApplyFilters')?.addEventListener('click', () => {
    appliedFilters = cleanFilterPayload(draftFilters).map(item => ({id: nextRuleId++, ...item}));
    renderFilterChips();
    closeFilterPanel();
    search();
  });

  filterRuleList?.addEventListener('click', event => {
    // Evita que la selección de una clave llegue al listener global de clic
    // mientras esta fila se vuelve a dibujar.
    event.stopPropagation();
    const row = event.target.closest('.od-filter-rule');
    if (!row) return;
    const ruleId = Number(row.dataset.ruleId);
    const rule = findDraftRule(ruleId);
    if (!rule) return;

    if (event.target.closest('[data-action="pick-key"]')) {
      const menu = row.querySelector('.od-filter-key-menu');
      const opening = menu.classList.contains('hidden');
      hideRuleMenus(row);
      menu.classList.toggle('hidden', !opening);
      if (opening) {
        const input = menu.querySelector('.od-filter-key-search');
        input.value = '';
        menu.querySelectorAll('.od-filter-key-option').forEach(option => option.classList.remove('hidden'));
        input.focus();
      }
      return;
    }

    const keyOption = event.target.closest('[data-filter-key]');
    if (keyOption) {
      rule.key = keyOption.dataset.filterKey || '';
      rule.value = '';
      renderFilterRules();
      const updatedRow = filterRuleList.querySelector(`[data-rule-id="${ruleId}"]`);
      updatedRow?.querySelector('.od-filter-value')?.focus();
      loadSuggestions(ruleId);
      return;
    }

    if (event.target.closest('[data-action="remove-rule"]')) {
      draftFilters = draftFilters.filter(item => item.id !== ruleId);
      if (!draftFilters.length) draftFilters = [newDraftRule()];
      renderFilterRules();
      return;
    }

    const suggestion = event.target.closest('[data-suggestion-value]');
    if (suggestion) {
      rule.value = suggestion.dataset.suggestionValue || '';
      const input = row.querySelector('.od-filter-value');
      if (input) input.value = rule.value;
      row.querySelector('.od-filter-suggestions')?.classList.add('hidden');
    }
  });

  filterRuleList?.addEventListener('input', event => {
    const row = event.target.closest('.od-filter-rule');
    if (!row) return;
    const rule = findDraftRule(Number(row.dataset.ruleId));
    if (!rule) return;
    if (event.target.classList.contains('od-filter-value')) {
      rule.value = event.target.value;
      scheduleSuggestions(rule.id);
      return;
    }
    if (event.target.classList.contains('od-filter-key-search')) {
      const needle = normalizeText(event.target.value);
      row.querySelectorAll('.od-filter-key-option').forEach(option => {
        option.classList.toggle('hidden', needle && !String(option.dataset.filterHaystack || '').includes(needle));
      });
    }
  });

  filterRuleList?.addEventListener('focusin', event => {
    if (!event.target.classList.contains('od-filter-value')) return;
    const row = event.target.closest('.od-filter-rule');
    if (row) loadSuggestions(Number(row.dataset.ruleId));
  });

  function suggestionButtonsFor(input) {
    const row = input?.closest('.od-filter-rule');
    const box = row?.querySelector('.od-filter-suggestions');
    if (!box || box.classList.contains('hidden')) return [];
    return Array.from(box.querySelectorAll('[data-suggestion-value]'));
  }

  function acceptSuggestion(input, button) {
    const row = input?.closest('.od-filter-rule');
    const rule = row ? findDraftRule(Number(row.dataset.ruleId)) : null;
    if (!row || !rule || !button) return false;
    rule.value = button.dataset.suggestionValue || '';
    input.value = rule.value;
    row.querySelector('.od-filter-suggestions')?.classList.add('hidden');
    return true;
  }

  filterRuleList?.addEventListener('keydown', event => {
    if (event.target.classList.contains('od-filter-value')) {
      const buttons = suggestionButtonsFor(event.target);
      if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && buttons.length) {
        event.preventDefault();
        let index = buttons.findIndex(button => button.classList.contains('is-active'));
        buttons.forEach(button => button.classList.remove('is-active'));
        if (event.key === 'ArrowDown') index = index < buttons.length - 1 ? index + 1 : 0;
        else index = index > 0 ? index - 1 : buttons.length - 1;
        buttons[index].classList.add('is-active');
        buttons[index].scrollIntoView({block: 'nearest'});
        return;
      }
      if ((event.key === 'Tab' || event.key === 'Enter') && buttons.length) {
        const selected = buttons.find(button => button.classList.contains('is-active')) || buttons[0];
        const accepted = acceptSuggestion(event.target, selected);
        if (event.key === 'Enter' && accepted) event.preventDefault();
        return;
      }
      if (event.key === 'Enter') {
        event.preventDefault();
        document.getElementById('odApplyFilters')?.click();
        return;
      }
    }
    if (event.key === 'Enter' && event.target.classList.contains('od-filter-key-search')) {
      event.preventDefault();
    }
  });

  filterChips?.addEventListener('click', event => {
    const remove = event.target.closest('[data-remove-filter]');
    if (remove) {
      const index = Number(remove.dataset.removeFilter);
      appliedFilters.splice(index, 1);
      renderFilterChips();
      search();
      return;
    }
    const chip = event.target.closest('.od-filter-chip');
    if (chip) openFilterPanel(Number(chip.dataset.filterIndex));
  });

  nearestNotice?.addEventListener('click', event => {
    const button = event.target.closest('[data-nearest-key][data-nearest-value]');
    if (!button) return;
    const key = button.dataset.nearestKey;
    const value = button.dataset.nearestValue;
    const existing = appliedFilters.find(item => item.key === key);
    if (existing) existing.value = value; else appliedFilters.push({id: nextRuleId++, key, value});
    renderFilterChips();
    search();
  });

  list.addEventListener('click', event => {
    const row = event.target.closest('.od-list-row');
    if (row) selectOpportunity(Number(row.dataset.id));
  });
  searchInput.addEventListener('input', scheduleSearch);
  clearButton.addEventListener('click', () => { searchInput.value = ''; searchInput.focus(); search(); });

  // La altura elegida por el usuario se conserva en este navegador.
  if (projectTableShell) {
    const storageKey = 'oga.od.projectTableHeight';
    const savedHeight = Number(window.localStorage?.getItem(storageKey) || 0);
    if (savedHeight >= 220) projectTableShell.style.height = `${savedHeight}px`;
    if (window.ResizeObserver) {
      let resizeTimer = null;
      const observer = new ResizeObserver(entries => {
        const height = Math.round(entries[0]?.contentRect?.height || 0);
        if (height < 220) return;
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
          try { window.localStorage?.setItem(storageKey, String(height)); } catch (error) {}
        }, 160);
      });
      observer.observe(projectTableShell);
    }
  }

  renderFilterChips();
  renderNearestNotice(initialSearchMeta);
  if (initialSearchMeta?.approximate) {
    const currentRows = list.querySelectorAll('.od-list-row').length;
    resultCount.textContent = `${currentRows} resultado${currentRows === 1 ? '' : 's'} cercanos`;
  }

  document.getElementById('odNewButton')?.addEventListener('click', () => openModal('odNewModal'));
  const sidebarNew = document.querySelector('[data-od-sidebar-new]');
  sidebarNew?.addEventListener('click', event => {
    if (document.getElementById('odNewModal')) {
      event.preventDefault();
      openModal('odNewModal');
    }
  });
  if (window.location.hash === '#nueva-od' && document.getElementById('odNewModal')) openModal('odNewModal');

  async function getCurrentData(force = false) {
    if (!currentId) return null;
    if (currentData && !force) return currentData;
    const response = await fetch(urlForId(app.dataset.dataUrlTemplate, currentId), {headers:{'Accept':'application/json'}});
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || 'No fue posible cargar los datos.');
    currentData = data.opportunity;
    return currentData;
  }

  function setFormValues(form, values, fields) {
    fields.forEach(field => {
      const control = form.elements[field];
      if (!control) return;
      const value = values[field] ?? '';
      if (control.tagName === 'SELECT' && !control.multiple && value) {
        const options = Array.from(control.options);
        const match = options.find(option => option.value.localeCompare(String(value), 'es', {sensitivity:'base'}) === 0);
        if (match) {
          control.value = match.value;
          return;
        }
        // Compatibilidad: si un proyecto histórico tiene un valor que ya no
        // existe en el catálogo maestro, se conserva como opción seleccionada.
        const legacy = document.createElement('option');
        legacy.value = String(value);
        legacy.textContent = String(value);
        control.appendChild(legacy);
      }
      control.value = value;
    });
  }

  const opportunityFields = ['proyecto','cliente','industria','fecha_inicio'];
  const subsystemFields = [
    'nombre','material_transportado','punto_ingreso','punto_destino','flujo_kg_h',
    'distancia_horizontal_m','distancia_vertical_m','curvas_90','distancia_unidad_soplado_m',
    'curvas_unidad_soplado','tipo_flujo','atex','material_contacto','voltaje_potencia',
    'tipo_transporte','diametro_tuberia','tipo_acople','potencia_hp','caudal_cfm',
    'diferencial_presion_psi','tipo_bomba','area_filtracion_m2','micraje_filtracion',
    'consumo_aire_cfm','presion_alimentacion_psi'
  ];

  function fillSelectOptions(select, options, placeholder = 'Seleccione tipo') {
    if (!select) return;
    const current = select.value;
    select.innerHTML = `<option value="">${escapeHtml(placeholder)}</option>` + (options || []).map(value =>
      `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`
    ).join('');
    if (current && Array.from(select.options).some(option => option.value === current)) select.value = current;
  }

  document.addEventListener('click', async event => {
    const closeDetailButton = event.target.closest('.od-js-close-detail');
    if (closeDetailButton) {
      closeDetail();
      return;
    }

    const resourceButton = event.target.closest('.od-js-show-offers, .od-js-show-images, .od-js-show-materials');
    if (resourceButton) {
      const shell = resourceButton.closest('.od-detail-shell');
      const panel = document.getElementById(resourceButton.dataset.panel);
      const wasHidden = panel?.classList.contains('hidden');
      shell?.querySelectorAll('.od-top-resource-panel').forEach(node => node.classList.add('hidden'));
      shell?.querySelectorAll('.od-top-resource-button').forEach(node => node.classList.remove('active'));
      if (panel && wasHidden) {
        panel.classList.remove('hidden');
        resourceButton.classList.add('active');
      }
      return;
    }

    const menuButton = event.target.closest('.od-js-detail-menu');
    if (menuButton) {
      menuButton.closest('.od-detail-fab')?.classList.toggle('open');
      return;
    }

    const floatingButton = event.target.closest('.od-js-floating-table');
    if (floatingButton) {
      const shell = floatingButton.closest('.od-detail-shell');
      const card = shell?.querySelector('.od-floating-table-card');
      if (!card) return;
      const kind = floatingButton.dataset.kind;
      card.classList.remove('hidden');
      const title = card.querySelector('[id^="odFloatingTitle-"]');
      if (title) title.textContent = floatingButton.dataset.title || 'Datos relacionados';
      card.querySelectorAll('.od-floating-table-panel').forEach(panel => panel.classList.toggle('hidden', panel.dataset.floatingPanel !== kind));
      shell.querySelectorAll('.od-js-floating-table').forEach(button => button.classList.toggle('active', button === floatingButton));
      shell.querySelector('.od-detail-fab')?.classList.add('open');
      return;
    }

    const closeFloating = event.target.closest('.od-js-close-floating-table');
    if (closeFloating) {
      const shell = closeFloating.closest('.od-detail-shell');
      shell?.querySelector('.od-floating-table-card')?.classList.add('hidden');
      shell?.querySelectorAll('.od-js-floating-table').forEach(button => button.classList.remove('active'));
      return;
    }

    const image = event.target.closest('.od-js-image-preview');
    if (image) {
      document.getElementById('odImagePreview').src = image.dataset.imageUrl;
      document.getElementById('odImageTitle').textContent = image.dataset.imageTitle || 'Imagen';
      openModal('odImageModal');
      return;
    }

    const editOd = event.target.closest('.od-js-edit-opportunity');
    if (editOd) {
      try {
        currentId = Number(editOd.dataset.id || currentId);
        const data = await getCurrentData(true);
        const form = document.getElementById('odEditForm');
        setFormValues(form, data, opportunityFields);
        const selected = new Set((data.responsibles || []).map(item => String(item.user_id)));
        Array.from(form.elements.responsables?.options || []).forEach(option => option.selected = selected.has(String(option.value)));
        form.action = urlForId(app.dataset.editUrlTemplate, currentId);
        openModal('odEditModal');
      } catch (error) { alert(error.message); }
      return;
    }

    const addSubsystem = event.target.closest('.od-js-add-subsystem');
    if (addSubsystem) {
      const form = document.getElementById('odSubsystemForm');
      form.reset();
      if (form.elements.nombre) form.elements.nombre.value = 'Principal';
      form.action = urlForId(app.dataset.addSubsystemUrlTemplate, Number(addSubsystem.dataset.opportunityId));
      document.getElementById('odSubsystemModalTitle').textContent = 'Nuevos datos técnicos';
      openModal('odSubsystemModal');
      return;
    }

    const editSubsystem = event.target.closest('.od-js-edit-subsystem');
    if (editSubsystem) {
      try {
        currentId = Number(editSubsystem.dataset.opportunityId || currentId);
        const data = await getCurrentData(true);
        const subsystem = (data.subsystems || []).find(item => Number(item.id) === Number(editSubsystem.dataset.id));
        if (!subsystem) throw new Error('Datos técnicos no encontrados.');
        const form = document.getElementById('odSubsystemForm');
        form.reset();
        const editable = {
          ...subsystem,
          punto_ingreso: subsystem.entry_points?.[0]?.tipo || '',
          punto_destino: subsystem.exit_points?.[0]?.tipo || ''
        };
        setFormValues(form, editable, subsystemFields);
        form.action = urlForId(app.dataset.editSubsystemUrlTemplate, subsystem.id);
        document.getElementById('odSubsystemModalTitle').textContent = 'Editar datos técnicos';
        openModal('odSubsystemModal');
      } catch (error) { alert(error.message); }
      return;
    }

    const addOffer = event.target.closest('.od-js-add-offer');
    const addImage = event.target.closest('.od-js-add-image');
    if (addOffer || addImage) {
      const isOffer = !!addOffer;
      const node = addOffer || addImage;
      const id = Number(node.dataset.subsystemId);
      const form = document.getElementById('odAttachmentForm');
      form.reset();
      form.action = urlForId(isOffer ? app.dataset.addOfferUrlTemplate : app.dataset.addImageUrlTemplate, id);
      document.getElementById('odAttachmentTitle').textContent = isOffer ? 'Agregar oferta PDF' : 'Agregar imagen';
      document.getElementById('odAttachmentLabel').placeholder = isOffer ? 'Ej. Oferta Rev01' : 'Ej. Vista conceptual';
      document.getElementById('odAttachmentFile').accept = isOffer ? 'application/pdf,.pdf' : 'image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp';
      openModal('odAttachmentModal');
      return;
    }

    const addPoint = event.target.closest('.od-js-add-point');
    if (addPoint) {
      const form = document.getElementById('odPointForm');
      form.reset();
      form.elements.cantidad.value = '1';
      const kind = addPoint.dataset.kind;
      const pointOptions = technicalOptions[kind === 'entrada' ? 'punto_ingreso' : 'punto_destino'] || [];
      fillSelectOptions(document.getElementById('odPointType'), pointOptions, kind === 'entrada' ? 'Seleccione punto de origen' : 'Seleccione punto de destino');
      let url = urlForId(app.dataset.addPointUrlTemplate, Number(addPoint.dataset.subsystemId));
      url = url.replace('/entrada/agregar', `/${kind}/agregar`);
      form.action = url;
      document.getElementById('odPointTitle').textContent = kind === 'entrada' ? 'Agregar punto de origen' : 'Agregar punto de destino';
      openModal('odPointModal');
      return;
    }

    const addEquipment = event.target.closest('.od-js-add-equipment');
    if (addEquipment) {
      const form = document.getElementById('odEquipmentForm');
      form.reset();
      form.elements.cantidad.value = '1';
      form.action = urlForId(app.dataset.addEquipmentUrlTemplate, Number(addEquipment.dataset.subsystemId));
      openModal('odEquipmentModal');
    }
  });
})();
