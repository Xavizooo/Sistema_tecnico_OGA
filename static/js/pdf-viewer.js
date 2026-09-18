// Visor de PDF con pdf.js (renderizado en <canvas>, con navegacion de hojas y zoom).
// Expone funciones globales para que planos.js (script clasico) las use.
import * as pdfjsLib from 'https://cdn.jsdelivr.net/npm/pdfjs-dist@4.10.38/build/pdf.mjs';

pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdn.jsdelivr.net/npm/pdfjs-dist@4.10.38/build/pdf.worker.min.mjs';

const viewers = {}; // containerId -> { pdf, pageNum, scale, canvas }

async function renderPage(containerId) {
  const state = viewers[containerId];
  if (!state) return;
  const page = await state.pdf.getPage(state.pageNum);
  const viewport = page.getViewport({ scale: state.scale });
  const canvas = state.canvas;
  const ctx = canvas.getContext('2d');
  const outputScale = window.devicePixelRatio || 1;
  canvas.width = Math.floor(viewport.width * outputScale);
  canvas.height = Math.floor(viewport.height * outputScale);
  canvas.style.width = Math.floor(viewport.width) + 'px';
  canvas.style.height = Math.floor(viewport.height) + 'px';
  const transform = outputScale !== 1 ? [outputScale, 0, 0, outputScale, 0, 0] : null;
  await page.render({ canvasContext: ctx, transform: transform, viewport: viewport }).promise;
  const label = document.getElementById(containerId + 'PageLabel');
  if (label) label.textContent = 'Hoja ' + state.pageNum + ' de ' + state.pdf.numPages;
}

async function renderPdfPreview(fileOrArrayBuffer, containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = '<canvas class="pdf-canvas"></canvas>';
  const canvas = container.querySelector('canvas');
  let src;
  if (fileOrArrayBuffer instanceof File) {
    src = await fileOrArrayBuffer.arrayBuffer();
  } else {
    src = fileOrArrayBuffer;
  }
  const loadingTask = pdfjsLib.getDocument(src);
  const pdf = await loadingTask.promise;
  viewers[containerId] = { pdf: pdf, pageNum: 1, scale: 1.15, canvas: canvas };
  await renderPage(containerId);
}

function pdfNextPage(containerId) {
  const state = viewers[containerId];
  if (!state) return;
  if (state.pageNum < state.pdf.numPages) { state.pageNum++; renderPage(containerId); }
}

function pdfPrevPage(containerId) {
  const state = viewers[containerId];
  if (!state) return;
  if (state.pageNum > 1) { state.pageNum--; renderPage(containerId); }
}

function pdfZoom(containerId, delta) {
  const state = viewers[containerId];
  if (!state) return;
  state.scale = Math.min(3, Math.max(0.5, state.scale + delta));
  renderPage(containerId);
}

function pdfViewerReady() {
  return true;
}

window.renderPdfPreview = renderPdfPreview;
window.pdfNextPage = pdfNextPage;
window.pdfPrevPage = pdfPrevPage;
window.pdfZoom = pdfZoom;
window.pdfViewerReady = pdfViewerReady;
