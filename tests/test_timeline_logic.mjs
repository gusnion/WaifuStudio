import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { applyFirstClipProfile, clipDurationForItem } from "../static/js/tabs/timeline.js";

console.log("--- Iniciando tests de lógica de Timeline (Node) ---");

// Test 1: Video con item.params.seconds usa ese valor
{
  const item = { kind: "video", params: { seconds: 8 } };
  const dur = clipDurationForItem(item);
  assert.equal(dur, 8, "Debe usar seconds de params cuando es > 0");
  console.log("✔ Test 1: Video con params.seconds usa seconds");
}

// Test 2: Video con item.params.duration usa duration si seconds falta o es <= 0
{
  const item1 = { kind: "video", params: { duration: 10 } };
  assert.equal(clipDurationForItem(item1), 10, "Debe usar duration si seconds falta");

  const item2 = { kind: "video", params: { seconds: 0, duration: 6.5 } };
  assert.equal(clipDurationForItem(item2), 6.5, "Debe usar duration si seconds <= 0");
  console.log("✔ Test 2: Video con params.duration como segundo recurso");
}

// Test 3: Video sin params usa metadataDuration cuando está disponible
{
  const item = { kind: "video" };
  const dur1 = clipDurationForItem(item, 7.42);
  assert.equal(dur1, 7.4, "Debe redondear metadataDuration a 1 decimal");

  const dur2 = clipDurationForItem(item, "8.6");
  assert.equal(dur2, 8.6, "Debe aceptar metadataDuration como número o cadena numérica");
  console.log("✔ Test 3: Video usa metadataDuration si params no están disponibles");
}

// Test 4: Video sin params ni metadataDuration usa fallback 5.0
{
  const item1 = { kind: "video", params: {} };
  assert.equal(clipDurationForItem(item1), 5.0, "Fallback debe ser 5.0 cuando no hay metadato");

  const item2 = { kind: "video", params: { seconds: -1, duration: 0 } };
  assert.equal(clipDurationForItem(item2, null), 5.0, "Fallback debe ser 5.0 si valores son inválidos");

  assert.equal(clipDurationForItem(item2, 0), 5.0, "Fallback debe ser 5.0 si metadataDuration es 0");
  console.log("✔ Test 4: Fallback 5.0 en video sin metadatos");
}

// Test 5: Clips de imagen tienen duración por defecto 3.0 o params.duration
{
  const itemImgDefault = { kind: "image" };
  assert.equal(clipDurationForItem(itemImgDefault), 3.0, "Imagen por defecto debe ser 3.0s");

  const itemImgCustom = { kind: "image", params: { duration: 4.5 } };
  assert.equal(clipDurationForItem(itemImgCustom), 4.5, "Imagen con params.duration debe respetarlo");
  console.log("✔ Test 5: Clips de imagen respetan 3.0s y params.duration");
}

// Test 6: Verificación de contrato en templates/index.html (BUG-TIMELINE-03)
{
  const htmlPath = path.resolve("templates/index.html");
  const htmlContent = fs.readFileSync(htmlPath, "utf-8");
  assert.ok(
    htmlContent.includes('id="timeline-preview-video"'),
    "index.html debe contener el elemento video de preview"
  );
  assert.ok(
    htmlContent.includes('id="timeline-preview-image"'),
    "index.html debe contener el elemento img de preview"
  );
  console.log("✔ Test 6: templates/index.html incluye video e img para preview de timeline");
}

// Test 7: Verificación de contrato en static/css/tabs/timeline.css
{
  const cssPath = path.resolve("static/css/tabs/timeline.css");
  const cssContent = fs.readFileSync(cssPath, "utf-8");
  assert.ok(
    cssContent.includes("#timeline-preview-video") && cssContent.includes("#timeline-preview-image"),
    "timeline.css debe aplicar estilos tanto a video como a img de preview"
  );
  console.log("✔ Test 7: static/css/tabs/timeline.css incluye estilos para #timeline-preview-image");
}

// Test 8: el primer clip define el lienzo del proyecto (BUG-TIMELINE-11)
{
  const project = { width: 1280, height: 720, fps: 24 };
  assert.equal(
    applyFirstClipProfile(project, { kind: "video", params: { width: 432, height: 768, fps: 16 } }),
    true
  );
  assert.deepEqual(project, { width: 432, height: 768, fps: 16 });
  const project2 = { width: 1280, height: 720, fps: 24 };
  applyFirstClipProfile(project2, { kind: "video", params: { aspect: "vertical" } });
  assert.deepEqual(project2, { width: 432, height: 768, fps: 24 });
  console.log("✔ Test 8: el primer clip define ancho, alto y fps del proyecto");
}

console.log("=== TODOS LOS TESTS DE TIMELINE LOGIC PASARON EXITOSAMENTE ===");
