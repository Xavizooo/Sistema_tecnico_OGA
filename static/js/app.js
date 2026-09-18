function openArchiveModal() {
  const modal = document.getElementById('archiveModal');
  if (modal) modal.classList.remove('hidden');
}

function closeArchiveModal() {
  const modal = document.getElementById('archiveModal');
  if (modal) modal.classList.add('hidden');
}

function securityToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.content : '';
}

function protectForms() {
  const token = securityToken();
  if (!token) return;
  document.querySelectorAll('form').forEach(form => {
    const method = (form.getAttribute('method') || 'get').toLowerCase();
    if (method === 'get' || form.querySelector('input[name="_csrf_token"]')) return;
    const input = document.createElement('input');
    input.type = 'hidden';
    input.name = '_csrf_token';
    input.value = token;
    form.appendChild(input);
  });
}

const originalFetch = window.fetch.bind(window);
window.fetch = function(input, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const headers = new Headers(options.headers || {});
    headers.set('X-CSRF-Token', securityToken());
    options = { ...options, headers, credentials: options.credentials || 'same-origin' };
  }
  return originalFetch(input, options);
};

function requestAutoSave(useBeacon = false) {
  const url = '/autosave/checkpoint';
  if (useBeacon && navigator.sendBeacon) {
    const data = new FormData();
    data.append('_csrf_token', securityToken());
    try {
      if (navigator.sendBeacon(url, data)) return;
    } catch (_) { /* Fall back to fetch if the browser rejects the beacon. */ }
  }
  fetch(url, { method: 'POST', credentials: 'same-origin', keepalive: true }).catch(() => {});
}

document.addEventListener('keydown', event => {
  if (event.key === 'Escape') closeArchiveModal();
});

protectForms();

// El servidor evita crear duplicados cuando el trabajo no ha cambiado.
window.setInterval(() => requestAutoSave(false), 3 * 60 * 1000);

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') requestAutoSave(true);
});

// REV 14 · controles exclusivamente visuales de la nueva interfaz.
(function () {
  const body = document.body;
  const sidebar = document.getElementById('appSidebar');
  const toggle = document.getElementById('sidebarToggle');
  const overlay = document.getElementById('sidebarOverlay');
  if (!sidebar || !toggle) return;

  const storageKey = 'oga-sidebar-collapsed';
  const desktop = () => window.matchMedia('(min-width: 961px)').matches;

  function storedSidebarState() {
    try { return localStorage.getItem(storageKey) === '1'; } catch (_) { return false; }
  }

  function syncStoredState() {
    if (desktop()) {
      body.classList.toggle('sidebar-collapsed', storedSidebarState());
      body.classList.remove('sidebar-mobile-open');
    } else {
      body.classList.remove('sidebar-collapsed');
    }
  }

  toggle.addEventListener('click', function () {
    if (desktop()) {
      const collapsed = body.classList.toggle('sidebar-collapsed');
      try { localStorage.setItem(storageKey, collapsed ? '1' : '0'); } catch (_) { /* Storage can be blocked by the browser. */ }
    } else {
      body.classList.toggle('sidebar-mobile-open');
    }
  });

  if (overlay) overlay.addEventListener('click', () => body.classList.remove('sidebar-mobile-open'));
  window.addEventListener('resize', syncStoredState);
  syncStoredState();

  document.querySelectorAll('.side-nav-group').forEach(group => {
    group.addEventListener('toggle', () => {
      if (!group.open) return;
      document.querySelectorAll('.side-nav-group').forEach(other => {
        if (other !== group && other.open && !other.querySelector('.active')) other.open = false;
      });
    });
  });
})();
