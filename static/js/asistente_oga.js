(function () {
  'use strict';

  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches === true;

  function setAssistantState(root, state) {
    if (!root) return;
    const thinking = state === 'thinking';
    root.classList.toggle('is-thinking', thinking);
    root.querySelectorAll('[data-ai-live-state]').forEach(label => {
      label.textContent = thinking ? 'CONSULTANDO' : 'LISTO';
    });
  }

  function initParticleField(canvas) {
    if (!canvas || reduceMotion || canvas.dataset.aiParticleBound === '1') return;
    canvas.dataset.aiParticleBound = '1';
    const context = canvas.getContext('2d', { alpha: true });
    if (!context) return;
    const mode = canvas.dataset.aiParticles || 'page';
    const host = canvas.parentElement;
    const palette = mode === 'panel'
      ? [[255,255,255],[236,246,255],[217,238,255]]
      : [[255,255,255],[241,248,255],[221,239,255],[202,229,255]];
    let width = 0;
    let height = 0;
    let ratio = 1;
    let particles = [];
    let raf = 0;

    function buildParticles() {
      const area = Math.max(1, width * height);
      const divisor = mode === 'panel' ? 8500 : 10500;
      const max = mode === 'panel' ? 72 : 118;
      const min = mode === 'panel' ? 38 : 64;
      const count = Math.max(min, Math.min(max, Math.round(area / divisor)));
      particles = Array.from({ length: count }, () => {
        const c = palette[Math.floor(Math.random() * palette.length)];
        return {
          x: Math.random() * width,
          y: Math.random() * height,
          vx: (Math.random() - .5) * (mode === 'panel' ? .17 : .22),
          vy: (Math.random() - .5) * (mode === 'panel' ? .15 : .20),
          r: .42 + Math.random() * 1.18,
          a: .06 + Math.random() * .24,
          c
        };
      });
    }

    function resize() {
      const rect = canvas.getBoundingClientRect();
      const nextWidth = Math.max(1, Math.round(rect.width));
      const nextHeight = Math.max(1, Math.round(rect.height));
      if (nextWidth === width && nextHeight === height) return;
      width = nextWidth;
      height = nextHeight;
      ratio = Math.min(window.devicePixelRatio || 1, 1.5);
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      buildParticles();
    }

    function loop() {
      raf = requestAnimationFrame(loop);
      if (document.hidden) return;
      if (mode === 'panel' && host?.classList.contains('oga-ai-panel') && !host.classList.contains('open')) return;
      resize();
      context.clearRect(0, 0, width, height);
      const active = host?.classList.contains('is-thinking');
      const speed = active ? 1.75 : 1;
      const connectionDistance = mode === 'panel' ? 66 : 82;
      for (let i = 0; i < particles.length; i++) {
        const p = particles[i];
        p.x += p.vx * speed;
        p.y += p.vy * speed;
        if (p.x < -8) p.x = width + 8;
        if (p.x > width + 8) p.x = -8;
        if (p.y < -8) p.y = height + 8;
        if (p.y > height + 8) p.y = -8;

        context.beginPath();
        context.arc(p.x, p.y, active ? p.r * 1.18 : p.r, 0, Math.PI * 2);
        context.fillStyle = `rgba(${p.c[0]},${p.c[1]},${p.c[2]},${active ? Math.min(.50,p.a+.09) : p.a})`;
        context.shadowBlur = active ? 9 : 4;
        context.shadowColor = `rgba(255,255,255,.22)`;
        context.fill();
        context.shadowBlur = 0;

        for (let j = i + 1; j < particles.length; j++) {
          const q = particles[j];
          const dx = p.x - q.x;
          const dy = p.y - q.y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist >= connectionDistance) continue;
          const alpha = (1 - dist / connectionDistance) * (active ? .055 : .025);
          context.beginPath();
          context.moveTo(p.x, p.y);
          context.lineTo(q.x, q.y);
          context.strokeStyle = `rgba(255,255,255,${alpha})`;
          context.lineWidth = .55;
          context.stroke();
        }
      }
    }

    resize();
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(resize) : null;
    observer?.observe(canvas);
    loop();
    canvas._ogaAiCleanup = () => {
      cancelAnimationFrame(raf);
      observer?.disconnect();
    };
  }

  function initParticles() {
    document.querySelectorAll('[data-ai-particles]').forEach(initParticleField);
  }

  function escapeText(value) {
    return String(value == null ? '' : value);
  }

  function currentContext(scope) {
    if (scope === 'global') return { scope: 'global' };
    const body = document.body;
    const context = {
      scope: 'current',
      endpoint: body.dataset.ogaEndpoint || '',
      path: window.location.pathname,
      query: window.location.search
    };
    const activeOd = document.querySelector('.od-list-row.active');
    const urlOd = new URL(window.location.href).searchParams.get('od');
    const opportunityId = activeOd?.dataset.id || urlOd;
    if (opportunityId) context.opportunity_id = Number(opportunityId);
    const activeSubsystem = document.querySelector('.od-subsystem-tab.active');
    if (activeSubsystem) context.subsystem = activeSubsystem.textContent.trim();
    return context;
  }

  function contextLabel(scope) {
    if (scope === 'global') return 'Toda OGA';
    const ctx = currentContext(scope);
    if (ctx.opportunity_id) {
      const row = document.querySelector(`.od-list-row[data-id="${ctx.opportunity_id}"]`);
      const project = row?.querySelector('.od-row-main strong')?.textContent?.trim();
      const radicado = row?.querySelector('.od-row-main b')?.textContent?.trim();
      const sub = ctx.subsystem ? ` | ${ctx.subsystem}` : '';
      return `${project ? 'Proyecto ' + project : 'OD #' + ctx.opportunity_id}${radicado ? ' | Rad. ' + radicado : ''}${sub}`;
    }
    const names = {
      'asistente_oga.index': 'Asistente OGA',
      'capacitaciones.index': 'Capacitaciones',
      'biblioteca.equipos': 'Biblioteca de equipos',
      'biblioteca.buscador': 'Buscador de referencias',
      'planos.planos_home': 'Revisor de Planos',
      'proyectos_diseno.index': 'Proyectos Diseño',
      'factory': 'Lista Maestra / Factory',
      'rq': 'RQ · Requisiciones',
      'repuestos': 'Repuestos',
      'valor': 'Valor del proyecto',
      'calendario': 'Calendario',
      'historico': 'Histórico',
      'inicio': 'Inicio'
    };
    return names[ctx.endpoint] || (ctx.endpoint ? ctx.endpoint.replaceAll('_', ' ') : 'Pagina actual');
  }

  function formatSize(bytes) {
    const size = Number(bytes || 0);
    if (size >= 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`;
    if (size >= 1024) return `${Math.round(size / 1024)} KB`;
    return size ? `${size} B` : '';
  }

  function create(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = escapeText(text);
    return el;
  }

  function renderCard(item) {
    const card = create('div', 'oga-ai-card');
    const top = create('div', 'oga-ai-card-top');
    const titleBox = create('div');
    titleBox.append(create('strong', '', item.title || 'Resultado'));
    if (item.subtitle) titleBox.append(create('div', 'oga-ai-card-sub', item.subtitle));
    top.append(titleBox);
    if (item.score !== undefined && item.score !== null) top.append(create('span', 'oga-ai-score', `${item.score}% similar`));
    card.append(top);

    if (item.client) card.append(create('div', 'oga-ai-card-client', item.client));
    if (item.status || item.meta || item.internal_id) {
      const meta = create('div', 'oga-ai-card-meta');
      if (item.internal_id) meta.append(create('span', 'oga-ai-chip', `ID OD: ${item.internal_id}`));
      if (item.status) meta.append(create('span', 'oga-ai-chip', item.status));
      if (item.meta) meta.append(create('span', 'oga-ai-chip', item.meta));
      card.append(meta);
    }
    if (item.reason) card.append(create('div', 'oga-ai-card-sub', `Coincide en: ${item.reason}`));
    if (Array.isArray(item.criteria) && item.criteria.length) {
      const list = create('ul', 'oga-ai-card-list');
      item.criteria.forEach(value => list.append(create('li', '', value)));
      card.append(list);
      const meta = create('div', 'oga-ai-card-meta');
      meta.append(create('span', 'oga-ai-chip', `${item.equipment_count || 0} equipos`));
      meta.append(create('span', 'oga-ai-chip', `${item.offer_count || 0} ofertas`));
      meta.append(create('span', 'oga-ai-chip', `${item.image_count || 0} imagenes`));
      card.append(meta);
    }
    if (Array.isArray(item.items) && item.items.length) {
      const list = create('ul', 'oga-ai-card-list');
      item.items.forEach(value => list.append(create('li', '', value)));
      card.append(list);
    }
    if (item.kind) {
      const meta = create('div', 'oga-ai-card-meta');
      meta.append(create('span', 'oga-ai-chip', item.kind));
      if (item.size) meta.append(create('span', 'oga-ai-chip', formatSize(item.size)));
      card.append(meta);
    }
    const actions = create('div', 'oga-ai-card-actions');
    if (item.url) {
      const link = create('a', '', item.action_label || 'Abrir');
      link.href = item.url;
      actions.append(link);
    }
    if (item.view_url) {
      const link = create('a', '', item.view_label || (item.kind === 'IMAGEN' ? 'Ver imagen' : 'Abrir archivo'));
      link.href = item.view_url;
      link.target = '_blank';
      link.rel = 'noopener';
      actions.append(link);
    }
    if (item.download_url) {
      const link = create('a', '', item.download_label || (item.kind === 'PDF' ? 'Descargar PDF' : 'Descargar'));
      link.href = item.download_url;
      actions.append(link);
    }
    if (actions.children.length) card.append(actions);
    return card;
  }

  function appendMessage(thread, role, text, cards, engine, warning) {
    const message = create('div', `oga-ai-message ${role}`);
    const avatar = create('div', 'oga-ai-avatar', role === 'user' ? 'TU' : 'AI');
    const content = create('div');
    const bubble = create('div', 'oga-ai-bubble', text || '');
    content.append(bubble);
    if (Array.isArray(cards) && cards.length) {
      const results = create('div', 'oga-ai-result-cards');
      cards.forEach(item => results.append(renderCard(item)));
      content.append(results);
    }
    if (role === 'assistant' && (engine || warning)) {
      const meta = create('div', 'oga-ai-response-meta');
      if (engine) meta.append(create('span', '', engine));
      if (warning) meta.append(create('span', 'warning', 'IA avanzada no disponible; se uso respaldo local.'));
      content.append(meta);
    }
    message.append(avatar, content);
    thread.append(message);
    thread.scrollTop = thread.scrollHeight;
    return message;
  }

  function appendLoading(thread) {
    const message = create('div', 'oga-ai-message assistant');
    const avatar = create('div', 'oga-ai-avatar', 'AI');
    const bubble = create('div', 'oga-ai-bubble');
    const loading = create('div', 'oga-ai-loading');
    loading.append(create('i'), create('i'), create('i'));
    bubble.append(loading);
    message.append(avatar, bubble);
    thread.append(message);
    thread.scrollTop = thread.scrollHeight;
    return message;
  }

  function bindAssistant(root) {
    if (!root || root.dataset.bound === '1') return;
    root.dataset.bound = '1';
    const url = root.dataset.consultUrl;
    const form = root.querySelector('[data-ai-form]');
    const input = root.querySelector('[data-ai-input]');
    const thread = root.querySelector('[data-ai-thread]');
    const send = root.querySelector('[data-ai-send]');
    const scope = root.querySelector('[data-ai-scope]');
    const labels = root.querySelectorAll('[data-ai-context-label]');
    if (!url || !form || !input || !thread) return;
    setAssistantState(root, 'ready');
    const history = [];
    const conversationState = {
      lastResultIds: [],
      lastOpportunityId: null,
      assistantModule: '',
      lastEntityKeys: []
    };

    function updateConversationState(data) {
      const cards = Array.isArray(data?.cards) ? data.cards : [];
      const sources = Array.isArray(data?.sources) ? data.sources : [];
      const resultIds = cards
        .filter(item => item && item.type === 'opportunity' && Number(item.id) > 0)
        .map(item => Number(item.id));
      const sourceIds = sources
        .filter(item => item && item.type === 'opportunity' && Number(item.id) > 0)
        .map(item => Number(item.id));

      if (resultIds.length) {
        conversationState.lastResultIds = [...new Set(resultIds)].slice(0, 20);
        conversationState.lastOpportunityId = resultIds.length === 1 ? resultIds[0] : null;
      }
      if (sourceIds.length === 1) {
        conversationState.lastOpportunityId = sourceIds[0];
      }
      if (data?.context_update && typeof data.context_update === 'object') {
        conversationState.assistantModule = String(data.context_update.module || '');
        conversationState.lastEntityKeys = Array.isArray(data.context_update.entity_keys)
          ? data.context_update.entity_keys.map(String).slice(0, 20)
          : [];
      }
    }

    function remember(role, content) {
      const text = String(content || '').trim();
      if (!text) return;
      history.push({ role, content: text.slice(0, 1500) });
      if (history.length > 10) history.splice(0, history.length - 10);
    }

    function refreshContext() {
      const value = scope?.value || 'current';
      labels.forEach(label => { label.textContent = contextLabel(value); });
    }
    refreshContext();
    scope?.addEventListener('change', refreshContext);

    root.querySelectorAll('[data-ai-prompt]').forEach(button => {
      button.addEventListener('click', () => {
        input.value = button.dataset.aiPrompt || '';
        input.focus();
      });
    });

    input.addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        form.requestSubmit();
      }
    });

    form.addEventListener('submit', async event => {
      event.preventDefault();
      const message = input.value.trim();
      if (!message || send?.disabled) return;
      appendMessage(thread, 'user', message);
      remember('user', message);
      input.value = '';
      setAssistantState(root, 'thinking');
      const loading = appendLoading(thread);
      if (send) send.disabled = true;
      try {
        const response = await fetch(url, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-CSRF-Token': csrf
          },
          body: JSON.stringify({
            message,
            context: {
              ...currentContext(scope?.value || 'current'),
              last_result_ids: conversationState.lastResultIds,
              last_opportunity_id: conversationState.lastOpportunityId,
              assistant_module: conversationState.assistantModule,
              last_entity_keys: conversationState.lastEntityKeys
            },
            history: history.slice(0, -1)
          })
        });
        const data = await response.json().catch(() => ({}));
        loading.remove();
        if (!response.ok || !data.ok) throw new Error(data.error || 'No fue posible completar la consulta.');
        const answer = data.answer || 'Consulta completada.';
        updateConversationState(data);
        appendMessage(thread, 'assistant', answer, data.cards || [], data.engine || '', data.provider_warning || '');
        remember('assistant', answer);
      } catch (error) {
        loading.remove();
        const messageError = `No fue posible consultar: ${error.message}`;
        appendMessage(thread, 'assistant', messageError);
        remember('assistant', messageError);
      } finally {
        setAssistantState(root, 'ready');
        if (send) send.disabled = false;
        input.focus();
        refreshContext();
      }
    });
  }

  initParticles();

  const panel = document.getElementById('ogaAiPanel');
  const launcher = document.getElementById('ogaAiLauncher');
  const close = document.getElementById('ogaAiClose');
  const overlay = document.getElementById('ogaAiOverlay');
  if (panel && launcher) {
    bindAssistant(panel);
    const setOpen = open => {
      panel.classList.toggle('open', open);
      panel.setAttribute('aria-hidden', open ? 'false' : 'true');
      launcher.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (overlay) overlay.hidden = !open;
      if (open) {
        const scope = panel.querySelector('[data-ai-scope]');
        panel.querySelectorAll('[data-ai-context-label]').forEach(label => { label.textContent = contextLabel(scope?.value || 'current'); });
        setTimeout(() => {
          window.dispatchEvent(new Event('resize'));
          panel.querySelector('[data-ai-input]')?.focus();
        }, 120);
      }
    };
    launcher.addEventListener('click', () => setOpen(!panel.classList.contains('open')));
    close?.addEventListener('click', () => setOpen(false));
    overlay?.addEventListener('click', () => setOpen(false));
    document.addEventListener('keydown', event => { if (event.key === 'Escape') setOpen(false); });
  }

  bindAssistant(document.getElementById('ogaAiFull'));
})();
