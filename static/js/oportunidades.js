(() => {
  const app = document.getElementById('odApp');
  if (!app) return;

  const searchInput = document.getElementById('odSearch');
  const clearButton = document.getElementById('odClearSearch');
  const list = document.getElementById('odList');
  const detail = document.getElementById('odDetail');
  const detailBackdrop = document.getElementById('odDetailBackdrop');
  const resultCount = document.getElementById('odResultCount');
  let currentId = Number(document.querySelector('.od-list-row.active')?.dataset.id || 0);
  let debounceTimer = null;
  let requestSerial = 0;
  let currentData = null;
  let technicalOptions = {};
  try {
    technicalOptions = JSON.parse(document.getElementById('odTechnicalOptions')?.textContent || '{}');
  } catch (error) {
    technicalOptions = {};
  }

  const urlForId = (template, id) => template.replace('999999', String(id));
  const openModal = (id) => document.getElementById(id)?.classList.remove('hidden');
  const closeModal = (node) => node?.closest('.od-modal-backdrop')?.classList.add('hidden');

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  }

  function updateBrowserUrl(q, id) {
    const url = new URL(window.location.href);
    if (q) url.searchParams.set('q', q); else url.searchParams.delete('q');
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

  document.addEventListener('click', (event) => {
    const close = event.target.closest('[data-close-modal]');
    if (close) closeModal(close);
    if (event.target.classList.contains('od-modal-backdrop')) event.target.classList.add('hidden');
  });

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    const openedModals = document.querySelectorAll('.od-modal-backdrop:not(.hidden)');
    if (openedModals.length) {
      openedModals.forEach(m => m.classList.add('hidden'));
      return;
    }
    if (detail && !detail.classList.contains('hidden')) closeDetail();
  });

  detailBackdrop?.addEventListener('click', () => closeDetail());

  function renderRows(rows) {
    resultCount.textContent = `${rows.length} resultado${rows.length === 1 ? '' : 's'}`;
    if (!rows.length) {
      list.innerHTML = '<div class="od-list-empty"><strong>Sin coincidencias</strong><p>Pruebe otra palabra o quite algún filtro avanzado.</p></div>';
      closeDetail(false);
      return;
    }
    list.innerHTML = rows.map(row => `
      <button class="od-list-row ${Number(row.id) === currentId ? 'active' : ''}" type="button" data-id="${Number(row.id)}" role="row">
        <span class="od-cell-proyecto" data-label="Proyecto"><strong>${escapeHtml(row.proyecto)}</strong></span>
        <span class="od-cell-cliente" data-label="Cliente">${escapeHtml(row.cliente)}</span>
        <span class="od-cell-nombre" data-label="Oportunidad">${escapeHtml(row.nombre)}<small>${Number(row.subsystem_count || 0)} grupo${Number(row.subsystem_count || 0) === 1 ? '' : 's'} técnico${Number(row.subsystem_count || 0) === 1 ? '' : 's'}</small></span>
        <span class="od-cell-responsable" data-label="Responsable">${escapeHtml(row.responsible_names || '—')}</span>
      </button>`).join('');

    if (currentId && !rows.some(row => Number(row.id) === currentId)) closeDetail(false);
  }

  async function search() {
    const serial = ++requestSerial;
    const q = searchInput.value.trim();
    try {
      const response = await fetch(`${app.dataset.searchUrl}?q=${encodeURIComponent(q)}`, {headers:{'Accept':'application/json'}});
      const data = await response.json();
      if (serial !== requestSerial || !data.ok) return;
      renderRows(data.rows || []);
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

  list.addEventListener('click', event => {
    const row = event.target.closest('.od-list-row');
    if (row) selectOpportunity(Number(row.dataset.id));
  });
  searchInput.addEventListener('input', scheduleSearch);
  clearButton.addEventListener('click', () => { searchInput.value = ''; searchInput.focus(); search(); });
  document.querySelectorAll('.od-search-token').forEach(button => button.addEventListener('click', () => {
    const token = button.dataset.token || '';
    const base = searchInput.value.trim();
    searchInput.value = `${base}${base ? ' ' : ''}${token}`;
    searchInput.focus();
    searchInput.setSelectionRange(searchInput.value.length, searchInput.value.length);
    scheduleSearch();
  }));

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

  const opportunityFields = ['proyecto','nombre','cliente','descripcion','planta','ciudad','pais','industria','tipo_oportunidad','fecha_inicio','valor_estimado','observaciones'];
  const subsystemFields = ['nombre','voltaje_potencia','material_transportado','flujo_kg_h','potencia_hp','diferencial_presion_psi','caudal_cfm','area_filtracion_m2'];
  const visibleTechnicalFields = [
    ['voltaje_potencia', 'Voltaje de potencia (V)'],
    ['material_transportado', 'Material transportado'],
    ['flujo_kg_h', 'Flujo (kg/h)'],
    ['potencia_hp', 'Potencia (HP)'],
    ['diferencial_presion_psi', 'Diferencial de presión (PSI)'],
    ['caudal_cfm', 'Caudal (CFM)'],
    ['area_filtracion_m2', 'Área de filtración (m²)'],
  ];

  function renderTechnicalControl(field, label, subsystemId, rawValue) {
    const name = `tech_${subsystemId}_${field}`;
    const value = String(rawValue ?? '');
    const options = Array.isArray(technicalOptions[field]) ? technicalOptions[field] : [];
    if (!options.length) {
      return `<label>${escapeHtml(label)}<input name="${name}" value="${escapeHtml(value)}"></label>`;
    }

    const matched = options.find(option => String(option).localeCompare(value, 'es', {sensitivity:'base'}) === 0);
    const selectedValue = matched !== undefined ? String(matched) : value;
    const legacyOption = value && matched === undefined
      ? `<option value="${escapeHtml(value)}" selected>${escapeHtml(value)}</option>`
      : '';
    const optionHtml = options.map(option => {
      const optionValue = String(option);
      const selected = optionValue === selectedValue ? ' selected' : '';
      return `<option value="${escapeHtml(optionValue)}"${selected}>${escapeHtml(optionValue)}</option>`;
    }).join('');
    const placeholder = field === 'voltaje_potencia' ? 'Seleccione voltaje' : 'Seleccione material';
    return `<label>${escapeHtml(label)}<select name="${name}"><option value="">${placeholder}</option>${legacyOption}${optionHtml}</select></label>`;
  }

  function renderEditTechnicalSections(data) {
    const container = document.getElementById('odEditTechnicalSections');
    if (!container) return;
    const subsystems = Array.isArray(data?.subsystems) ? data.subsystems : [];
    if (!subsystems.length) {
      container.innerHTML = '<div class="od-edit-tech-empty">Este proyecto todavía no tiene datos técnicos registrados.</div>';
      return;
    }
    container.innerHTML = subsystems.map((subsystem, index) => {
      const id = Number(subsystem.id);
      const groupName = escapeHtml(subsystem.nombre || `Grupo ${index + 1}`);
      const fields = visibleTechnicalFields.map(([field, label]) =>
        renderTechnicalControl(field, label, id, subsystem[field])
      ).join('');
      return `
        <section class="od-edit-tech-card">
          <div class="od-edit-tech-card-head">
            <div><span>GRUPO TÉCNICO ${index + 1}</span><strong>${groupName}</strong></div>
          </div>
          <input type="hidden" name="technical_subsystem_id" value="${id}">
          <div class="od-form-grid od-form-grid-3">${fields}</div>
        </section>`;
    }).join('');
  }

  document.addEventListener('click', async event => {
    const closeDetailButton = event.target.closest('.od-js-close-detail');
    if (closeDetailButton) {
      closeDetail();
      return;
    }

    const resourceButton = event.target.closest('.od-js-show-offers, .od-js-show-images');
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
        renderEditTechnicalSections(data);
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
        setFormValues(form, subsystem, subsystemFields);
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
      let url = urlForId(app.dataset.addPointUrlTemplate, Number(addPoint.dataset.subsystemId));
      url = url.replace('/entrada/agregar', `/${kind}/agregar`);
      form.action = url;
      document.getElementById('odPointTitle').textContent = kind === 'entrada' ? 'Agregar punto de entrada' : 'Agregar punto de salida';
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
