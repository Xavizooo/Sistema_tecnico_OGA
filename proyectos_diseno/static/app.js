(() => {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const fmtMoney = new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP', maximumFractionDigits: 0 });
  const fmtNumber = new Intl.NumberFormat('es-CO', { maximumFractionDigits: 2 });
  const fmtDate = (value) => value ? new Date(`${String(value).slice(0, 10)}T12:00:00`).toLocaleDateString('es-CO') : '—';
  const projectNumberValue = (value) => { const digits = String(value ?? '').match(/\d+/g); return digits ? Number(digits.join('')) : Number.MAX_SAFE_INTEGER; };
  const sortProjectsNumeric = (rows) => [...rows].sort((a, b) => projectNumberValue(a.numero) - projectNumberValue(b.numero) || String(a.numero).localeCompare(String(b.numero), 'es', { numeric: true }));
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const APP_ROOT = document.getElementById('projectDesignApp');
  const MODULE_BASE = (APP_ROOT?.dataset.baseUrl || '').replace(/\/$/, '');
  const CSRF_TOKEN = APP_ROOT?.dataset.csrfToken || '';
  const INITIAL_VIEW = APP_ROOT?.dataset.initialView || 'dashboard';
  const INITIAL_PROJECT_ID = APP_ROOT?.dataset.initialProjectId || '';
  const ALERT_SESSION_KEY = 'oga_project_alerts_muted';
  const moduleUrl = (url) => (url.startsWith('/api/') || url.startsWith('/project-images/')) ? `${MODULE_BASE}${url}` : url;

  const state = {
    catalogs: { designers: [], pmps: [], activities: [], equipment: [], holidays: [], additionals: [], project_sizes: [], history_statuses: {} },
    dashboard: null,
    scale: 'month',
    mode: 'general',
    designerId: '',
    projectId: '',
    cart: [],
    stagePeriods: { 0: [], 1: [], 2: [], 3: [] },
    revisions: [],
    currentProject: null,
    charts: {},
    alertsShown: false,
  };

  async function api(url, options = {}) {
    const opts = { ...options, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': CSRF_TOKEN, ...(options.headers || {}) } };
    const response = await fetch(moduleUrl(url), opts);
    let body;
    try { body = await response.json(); } catch { body = { ok: false, message: 'Respuesta inválida del servidor.' }; }
    if (!response.ok || body.ok === false) throw new Error(body.message || 'No fue posible completar la operación.');
    return body.data;
  }

  function toast(message, type = 'success') {
    const node = $('#toast');
    node.textContent = message;
    node.className = `toast show ${type}`;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => node.className = 'toast', 3200);
  }

  function emptyRow(columns, message = 'No hay información registrada.') {
    return `<tr class="empty-row"><td colspan="${columns}">${escapeHtml(message)}</td></tr>`;
  }

  function showView(name) {
    const validViews = new Set(['dashboard','projects','designers','activities','equipment','additionals','holidays','history']);
    if (!validViews.has(name)) name = 'dashboard';
    $$('.view', APP_ROOT || document).forEach(v => v.classList.toggle('active', v.id === `view-${name}`));
    $$('.nav', APP_ROOT || document).forEach(btn => btn.classList.toggle('active', btn.dataset.view === name));
    $$('.side-submenu a').forEach(link => {
      try {
        const target = new URL(link.href, window.location.origin);
        if (target.pathname.includes('/proyectos-diseno/app/') || target.pathname === '/proyectos-diseno') link.classList.toggle('active', target.searchParams.get('view') === name);
      } catch (_) {}
    });
    try {
      const pageUrl = new URL(window.location.href);
      pageUrl.searchParams.set('view', name);
      window.history.replaceState({}, '', pageUrl);
    } catch (_) {}
    if (name === 'history') {
      state.mode = 'general'; state.designerId = ''; state.projectId = '';
      $('#calendarMode').value = 'general'; $('#designerFilterWrap').classList.remove('hidden'); $('#projectFilterWrap').classList.add('hidden');
      loadDashboard({ history: true }).catch(err => toast(err.message, 'error'));
    } else if (state.dashboard?.selected?.history) {
      state.mode = 'general'; state.designerId = ''; state.projectId = '';
      $('#calendarMode').value = 'general';
      $('#designerFilterWrap').classList.remove('hidden');
      $('#projectFilterWrap').classList.add('hidden');
      loadDashboard().catch(err => toast(err.message, 'error'));
    } else if (name === 'dashboard') {
      loadDashboard().catch(err => toast(err.message, 'error'));
    }
  }

  async function init() {
    const data = await api('/api/init');
    state.catalogs = data.catalogs;
    state.dashboard = data.dashboard;
    $('#holidayYear').value = new Date().getFullYear();
    renderAll();
    bindEvents();
    showView(INITIAL_PROJECT_ID ? 'projects' : INITIAL_VIEW);
    if (INITIAL_PROJECT_ID) {
      try {
        await openProjectDetail(INITIAL_PROJECT_ID);
      } catch (error) {
        toast(error.message || 'No fue posible abrir el proyecto solicitado.', 'error');
      }
    }
    showAlertPopup();
  }

  function bindEvents() {
    $$('.nav').forEach(btn => btn.addEventListener('click', () => showView(btn.dataset.view)));
    $('#newProjectTopBtn').addEventListener('click', openNewProject);
    $('#newProjectBtn').addEventListener('click', openNewProject);
    $('#newUpcomingBtn').addEventListener('click', openUpcomingProject);
    $('#newDesignerBtn').addEventListener('click', () => openDesigner());
    $('#newPmpBtn').addEventListener('click', () => openPmp());
    $('#newActivityBtn').addEventListener('click', () => openActivity());
    $('#newEquipmentBtn').addEventListener('click', () => openEquipment());
    $('#newAdditionalBtn').addEventListener('click', () => openAdditional());
    $('#newHolidayBtn').addEventListener('click', () => $('#holidayModal').showModal());
    $('#refreshBtn').addEventListener('click', refreshEverything);
    $('#syncExcelBtn').addEventListener('click', syncExcel);
    $('#backupBtn').addEventListener('click', backup);
    $('#loadColombiaBtn').addEventListener('click', loadColombia);

    $('#calendarMode').addEventListener('change', async e => {
      state.mode = e.target.value;
      $('#designerFilterWrap').classList.toggle('hidden', state.mode === 'project');
      $('#projectFilterWrap').classList.toggle('hidden', state.mode !== 'project');
      if (state.mode === 'general') { state.designerId = ''; state.projectId = ''; }
      if (state.mode === 'designer') { state.projectId = ''; state.designerId = $('#designerFilter').value; }
      if (state.mode === 'project') { state.designerId = ''; state.projectId = $('#projectFilter').value; }
      await loadDashboard();
    });
    $('#designerFilter').addEventListener('change', async e => {
      state.designerId = e.target.value;
      if (state.mode !== 'designer') { state.mode = 'designer'; $('#calendarMode').value = 'designer'; }
      await loadDashboard();
    });
    $('#projectFilter').addEventListener('change', async e => {
      state.projectId = e.target.value;
      if (state.mode !== 'project') { state.mode = 'project'; $('#calendarMode').value = 'project'; }
      await loadDashboard();
    });

    $$('.scale-btn').forEach(btn => btn.addEventListener('click', () => {
      state.scale = btn.dataset.scale;
      $$('.scale-btn').forEach(b => b.classList.toggle('active', b === btn));
      renderTimeline();
    }));
    $('#calendarFitBtn').addEventListener('click', () => renderTimeline(true));
    $('#exportCalendarPdfBtn').addEventListener('click', exportCalendarPdf);

    $('#saveDesignerBtn').addEventListener('click', saveDesigner);
    $('#savePmpBtn').addEventListener('click', savePmp);
    $('#saveActivityBtn').addEventListener('click', saveActivity);
    $('#saveEquipmentBtn').addEventListener('click', saveEquipment);
    $('#saveAdditionalBtn').addEventListener('click', saveAdditional);
    $('#additionalStart').addEventListener('change', updateAdditionalDurationPreview);
    $('#additionalEnd').addEventListener('change', updateAdditionalDurationPreview);
    $('#saveHolidayBtn').addEventListener('click', saveHoliday);
    $('#saveProjectBtn').addEventListener('click', saveProject);
    $('#manageProjectSizesBtn').addEventListener('click', openProjectSizes);
    $('#addProjectSizeBtn').addEventListener('click', addProjectSize);
    $('#closeProjectSizesBtn').addEventListener('click', () => $('#projectSizesModal').close());
    $('#closeProjectSizesFooterBtn').addEventListener('click', () => $('#projectSizesModal').close());
    $('#addRevisionBtn').addEventListener('click', addRevision);
    $('#projectImage').addEventListener('change', previewProjectImage);
    $('#saveUpcomingBtn').addEventListener('click', saveUpcomingProject);
    $('#confirmFinishBtn').addEventListener('click', confirmFinishProject);
    $('#saveHistoryMetaBtn').addEventListener('click', saveHistoryMeta);
    $('#addCartBtn').addEventListener('click', addCartItem);
    $('#projectStart').addEventListener('change', syncProjectStart);
    $('#projectType').addEventListener('change', updateProjectTypeStatus);
    $$('.add-period').forEach(btn => btn.addEventListener('click', () => addStagePeriod(Number(btn.dataset.stage))));

    $('#projectSearch').addEventListener('input', renderProjects);
    $('#historySearch').addEventListener('input', renderHistory);
    $('#closeDetailBtn').addEventListener('click', () => $('#detailModal').close());
    $('#closeAlertBtn').addEventListener('click', closeAlertPopup);
    $('#ackAlertsBtn').addEventListener('click', closeAlertPopup);

    window.addEventListener('resize', debounce(() => renderCharts(), 150));
  }

  async function refreshEverything() {
    const data = await api('/api/init');
    state.catalogs = data.catalogs;
    state.dashboard = data.dashboard;
    renderAll();
    toast('Información actualizada.');
  }

  async function loadDashboard(options = {}) {
    const params = new URLSearchParams();
    params.set('view', state.mode);
    if (state.mode === 'designer' && state.designerId) params.set('designer_id', state.designerId);
    if (state.mode === 'project' && state.projectId) params.set('project_id', state.projectId);
    if (options.history) params.set('history', '1');
    state.dashboard = await api(`/api/dashboard?${params.toString()}`);
    renderDashboard();
    renderTimeline();
    renderProjects();
    renderAdditionals();
    renderHistory();
    populateFilters();
  }

  function renderAll() {
    populateFilters();
    renderCatalogs();
    renderDashboard();
    renderTimeline();
    renderProjects();
    renderAdditionals();
    renderHistory();
  }

  function populateFilters() {
    const activeDesigners = state.catalogs.designers.filter(d => d.activo !== false);
    const designerOptions = `<option value="">Todos</option>` + activeDesigners.map(d => `<option value="${d.id}">${escapeHtml(d.nombre)}</option>`).join('');
    $('#designerFilter').innerHTML = designerOptions;
    $('#projectDesigner').innerHTML = `<option value="">Seleccione</option>` + activeDesigners.map(d => `<option value="${d.id}">${escapeHtml(d.nombre)}</option>`).join('');
    const activePmps = (state.catalogs.pmps || []).filter(p => p.activo !== false);
    $('#projectPmp').innerHTML = `<option value="">Seleccione PMP</option>` + activePmps.map(p => `<option value="${p.id}">${escapeHtml(p.nombre)}</option>`).join('');
    const activeSizes = (state.catalogs.project_sizes || []).filter(x => x.activo !== false);
    $('#projectSize').innerHTML = `<option value="">Seleccione tamaño</option>` + activeSizes.map(x => `<option value="${x.id}">${escapeHtml(x.nombre)} (${fmtNumber.format(x.minimo)}-${fmtNumber.format(x.maximo)})</option>`).join('');

    const projects = sortProjectsNumeric(state.dashboard?.all_active_projects || []);
    $('#projectFilter').innerHTML = `<option value="">Todos los proyectos</option>` + projects.map(p => `<option value="${p.id}">${escapeHtml(p.numero)} · ${escapeHtml(p.cliente)}</option>`).join('');
    $('#designerFilter').value = state.designerId;
    $('#projectFilter').value = state.projectId;

    const equipment = state.catalogs.equipment.filter(e => e.activo !== false);
    $('#cartEquipment').innerHTML = `<option value="">Seleccione un equipo</option>` + equipment.map(e => `<option value="${e.id}">${escapeHtml(e.codigo)} · ${escapeHtml(e.nombre)}</option>`).join('');
  }


  function renderDashboard() {
    const d = state.dashboard;
    if (!d) return;
    $('#metricActive').textContent = d.summary.active_projects;
    $('#metricProgress').textContent = `${fmtNumber.format(d.summary.progress)} %`;
    $('#metricHours').textContent = `${fmtNumber.format(d.summary.hours)} h`;
    $('#metricCost').textContent = fmtMoney.format(d.summary.cost);
    $('#metricLate').textContent = d.summary.late_projects;
    $('#alertsCount').textContent = d.alerts.length;

    let context = 'Área completa';
    if (state.mode === 'designer' && state.designerId) context = state.catalogs.designers.find(x => x.id === state.designerId)?.nombre || 'Diseñador';
    if (state.mode === 'project') {
      if (d.projects.length === 1) context = `${d.projects[0].numero} · ${d.projects[0].cliente}`;
      else context = 'Todos los proyectos';
    }
    $('#selectedContextLabel').textContent = context;

    $('#alertsBody').innerHTML = d.alerts.length ? d.alerts.map(a => `
      <tr data-project-id="${a.project_id}" class="clickable-row">
        <td><strong>${escapeHtml(a.numero)}</strong><br><span class="muted">${escapeHtml(a.cliente)}</span></td>
        <td>${escapeHtml(a.designer)}</td><td>${escapeHtml(a.phase)}</td>
        <td><span class="status ${a.type === 'danger' ? 'danger' : 'warning'}">${escapeHtml(a.message)}</span></td>
        <td>${fmtDate(a.deadline)}</td>
      </tr>`).join('') : emptyRow(5, 'No hay alertas activas.');
    $$('#alertsBody tr[data-project-id]').forEach(row => row.addEventListener('click', () => openProjectDetail(row.dataset.projectId)));

    const upcoming = sortProjectsNumeric(d.upcoming || []);
    $('#upcomingBody').innerHTML = upcoming.length ? upcoming.map(p => `
      <tr><td><strong>${escapeHtml(p.numero)}</strong></td><td>${escapeHtml(p.cliente)}</td><td>${escapeHtml(p.designer_name)}</td><td>${fmtDate(p.fecha_inicio)}</td><td>${fmtNumber.format(p.dias_referencia)} días</td><td><div class="row-actions"><button class="mini-btn edit-upcoming" data-id="${p.id}">EDITAR</button><button class="mini-btn red delete-upcoming" data-id="${p.id}">BORRAR</button></div></td></tr>
    `).join('') : emptyRow(6, 'No hay proyectos por empezar registrados.');
    $$('.edit-upcoming').forEach(button => button.addEventListener('click', () => openUpcomingProject(button.dataset.id)));
    $$('.delete-upcoming').forEach(button => button.addEventListener('click', () => deleteUpcomingProject(button.dataset.id)));
    renderCharts();
  }

  function renderCatalogs() {
    renderDesigners(); renderPmps(); renderActivities(); renderEquipment(); renderProjectSizes(); renderHolidays();
  }

  function renderDesigners() {
    const rows = state.catalogs.designers;
    $('#designersBody').innerHTML = rows.length ? rows.map(d => {
      const daily = dailyHours(d);
      return `<tr><td><span class="color-chip" style="background:${escapeHtml(d.color)}"></span></td><td><strong>${escapeHtml(d.nombre)}</strong></td><td>${fmtMoney.format(Number(d.costo_mensual_empresa || 0))}</td><td>${escapeHtml(d.hora_entrada)} – ${escapeHtml(d.hora_salida)}</td><td>${escapeHtml(d.almuerzo_inicio)} – ${escapeHtml(d.almuerzo_fin)}</td><td>${fmtNumber.format(daily)} h</td><td><span class="status ${d.activo !== false ? 'active' : 'inactive'}">${d.activo !== false ? 'Activo' : 'Inactivo'}</span></td><td><div class="row-actions"><button class="mini-btn edit-designer" data-id="${d.id}">EDITAR</button><button class="mini-btn red delete-designer" data-id="${d.id}">ELIMINAR</button></div></td></tr>`;
    }).join('') : emptyRow(8);
    $$('.edit-designer').forEach(b => b.addEventListener('click', () => openDesigner(b.dataset.id)));
    $$('.delete-designer').forEach(b => b.addEventListener('click', () => deleteItem('designers', b.dataset.id)));
  }

  function renderPmps() {
    const rows = state.catalogs.pmps || [];
    $('#pmpsBody').innerHTML = rows.length ? rows.map(p => `<tr><td><strong>${escapeHtml(p.nombre)}</strong></td><td><span class="status ${p.activo !== false ? 'active' : 'inactive'}">${p.activo !== false ? 'Activa' : 'Inactiva'}</span></td><td><div class="row-actions"><button class="mini-btn edit-pmp" data-id="${p.id}">EDITAR</button><button class="mini-btn red delete-pmp" data-id="${p.id}">ELIMINAR</button></div></td></tr>`).join('') : emptyRow(3);
    $$('.edit-pmp').forEach(b => b.addEventListener('click', () => openPmp(b.dataset.id)));
    $$('.delete-pmp').forEach(b => b.addEventListener('click', () => deleteItem('pmps', b.dataset.id)));
  }

  function parseActivityTypes(value) {
    return String(value || '').split(',').map(x => x.trim().toUpperCase()).filter(Boolean);
  }

  function projectTypeLabel(code) {
    return ({T1:'T1 · Proyecto',T2:'T2 · Solo Ingeniería',T3:'T3 · OT',T4:'T4 · Garantía'})[code] || code;
  }

  function activityTotals() {
    const totals = {T1:0,T2:0,T3:0,T4:0};
    state.catalogs.activities.filter(r => r.activa !== false).forEach(row => {
      parseActivityTypes(row.tipos_proyecto).forEach(code => { if (code in totals) totals[code] += Number(row.porcentaje || 0); });
    });
    return totals;
  }

  function renderActivities() {
    const rows = state.catalogs.activities;
    const totals = activityTotals();
    $('#activityTotalsGrid').innerHTML = Object.entries(totals).map(([code,total]) => `<div class="type-total ${Math.abs(total-100)<0.001?'complete':'incomplete'}"><span>${projectTypeLabel(code)}</span><strong>${fmtNumber.format(total)} %</strong></div>`).join('');
    const invalid = Object.entries(totals).filter(([,total]) => Math.abs(total - 100) >= 0.001);
    const warning = $('#activityTotalWarning');
    warning.classList.toggle('hidden', invalid.length === 0);
    warning.textContent = invalid.length ? `Grupos pendientes: ${invalid.map(([code,total]) => `${code} suma ${fmtNumber.format(total)} %`).join(' · ')}. Cada grupo debe completar 100 % para crear proyectos de ese tipo.` : '';
    $('#activitiesBody').innerHTML = rows.length ? rows.map(a => `<tr><td><strong>${escapeHtml(a.nombre)}</strong></td><td>Etapa 0${a.etapa} · ${stageName(a.etapa)}</td><td>${parseActivityTypes(a.tipos_proyecto).map(code=>`<span class="type-chip">${escapeHtml(code)}</span>`).join(' ')}</td><td>${fmtNumber.format(a.porcentaje)} %</td><td><span class="status ${a.activa !== false ? 'active' : 'inactive'}">${a.activa !== false ? 'Activa' : 'Inactiva'}</span></td><td><div class="row-actions"><button class="mini-btn edit-activity" data-id="${a.id}">EDITAR</button><button class="mini-btn red delete-activity" data-id="${a.id}">ELIMINAR</button></div></td></tr>`).join('') : emptyRow(6);
    $$('.edit-activity').forEach(b => b.addEventListener('click', () => openActivity(b.dataset.id)));
    $$('.delete-activity').forEach(b => b.addEventListener('click', () => deleteItem('activities', b.dataset.id)));
  }

  function renderEquipment() {
    const rows = state.catalogs.equipment;
    $('#equipmentBody').innerHTML = rows.length ? rows.map(e => `<tr><td><strong>${escapeHtml(e.codigo)}</strong></td><td>${escapeHtml(e.nombre)}</td><td>${fmtNumber.format(e.dias_estandar)} días</td><td>${fmtNumber.format(e.dias_medio||0)} días</td><td>${fmtNumber.format(e.dias_no_estandar)} días</td><td>${fmtNumber.format(e.dias_complejo||0)} días</td><td><span class="status ${e.activo !== false ? 'active' : 'inactive'}">${e.activo !== false ? 'Activo' : 'Inactivo'}</span></td><td><div class="row-actions"><button class="mini-btn edit-equipment" data-id="${e.id}">EDITAR</button><button class="mini-btn red delete-equipment" data-id="${e.id}">ELIMINAR</button></div></td></tr>`).join('') : emptyRow(8);
    $$('.edit-equipment').forEach(b => b.addEventListener('click', () => openEquipment(b.dataset.id)));
    $$('.delete-equipment').forEach(b => b.addEventListener('click', () => deleteItem('equipment', b.dataset.id)));
  }

  function renderProjectSizes() {
    const root=$('#projectSizesBody'); if(!root) return;
    const rows=state.catalogs.project_sizes||[];
    root.innerHTML=rows.length?rows.map(x=>`<tr><td><input class="size-edit-name" data-id="${x.id}" value="${escapeHtml(x.nombre)}"></td><td><input class="size-edit-min" data-id="${x.id}" type="number" min="1" value="${Number(x.minimo||0)}"></td><td><input class="size-edit-max" data-id="${x.id}" type="number" min="1" value="${Number(x.maximo||0)}"></td><td><span class="status ${x.activo!==false?'active':'inactive'}">${x.activo!==false?'Activo':'Inactivo'}</span></td><td><div class="row-actions"><button class="mini-btn save-size" data-id="${x.id}">GUARDAR</button><button class="mini-btn red delete-size" data-id="${x.id}">ELIMINAR</button></div></td></tr>`).join(''):emptyRow(5);
    $$('.save-size',root).forEach(b=>b.addEventListener('click',()=>saveProjectSize(b.dataset.id)));
    $$('.delete-size',root).forEach(b=>b.addEventListener('click',()=>deleteItem('project-sizes',b.dataset.id)));
  }

  function renderHolidays() {
    const rows = [...state.catalogs.holidays].sort((a,b) => String(a.fecha).localeCompare(String(b.fecha)));
    $('#holidaysBody').innerHTML = rows.length ? rows.map(h => `<tr><td>${fmtDate(h.fecha)}</td><td>${escapeHtml(h.nombre)}</td><td>${escapeHtml(h.origen)}</td><td><button class="mini-btn red delete-holiday" data-id="${h.id}">ELIMINAR</button></td></tr>`).join('') : emptyRow(4);
    $$('.delete-holiday').forEach(b => b.addEventListener('click', () => deleteItem('holidays', b.dataset.id)));
  }

  function renderProjects() {
    const projects = sortProjectsNumeric(state.dashboard?.all_active_projects || []);
    const q = ($('#projectSearch')?.value || '').trim().toLowerCase();
    const filtered = projects.filter(p => !q || [p.numero,p.cliente,p.designer_name,p.pmp_name,p.bodega].some(x => String(x).toLowerCase().includes(q)));
    $('#projectsBody').innerHTML = filtered.length ? filtered.map(projectRow).join('') : emptyRow(12);
    bindProjectRows('#projectsBody');
  }

  function projectRow(p) {
    const alert = p.alert ? `<span class="status ${p.alert.type === 'danger' ? 'danger' : 'warning'}">${escapeHtml(p.alert.message)}</span>` : '—';
    return `<tr>
      <td><strong>${escapeHtml(p.numero)}</strong></td><td>${escapeHtml(p.cliente)}</td><td><span class="type-chip">${escapeHtml(p.tipo_proyecto || 'T1')}</span></td>
      <td><span class="color-chip" style="background:${p.designer_color}"></span> ${escapeHtml(p.designer_name)}</td>
      <td>${escapeHtml(p.pmp_name || "Sin PMP")}</td><td><strong>${escapeHtml(p.bodega || "—")}</strong></td>
      <td>${escapeHtml(p.phase.label)}</td>
      <td class="progress-cell"><strong>${fmtNumber.format(p.metrics.avance)} %</strong><div class="progress-track"><div class="progress-fill" style="width:${Math.min(100,p.metrics.avance)}%"></div></div></td>
      <td>${fmtNumber.format(p.planned_hours)} h</td><td>${fmtMoney.format(p.planned_cost)}</td><td>${alert}</td>
      <td><div class="row-actions"><button class="mini-btn view-project" data-id="${p.id}">VER</button><button class="mini-btn edit-project" data-id="${p.id}">EDITAR</button><button class="mini-btn red delete-project" data-id="${p.id}" data-number="${escapeHtml(p.numero)}" data-client="${escapeHtml(p.cliente)}">BORRAR</button></div></td>
    </tr>`;
  }

  function bindProjectRows(root) {
    $$(`${root} .view-project`).forEach(b => b.addEventListener('click', () => openProjectDetail(b.dataset.id)));
    $$(`${root} .edit-project`).forEach(b => b.addEventListener('click', () => openEditProject(b.dataset.id)));
    $$(`${root} .delete-project`).forEach(b => b.addEventListener('click', () => deleteProject(b.dataset.id, b.dataset.number, b.dataset.client)));
  }

  function historyStatusColor(status) {
    return ({'PRODUCCION':'#3b82f6','ENSAMBLE':'#ef4444','DESPACHADO':'#22c55e','PUESTA EN MARCHA':'#f06292','FINALIZADO':'#7dd3fc'})[String(status||'PRODUCCION').toUpperCase()] || '#94a3b8';
  }
  function historyStatusOptions(selected) {
    return ['PRODUCCION','ENSAMBLE','DESPACHADO','PUESTA EN MARCHA','FINALIZADO'].map(value => `<option value="${value}" ${value===selected?'selected':''}>${value}</option>`).join('');
  }
  async function updateHistoryStatus(projectId, status) {
    await api(`/api/projects/${projectId}/history`, { method:'PATCH', body:JSON.stringify({estatus_historico:status}) });
    await loadDashboard({history:true}); toast('ESTATUS histórico actualizado.');
  }
  function renderHistory() {
    const history = state.dashboard?.history || [];
    const q = ($('#historySearch')?.value || '').trim().toLowerCase();
    const filtered = history.filter(p => !q || [p.numero,p.cliente,p.designer_name,p.pmp_name,p.bodega,p.tamano_nombre,p.estatus_historico].some(x => String(x).toLowerCase().includes(q)));
    $('#historyBody').innerHTML = filtered.length ? filtered.map(p => {
      const phase=p.phase_days||{}; const stage1=Number(phase.stage1||0),stage2=Number(phase.stage2||0),stage3=Number(phase.stage3||0);
      const totalStages=stage1+stage2+stage3; const status=String(p.estatus_historico||'PRODUCCION').toUpperCase();
      const image=p.imagen_url?`<img class="history-thumb" src="${escapeHtml(p.imagen_url)}" alt="${escapeHtml(p.numero)}">`:'—';
      return `<tr><td><strong>${escapeHtml(p.numero)}</strong></td><td>${escapeHtml(p.cliente)}</td><td>${escapeHtml(p.designer_name)}</td><td>${escapeHtml(p.pmp_name||'Sin PMP')}</td><td><strong>${escapeHtml(p.bodega||'—')}</strong></td><td>${escapeHtml(p.tamano_nombre||'Sin tamaño')}</td><td>${Number(p.numero_revisiones||0)}</td><td>${image}</td><td><div class="history-status-control"><span class="history-status-dot" style="background:${historyStatusColor(status)}"></span><select class="history-status-select" data-id="${p.id}">${historyStatusOptions(status)}</select></div></td><td>${fmtDate(p.fecha_recepcion_alcance)}</td><td>${fmtDate(p.fecha_inicio)}</td><td>${fmtDate(p.fecha_finalizacion)}</td><td>${fmtNumber.format(p.approval_days||0)}</td><td>${fmtNumber.format(stage1)}</td><td>${fmtNumber.format(stage2)}</td><td>${fmtNumber.format(stage3)}</td><td><strong>${fmtNumber.format(totalStages)}</strong></td><td>${fmtNumber.format(p.planned_hours)} h</td><td>${fmtMoney.format(p.planned_cost)}</td><td><div class="row-actions"><button class="mini-btn view-history" data-id="${p.id}">CONSULTAR</button><button class="mini-btn blue restore-history" data-id="${p.id}">DEVOLVER AL TABLERO</button></div></td></tr>`;
    }).join('') : emptyRow(20);
    $$('.view-history').forEach(b=>b.addEventListener('click',()=>openProjectDetail(b.dataset.id)));
    $$('.restore-history').forEach(b=>b.addEventListener('click',()=>restoreHistoryProject(b.dataset.id)));
    $$('.history-status-select').forEach(sel=>sel.addEventListener('change',()=>updateHistoryStatus(sel.dataset.id,sel.value).catch(err=>toast(err.message,'error'))));
  }

  async function restoreHistoryProject(id){if(!confirm('El proyecto volverá a Proyectos activos para poder editarlo. Las actividades cumplidas se conservarán. ¿Continuar?'))return;await api(`/api/projects/${id}/restore`,{method:'POST',body:'{}'});await refreshEverything();showView('projects');toast('Proyecto devuelto al tablero.');}

  function additionalBusinessDays(startValue,endValue){if(!startValue||!endValue)return 0;const start=parseLocalDate(startValue),end=parseLocalDate(endValue);if(end<start)return 0;const holidays=holidayMap();let count=0;for(let day=start;day<=end;day=addDays(day,1))if(isBusinessDate(day,holidays))count++;return count;}
  function updateAdditionalDurationPreview(){const value=additionalBusinessDays($('#additionalStart')?.value,$('#additionalEnd')?.value);if($('#additionalDuration'))$('#additionalDuration').value=`${fmtNumber.format(value)} días`;}
  function renderAdditionals(){const rows=state.catalogs.additionals||[];const total=rows.reduce((sum,row)=>sum+Number(row.dias_duracion||0),0);if($('#additionalTotalDays'))$('#additionalTotalDays').textContent=`${fmtNumber.format(total)} días`;if(!$('#additionalsBody'))return;$('#additionalsBody').innerHTML=rows.length?rows.map(r=>`<tr><td><strong>${escapeHtml(r.titulo)}</strong></td><td>${escapeHtml(r.proyecto)}</td><td>${escapeHtml(r.solicita)}</td><td class="additional-description">${escapeHtml(r.descripcion)}</td><td>${fmtDate(r.fecha_inicio)}</td><td>${fmtDate(r.fecha_finalizacion)}</td><td><strong>${fmtNumber.format(r.dias_duracion||0)} d</strong></td><td><div class="row-actions"><button class="mini-btn edit-additional" data-id="${r.id}">EDITAR</button><button class="mini-btn red delete-additional" data-id="${r.id}">BORRAR</button></div></td></tr>`).join(''):emptyRow(8);$$('.edit-additional').forEach(b=>b.addEventListener('click',()=>openAdditional(b.dataset.id)));$$('.delete-additional').forEach(b=>b.addEventListener('click',()=>deleteAdditional(b.dataset.id)));}
  function openAdditional(id=''){const row=(state.catalogs.additionals||[]).find(r=>r.id===id);$('#additionalModalTitle').textContent=row?'Editar adicional':'Crear adicional';$('#additionalId').value=row?.id||'';$('#additionalTitle').value=row?.titulo||'';$('#additionalProject').value=row?.proyecto||'';$('#additionalRequester').value=row?.solicita||'';$('#additionalDescription').value=row?.descripcion||'';$('#additionalStart').value=row?.fecha_inicio||'';$('#additionalEnd').value=row?.fecha_finalizacion||'';updateAdditionalDurationPreview();$('#additionalModal').showModal();}
  async function saveAdditional(){const id=$('#additionalId').value;const body={titulo:$('#additionalTitle').value,proyecto:$('#additionalProject').value,solicita:$('#additionalRequester').value,descripcion:$('#additionalDescription').value,fecha_inicio:$('#additionalStart').value,fecha_finalizacion:$('#additionalEnd').value};await api(id?`/api/additionals/${id}`:'/api/additionals',{method:id?'PUT':'POST',body:JSON.stringify(body)});$('#additionalModal').close();await refreshEverything();showView('additionals');toast(id?'Adicional actualizado.':'Adicional creado.');}
  async function deleteAdditional(id){const row=(state.catalogs.additionals||[]).find(r=>r.id===id);if(!row)return;if(!confirm(`¿Borrar el adicional "${row.titulo}"?`))return;await api(`/api/additionals/${id}`,{method:'DELETE'});await refreshEverything();showView('additionals');toast('Adicional eliminado.');}

  function holidayMap() {
    return new Map(
      state.catalogs.holidays
        .filter(h => h.activo !== false)
        .map(h => [String(h.fecha).slice(0, 10), h.nombre || 'Festivo'])
    );
  }

  function isBusinessDate(day, holidays = holidayMap()) {
    const weekday = day.getDay();
    return weekday !== 0 && weekday !== 6 && !holidays.has(toISO(day));
  }

  function businessRuns(start, end) {
    const holidays = holidayMap();
    const runs = [];
    let runStart = null;
    let previous = null;
    for (let day = new Date(start); day <= end; day = addDays(day, 1)) {
      if (isBusinessDate(day, holidays)) {
        if (!runStart) runStart = new Date(day);
        previous = new Date(day);
      } else if (runStart) {
        runs.push({ start: runStart, end: previous });
        runStart = null;
        previous = null;
      }
    }
    if (runStart) runs.push({ start: runStart, end: previous });
    return runs;
  }

  function nonWorkingColumnsHtml(min, max, dayWidth) {
    const holidays = holidayMap();
    let html = '';
    const total = dayDiff(min, max) + 1;
    for (let i = 0; i < total; i++) {
      const day = addDays(min, i);
      const isoDay = toISO(day);
      const weekend = day.getDay() === 0 || day.getDay() === 6;
      const holidayName = holidays.get(isoDay);
      if (!weekend && !holidayName) continue;
      const reason = holidayName || (day.getDay() === 6 ? 'Sábado' : 'Domingo');
      html += `<div class="nonworking-column ${holidayName ? 'holiday' : 'weekend'}" title="${escapeHtml(reason)} · ${fmtDate(isoDay)}" style="left:${i * dayWidth}px;width:${dayWidth}px"></div>`;
    }
    return html;
  }

  function exportCalendarPdf(){
    const panel=document.querySelector('.calendar-panel'); if(!panel)return; const win=window.open('','_blank','width=1400,height=900'); if(!win){toast('El navegador bloqueó la ventana de exportación.','error');return;}
    const css=[...document.querySelectorAll('link[rel="stylesheet"]')].map(x=>`<link rel="stylesheet" href="${x.href}">`).join('');
    win.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>Calendario de proyectos</title>${css}<style>@page{size:landscape;margin:8mm}body{background:white!important;margin:0!important}.calendar-panel{box-shadow:none!important;border:0!important;margin:0!important}.calendar-toolbar .toolbar-controls{display:none!important}.timeline{overflow:visible!important;max-height:none!important;height:auto!important}.timeline-inner{transform-origin:top left} .calendar-legend{margin-top:8px}</style></head><body>${panel.outerHTML}<script>window.addEventListener('load',()=>setTimeout(()=>window.print(),350));<\/script></body></html>`); win.document.close();
  }

  function renderTimeline(fit = false) {
    const rows = state.dashboard?.calendar_rows || [];
    const timeline = $('#timeline');
    if (!rows.length) { timeline.style.height = '104px'; timeline.style.minHeight = '104px'; timeline.style.maxHeight = '104px'; timeline.innerHTML = '<div class="timeline-empty">No hay proyectos en la selección actual.</div>'; $('#calendarRangeLabel').textContent = ''; renderLegend(); return; }

    const dateValues = [];
    rows.forEach(r => r.projects.forEach(p => p.segments.forEach(s => { if(s.start) dateValues.push(parseLocalDate(s.start)); if(s.end) dateValues.push(parseLocalDate(s.end)); })));
    if (!dateValues.length) { timeline.style.height = '104px'; timeline.style.minHeight = '104px'; timeline.style.maxHeight = '104px'; timeline.innerHTML = '<div class="timeline-empty">Los proyectos no tienen fechas programadas.</div>'; return; }
    let min = new Date(Math.min(...dateValues));
    let max = new Date(Math.max(...dateValues));
    const padding = { week: 2, month: 5, quarter: 10, year: 20 }[state.scale];
    min = addDays(min, -padding); max = addDays(max, padding);
    const today = stripTime(new Date());
    if (today >= addDays(min,-30) && today <= addDays(max,30)) { min = new Date(Math.min(min, addDays(today,-2))); max = new Date(Math.max(max, addDays(today,2))); }

    const showDesignerColumn = state.mode !== 'general';
    const showPmpColumn = state.mode !== 'general';
    const showWarehouseColumn = state.mode !== 'general';

    // Rev12.1: altura dinámica. Se muestran completos hasta 15 proyectos/líneas
    // y, cuando hay menos, el calendario reduce su altura al contenido real.
    const rowMetrics = rows.map(row => ({
      lanes: Math.max(1, row.projects.length),
      height: Math.max(1, row.projects.length) * 24 + 6
    }));
    let remainingVisibleProjects = 15;
    let visibleBodyHeight = 0;
    for (const metric of rowMetrics) {
      if (remainingVisibleProjects <= 0) break;
      const visibleLanes = Math.min(metric.lanes, remainingVisibleProjects);
      visibleBodyHeight += visibleLanes * 24 + 6;
      remainingVisibleProjects -= visibleLanes;
    }
    const totalBodyHeight = rowMetrics.reduce((sum, metric) => sum + metric.height, 0);
    const headerHeight = 55;
    const scrollbarAllowance = 18;
    const timelineHeight = Math.max(104, headerHeight + Math.min(totalBodyHeight, visibleBodyHeight) + scrollbarAllowance);
    timeline.style.height = `${timelineHeight}px`;
    timeline.style.minHeight = `${timelineHeight}px`;
    timeline.style.maxHeight = `${timelineHeight}px`;

    const projectLabelWidth = 165;
    const designerLabelWidth = showDesignerColumn ? 165 : 0;
    const pmpLabelWidth = showPmpColumn ? 130 : 0;
    const warehouseLabelWidth = showWarehouseColumn ? 95 : 0;
    const fixedWidth = projectLabelWidth + designerLabelWidth + pmpLabelWidth + warehouseLabelWidth;
    const totalDays = dayDiff(min, max) + 1;
    const baseWidth = { week: 42, month: 26, quarter: 16, year: 8 }[state.scale];
    const available = Math.max(600, timeline.clientWidth - fixedWidth);
    const dayWidth = fit ? Math.max(8, available / totalDays) : baseWidth;
    const trackWidth = Math.max(available, Math.ceil(totalDays * dayWidth));
    $('#calendarRangeLabel').textContent = `${fmtDate(toISO(min))} – ${fmtDate(toISO(max))}`;

    const headerColumns = showDesignerColumn
      ? `${projectLabelWidth}px ${designerLabelWidth}px ${pmpLabelWidth}px ${warehouseLabelWidth}px ${trackWidth}px`
      : `${projectLabelWidth}px ${trackWidth}px`;
    const headerLabels = showDesignerColumn
      ? `<div class="timeline-corner timeline-corner-project" style="left:0;width:${projectLabelWidth}px">Proyecto</div><div class="timeline-corner timeline-corner-designer" style="left:${projectLabelWidth}px;width:${designerLabelWidth}px">Diseñador</div><div class="timeline-corner timeline-corner-pmp" style="left:${projectLabelWidth + designerLabelWidth}px;width:${pmpLabelWidth}px">PMP</div><div class="timeline-corner timeline-corner-bodega" style="left:${projectLabelWidth + designerLabelWidth + pmpLabelWidth}px;width:${warehouseLabelWidth}px">BODEGA</div>`
      : `<div class="timeline-corner" style="left:0;width:${projectLabelWidth}px">Diseñador</div>`;

    let html = `<div class="timeline-inner" style="width:${fixedWidth + trackWidth}px">
      <div class="timeline-header" style="grid-template-columns:${headerColumns}">
        ${headerLabels}
        <div class="timeline-axis" style="width:${trackWidth}px">${axisHtml(min,max,dayWidth)}</div>
      </div>`;
    rows.forEach((row, rowIndex) => {
      const lanes = rowMetrics[rowIndex].lanes;
      const rowHeight = rowMetrics[rowIndex].height;
      const rowColumns = showDesignerColumn
        ? `${projectLabelWidth}px ${designerLabelWidth}px ${pmpLabelWidth}px ${warehouseLabelWidth}px ${trackWidth}px`
        : `${projectLabelWidth}px ${trackWidth}px`;
      const projectLabel = `<button class="timeline-label timeline-project-label" data-row-id="${row.id}" style="left:0;width:${projectLabelWidth}px;height:${rowHeight}px;text-align:left;border-top:0;border-bottom:0;border-left:0">${escapeHtml(row.label)}</button>`;
      const designerLabel = showDesignerColumn
        ? `<div class="timeline-designer-label" style="left:${projectLabelWidth}px;width:${designerLabelWidth}px;height:${rowHeight}px" title="${escapeHtml(row.designer_name || 'Sin diseñador')}"><i class="timeline-designer-dot" style="background:${row.designer_color || row.color || '#64748b'}"></i><span>${escapeHtml(row.designer_name || 'Sin diseñador')}</span></div>`
        : '';
      const pmpLabel = showPmpColumn
        ? `<div class="timeline-pmp-label" style="left:${projectLabelWidth + designerLabelWidth}px;width:${pmpLabelWidth}px;height:${rowHeight}px" title="${escapeHtml(row.pmp_name || 'Sin PMP')}"><span>${escapeHtml(row.pmp_name || 'Sin PMP')}</span></div>`
        : '';
      const warehouseLabel = showWarehouseColumn
        ? `<div class="timeline-bodega-label" style="left:${projectLabelWidth + designerLabelWidth + pmpLabelWidth}px;width:${warehouseLabelWidth}px;height:${rowHeight}px" title="BODEGA ${escapeHtml(row.bodega || '—')}"><span>${escapeHtml(row.bodega || '—')}</span></div>`
        : '';
      html += `<div class="timeline-row" style="grid-template-columns:${rowColumns};min-height:${rowHeight}px">
        ${projectLabel}${designerLabel}${pmpLabel}${warehouseLabel}
        <div class="timeline-track" style="width:${trackWidth}px;height:${rowHeight}px;background-size:${dayWidth}px 100%">${nonWorkingColumnsHtml(min,max,dayWidth)}`;
      row.projects.forEach((p, lane) => {
        html += `<div class="project-lane" style="height:24px">`;
        p.segments.forEach(seg => {
          const start = parseLocalDate(seg.start), end = parseLocalDate(seg.end);
          if (seg.point || ['reception','revision','contra'].includes(seg.kind)) {
            const left = dayDiff(min, start) * dayWidth + dayWidth / 2;
            const markerClass = seg.kind === 'revision' ? 'revision-marker' : (seg.kind === 'contra' ? 'contra-marker' : 'reception-marker');
            html += `<button class="timeline-marker ${markerClass}" data-project-id="${p.id}" title="${escapeHtml(p.numero)} · ${escapeHtml(seg.label||'Hito')} · ${fmtDate(seg.start)}" style="left:${left}px"></button>`;
            return;
          }
          const runs = businessRuns(start, end);
          if (!runs.length) return;
          const longestIndex = runs.reduce((best, run, index) => dayDiff(run.start, run.end) > dayDiff(runs[best].start, runs[best].end) ? index : best, 0);
          const businessCount = runs.reduce((sum, run) => sum + dayDiff(run.start, run.end) + 1, 0);
          const color = state.mode === 'general' ? p.color : (seg.color || p.color);
          const cssClass = seg.kind || '';
          runs.forEach((run, runIndex) => {
            const left = dayDiff(min, run.start) * dayWidth;
            const width = Math.max(dayWidth, (dayDiff(run.start, run.end) + 1) * dayWidth);
            const label = runIndex === longestIndex ? (state.mode === 'general' ? p.numero : seg.label) : '';
            const editable = Boolean(seg.period_id);
            const handles = editable ? `${runIndex===0?'<i class="resize-handle left" data-resize="start"></i>':''}${runIndex===runs.length-1?'<i class="resize-handle right" data-resize="end"></i>':''}` : '';
            html += `<button class="timeline-bar ${cssClass} ${runIndex ? 'continuation' : ''} ${editable?'editable-period':''}" data-project-id="${p.id}" data-period-id="${escapeHtml(seg.period_id||'')}" data-stage="${seg.stage||''}" data-period-start="${escapeHtml(seg.start)}" data-period-end="${escapeHtml(seg.end)}" data-day-width="${dayWidth}" title="${escapeHtml(p.numero)} · ${escapeHtml(seg.label || 'Proyecto')} · ${fmtDate(seg.start)} a ${fmtDate(seg.end)} · ${businessCount} día(s) hábil(es)" style="left:${left}px;width:${width}px;background:${color}">${handles}<span class="timeline-bar-label">${escapeHtml(label)}</span></button>`;
          });
        });
        html += '</div>';
      });
      html += '</div>';
      if (today >= min && today <= max) {
        const left = fixedWidth + dayDiff(min,today)*dayWidth + dayWidth / 2;
        html += `<div class="today-line" style="left:${left}px"></div>`;
      }
      html += '</div>';
    });
    html += '</div>';
    timeline.innerHTML = html;
    $$('.timeline-bar, .timeline-marker', timeline).forEach(bar => bar.addEventListener('click', async (event) => {
      if (bar.dataset.dragged === '1' || event.target.closest('.resize-handle')) { bar.dataset.dragged='0'; return; }
      state.mode = 'project'; state.projectId = bar.dataset.projectId; state.designerId = '';
      $('#calendarMode').value = 'project'; $('#projectFilterWrap').classList.remove('hidden'); $('#designerFilterWrap').classList.add('hidden');
      await loadDashboard(); await openProjectDetail(bar.dataset.projectId);
    }));
    $$('.timeline-bar.editable-period', timeline).forEach(bar => bar.addEventListener('pointerdown', beginTimelinePeriodDrag));
    $$('.timeline-label', timeline).forEach(label => label.addEventListener('click', async () => {
      if (state.mode === 'general' && label.dataset.rowId !== 'unassigned') {
        state.mode = 'designer'; state.designerId = label.dataset.rowId; state.projectId = '';
        $('#calendarMode').value = 'designer'; $('#designerFilterWrap').classList.remove('hidden'); $('#projectFilterWrap').classList.add('hidden');
        await loadDashboard();
      }
    }));
    if (!fit && today >= min && today <= max) timeline.scrollLeft = Math.max(0, fixedWidth + dayDiff(min,today)*dayWidth - timeline.clientWidth/2);
    renderLegend();
  }

  function snapBusinessDate(day, direction=1){const holidays=holidayMap();let d=stripTime(day);let guard=0;while(!isBusinessDate(d,holidays)&&guard<20){d=addDays(d,direction>=0?1:-1);guard++;}return d;}
  function beginTimelinePeriodDrag(event){
    if(event.button!==0)return; const bar=event.currentTarget; const projectId=bar.dataset.projectId,periodId=bar.dataset.periodId;if(!periodId)return;
    event.preventDefault(); const startX=event.clientX; const dayWidth=Number(bar.dataset.dayWidth||20); const originalStart=parseLocalDate(bar.dataset.periodStart),originalEnd=parseLocalDate(bar.dataset.periodEnd); const resize=event.target.closest('.resize-handle')?.dataset.resize||'move';
    bar.setPointerCapture?.(event.pointerId); bar.classList.add('dragging');
    const move=e=>{const dx=e.clientX-startX;bar.style.transform=`translateX(${dx}px)`;};
    const up=async e=>{bar.removeEventListener('pointermove',move);bar.removeEventListener('pointerup',up);bar.removeEventListener('pointercancel',up);bar.classList.remove('dragging');bar.style.transform='';const dx=e.clientX-startX;if(Math.abs(dx)<3)return;bar.dataset.dragged='1';setTimeout(()=>{bar.dataset.dragged='0';},500);const delta=Math.round(dx/dayWidth);let nextStart=new Date(originalStart),nextEnd=new Date(originalEnd);if(resize==='start'){nextStart=snapBusinessDate(addDays(originalStart,delta),delta>=0?1:-1);}else if(resize==='end'){nextEnd=snapBusinessDate(addDays(originalEnd,delta),delta>=0?1:-1);}else{nextStart=snapBusinessDate(addDays(originalStart,delta),delta>=0?1:-1);const shift=dayDiff(originalStart,nextStart);nextEnd=snapBusinessDate(addDays(originalEnd,shift),shift>=0?1:-1);}if(nextEnd<nextStart){toast('El lapso no puede terminar antes de comenzar.','error');return;}try{await api(`/api/projects/${projectId}/periods/${periodId}`,{method:'PATCH',body:JSON.stringify({inicio:toISO(nextStart),fin:toISO(nextEnd)})});await loadDashboard();toast('Fechas actualizadas desde el calendario.');}catch(err){toast(err.message,'error');renderTimeline();}};
    bar.addEventListener('pointermove',move);bar.addEventListener('pointerup',up);bar.addEventListener('pointercancel',up);
  }

  function axisHtml(min,max,dayWidth) {
    const total = dayDiff(min,max)+1;
    const holidays = holidayMap();
    const weekdayShort = ['Dom','Lun','Mar','Mié','Jue','Vie','Sáb'];
    const weekdayLetter = ['D','L','M','X','J','V','S'];
    let html = '';
    let cursor = new Date(min);
    while (cursor <= max) {
      const monthEnd = new Date(cursor.getFullYear(),cursor.getMonth()+1,0);
      const start = cursor < min ? min : cursor;
      const end = monthEnd > max ? max : monthEnd;
      const left = dayDiff(min,start)*dayWidth;
      const width = (dayDiff(start,end)+1)*dayWidth;
      html += `<div class="axis-month" style="left:${left}px;width:${width}px">${start.toLocaleDateString('es-CO',{month:'long',year:'numeric'})}</div>`;
      cursor = addDays(monthEnd,1);
    }
    for (let i=0;i<total;i++) {
      const day = addDays(min,i);
      const isoDay = toISO(day);
      const weekend = day.getDay()===0 || day.getDay()===6;
      const holidayName = holidays.get(isoDay);
      const weekday = dayWidth >= 34 ? weekdayShort[day.getDay()] : weekdayLetter[day.getDay()];
      const title = holidayName ? `${holidayName} · ${weekdayShort[day.getDay()]} ${fmtDate(isoDay)}` : `${weekdayShort[day.getDay()]} ${fmtDate(isoDay)}`;
      html += `<div class="axis-day ${weekend?'weekend':''} ${holidayName?'holiday':''}" title="${escapeHtml(title)}" style="left:${i*dayWidth}px;width:${dayWidth}px"><span class="axis-weekday">${weekday}</span><span class="axis-number">${String(day.getDate()).padStart(2,'0')}</span></div>`;
    }
    const today = stripTime(new Date());
    if (today >= min && today <= max) html += `<div class="today-label" style="left:${dayDiff(min,today)*dayWidth + dayWidth/2}px">HOY</div>`;
    return html;
  }

  function renderLegend() {
    const legend = $('#calendarLegend');
    let items = '';
    if (state.mode === 'general') {
      items = state.catalogs.designers.filter(d => d.activo !== false).map(d => `<span class="legend-item"><i class="legend-dot" style="background:${d.color}"></i>${escapeHtml(d.nombre)}</span>`).join('');
    } else {
      items = `<span class="legend-item"><i class="legend-dot" style="background:#6dcff4"></i>Etapa 01</span><span class="legend-item"><i class="legend-dot" style="background:#f06292"></i>Aprobación</span><span class="legend-item"><i class="legend-dot" style="background:#ffb91b"></i>Etapa 02</span><span class="legend-item"><i class="legend-dot" style="background:#1dd5a3"></i>Etapa 03</span>`;
    }
    legend.innerHTML = `<span class="legend-item"><i class="legend-dot reception-legend"></i>Recepción de alcance</span><span class="legend-item"><i class="legend-dot revision-legend"></i>Revisión</span><span class="legend-item"><i class="legend-dot contra-legend"></i>CONTRA ACTUAL</span>${items}<span class="legend-item"><i class="legend-dot nonworking"></i>Sábados, domingos y festivos</span>`;
  }

  function renderCharts() {
    const d = state.dashboard; if (!d) return;
    drawDonut($('#progressChart'), d.summary.progress, 'Avance');
    const projects = d.projects || [];
    if (projects.length === 1) {
      const p = projects[0];
      const phase = p.phase_days || {};
      $('#stageChartTitle').textContent = 'DÍAS HÁBILES POR ETAPA';
      drawHorizontalBars(
        $('#stageChart'),
        ['Etapa 01','Aprobación','Etapa 02','Etapa 03'],
        [phase.stage1 || 0, phase.approval || 0, phase.stage2 || 0, phase.stage3 || 0],
        ['#6dcff4','#f06292','#ffb91b','#1dd5a3'],
        ' d'
      );
    } else {
      $('#stageChartTitle').textContent = 'AVANCE POR ETAPA';
      const stageValues = [1,2,3].map(stage => {
        if (!projects.length) return 0;
        return projects.reduce((sum,p) => sum + Number(p.metrics.stages[String(stage)]?.avance ?? p.metrics.stages[stage]?.avance ?? 0), 0) / projects.length;
      });
      drawHorizontalBars($('#stageChart'), ['Etapa 01','Etapa 02','Etapa 03'], stageValues, ['#6dcff4','#ffb91b','#1dd5a3'], '%');
    }
    const workload = d.designer_workload || [];
    drawHorizontalBars($('#workloadChart'), workload.map(x=>x.nombre), workload.map(x=>x.hours), workload.map(x=>x.color), ' h', true);
  }

  function setupCanvas(canvas) {
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const width = Math.max(260, rect.width || canvas.parentElement.clientWidth || 400);
    const height = Math.max(150, rect.height || canvas.parentElement.clientHeight || 190);
    canvas.width = width*dpr; canvas.height = height*dpr; canvas.style.width=`${width}px`; canvas.style.height=`${height}px`;
    const ctx = canvas.getContext('2d'); ctx.setTransform(dpr,0,0,dpr,0,0); ctx.clearRect(0,0,width,height);
    return {ctx,width,height};
  }

  function drawDonut(canvas, value, label) {
    const {ctx,width,height}=setupCanvas(canvas); const v=Math.max(0,Math.min(100,Number(value)||0));
    const cx=width/2,cy=height/2,r=Math.min(width,height)*.32,line=Math.max(16,r*.22);
    ctx.lineWidth=line;ctx.lineCap='round';ctx.strokeStyle='#e5e7eb';ctx.beginPath();ctx.arc(cx,cy,r,0,Math.PI*2);ctx.stroke();
    ctx.strokeStyle='#1268c9';ctx.beginPath();ctx.arc(cx,cy,r,-Math.PI/2,-Math.PI/2+Math.PI*2*v/100);ctx.stroke();
    ctx.fillStyle='#075aa8';ctx.textAlign='center';ctx.font='700 28px Arial';ctx.fillText(`${fmtNumber.format(v)} %`,cx,cy+6);
    ctx.fillStyle='#6b7280';ctx.font='700 11px Arial';ctx.fillText(label.toUpperCase(),cx,cy+28);
  }

  function drawHorizontalBars(canvas, labels, values, colors, suffix='', compact=false) {
    const {ctx,width,height}=setupCanvas(canvas); if(!labels.length){ctx.fillStyle='#94a3b8';ctx.textAlign='center';ctx.font='12px Arial';ctx.fillText('Sin datos para mostrar',width/2,height/2);return;}
    const left=Math.min(compact?150:110,width*.35),right=55,top=16,bottom=18;
    const max=Math.max(...values.map(Number),suffix==='%'?100:1,1); const rowH=(height-top-bottom)/labels.length; const barH=Math.min(18,rowH*.52);
    ctx.font='10px Arial';ctx.textBaseline='middle';
    labels.forEach((label,i)=>{const y=top+i*rowH+rowH/2;ctx.fillStyle='#374151';ctx.textAlign='right';ctx.fillText(String(label).slice(0,24),left-8,y);ctx.fillStyle='#e5e7eb';roundRect(ctx,left,y-barH/2,width-left-right,barH,5,true);const w=(width-left-right)*(Number(values[i])||0)/max;ctx.fillStyle=colors[i]||'#1268c9';roundRect(ctx,left,y-barH/2,Math.max(0,w),barH,5,true);ctx.fillStyle='#111827';ctx.textAlign='left';ctx.font='700 10px Arial';ctx.fillText(`${fmtNumber.format(values[i]||0)}${suffix}`,Math.min(width-right+5,left+w+7),y);ctx.font='10px Arial';});
  }

  function roundRect(ctx,x,y,w,h,r,fill){if(w<=0)return;ctx.beginPath();ctx.moveTo(x+r,y);ctx.arcTo(x+w,y,x+w,y+h,r);ctx.arcTo(x+w,y+h,x,y+h,r);ctx.arcTo(x,y+h,x,y,r);ctx.arcTo(x,y,x+w,y,r);ctx.closePath();if(fill)ctx.fill();}

  function openDesigner(id='') {
    const d = state.catalogs.designers.find(x=>x.id===id);
    $('#designerModalTitle').textContent = d ? 'Editar diseñador' : 'Crear diseñador';
    $('#designerId').value=d?.id||''; $('#designerName').value=d?.nombre||''; $('#designerColor').value=d?.color||'#1268c9'; $('#designerCost').value=d?.costo_mensual_empresa||''; $('#designerStart').value=d?.hora_entrada||'07:00'; $('#designerEnd').value=d?.hora_salida||'17:00'; $('#lunchStart').value=d?.almuerzo_inicio||'12:00'; $('#lunchEnd').value=d?.almuerzo_fin||'13:00';
    $('#designerModal').showModal();
  }

  async function saveDesigner() {
    const id=$('#designerId').value; const body={nombre:$('#designerName').value,color:$('#designerColor').value,costo_mensual_empresa:Number($('#designerCost').value),hora_entrada:$('#designerStart').value,hora_salida:$('#designerEnd').value,almuerzo_inicio:$('#lunchStart').value,almuerzo_fin:$('#lunchEnd').value};
    await api(id?`/api/designers/${id}`:'/api/designers',{method:id?'PUT':'POST',body:JSON.stringify(body)}); $('#designerModal').close(); await refreshEverything(); toast(id?'Diseñador actualizado.':'Diseñador creado.');
  }

  function openPmp(id='') {
    const pmp = (state.catalogs.pmps || []).find(x => x.id === id);
    $('#pmpModalTitle').textContent = pmp ? 'Editar PMP' : 'Crear PMP';
    $('#pmpId').value = pmp?.id || '';
    $('#pmpName').value = pmp?.nombre || '';
    $('#pmpModal').showModal();
  }
  async function savePmp(){
    const id = $('#pmpId').value;
    await api(id ? `/api/pmps/${id}` : '/api/pmps', {method: id ? 'PUT' : 'POST', body: JSON.stringify({nombre: $('#pmpName').value})});
    $('#pmpModal').close(); await refreshEverything(); toast(id ? 'PMP actualizada.' : 'PMP creada.');
  }

  function openActivity(id='') {
    const a=state.catalogs.activities.find(x=>x.id===id);
    $('#activityModalTitle').textContent=a?'Editar actividad':'Crear actividad';
    $('#activityId').value=a?.id||'';
    $('#activityName').value=a?.nombre||'';
    $('#activityStage').value=a?.etapa||1;
    $('#activityPercent').value=a?.porcentaje||'';
    const selected = new Set(parseActivityTypes(a?.tipos_proyecto || 'T1'));
    $$('.activity-type-check').forEach(check => { check.checked = selected.has(check.value); });
    $('#activityModal').showModal();
  }
  async function saveActivity(){
    const id=$('#activityId').value;
    const tipos_proyecto=$$('.activity-type-check').filter(check=>check.checked).map(check=>check.value);
    const body={nombre:$('#activityName').value,etapa:Number($('#activityStage').value),porcentaje:Number($('#activityPercent').value),tipos_proyecto};
    const result = await api(id?`/api/activities/${id}`:'/api/activities',{method:id?'PUT':'POST',body:JSON.stringify(body)});
    $('#activityModal').close();
    await refreshEverything();
    if (id) {
      const updatedProjects = Number(result?.updated_projects || 0);
      const renamedRows = Number(result?.renamed_rows || 0);
      toast(updatedProjects || renamedRows
        ? `Actividad actualizada. Se sincronizaron ${updatedProjects} proyecto(s) y ${renamedRows} nombre(s) en registros existentes.`
        : 'Actividad actualizada.');
    } else {
      toast('Actividad creada.');
    }
  }
  function openProjectSizes(){renderProjectSizes();$('#projectSizesModal').showModal();}
  async function addProjectSize(){
    const body={nombre:$('#sizeName').value,minimo:Number($('#sizeMin').value),maximo:Number($('#sizeMax').value)};
    await api('/api/project-sizes',{method:'POST',body:JSON.stringify(body)}); $('#sizeName').value='';$('#sizeMin').value='';$('#sizeMax').value=''; await refreshEverything(); renderProjectSizes(); toast('Tamaño creado.');
  }
  async function saveProjectSize(id){
    const root=$('#projectSizesBody'); const name=$(`.size-edit-name[data-id="${id}"]`,root)?.value; const min=$(`.size-edit-min[data-id="${id}"]`,root)?.value; const max=$(`.size-edit-max[data-id="${id}"]`,root)?.value;
    await api(`/api/project-sizes/${id}`,{method:'PUT',body:JSON.stringify({nombre:name,minimo:Number(min),maximo:Number(max)})}); await refreshEverything(); renderProjectSizes(); toast('Tamaño actualizado.');
  }

  function openEquipment(id=''){const e=state.catalogs.equipment.find(x=>x.id===id);$('#equipmentModalTitle').textContent=e?'Editar equipo':'Crear equipo';$('#equipmentId').value=e?.id||'';$('#equipmentCode').value=e?.codigo||'';$('#equipmentName').value=e?.nombre||'';$('#equipmentStandard').value=e?.dias_estandar??'';$('#equipmentMedium').value=e?.dias_medio??0;$('#equipmentNonStandard').value=e?.dias_no_estandar??'';$('#equipmentComplex').value=e?.dias_complejo??0;$('#equipmentModal').showModal();}
  async function saveEquipment(){const id=$('#equipmentId').value;const body={codigo:$('#equipmentCode').value,nombre:$('#equipmentName').value,dias_estandar:Number($('#equipmentStandard').value),dias_medio:Number($('#equipmentMedium').value),dias_no_estandar:Number($('#equipmentNonStandard').value),dias_complejo:Number($('#equipmentComplex').value)};await api(id?`/api/equipment/${id}`:'/api/equipment',{method:id?'PUT':'POST',body:JSON.stringify(body)});$('#equipmentModal').close();await refreshEverything();toast(id?'Equipo actualizado.':'Equipo creado.');}
  async function saveHoliday(){const body={fecha:$('#holidayDate').value,nombre:$('#holidayName').value};await api('/api/holidays',{method:'POST',body:JSON.stringify(body)});$('#holidayModal').close();await refreshEverything();toast('Festivo agregado.');}
  async function loadColombia(){const year=Number($('#holidayYear').value);const result=await api(`/api/holidays/colombia/${year}`,{method:'POST',body:'{}'});await refreshEverything();toast(`Se agregaron ${result.added} festivos.`);}

  async function deleteItem(kind,id){if(!confirm('¿Confirma eliminar o desactivar este registro?'))return;await api(`/api/${kind}/${id}`,{method:'DELETE'});await refreshEverything();toast('Registro actualizado.');}
  async function syncExcel(){
    if(!confirm('Se validarán y cargarán los cambios manuales de los archivos Excel. ¿Continuar?')) return;
    const data=await api('/api/sync-excel',{method:'POST',body:'{}'});
    await refreshEverything();
    const updatedProjects=Number(data?.updated_projects||0);
    toast(updatedProjects
      ? `Información actualizada desde Excel. Se recalcularon ${updatedProjects} proyecto(s) activo(s).`
      : 'Información actualizada desde Excel.');
  }
  async function backup(){const data=await api('/api/backup',{method:'POST',body:'{}'});toast('Copia de seguridad creada.');}

  function openUpcomingProject(id = ''){
    const item = (state.dashboard?.upcoming || []).find(row => row.id === id);
    $('#upcomingModalTitle').textContent = item ? `Editar proyecto por empezar ${item.numero}` : 'Agregar proyecto por empezar';
    $('#upcomingId').value = item?.id || '';
    $('#upcomingNumber').value = item?.numero || '';
    $('#upcomingClient').value = item?.cliente || '';
    $('#upcomingDesigner').innerHTML = $('#projectDesigner').innerHTML;
    $('#upcomingDesigner').value = item?.designer_id || '';
    $('#upcomingStart').value = item?.fecha_inicio || '';
    $('#upcomingReferenceDays').value = item?.dias_referencia ?? 0;
    $('#upcomingModal').showModal();
  }

  async function saveUpcomingProject(){
    const id = $('#upcomingId').value;
    const body = {
      numero: $('#upcomingNumber').value,
      cliente: $('#upcomingClient').value,
      designer_id: $('#upcomingDesigner').value,
      fecha_inicio: $('#upcomingStart').value,
      dias_referencia: Number($('#upcomingReferenceDays').value || 0),
    };
    await api(id ? `/api/upcoming-projects/${id}` : '/api/upcoming-projects', {
      method: id ? 'PUT' : 'POST',
      body: JSON.stringify(body),
    });
    $('#upcomingModal').close();
    await refreshEverything();
    toast(id ? 'Proyecto por empezar actualizado.' : 'Proyecto por empezar agregado.');
  }

  async function deleteUpcomingProject(id){
    const item = (state.dashboard?.upcoming || []).find(row => row.id === id);
    const label = item ? `${item.numero} · ${item.cliente}` : 'este registro';
    if (!confirm(`¿Borrar ${label} de la lista informativa de proyectos por empezar?`)) return;
    await api(`/api/upcoming-projects/${id}`, { method: 'DELETE' });
    await refreshEverything();
    toast('Proyecto por empezar eliminado.');
  }

  async function deleteProject(id, number, client){
    if (!confirm(`¿Borrar definitivamente el proyecto ${number} · ${client}?

También se eliminarán sus equipos seleccionados y el avance de sus actividades. Esta acción no se puede deshacer.`)) return;
    await api(`/api/projects/${id}`, { method: 'DELETE' });
    if (state.projectId === id) state.projectId = '';
    await refreshEverything();
    if (state.mode === 'project') await loadDashboard();
    toast(`Proyecto ${number} eliminado.`);
  }


  function updateProjectTypeStatus() {
    const code = $('#projectType').value || 'T1';
    const total = activityTotals()[code] || 0;
    const info = $('#projectTypeLockInfo');
    if ($('#projectId').value) {
      info.classList.remove('hidden');
      info.textContent = `Tipo bloqueado: ${projectTypeLabel(code)}. Para cambiarlo debe borrar el proyecto y crearlo nuevamente.`;
    } else if (Math.abs(total - 100) >= 0.001) {
      info.classList.remove('hidden');
      info.textContent = `${projectTypeLabel(code)} tiene ${fmtNumber.format(total)} % en actividades. Debe sumar 100 % antes de guardar.`;
    } else {
      info.classList.add('hidden');
    }
  }

  function renderProjectImagePreview(url='') {
    const root=$('#projectImagePreview'); if(!root) return; root.innerHTML=url?`<img src="${escapeHtml(url)}" alt="Imagen del proyecto">`:'<span class="muted">Sin imagen cargada</span>';
  }
  function previewProjectImage(){const file=$('#projectImage').files?.[0];if(!file){renderProjectImagePreview(state.currentProject?.imagen_url||'');return;}const number=$('#projectNumber').value.trim();const normalizedNumber=number.toLowerCase().replace(/[^a-z0-9]/g,'');const normalizedFile=file.name.toLowerCase().replace(/[^a-z0-9]/g,'');if(number&&!normalizedFile.includes(normalizedNumber)){toast(`El nombre del archivo debe contener el número del proyecto ${number}.`,'error');$('#projectImage').value='';return;}const url=URL.createObjectURL(file);renderProjectImagePreview(url);}

  function renderRevisions(){const root=$('#projectRevisionsList'); if(!root)return; root.innerHTML=state.revisions.length?state.revisions.map((r,i)=>`<div class="revision-row"><span>${i+1}</span><label>Revisión<input class="revision-number" data-index="${i}" value="${escapeHtml(r.numero_revision||'REV '+String(i+1).padStart(2,'0'))}"></label><label>Fecha<span class="date-wrap"><input type="date" class="revision-date" data-index="${i}" value="${escapeHtml(r.fecha||'')}"></span></label><button type="button" class="mini-btn red remove-revision" data-index="${i}">QUITAR</button></div>`).join(''):'<p class="muted">Sin revisiones registradas.</p>';$$('.revision-number',root).forEach(x=>x.addEventListener('input',()=>state.revisions[Number(x.dataset.index)].numero_revision=x.value));$$('.revision-date',root).forEach(x=>x.addEventListener('change',()=>state.revisions[Number(x.dataset.index)].fecha=x.value));$$('.remove-revision',root).forEach(x=>x.addEventListener('click',()=>{state.revisions.splice(Number(x.dataset.index),1);renderRevisions();}));}
  function addRevision(){state.revisions.push({id:'',numero_revision:`REV ${String(state.revisions.length+1).padStart(2,'0')}`,fecha:''});renderRevisions();}

  function openNewProject(){
    state.cart=[];state.revisions=[];state.currentProject=null;state.stagePeriods={0:[],1:[],2:[],3:[]};
    $('#projectModalTitle').textContent='Crear proyecto';$('#projectId').value='';$('#projectNumber').value='';$('#projectClient').value='';$('#projectDesigner').value='';$('#projectPmp').value='';$('#projectWarehouse').value='';$('#projectSize').value='';$('#projectContraActual').value='';$('#projectType').value='T1';$('#projectType').disabled=false;$('#projectImage').value='';renderProjectImagePreview('');
    const today=toISO(new Date()); const stageStart=toISO(nextBusinessDate(addDays(parseLocalDate(today),1))); $('#projectReception').value=today; $('#projectStart').value=stageStart;
    state.stagePeriods[1]=[{id:'',etapa:1,inicio:stageStart,fin:''}];
    renderCart();renderStagePeriods();renderRevisions();updateProjectTypeStatus();updateApprovalPreview();$('#projectModal').showModal();
  }

  async function openEditProject(id){
    const p=await api(`/api/projects/${id}`);state.currentProject=p;
    state.cart=p.equipment_rows.map(r=>({equipment_id:r.equipment_id,cantidad:Number(r.cantidad),tipo:r.tipo})); state.revisions=(p.revision_rows||[]).map(r=>({...r}));
    state.stagePeriods={0:[],1:[],2:[],3:[]};
    (p.stage_periods||[]).forEach(period=>state.stagePeriods[Number(period.etapa)].push({...period}));
    $('#projectModalTitle').textContent=`Editar proyecto ${p.numero}`;$('#projectId').value=p.id;$('#projectNumber').value=p.numero;$('#projectClient').value=p.cliente;$('#projectType').value=p.tipo_proyecto||'T1';$('#projectType').disabled=true;$('#projectDesigner').value=p.designer_id;$('#projectPmp').value=p.pmp_id||'';$('#projectWarehouse').value=p.bodega||'';if(p.tamano_id && ![...$('#projectSize').options].some(o=>o.value===p.tamano_id)){const opt=document.createElement('option');opt.value=p.tamano_id;opt.textContent=`${p.tamano_nombre||'Tamaño'} (Inactivo)`;$('#projectSize').appendChild(opt);}$('#projectSize').value=p.tamano_id||'';$('#projectContraActual').value=p.fecha_contra_actual||'';$('#projectReception').value=p.fecha_recepcion_alcance||'';$('#projectStart').value=p.fecha_inicio;$('#projectImage').value='';renderProjectImagePreview(p.imagen_url||'');
    renderCart();renderStagePeriods();renderRevisions();updateProjectTypeStatus();updateApprovalPreview();$('#projectModal').showModal();
  }

  function syncProjectStart(){
    const value=$('#projectStart').value;
    if (!state.stagePeriods[1].length) state.stagePeriods[1].push({id:'',etapa:1,inicio:value,fin:''});
    state.stagePeriods[1][0].inicio=value;
    if (state.stagePeriods[1][0].fin && state.stagePeriods[1][0].fin < value) state.stagePeriods[1][0].fin='';
    renderStagePeriods();renderCart();updateApprovalPreview();
  }

  function addStagePeriod(stage){
    const rows=state.stagePeriods[stage]; let start='';
    if(stage===1 && !rows.length) start=$('#projectStart').value;
    if(rows.length && rows[rows.length-1].fin) start=toISO(addDays(parseLocalDate(rows[rows.length-1].fin),1));
    if(stage===0 && !rows.length){const s1=state.stagePeriods[1].filter(p=>p.fin).sort((a,b)=>String(a.fin).localeCompare(String(b.fin)));if(s1.length)start=toISO(addDays(parseLocalDate(s1[0].fin),1));}
    state.stagePeriods[stage].push({id:'',etapa:stage,inicio:start,fin:''});renderStagePeriods();updateApprovalPreview();
  }

  function removeStagePeriod(stage,index){
    if(stage===1 && state.stagePeriods[1].length===1){toast('La Etapa 01 debe conservar al menos un lapso.','error');return;}
    state.stagePeriods[stage].splice(index,1);renderStagePeriods();updateApprovalPreview();
  }

  function renderStagePeriods(){
    const roots={0:'approvalPeriods',1:'stage1Periods',2:'stage2Periods',3:'stage3Periods'};
    [1,0,2,3].forEach(stage=>{const root=$(`#${roots[stage]}`);if(!root)return;const rows=state.stagePeriods[stage];root.innerHTML=rows.length?rows.map((period,index)=>`<div class="period-row"><span class="period-number">${index+1}</span><label>Inicio<span class="date-wrap"><input type="date" class="period-start" data-stage="${stage}" data-index="${index}" value="${escapeHtml(period.inicio||'')}" ${stage===1&&index===0?'disabled':''}></span></label><label>Final<span class="date-wrap"><input type="date" class="period-end" data-stage="${stage}" data-index="${index}" value="${escapeHtml(period.fin||'')}"></span></label><button type="button" class="mini-btn red remove-period" data-stage="${stage}" data-index="${index}">QUITAR</button></div>`).join(''):`<p class="muted">Sin lapsos programados.</p>`;});
    $$('.period-start').forEach(input=>input.addEventListener('change',()=>{const stage=Number(input.dataset.stage),index=Number(input.dataset.index);state.stagePeriods[stage][index].inicio=input.value;sortStagePeriods(stage);renderStagePeriods();updateApprovalPreview();}));
    $$('.period-end').forEach(input=>input.addEventListener('change',()=>{const stage=Number(input.dataset.stage),index=Number(input.dataset.index);state.stagePeriods[stage][index].fin=input.value;sortStagePeriods(stage);renderStagePeriods();updateApprovalPreview();}));
    $$('.remove-period').forEach(btn=>btn.addEventListener('click',()=>removeStagePeriod(Number(btn.dataset.stage),Number(btn.dataset.index))));
  }

  function sortStagePeriods(stage){
    state.stagePeriods[stage].sort((a,b)=>String(a.inicio).localeCompare(String(b.inicio))||String(a.fin).localeCompare(String(b.fin)));
    if(stage===1 && state.stagePeriods[1].length) state.stagePeriods[1][0].inicio=$('#projectStart').value;
  }

  function allStagePeriods(){return [0,1,2,3].flatMap(stage=>state.stagePeriods[stage].map((period,index)=>({...period,etapa:stage,orden:index+1})));}

  function addCartItem(){const equipmentId=$('#cartEquipment').value;if(!equipmentId){toast('Seleccione un equipo.','error');return;}if(state.cart.some(x=>x.equipment_id===equipmentId)){toast('Ese equipo ya está en el carrito.','error');return;}state.cart.push({equipment_id:equipmentId,tipo:$('#cartType').value,cantidad:Math.max(1,Number($('#cartQuantity').value)||1)});renderCart();}
  function renderCart(){let total=0;const typeLabel={estandar:'Estándar',medio:'Medio',no_estandar:'No estándar',complejo:'Complejo'};const field={estandar:'dias_estandar',medio:'dias_medio',no_estandar:'dias_no_estandar',complejo:'dias_complejo'};$('#cartBody').innerHTML=state.cart.length?state.cart.map((item,i)=>{const e=state.catalogs.equipment.find(x=>x.id===item.equipment_id);if(!e)return'';const days=Number(e[field[item.tipo]||'dias_estandar'])||0;total+=days;return`<tr><td>${escapeHtml(e.codigo)}</td><td>${escapeHtml(e.nombre)}</td><td>${item.cantidad}</td><td>${typeLabel[item.tipo]||item.tipo}</td><td>${fmtNumber.format(days)}</td><td><button type="button" class="mini-btn red remove-cart" data-index="${i}">QUITAR</button></td></tr>`}).join(''):emptyRow(6,'No hay equipos seleccionados.');$$('.remove-cart').forEach(b=>b.addEventListener('click',()=>{state.cart.splice(Number(b.dataset.index),1);renderCart();}));$('#cartDays').textContent=`${fmtNumber.format(total)} días`;$('#tentativeDate').textContent=tentativeDate($('#projectStart').value,Math.max(0,Math.round(total)));}
  function tentativeDate(start,count){if(!start||!count)return start?fmtDate(start):'—';const holidays=new Set(state.catalogs.holidays.filter(h=>h.activo!==false).map(h=>String(h.fecha).slice(0,10)));let d=parseLocalDate(start),remaining=count-1;while(remaining>0){d=addDays(d,1);if(d.getDay()>0&&d.getDay()<6&&!holidays.has(toISO(d)))remaining--;}return fmtDate(toISO(d));}

  function updateApprovalPreview(){const output=$('#approvalDaysPreview');if(!output)return;const holidays=holidayMap(),days=new Set();(state.stagePeriods[0]||[]).forEach(p=>{if(!p.inicio||!p.fin)return;const s=parseLocalDate(p.inicio),e=parseLocalDate(p.fin);if(e<s)return;for(let d=s;d<=e;d=addDays(d,1))if(isBusinessDate(d,holidays))days.add(toISO(d));});output.textContent=String(days.size);}

  async function uploadProjectImage(projectId){const input=$('#projectImage');const file=input.files?.[0];if(!file)return;const fd=new FormData();fd.append('image',file);const response=await fetch(moduleUrl(`/api/projects/${projectId}/image`),{method:'POST',headers:{'X-CSRF-Token':CSRF_TOKEN},body:fd});let body;try{body=await response.json();}catch{body={ok:false,message:'Respuesta inválida al cargar la imagen.'}}if(!response.ok||body.ok===false)throw new Error(body.message||'No fue posible cargar la imagen.');}

  async function saveProject(){
    const id=$('#projectId').value;
    const imageFile=$('#projectImage').files?.[0]; const projectNumber=$('#projectNumber').value.trim();
    if(imageFile){const n=projectNumber.toLowerCase().replace(/[^a-z0-9]/g,'');const f=imageFile.name.toLowerCase().replace(/[^a-z0-9]/g,'');if(!n||!f.includes(n)){throw new Error(`El nombre de la imagen debe contener el número del proyecto ${projectNumber}.`);}}
    const body={numero:$('#projectNumber').value,cliente:$('#projectClient').value,tipo_proyecto:$('#projectType').value,designer_id:$('#projectDesigner').value,pmp_id:$('#projectPmp').value,bodega:$('#projectWarehouse').value,tamano_id:$('#projectSize').value,fecha_contra_actual:$('#projectContraActual').value,fecha_recepcion_alcance:$('#projectReception').value,fecha_inicio:$('#projectStart').value,stage_periods:allStagePeriods(),revisions:state.revisions,equipment:state.cart};
    const saved=await api(id?`/api/projects/${id}`:'/api/projects',{method:id?'PUT':'POST',body:JSON.stringify(body)});
    const projectId=id||saved.id; await uploadProjectImage(projectId);
    $('#projectModal').close();await refreshEverything();showView('projects');toast(id?'Proyecto actualizado.':'Proyecto creado.');
  }

  function phaseDaysGraphic(phaseDays = {}) {
    const entries = [
      ['Etapa 01', Number(phaseDays.stage1 || 0), '#6dcff4'],
      ['Aprobación', Number(phaseDays.approval || 0), '#f06292'],
      ['Etapa 02', Number(phaseDays.stage2 || 0), '#ffb91b'],
      ['Etapa 03', Number(phaseDays.stage3 || 0), '#1dd5a3'],
    ];
    const max = Math.max(1, ...entries.map(item => item[1]));
    return `<section class="phase-days-panel"><h3>Tiempo hábil por etapa</h3>${entries.map(([label,value,color]) => `<div class="phase-days-row"><span>${label}</span><div class="phase-days-track"><i style="width:${(value/max)*100}%;background:${color}"></i></div><strong>${fmtNumber.format(value)} d</strong></div>`).join('')}</section>`;
  }

  function periodsDetail(p,stage){const rows=(p.periods_by_stage?.[String(stage)]||[]);const label=stage===0?'Aprobación':`Etapa 0${stage}`;return rows.length?rows.map((period,index)=>stageLine(`${label} · Lapso ${index+1}`,period.inicio,period.fin)).join(''):`<div class="stage-line"><span>${label}</span><strong>Sin programación</strong></div>`;}

  function historyExecutionGraphic(p){
    if(p.estado!=='Finalizado')return'';const items=[];(p.stage_periods||[]).forEach(period=>{const stage=Number(period.etapa),cfg={0:['Aprobación','#f06292'],1:['Etapa 01','#6dcff4'],2:['Etapa 02','#ffb91b'],3:['Etapa 03','#1dd5a3']}[stage];if(cfg)items.push({label:cfg[0],start:period.inicio,end:period.fin,color:cfg[1]});});
    const dates=items.flatMap(x=>[parseLocalDate(x.start),parseLocalDate(x.end)]);if(p.fecha_recepcion_alcance)dates.push(parseLocalDate(p.fecha_recepcion_alcance));if(p.fecha_contra_actual)dates.push(parseLocalDate(p.fecha_contra_actual));(p.revision_rows||[]).forEach(r=>{if(r.fecha)dates.push(parseLocalDate(r.fecha));});if(p.fecha_finalizacion)dates.push(parseLocalDate(p.fecha_finalizacion));if(!dates.length)return'';const min=new Date(Math.min(...dates)),max=new Date(Math.max(...dates)),total=Math.max(1,dayDiff(min,max)+1);const bars=items.map(item=>{const left=(dayDiff(min,parseLocalDate(item.start))/total)*100,width=Math.max(1.2,((dayDiff(parseLocalDate(item.start),parseLocalDate(item.end))+1)/total)*100);return`<div class="history-exec-bar" title="${escapeHtml(item.label)} · ${fmtDate(item.start)} a ${fmtDate(item.end)}" style="left:${left}%;width:${width}%;background:${item.color}"><span>${escapeHtml(item.label)}</span></div>`;}).join('');const reception=p.fecha_recepcion_alcance?`<i class="history-reception-point" title="Recepción de alcance · ${fmtDate(p.fecha_recepcion_alcance)}" style="left:${(dayDiff(min,parseLocalDate(p.fecha_recepcion_alcance))/total)*100}%"></i>`:'';const contra=p.fecha_contra_actual?`<i class="history-event-point contra" title="CONTRA ACTUAL · ${fmtDate(p.fecha_contra_actual)}" style="left:${(dayDiff(min,parseLocalDate(p.fecha_contra_actual))/total)*100}%"></i>`:'';const revisions=(p.revision_rows||[]).filter(r=>r.fecha).map(r=>`<i class="history-event-point revision" title="${escapeHtml(r.numero_revision)} · ${fmtDate(r.fecha)}" style="left:${(dayDiff(min,parseLocalDate(r.fecha))/total)*100}%"></i>`).join('');return`<section class="history-execution"><h3>Ejecución final del proyecto</h3><div class="history-exec-dates"><span>${fmtDate(toISO(min))}</span><span>${fmtDate(toISO(max))}</span></div><div class="history-exec-track">${bars}${reception}${contra}${revisions}</div></section>`;
  }

  async function openProjectDetail(id){
    const p=await api(`/api/projects/${id}`);state.currentProject=p;
    $('#detailTitle').textContent=`${p.numero} · ${p.cliente}`;
    $('#detailSubtitle').textContent=`${p.project_type_name||p.tipo_proyecto} · ${p.designer_name} · PMP: ${p.pmp_name||'Sin PMP'} · Tamaño: ${p.tamano_nombre||'Sin tamaño'} · ${p.phase.label}`;
    const historic=p.estado==='Finalizado';const grouped={1:[],2:[],3:[]};p.progress_rows.forEach(r=>(grouped[Number(r.etapa)]||[]).push(r));
    const typeLabel={estandar:'Estándar',medio:'Medio',no_estandar:'No estándar',complejo:'Complejo'};
    const imageBox=`<div class="detail-project-image">${p.imagen_url?`<img src="${escapeHtml(p.imagen_url)}" alt="Imagen proyecto ${escapeHtml(p.numero)}">`:'<span class="muted">Sin imagen del proyecto</span>'}</div>`;
    const revisions=(p.revision_rows||[]);
    $('#detailContent').innerHTML=`
    <div class="detail-summary"><div class="detail-stat"><span>Tipo</span><strong>${escapeHtml(p.tipo_proyecto||'T1')}</strong></div><div class="detail-stat"><span>PMP</span><strong>${escapeHtml(p.pmp_name||'Sin PMP')}</strong></div><div class="detail-stat"><span>BODEGA</span><strong>${escapeHtml(p.bodega||'—')}</strong></div><div class="detail-stat"><span>Tamaño</span><strong>${escapeHtml(p.tamano_nombre||'Sin tamaño')}</strong></div><div class="detail-stat"><span>N° revisiones</span><strong>${Number(p.numero_revisiones||0)}</strong></div><div class="detail-stat"><span>CONTRA ACTUAL</span><strong>${fmtDate(p.fecha_contra_actual)}</strong></div><div class="detail-stat"><span>Recepción alcance</span><strong>${fmtDate(p.fecha_recepcion_alcance)}</strong></div><div class="detail-stat"><span>Avance</span><strong>${fmtNumber.format(p.metrics.avance)} %</strong></div><div class="detail-stat"><span>Horas</span><strong>${fmtNumber.format(p.planned_hours)} h</strong></div><div class="detail-stat"><span>Costo</span><strong>${fmtMoney.format(p.planned_cost)}</strong></div><div class="detail-stat"><span>Días aprobación</span><strong>${p.approval_days}</strong></div><div class="detail-stat"><span>Estado</span><strong>${escapeHtml(p.estado)}</strong></div></div>
    ${phaseDaysGraphic(p.phase_days)}
    ${historyExecutionGraphic(p)}
    ${historic?`<section class="history-meta-summary"><h3>Registro histórico</h3><div class="history-notes"><strong>Notas / observaciones</strong><p>${escapeHtml(p.notas_historico||'Sin notas registradas.')}</p></div></section>`:''}
    <div class="detail-grid"><section class="detail-section"><h3>Programación por lapsos</h3>${stageLine('Recepción de alcance',p.fecha_recepcion_alcance,p.fecha_recepcion_alcance)}${stageLine('CONTRA ACTUAL',p.fecha_contra_actual,p.fecha_contra_actual)}${periodsDetail(p,1)}${periodsDetail(p,0)}${periodsDetail(p,2)}${periodsDetail(p,3)}${p.alert?`<div class="callout ${p.alert.type==='danger'?'warning':'info'}">${escapeHtml(p.alert.message)} · Fecha límite ${fmtDate(p.alert.deadline)}</div>`:''}<h3 style="margin-top:12px">Revisiones</h3>${revisions.length?revisions.map(r=>`<div class="stage-line"><span>${escapeHtml(r.numero_revision)}</span><strong>${fmtDate(r.fecha)}</strong></div>`).join(''):'<p class="muted">Sin revisiones.</p>'}<h3 style="margin-top:12px">Equipos</h3>${p.equipment_rows.length?p.equipment_rows.map(e=>`<div class="stage-line"><span>${escapeHtml(e.codigo)} · ${escapeHtml(e.nombre)} × ${e.cantidad}</span><strong>${escapeHtml(typeLabel[e.tipo]||e.tipo)} · ${fmtNumber.format(e.dias_aplicados)} d</strong></div>`).join(''):'<p class="muted">Sin equipos.</p>'}${imageBox}</section>
    <section class="detail-section"><h3>Actividades y avance</h3>${[1,2,3].map(stage=>`<div class="activity-group"><h4>Etapa 0${stage} · ${stageName(stage)} (${fmtNumber.format(p.metrics.stages[String(stage)]?.avance??p.metrics.stages[stage]?.avance??0)} %)</h4>${grouped[stage].length?grouped[stage].map(a=>`<div class="activity-record"><label class="activity-check"><input type="checkbox" class="project-activity-check" data-id="${a.id}" ${a.cumplida?'checked':''} ${historic?'disabled':''}><span>${escapeHtml(a.actividad)}</span><span class="weight">${fmtNumber.format(a.porcentaje)} %</span></label><label class="activity-date-label">Fecha<input type="date" class="activity-date" data-id="${a.id}" data-completed="${a.cumplida?'1':'0'}" value="${escapeHtml(a.fecha_cumplimiento||'')}" ${historic?'disabled':''}></label></div>`).join(''):'<p class="muted">Sin actividades en esta etapa.</p>'}</div>`).join('')}</section></div>`;
    $$('.project-activity-check',$('#detailContent')).forEach(ch=>ch.addEventListener('change',async()=>{await api(`/api/projects/${p.id}/activities/${ch.dataset.id}`,{method:'PATCH',body:JSON.stringify({cumplida:ch.checked})});await loadDashboard();await openProjectDetail(p.id);toast('Avance actualizado.');}));
    $$('.activity-date',$('#detailContent')).forEach(input=>input.addEventListener('change',async()=>{await api(`/api/projects/${p.id}/activities/${input.dataset.id}`,{method:'PATCH',body:JSON.stringify({cumplida:input.dataset.completed==='1',fecha_cumplimiento:input.value})});await loadDashboard();await openProjectDetail(p.id);toast('Fecha de actividad actualizada.');}));
    const footer=$('#detailFooter');footer.innerHTML=`<button class="btn outline" id="detailCloseFooter">CERRAR</button>${historic?`<button class="btn blue" id="restoreHistoryBtn">DEVOLVER AL TABLERO</button>`:`<button class="btn blue" id="detailEdit">EDITAR PROYECTO</button>`}${!historic&&p.metrics.avance>=99.999?`<button class="btn green" id="finishBtn">FINALIZAR PROYECTO</button>`:''}`;
    $('#detailCloseFooter').addEventListener('click',()=>$('#detailModal').close());if($('#detailEdit'))$('#detailEdit').addEventListener('click',()=>{$('#detailModal').close();openEditProject(p.id)});if($('#restoreHistoryBtn'))$('#restoreHistoryBtn').addEventListener('click',()=>{$('#detailModal').close();restoreHistoryProject(p.id)});if($('#finishBtn'))$('#finishBtn').addEventListener('click',()=>finishProject(p.id));$('#detailModal').showModal();
  }

  function stageLine(label,start,end){return`<div class="stage-line"><span>${label}</span><strong>${start?fmtDate(start):'—'} → ${end?(String(end).includes('-')?fmtDate(end):escapeHtml(end)):'—'}</strong></div>`;}
  async function finishProject(id){
    const p=await api(`/api/projects/${id}`);
    $('#finishProjectId').value=id; $('#finishDate').value=toISO(new Date()); $('#finishNotes').value=p.notas_historico||'';
    $('#finishModal').showModal();
  }
  async function confirmFinishProject(){
    const id=$('#finishProjectId').value;
    if(!confirm('El proyecto saldrá del calendario activo y pasará al histórico. ¿Continuar?'))return;
    const body={fecha_finalizacion:$('#finishDate').value,notas_historico:$('#finishNotes').value};
    await api(`/api/projects/${id}/finish`,{method:'POST',body:JSON.stringify(body)}); $('#finishModal').close(); $('#detailModal').close(); await refreshEverything(); showView('history'); toast('Proyecto enviado al histórico.');
  }
  async function openHistoryMeta(id){
    const p=await api(`/api/projects/${id}`);
    $('#historyMetaProjectId').value=id;
    const pmps=state.catalogs.pmps||[];
    const options=pmps.filter(x=>x.activo!==false||x.id===p.pmp_id).map(x=>`<option value="${escapeHtml(x.id)}">${escapeHtml(x.nombre)}${x.activo===false?' (Inactiva)':''}</option>`).join('');
    $('#historyPmp').innerHTML=`<option value="">Seleccione PMP</option>${options}`;
    $('#historyPmp').value=p.pmp_id||'';
    $('#historyWarehouse').value=p.bodega||'';
    $('#historyReception').value=p.fecha_recepcion_alcance||'';
    $('#historyStatus').value=p.estatus_historico||'PRODUCCION';
    $('#historyDelay1').value=p.retraso_etapa1||0; $('#historyDelay2').value=p.retraso_etapa2||0; $('#historyDelay3').value=p.retraso_etapa3||0; $('#historyNotes').value=p.notas_historico||'';
    $('#historyMetaModal').showModal();
  }
  async function saveHistoryMeta(){
    const id=$('#historyMetaProjectId').value;
    const body={pmp_id:$('#historyPmp').value,bodega:$('#historyWarehouse').value,fecha_recepcion_alcance:$('#historyReception').value,estatus_historico:$('#historyStatus').value,retraso_etapa1:Number($('#historyDelay1').value||0),retraso_etapa2:Number($('#historyDelay2').value||0),retraso_etapa3:Number($('#historyDelay3').value||0),notas_historico:$('#historyNotes').value};
    await api(`/api/projects/${id}/history`,{method:'PATCH',body:JSON.stringify(body)}); $('#historyMetaModal').close(); await loadDashboard({history:true}); if($('#detailModal').open) await openProjectDetail(id); toast('Registro histórico actualizado.');
  }

  function alertsMutedForSession(){
    try { return sessionStorage.getItem(ALERT_SESSION_KEY) === '1'; } catch (_) { return false; }
  }

  function closeAlertPopup(){
    const checkbox = $('#muteAlertsSession');
    if (checkbox?.checked) {
      try { sessionStorage.setItem(ALERT_SESSION_KEY, '1'); } catch (_) {}
    }
    $('#alertModal').close();
  }

  function showAlertPopup(){
    const alerts=state.dashboard?.alerts||[];
    if(!alerts.length||state.alertsShown||alertsMutedForSession())return;
    state.alertsShown=true;
    const checkbox=$('#muteAlertsSession');
    if(checkbox) checkbox.checked=false;
    $('#alertModalBody').innerHTML=alerts.map(a=>`<div class="alert-item ${a.type==='danger'?'danger':''}" data-project-id="${a.project_id}"><strong>${escapeHtml(a.numero)} · ${escapeHtml(a.client||a.cliente||'')}</strong><p>${escapeHtml(a.designer)} · ${escapeHtml(a.phase)} · ${escapeHtml(a.message)} · Límite ${fmtDate(a.deadline)}</p></div>`).join('');
    $$('.alert-item').forEach(x=>x.addEventListener('click',()=>{ closeAlertPopup(); openProjectDetail(x.dataset.projectId); }));
    $('#alertModal').showModal();
  }

  function dailyHours(d){const mins=t=>{const [h,m]=String(t||'00:00').split(':').map(Number);return h*60+m};return Math.max(0,(mins(d.hora_salida)-mins(d.hora_entrada)-Math.max(0,mins(d.almuerzo_fin)-mins(d.almuerzo_inicio)))/60);}
  function stageName(stage){return ({1:'Plano general',2:'Fabricación',3:'Adicionales'})[Number(stage)]||'';}
  function parseLocalDate(value){return new Date(`${String(value).slice(0,10)}T12:00:00`);}
  function stripTime(value){return new Date(value.getFullYear(),value.getMonth(),value.getDate(),12);}
  function addDays(value,days){const d=new Date(value);d.setDate(d.getDate()+days);return stripTime(d);}
  function dayDiff(a,b){return Math.round((stripTime(b)-stripTime(a))/86400000);}
  function toISO(d){return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;}
  function nextBusinessDate(value){let d=stripTime(value);const holidays=holidayMap();while(!isBusinessDate(d,holidays))d=addDays(d,1);return d;}
  function debounce(fn,wait){let t;return(...args)=>{clearTimeout(t);t=setTimeout(()=>fn(...args),wait)}}

  document.addEventListener('DOMContentLoaded', () => init().catch(err => { console.error(err); toast(err.message,'error'); }));
  window.addEventListener('unhandledrejection', event => { console.error(event.reason); toast(event.reason?.message || 'Ocurrió un error.','error'); });
})();
