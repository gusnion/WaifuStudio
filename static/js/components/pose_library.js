// WaifuStudio — Librería de poses (esqueletos COCO-17) para OC Maker
// Qué hace: carga static/pose-skeletons.json (local), dibuja miniaturas de esqueleto en canvas,
//   busca por texto, filtra por sistema/clase/ángulo y permite seleccionar una pose.
// Qué no hace: no usa red externa ni PNGs, no edita el JSON y no envía la pose a ControlNet/generación:
//   solo emite el evento `waifu:pose-select` y expone getSelectedPose().
// Dependencias: static/js/dom.js (solo $ y on).

import { $, on } from "../dom.js";

const POSE_DATA_URL = "/static/pose-skeletons.json";
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
};

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

function renderPoseCard(pose) {
  const detected = hasDetection(pose);
  const card = document.createElement(detected ? "button" : "div");
  card.className = "pose-card";
  card.dataset.poseId = pose.id;
  if (detected) {
    card.type = "button";
    card.title = `${poseTitle(pose)} — ${pose.sistema_es}`;
    card.classList.toggle("selected", poseState.pendingId === pose.id);
    card.addEventListener("click", () => selectPendingPose(pose.id));
  } else {
    card.classList.add("no-detection");
    card.title = `${poseTitle(pose)} — ${NO_DETECTION_TEXT}`;
  }
  const canvas = makeCanvas(pose, 96);
  card.appendChild(canvas);
  drawSkeleton(canvas, pose, skeletonBones());
  const label = document.createElement("span");
  label.className = "pose-card-label";
  label.textContent = poseTitle(pose);
  card.appendChild(label);
  const sub = document.createElement("span");
  sub.className = "pose-card-sub";
  sub.textContent = detected ? pose.sistema_es || "" : NO_DETECTION_TEXT;
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

function populateFilters() {
  POSE_FILTERS.forEach(({ id, field, label }) => {
    const select = $(id);
    if (!select) return;
    select.replaceChildren();
    const all = document.createElement("option");
    all.value = "";
    all.textContent = label;
    select.appendChild(all);
    uniqueSorted(poseState.poses, field).forEach((value) => {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = value;
      select.appendChild(opt);
    });
  });
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
  const canvas = makeCanvas(pose, 150);
  box.appendChild(canvas);
  drawSkeleton(canvas, pose, skeletonBones());
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

function emitSelection() {
  const pose = poseState.selected;
  window.dispatchEvent(
    new CustomEvent("waifu:pose-select", { detail: { pose: pose ? { ...pose } : null } }),
  );
}

function confirmPose() {
  const pose = findPose(poseState.pendingId);
  if (!pose || !hasDetection(pose)) return;
  poseState.selected = pose;
  updateSelectedIndicator();
  emitSelection();
  closePoseLibrary();
}

function clearSelectedPose() {
  poseState.selected = null;
  poseState.pendingId = null;
  updateSelectedIndicator();
  emitSelection();
}

function getSelectedPose() {
  return poseState.selected ? { ...poseState.selected } : null;
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
        return data;
      })
      .catch((error) => {
        poseState.loading = null;
        throw error;
      });
  }
  return poseState.loading;
}

function openPoseLibrary() {
  const modal = $("pose-modal");
  if (!modal) {
    console.error("openPoseLibrary: falta #pose-modal (¿UI desactualizada? recarga con Ctrl+F5)");
    return;
  }
  modal.classList.remove("hidden");
  poseState.pendingId = poseState.selected ? poseState.selected.id : null;
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
  POSE_FILTERS.forEach(({ id }) => on(id, "change", applyPoseFilters));
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
    applyPoseFilters();
  });
  on("btn-oc-pose-clear", "click", clearSelectedPose);
  updateSelectedIndicator();
}

export {
  normalizeText,
  filterPoses,
  hasDetection,
  drawSkeleton,
  loadPoseLibrary,
  openPoseLibrary,
  closePoseLibrary,
  getSelectedPose,
  clearSelectedPose,
  initPoseLibrary,
};
