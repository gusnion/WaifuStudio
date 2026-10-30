// WaifuStudio — Librería de poses (esqueletos COCO-17) para OC Maker
// Qué hace: carga static/pose-skeletons.json (local), dibuja miniaturas de esqueleto en canvas,
//   busca por texto, filtra por sistema/clase/ángulo y permite seleccionar una pose.
// Qué no hace: no usa red externa ni PNGs, no edita el JSON y no envía la pose a ControlNet/generación:
//   solo emite el evento `waifu:pose-select` y expone getSelectedPose().
// Dependencias: static/js/dom.js (solo $ y on).

import { $, on } from "../dom.js";

const POSE_DATA_URL = "/static/pose-skeletons.json";
const POSE_API_URL = "/api/poses";
const POSE_TAGS_URL = "/api/poses/tags";
const POSE_STATUS_URL = "/api/poses/status";
const POSE_DOWNLOAD_URL = "/api/poses/download";
const POSE_PAGE_SIZE = 60;
const KP_MIN_CONF = 0.1;
const KP_DIM_CONF = 0.3;
const NO_DETECTION_TEXT = "sin detección";
const POSE_FILTERS = [
  { id: "pose-filter-sistema", field: "sistema_es", label: "Todos los sistemas" },
  { id: "pose-filter-clase", field: "clase_es", label: "Todas las clases" },
  { id: "pose-filter-angulo", field: "angulo_es", label: "Todos los ángulos" },
];

const poseState = {
  data: null,
  poses: [],
  filtered: [],
  visibleCount: POSE_PAGE_SIZE,
  pendingId: null,
  selected: null,
  loading: null,
  activeCaller: "oc",
  callerPoses: {},
  tags: { classes: {}, angles: {} },
  catalogInstalled: false,
  catalogState: "unknown",
  imagesBase: "",
};

let poseLibraryInitialized = false;
const callerCallbacks = new Map();

function registerPoseCallback(caller, callback) {
  if (typeof callback === "function") {
    callerCallbacks.set(caller, callback);
  }
}

