(() => {
  const search = document.getElementById('trainingSearch');
  const grid = document.getElementById('trainingGrid');
  if (search && grid) {
    search.addEventListener('input', () => {
      const q = search.value.trim().toLowerCase();
      grid.querySelectorAll('.training-video-card').forEach(card => {
        card.hidden = q && !String(card.dataset.search || '').includes(q);
      });
    });
  }

  const player = document.getElementById('trainingPlayer');
  if (player) {
    const hlsUrl = player.dataset.hls;
    const mp4Url = player.dataset.mp4;
    // Safari/iOS y algunos navegadores reproducen HLS de forma nativa.
    // En Chrome/Edge de escritorio usamos el MP4 con HTTP Range, que también
    // inicia de forma progresiva sin descargar el archivo completo.
    if (hlsUrl && player.canPlayType('application/vnd.apple.mpegurl')) {
      player.src = hlsUrl;
    } else if (window.Hls && window.Hls.isSupported && hlsUrl) {
      const hls = new window.Hls({ maxBufferLength: 30, backBufferLength: 30 });
      hls.loadSource(hlsUrl);
      hls.attachMedia(player);
    } else if (mp4Url) {
      player.src = mp4Url;
    }
  }

  const processing = document.querySelector('.training-processing[data-video-id]');
  if (processing) {
    const id = processing.dataset.videoId;
    const bar = processing.querySelector('.training-progress i');
    const number = processing.querySelector('.training-progress-number');
    let stopped = false;
    const poll = async () => {
      if (stopped || document.hidden) return;
      try {
        const response = await fetch(`/capacitaciones/api/${encodeURIComponent(id)}/estado`, {
          headers: { 'Accept': 'application/json' },
          cache: 'no-store'
        });
        if (!response.ok) return;
        const data = await response.json();
        if (bar) bar.style.width = `${data.progreso || 0}%`;
        if (number) number.textContent = `${data.progreso || 0}%`;
        if (data.listo || data.estado === 'ERROR') {
          stopped = true;
          window.location.reload();
        }
      } catch (_) {}
    };
    const timer = window.setInterval(poll, 2500);
    window.addEventListener('beforeunload', () => window.clearInterval(timer));
    document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
    poll();
  }
})();
