(() => {
  'use strict';

  const shell = document.querySelector('.industry-shell');
  if (!shell) return;

  const textInput = shell.querySelector('input[type="search"][name="q"]');
  const proximityInput = shell.querySelector('input[type="search"][name="prox_valor"]');
  const proximitySelect = shell.querySelector('select[name="prox_criterio"]');
  const searchForms = shell.querySelectorAll('form.industry-search');

  let controller = null;
  let requestId = 0;

  const normalizeNumber = value => {
    const raw = String(value || '').trim().replace(',', '.');
    if (!raw) return null;
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : null;
  };

  const buildUrl = () => {
    const url = new URL(window.location.pathname, window.location.origin);
    const q = textInput ? textInput.value.trim() : '';
    const proxValue = proximityInput ? proximityInput.value.trim() : '';
    const proxField = proximitySelect ? proximitySelect.value.trim() : '';

    if (q) url.searchParams.set('q', q);

    // Solo enviamos proximidad cuando el valor escrito ya es numérico.
    // Esto evita parpadeos/errores mientras el usuario está a mitad de teclear.
    if (proxValue && proxField && normalizeNumber(proxValue) !== null) {
      url.searchParams.set('prox_criterio', proxField);
      url.searchParams.set('prox_valor', proxValue);
    }

    return url;
  };

  const swapFromDocument = (nextDoc, selector) => {
    const current = shell.querySelector(selector);
    const next = nextDoc.querySelector(selector);
    if (current && next) {
      current.replaceWith(next);
      return next;
    }
    if (current && !next) {
      current.remove();
      return null;
    }
    return null;
  };

  const syncPagination = nextDoc => {
    const current = shell.querySelector('.industry-pagination');
    const next = nextDoc.querySelector('.industry-pagination');

    if (current && next) {
      current.replaceWith(next);
      return;
    }
    if (current && !next) {
      current.remove();
      return;
    }
    if (!current && next) {
      const table = shell.querySelector('.industry-table-card');
      if (table) table.insertAdjacentElement('afterend', next);
    }
  };

  const refreshResults = async () => {
    // En CS permitimos borrar el valor de proximidad para restaurar todo,
    // pero evitamos consultar mientras exista un texto numérico incompleto.
    if (proximityInput) {
      const raw = proximityInput.value.trim();
      if (raw && normalizeNumber(raw) === null) return;
    }

    const url = buildUrl();
    const thisRequest = ++requestId;

    if (controller) controller.abort();
    controller = new AbortController();

    shell.classList.add('industry-searching');
    shell.setAttribute('aria-busy', 'true');

    try {
      const response = await fetch(url.toString(), {
        method: 'GET',
        headers: {
          'Accept': 'text/html',
          'X-Requested-With': 'XMLHttpRequest'
        },
        cache: 'no-store',
        signal: controller.signal
      });

      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const html = await response.text();
      if (thisRequest !== requestId) return;

      const nextDoc = new DOMParser().parseFromString(html, 'text/html');
      const nextTable = nextDoc.querySelector('.industry-table-card');
      if (!nextTable) throw new Error('La respuesta no contiene la tabla de Industria.');

      swapFromDocument(nextDoc, '.industry-table-card');

      const currentCounter = shell.querySelector('.industry-counter');
      const nextCounter = nextDoc.querySelector('.industry-counter');
      if (currentCounter && nextCounter) currentCounter.innerHTML = nextCounter.innerHTML;

      syncPagination(nextDoc);

      // Mantiene una URL limpia/compartible sin crear un historial por tecla.
      window.history.replaceState({}, '', `${url.pathname}${url.search}`);
      document.dispatchEvent(new CustomEvent('industria:results-updated'));
    } catch (error) {
      if (error && error.name === 'AbortError') return;
      console.error('No fue posible actualizar la búsqueda de Industria:', error);
    } finally {
      if (thisRequest === requestId) {
        shell.classList.remove('industry-searching');
        shell.removeAttribute('aria-busy');
      }
    }
  };

  // Se dispara en cada carácter. La petición anterior se cancela automáticamente
  // si el usuario sigue escribiendo, por lo que siempre gana el valor más reciente.
  if (textInput) textInput.addEventListener('input', refreshResults);
  if (proximityInput) proximityInput.addEventListener('input', refreshResults);
  if (proximitySelect) proximitySelect.addEventListener('change', refreshResults);

  searchForms.forEach(form => {
    form.addEventListener('submit', event => {
      event.preventDefault();
      refreshResults();
    });
  });
})();