function normalizeText(value) {
  return String(value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

function visibleKeypoints(pose) {
  if (!pose || !Array.isArray(pose.keypoints)) return [];
  return pose.keypoints.map((kp) =>
    Array.isArray(kp) && kp.length >= 3 && Number(kp[2]) >= KP_MIN_CONF
      ? { x: Number(kp[0]), y: Number(kp[1]), conf: Number(kp[2]) }
      : null,
  );
}

function hasDetection(pose) {
  return visibleKeypoints(pose).some(Boolean);
}

function poseTitle(pose) {
  return `${pose.clase_es || "Pose"} · ${pose.angulo_es || "—"}`;
}

function poseTags(pose) {
  if (!pose) return [];
  const tags = [];
  const add = (value) => {
    const text = String(value || "").trim();
    if (text && !tags.includes(text)) tags.push(text);
  };
  for (const tag of poseState.tags.classes[pose.clase_es] || []) add(tag);
  for (const tag of poseState.tags.angles[pose.angulo_es] || []) add(tag);
  return tags;
}




function filterPoses(poses, { text = "", sistema = "", clase = "", angulo = "", onlyDetected = false } = {}) {
  const tokens = normalizeText(text).split(/\s+/).filter(Boolean);
  return poses.filter((pose) => {
    if (sistema && pose.sistema_es !== sistema) return false;
    if (clase && pose.clase_es !== clase) return false;
    if (angulo && pose.angulo_es !== angulo) return false;
    if (onlyDetected && !hasDetection(pose)) return false;
    if (!tokens.length) return true;
    const haystack = normalizeText(
      `${pose.id} ${pose.sistema_es} ${pose.clase_es} ${pose.angulo_es}`,
    );
    return tokens.every((token) => haystack.includes(token));
  });
}

function uniqueSorted(poses, field) {
  return [...new Set(poses.map((pose) => pose[field]).filter(Boolean))].sort((a, b) =>
    a.localeCompare(b, "es"),
  );
}

function drawSkeleton(canvas, pose, bones) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return false;
  const dpr = window.devicePixelRatio || 1;
  const cssW = Number(canvas.dataset.cssWidth) || canvas.clientWidth || canvas.width;
  const cssH = Number(canvas.dataset.cssHeight) || canvas.clientHeight || canvas.height;
  canvas.width = Math.round(cssW * dpr);
  canvas.height = Math.round(cssH * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);
  ctx.fillStyle = "#0e0f13";
  ctx.fillRect(0, 0, cssW, cssH);
  const points = visibleKeypoints(pose);
  if (!points.some(Boolean)) return false;
  // keypoints normalizados 0..1 respecto a la imagen original (width x height).
  const to = (p) => ({ x: p.x * cssW, y: p.y * cssH });
  ctx.lineCap = "round";
  ctx.lineWidth = Math.max(1.5, cssW / 60);
  for (const [a, b] of bones) {
    const pa = points[a];
    const pb = points[b];
    if (!pa || !pb) continue;
    const A = to(pa);
    const B = to(pb);
    ctx.globalAlpha = Math.min(pa.conf, pb.conf) >= KP_DIM_CONF ? 0.95 : 0.4;
    ctx.strokeStyle = "#7dd3fc";
    ctx.beginPath();
    ctx.moveTo(A.x, A.y);
    ctx.lineTo(B.x, B.y);
    ctx.stroke();
  }
  const radius = Math.max(2, cssW / 45);
  points.forEach((p) => {
    if (!p) return;
    const P = to(p);
    ctx.globalAlpha = p.conf >= KP_DIM_CONF ? 1 : 0.5;
    ctx.fillStyle = "#f472b6";
    ctx.beginPath();
    ctx.arc(P.x, P.y, radius, 0, Math.PI * 2);
    ctx.fill();
  });
  ctx.globalAlpha = 1;
  return true;
}

function skeletonBones() {
  const bones = poseState.data?.skeleton;
  return Array.isArray(bones) ? bones : [];
}

function makeCanvas(pose, cssWidth) {
  const ratio = (Number(pose.height) || 1200) / (Number(pose.width) || 900);
  const canvas = document.createElement("canvas");
  canvas.className = "pose-canvas";
  canvas.dataset.cssWidth = String(cssWidth);
  canvas.dataset.cssHeight = String(Math.round(cssWidth * ratio));
  canvas.style.width = `${cssWidth}px`;
  canvas.style.height = `${Math.round(cssWidth * ratio)}px`;
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", `Esqueleto: ${poseTitle(pose)}`);
  return canvas;
}

function setPoseStatus(text, isError = false) {
  const el = $("pose-status");
  if (!el) return;
  el.textContent = text;
  el.classList.toggle("error", Boolean(isError));
}

function currentFilters() {
  return {
    text: $("pose-search")?.value || "",
    sistema: $("pose-filter-sistema")?.value || "",
    clase: $("pose-filter-clase")?.value || "",
    angulo: $("pose-filter-angulo")?.value || "",
    onlyDetected: Boolean($("pose-only-detected")?.checked),
  };
}

function makePosePhoto(pose, field, width, className = "pose-photo") {
  const relative = String(pose?.[field] || "").trim();
  if (!relative || !poseState.imagesBase) return null;
  const img = document.createElement("img");
  img.className = className;
  img.loading = "lazy";
  img.decoding = "async";
  img.src = `${poseState.imagesBase}${relative}`;
  img.alt = pose.nombre_ja || poseTitle(pose);
  img.style.width = `${width}px`;
  img.style.maxWidth = "100%";
  img.addEventListener("error", () => {
    const fallback = hasDetection(pose)
      ? makeCanvas(pose, width)
      : document.createElement("span");
    if (fallback.tagName === "CANVAS") {
      drawSkeleton(fallback, pose, skeletonBones());
    } else {
      fallback.className = "pose-card-fallback";
      fallback.textContent = `${pose.clase_es || "Pose"} · ${pose.angulo_es || "—"}`;
    }
    img.replaceWith(fallback);
  });
  return img;
}

function renderPoseCard(pose) {
  const detected = hasDetection(pose);
  const card = document.createElement("button");
  card.type = "button";
  card.className = "pose-card";
  card.dataset.poseId = pose.id;
  card.title = `${poseTitle(pose)} — ${pose.sistema_es || ""}${detected ? "" : " — ficha sin esqueleto"}`;
  card.classList.toggle("selected", poseState.pendingId === pose.id);
  card.addEventListener("click", () => selectPendingPose(pose.id));
  const photo = makePosePhoto(pose, "thumb", 96);
  if (photo) {
    card.appendChild(photo);
  } else if (detected) {
    const canvas = makeCanvas(pose, 96);
    card.appendChild(canvas);
    drawSkeleton(canvas, pose, skeletonBones());
  } else {
    card.classList.add("no-detection");
    const fallback = document.createElement("span");
    fallback.className = "pose-card-fallback";
    fallback.textContent = `${pose.clase_es || "Pose"} · ${pose.angulo_es || "—"}`;
    card.appendChild(fallback);
  }
  const label = document.createElement("span");
  label.className = "pose-card-label";
  label.textContent = poseTitle(pose);
  card.appendChild(label);
  const sub = document.createElement("span");
  sub.className = "pose-card-sub";
  sub.textContent = pose.nombre_ja || pose.sistema_es || (detected ? "" : "ficha sin esqueleto");
  card.appendChild(sub);
  return card;
}

function renderPoseGrid() {
  const grid = $("pose-grid");
  if (!grid) return;
  grid.replaceChildren();
  const shown = poseState.filtered.slice(0, poseState.visibleCount);
  shown.forEach((pose) => grid.appendChild(renderPoseCard(pose)));
  if (!poseState.filtered.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Ninguna pose coincide con los filtros.";
    grid.appendChild(empty);
  }
  const more = $("btn-pose-more");
  if (more) {
    more.classList.toggle("hidden", poseState.filtered.length <= shown.length);
  }
  setPoseStatus(
    `${shown.length} de ${poseState.filtered.length} poses mostradas (${poseState.poses.length} en la librería)`,
  );
}

function applyPoseFilters() {
  poseState.filtered = filterPoses(poseState.poses, currentFilters());
  poseState.visibleCount = POSE_PAGE_SIZE;
  renderPoseGrid();
}

function fillFilterSelect(id, label, values, selected = "") {
  const select = $(id);
  if (!select) return;
  select.replaceChildren();
  const all = document.createElement("option");
  all.value = "";
  all.textContent = label;
  select.appendChild(all);
  for (const value of values) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = value;
    select.appendChild(opt);
  }
  select.value = values.includes(selected) ? selected : "";
}

