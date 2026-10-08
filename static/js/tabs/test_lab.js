// WaifuStudio — Controlador del Laboratorio Sandbox TEST (M18-03, M18-08)
// Qué hace: monta casos interactivos para validar los 18 requisitos de UI/UX sin afectar producción.
// Qué no hace: no despacha tareas reales de GPU.

import { $ } from "../dom.js";
import { UniversalViewer } from "../components/universal_viewer.js";
import { ResolutionKit } from "../components/resolution_kit.js";
import { initTooltipHelp } from "../components/tooltip_help.js";

let testViewerInstance = null;
let testResolutionKit = null;

// Generadores de imágenes de prueba SVG en memoria
function makeSampleSvg(title, color1, color2, detail = "") {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600" viewBox="0 0 800 600">
    <defs>
      <linearGradient id="grad" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="${color1}" />
        <stop offset="100%" stop-color="${color2}" />
      </linearGradient>
    </defs>
    <rect width="800" height="600" fill="url(#grad)" />
    <circle cx="400" cy="300" r="180" fill="rgba(255,255,255,0.15)" stroke="#fff" stroke-width="4" />
    <text x="400" y="290" font-family="system-ui, sans-serif" font-size="34" font-weight="bold" fill="#ffffff" text-anchor="middle">${title}</text>
    <text x="400" y="340" font-family="system-ui, sans-serif" font-size="20" fill="rgba(255,255,255,0.8)" text-anchor="middle">${detail}</text>
    <rect x="50" y="50" width="700" height="500" fill="none" stroke="rgba(255,255,255,0.3)" stroke-dasharray="8 8" />
  </svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

export function initTestLab() {
  const panel = $("panel-test");
  if (!panel) return;

  // 1. Selector Dual (ResolutionKit)
  const orientSelect = $("test-res-orientation");
  const qualSelect = $("test-res-quality");
  const badgeEl = $("test-res-badge");

  if (orientSelect && qualSelect) {
    testResolutionKit = new ResolutionKit({
      orientationSelect: orientSelect,
      qualitySelect: qualSelect,
      badgeEl: badgeEl,
    });
  }

  // 2. Tooltips y Ayuda (?)
  initTooltipHelp(panel);

  // 3. Visor Universal
  const viewerContainer = $("test-viewer-container");
  if (viewerContainer && !testViewerInstance) {
    testViewerInstance = new UniversalViewer({
      container: viewerContainer,
      features: ["zoom", "compare", "describe", "thumbnails", "download"],
      onDescribe: () => {
        alert("UniversalViewer: Describir ejecutado correctamente en Sandbox.");
      },
      onDownload: () => {
        alert("UniversalViewer: Descargar ejecutado correctamente en Sandbox.");
      },
    });

    // Muestras iniciales
    const imgBefore = makeSampleSvg("ORIGINAL (ANTES)", "#1e3c72", "#2a5298", "Detalle SD · Entrada limpia");
    const imgAfter = makeSampleSvg("PROCESADO (DESPUÉS)", "#e0567a", "#7a5cff", "Detalle 2K · Upscale & Edición");

    testViewerInstance.setMedia({
      type: "image",
      url: imgAfter,
      alt: "Imagen de Prueba Sandbox",
    });

    testViewerInstance.setCompareUrls(imgBefore, imgAfter);

    // Miniaturas iniciales con diferentes colores
    const initialThumbs = [
      { url: imgAfter, title: "Muestra 1 (Procesada)" },
      { url: imgBefore, title: "Muestra 2 (Original)" },
      { url: makeSampleSvg("MUESTRA 3", "#11998e", "#38ef7d", "Anima v4"), title: "Muestra 3" },
      { url: makeSampleSvg("MUESTRA 4", "#ff416c", "#ff4b2b", "H3 Render"), title: "Muestra 4" },
      { url: makeSampleSvg("MUESTRA 5", "#8a2387", "#e94057", "Editor UC"), title: "Muestra 5" },
    ];

    testViewerInstance.setThumbnails(initialThumbs, (item) => {
      testViewerInstance.setMedia({ type: "image", url: item.url, alt: item.title });
    });
  }

  // 4. Botones de interacción del sandbox
  const btnTestZoom = $("btn-test-zoom");
  if (btnTestZoom && testViewerInstance) {
    btnTestZoom.addEventListener("click", () => {
      testViewerInstance.scale = testViewerInstance.scale === 1 ? 2.5 : 1;
      testViewerInstance.applyTransform();
    });
  }

  const btnTestCompare = $("btn-test-compare");
  if (btnTestCompare && testViewerInstance) {
    btnTestCompare.addEventListener("click", () => {
      testViewerInstance.setCompareActive(!testViewerInstance.compareActive);
    });
  }

  const btnTestAddThumbs = $("btn-test-add-thumbs");
  if (btnTestAddThumbs && testViewerInstance) {
    btnTestAddThumbs.addEventListener("click", () => {
      const colors = [
        ["#2193b0", "#6dd5ed"],
        ["#ee9ca7", "#ffdde1"],
        ["#b92b27", "#1565c0"],
        ["#373b44", "#4286f4"],
      ];
      const newItems = colors.map(([c1, c2], idx) => ({
        url: makeSampleSvg(`DINÁMICO ${idx + 6}`, c1, c2, "ResizeObserver test"),
        title: `Dinámico ${idx + 6}`,
      }));
      const combined = [...testViewerInstance.thumbnails, ...newItems];
      testViewerInstance.setThumbnails(combined, (item) => {
        testViewerInstance.setMedia({ type: "image", url: item.url, alt: item.title });
      });
    });
  }

  // Escuchar recarga universal
  window.addEventListener("waifu:test-reload", () => {
    const statusEl = $("test-sandbox-status");
    if (statusEl) {
      statusEl.textContent = "¡Recarga universal recibida! Todo listo.";
      statusEl.style.color = "var(--accent)";
      setTimeout(() => {
        statusEl.textContent = "Laboratorio listo";
        statusEl.style.color = "";
      }, 2000);
    }
  });
}
