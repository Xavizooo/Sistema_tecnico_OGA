(() => {
  const app = document.getElementById('odApp');
  if (!app) return;

  const searchInput = document.getElementById('odSearch');
  const clearButton = document.getElementById('odClearSearch');
  const list = document.getElementById('odList');
  const detail = document.getElementById('odDetail');
  const resultCount = document.getElementById('odResultCount');
  let currentId = Number(document.querySelector('.od-list-row.active')?.dataset.id || 0);
  let debounceTimer = null;
  let requestSerial = 0;
  let currentData = null;

  const urlForId = (template, id) => template.replace('999999', String(id));
  const openModal = (id) => document.getElementById(id)?.classList.remove('hidden');
  const closeModal = (node) => node?.closest('.od-modal-backdrop')?.classList.add('hidden');
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';

  document.addEventListener('click', (event) => {
    const close = event.target.closest('[data-close-modal]');
    if (close) closeModal(close);
    if (event.target.classList.contains('od-modal-backdrop')) event.target.classList.add('hidden');
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') document.querySelectorAll('.od-modal-backdrop:not(.hidden)').forEach(m => m.classList.add('hidden'));
  });

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  }

  function renderRows(rows) {
    resultCount.textContent = `${rows.length} resultado${rows.length === 1 ? '' : 's'}`;
    if (!rows.length) {
      list.innerHTML = '<div class="od-list-empty"><strong>Sin coincidencias</strong><p>Pruebe otra palabra o quite algún filtro avanzado.</p></div>';
      detail.innerHTML = '<div class="od-empty-detail"><strong>No hay una OD seleccionada</strong><p>El detalle aparecerá aquí.</p></div>';
      currentId = 0;
      return;
    }
    list.innerHTML = rows.map(row => `
      <button class="od-list-row ${Number(row.id) === currentId ? 'active' : ''}" type="button" data-id="${Number(row.id)}">
        <span class="od-row-main"><b>${escapeHtml(row.radicado)}</b><strong>${escapeHtml(row.proyecto)}</strong><em>${escapeHtml(row.cliente)}</em></span>
        <span class="od-row-name">${escapeHtml(row.nombre)}</span>
        <span class="od-row-meta"><i class="od-status-dot"></i>${escapeHtml(row.estado)} · ${Number(row.subsystem_count || 0)} subsistema${Number(row.subsystem_count || 0) === 1 ? '' : 's'}</span>
      </button>`).join('');
    const exists = rows.some(row => Number(row.id) === currentId);
    if (!exists) selectOpportunity(Number(rows[0].id));
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
    debounceTimer = setTimeout(search, 330);
  }

  function updateBrowserUrl(q, id) {
    const url = new URL(window.location.href);
    if (q) url.searchParams.set('q', q); else url.searchParams.delete('q');
    if (id) url.searchParams.set('od', id); else url.searchParams.delete('od');
    history.replaceState({}, '', url);
  }

  async function selectOpportunity(id) {
    if (!id) return;
    currentId = id;
    currentData = null;
    list.querySelectorAll('.od-list-row').forEach(row => row.classList.toggle('active', Number(row.dataset.id) === id));
    detail.innerHTML = '<div class="od-loading">Cargando oportunidad...</div>';
    try {
      const response = await fetch(urlForId(app.dataset.detailUrlTemplate, id), {headers:{'Accept':'application/json'}});
      const data = await response.json();
      if (!data.ok) throw new Error(data.error || 'No disponible');
      detail.innerHTML = data.html;
      updateBrowserUrl(searchInput.value.trim(), id);
    } catch (error) {
      detail.innerHTML = `<div class="od-empty-detail"><strong>No fue posible abrir la OD</strong><p>${escapeHtml(error.message)}</p></div>`;
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
  }));

  document.getElementById('odNewButton')?.addEventListener('click', () => openModal('odNewModal'));

  const sidebarNew = document.querySelector('[data-od-sidebar-new]');
  sidebarNew?.addEventListener('click', event => {
    if (document.getElementById('odNewModal')) {
      event.preventDefault();
      openModal('odNewModal');
    }
  });
  if (window.location.hash === '#nueva-od' && document.getElementById('odNewModal')) {
    openModal('odNewModal');
  }

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
      if (control) control.value = values[field] ?? '';
    });
  }

  const opportunityFields = ['radicado','proyecto','nombre','cliente','descripcion','planta','ciudad','pais','industria','tipo_oportunidad','estado','fecha_inicio','valor_estimado','observaciones'];
  const subsystemFields = ['nombre','nombre_proceso','descripcion_proceso','voltaje_potencia','material_contacto','material_estructural','material_transportado','flujo_kg_h','distancia_horizontal_m','distancia_vertical_m','curvas_90','distancia_unidad_soplado_m','curvas_unidad_soplado','preferencia_tipologia','preferencia_acoples','tipo_flujo','pesaje_oga','atex','nec','ubicacion','aire_comprimido','tipo_transporte','diametro_tuberia','tipo_acople','potencia_hp','caudal_cfm','diferencial_presion_psi','tipo_bomba','area_filtracion_m2','micraje_filtracion','consumo_aire_cfm','presion_alimentacion_psi','es_multiequipos','observaciones'];

  document.addEventListener('click', async event => {
    const tab = event.target.closest('.od-subsystem-tab');
    if (tab) {
      const shell = tab.closest('.od-detail-shell');
      shell?.querySelectorAll('.od-subsystem-tab').forEach(node => node.classList.toggle('active', node === tab));
      shell?.querySelectorAll('.od-subsystem-panel').forEach(panel => panel.classList.toggle('hidden', panel.dataset.subsystemPanel !== tab.dataset.subsystemTarget));
      return;
    }
    const resourceButton = event.target.closest('.od-js-show-offers, .od-js-show-images');
    if (resourceButton) {
      const panel = document.getElementById(resourceButton.dataset.panel);
      panel?.classList.toggle('hidden');
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
      form.elements.nombre.value = 'Principal';
      form.action = urlForId(app.dataset.addSubsystemUrlTemplate, Number(addSubsystem.dataset.opportunityId));
      document.getElementById('odSubsystemModalTitle').textContent = 'Nuevo subsistema';
      openModal('odSubsystemModal');
      return;
    }

    const editSubsystem = event.target.closest('.od-js-edit-subsystem');
    if (editSubsystem) {
      try {
        currentId = Number(editSubsystem.dataset.opportunityId || currentId);
        const data = await getCurrentData(true);
        const subsystem = (data.subsystems || []).find(item => Number(item.id) === Number(editSubsystem.dataset.id));
        if (!subsystem) throw new Error('Subsistema no encontrado.');
        const form = document.getElementById('odSubsystemForm');
        form.reset();
        setFormValues(form, subsystem, subsystemFields);
        form.action = urlForId(app.dataset.editSubsystemUrlTemplate, subsystem.id);
        document.getElementById('odSubsystemModalTitle').textContent = `Editar · ${subsystem.nombre}`;
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