function refreshDependentFilters() {
  const sistema = $("pose-filter-sistema")?.value || "";
  const clase = $("pose-filter-clase")?.value || "";
  const claseValues = uniqueSorted(
    poseState.poses.filter((pose) => !sistema || pose.sistema_es === sistema),
    "clase_es",
  );
  fillFilterSelect("pose-filter-clase", "Todas las clases", claseValues, clase);
  const claseActual = $("pose-filter-clase")?.value || "";
  const angleValues = uniqueSorted(
    poseState.poses.filter(
      (pose) =>
        (!sistema || pose.sistema_es === sistema) &&
        (!claseActual || pose.clase_es === claseActual),
    ),
    "angulo_es",
  );
  fillFilterSelect("pose-filter-angulo", "Todos los ángulos", angleValues, $("pose-filter-angulo")?.value || "");
}

function populateFilters() {
  fillFilterSelect(
    "pose-filter-sistema",
    "Todos los sistemas",
    uniqueSorted(poseState.poses, "sistema_es"),
    $("pose-filter-sistema")?.value || "",
  );
  refreshDependentFilters();
}

function findPose(id) {
  return poseState.poses.find((pose) => pose.id === id) || null;
}

function renderPreview() {
  const box = $("pose-preview");
  const useBtn = $("btn-pose-use");
  if (!box) return;
  box.replaceChildren();
  const pose = findPose(poseState.pendingId);
  if (useBtn) useBtn.disabled = !pose;
  if (!pose) {
    const hint = document.createElement("p");
    hint.className = "oc-refs-note";
    hint.textContent = "Haz clic en una miniatura para previsualizarla.";
    box.appendChild(hint);
    return;
  }
  const photo = makePosePhoto(pose, "img", 150, "pose-photo pose-photo-preview");
  if (photo) {
    box.appendChild(photo);
  } else if (hasDetection(pose)) {
    const canvas = makeCanvas(pose, 150);
    box.appendChild(canvas);
    drawSkeleton(canvas, pose, skeletonBones());
  } else {
    const fallback = document.createElement("div");
    fallback.className = "pose-preview-fallback";
    fallback.textContent = `${pose.clase_es || "Pose"} · ${pose.angulo_es || "—"}`;
    box.appendChild(fallback);
  }
  const info = document.createElement("div");
  info.className = "pose-preview-info";
  const title = document.createElement("strong");
  title.textContent = poseTitle(pose);
  const meta = document.createElement("span");
  meta.textContent = pose.sistema_es || "";
  const id = document.createElement("code");
  id.textContent = pose.id;
  info.append(title, meta, id);
  box.appendChild(info);
}

function selectPendingPose(id) {
  poseState.pendingId = id;
  $("pose-grid")
    ?.querySelectorAll(".pose-card")
    .forEach((card) => card.classList.toggle("selected", card.dataset.poseId === id));
  renderPreview();
}

function updateSelectedIndicator() {
  const el = $("oc-pose-selected");
  if (!el) return;
  const pose = poseState.selected;
  el.textContent = pose ? `Pose: ${poseTitle(pose)} (${pose.id})` : "Pose: ninguna";
  el.title = pose ? pose.sistema_es || "" : "";
  const clear = $("btn-oc-pose-clear");
  if (clear) clear.classList.toggle("hidden", !pose);
}

function emitSelection(caller = null) {
  const pose = poseState.selected;
  const active = caller || poseState.activeCaller || "oc";
  window.dispatchEvent(
    new CustomEvent("waifu:pose-select", {
      detail: { pose: pose ? { ...pose } : null, caller: active },
    }),
  );
  window.dispatchEvent(
    new CustomEvent(`waifu:pose-select-${active}`, {
      detail: { pose: pose ? { ...pose } : null },
    }),
  );
}

function confirmPose() {
  const pose = findPose(poseState.pendingId);
  if (!pose) return;
  pose.tags = poseTags(pose);
  poseState.selected = pose;
  const caller = poseState.activeCaller || "oc";
  if (!poseState.callerPoses) {
    poseState.callerPoses = {};
  }
  poseState.callerPoses[caller] = pose;
  if (caller === "oc") {
    updateSelectedIndicator();
  }
  const cb = callerCallbacks.get(caller);
  if (typeof cb === "function") {
    cb(pose);
  }
  emitSelection(caller);
  closePoseLibrary();
}

function clearSelectedPose(caller = null) {
  const active = caller || poseState.activeCaller || "oc";
  poseState.selected = null;
  poseState.pendingId = null;
  if (poseState.callerPoses) {
    poseState.callerPoses[active] = null;
  }
  if (active === "oc") {
    updateSelectedIndicator();
  }
  emitSelection(active);
}

function getSelectedPose(caller = null) {
  if (caller && poseState.callerPoses?.[caller]) {
    return { ...poseState.callerPoses[caller] };
  }
  return poseState.selected ? { ...poseState.selected } : null;
}

function drawPoseSkeleton(canvas, pose) {
  return drawSkeleton(canvas, pose, skeletonBones());
}

function poseToDataUrl(pose, width = 512) {
  const pw = Number(pose?.width) || 900;
  const ph = Number(pose?.height) || 1200;
  const targetW = width;
  const targetH = Math.round(targetW * (ph / pw));
  const canvas = document.createElement("canvas");
  canvas.width = targetW;
  canvas.height = targetH;
  canvas.dataset.cssWidth = String(targetW);
  canvas.dataset.cssHeight = String(targetH);
  drawSkeleton(canvas, pose, skeletonBones());
  return canvas.toDataURL();
}

function ensurePoseDownload() {
  const modal = $("pose-modal");
  if (!modal) return;
  let hint = $("pose-empty-hint");
  if (!hint) {
    hint = document.createElement("p");
    hint.id = "pose-empty-hint";
    hint.className = "field-hint";
    const header = modal.querySelector(".modal-header");
    if (header) header.appendChild(hint);
  }
  let button = $("btn-pose-download");
  if (!button) {
    button = document.createElement("button");
    button.id = "btn-pose-download";
    button.type = "button";
    button.className = "secondary";
    button.textContent = "Descargar catálogo (505 KB)";
    button.addEventListener("click", () => {
      downloadPoseCatalog().catch((error) => setPoseStatus(error.message, true));
    });
    const header = modal.querySelector(".modal-header");
    if (header) header.appendChild(button);
  }
  const state = poseState.catalogState;
  const installed = state === "installed";
  const missing = state === "missing";
  const unavailable = state === "unavailable";
  button.classList.toggle("hidden", !missing);
  hint.classList.toggle("hidden", installed);
  hint.classList.toggle("error", unavailable);
  if (installed) {
    hint.textContent = "";
  } else if (unavailable) {
    hint.textContent = "La app no responde a la API de poses. Reinicia la app y vuelve a abrir esta ventana.";
  } else {
    hint.textContent = "Catálogo de poses no instalado (505 KB). Descárgalo para ver las 1.439 fichas.";
  }
}

async function downloadPoseCatalog() {
  setPoseStatus("Descargando catálogo de poses…");
  const response = await fetch(POSE_DOWNLOAD_URL, { method: "POST" });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || data.detail || `HTTP ${response.status}`);
  poseState.data = null;
  poseState.loading = null;
  await loadPoseLibrary();
  applyPoseFilters();
  setPoseStatus(`Catálogo instalado: ${poseState.poses.length} poses`);
}

function mergePoseCatalog(items) {
  if (!Array.isArray(items) || !items.length) return;
  const byId = new Map(poseState.poses.map((pose) => [pose.id, pose]));
  for (const item of items) {
    if (!item || !item.id) continue;
    const existing = byId.get(item.id);
    if (existing) {
      const keypoints = existing.keypoints;
      Object.assign(existing, item);
      existing._imagesBase = poseState.imagesBase;
      if (keypoints) existing.keypoints = keypoints;
    } else {
      item._imagesBase = poseState.imagesBase;
      byId.set(item.id, item);
    }
  }
  poseState.poses = [...byId.values()];
}

async function loadRemotePoses() {
  try {
    const statusResponse = await fetch(POSE_STATUS_URL, { cache: "no-store" });
    if (!statusResponse.ok) throw new Error(`HTTP ${statusResponse.status}`);
    const status = await statusResponse.json();
    poseState.catalogInstalled = Boolean(status.installed);
    poseState.catalogState = status.installed ? "installed" : "missing";
    poseState.imagesBase = String(status.images_base || "");
    ensurePoseDownload();
    if (!status.installed) return;
    const [indexResponse, tagsResponse] = await Promise.all([
      fetch(POSE_API_URL, { cache: "no-store" }),
      fetch(POSE_TAGS_URL, { cache: "no-store" }),
    ]);
    if (!indexResponse.ok) throw new Error(`No se pudo leer el índice de poses (HTTP ${indexResponse.status})`);
    const index = await indexResponse.json();
    mergePoseCatalog(index.items || []);
    if (tagsResponse.ok) {
      const tags = await tagsResponse.json();
      poseState.tags = {
        classes: tags.classes || {},
        angles: tags.angles || {},
      };
    }
    poseState.catalogInstalled = true;
    poseState.catalogState = "installed";
    ensurePoseDownload();
  } catch (_error) {
    poseState.catalogInstalled = false;
    poseState.catalogState = "unavailable";
    ensurePoseDownload();
  }
}


function loadPoseLibrary() {
  if (poseState.data) return Promise.resolve(poseState.data);
  if (!poseState.loading) {
    poseState.loading = fetch(POSE_DATA_URL, { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error(`No se pudo cargar la librería de poses (HTTP ${response.status})`);
        return response.json();
      })
      .then((data) => {
        if (!data || !Array.isArray(data.poses)) throw new Error("pose-skeletons.json inválido");
        poseState.data = data;
        poseState.poses = data.poses;
        populateFilters();
        applyPoseFilters();
        return loadRemotePoses().then(() => {
          populateFilters();
          applyPoseFilters();
          return data;
        });
      })
      .catch((error) => {
        poseState.loading = null;
        throw error;
      });
  }
  return poseState.loading;
}

function openPoseLibrary(callerOrEvent) {
  let caller = "oc";
  if (typeof callerOrEvent === "string") {
    caller = callerOrEvent;
  } else if (callerOrEvent && callerOrEvent.target && callerOrEvent.target.id) {
    const id = callerOrEvent.target.id;
    if (id === "btn-image-poses" || id === "btn-pose-open-image") caller = "image";
    else if (id === "btn-editor-poses") caller = "editor";
    else if (id === "btn-oc-poses") caller = "oc";
  } else {
    const panelEd = $("panel-editor");
    const panelImg = $("panel-image");
    if (panelEd && panelEd.classList.contains("active")) {
      caller = "editor";
    } else if (panelImg && panelImg.classList.contains("active")) {
      caller = "image";
    }
  }
  poseState.activeCaller = caller;

  const modal = $("pose-modal");
  if (!modal) {
    console.error("openPoseLibrary: falta #pose-modal (¿UI desactualizada? recarga con Ctrl+F5)");
    return;
  }
  modal.classList.remove("hidden");
  const current = getSelectedPose(caller);
  poseState.pendingId = current ? current.id : null;
  renderPreview();
  setPoseStatus("Cargando poses…");
  loadPoseLibrary()
    .then(() => applyPoseFilters())
    .catch((error) => {
      const grid = $("pose-grid");
      if (grid) grid.replaceChildren();
      setPoseStatus(error.message, true);
    });
}

function closePoseLibrary() {
  $("pose-modal")?.classList.add("hidden");
}

function initPoseLibrary() {
  if (poseLibraryInitialized) return;
  poseLibraryInitialized = true;

  on("btn-pose-close", "click", closePoseLibrary);
  on("btn-pose-use", "click", confirmPose);
  on("btn-pose-more", "click", () => {
    poseState.visibleCount += POSE_PAGE_SIZE;
    renderPoseGrid();
  });
  on("pose-modal", "click", (event) => {
    if (event.target === $("pose-modal")) closePoseLibrary();
  });
  let searchTimer = null;
  on("pose-search", "input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(applyPoseFilters, 200);
  });
  on("pose-filter-sistema", "change", () => {
    fillFilterSelect("pose-filter-clase", "Todas las clases", []);
    fillFilterSelect("pose-filter-angulo", "Todos los ángulos", []);
    refreshDependentFilters();
    applyPoseFilters();
  });
  on("pose-filter-clase", "change", () => {
    fillFilterSelect("pose-filter-angulo", "Todos los ángulos", []);
    refreshDependentFilters();
    applyPoseFilters();
  });
  on("pose-filter-angulo", "change", applyPoseFilters);
  on("pose-only-detected", "change", applyPoseFilters);
  on("btn-pose-reset", "click", () => {
    const search = $("pose-search");
    if (search) search.value = "";
    POSE_FILTERS.forEach(({ id }) => {
      const select = $(id);
      if (select) select.value = "";
    });
    const only = $("pose-only-detected");
    if (only) only.checked = false;
    populateFilters();
    applyPoseFilters();
  });
  on("btn-oc-pose-clear", "click", () => clearSelectedPose("oc"));
  updateSelectedIndicator();
}

export {
  normalizeText,
  filterPoses,
  hasDetection,
  drawSkeleton,
  drawPoseSkeleton,
  poseToDataUrl,
  registerPoseCallback,
  loadPoseLibrary,
  openPoseLibrary,
  closePoseLibrary,
  getSelectedPose,
  clearSelectedPose,
  initPoseLibrary,
};
