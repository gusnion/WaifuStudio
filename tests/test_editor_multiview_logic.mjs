import assert from "node:assert/strict";
import { multiviewPrompts } from "../static/js/components/editor_multiview.js";

console.log("--- Tests de prompts de multivista ---");

for (const count of [4, 6, 8]) {
  const prompts = multiviewPrompts("hero, blue coat", count);
  assert.equal(prompts.length, count);
  assert.ok(prompts.every((prompt) => prompt.includes("hero, blue coat")));
  assert.ok(prompts.some((prompt) => prompt.includes("front view")));
  assert.ok(prompts.some((prompt) => prompt.includes("back view")));
  console.log(`✔ ${count} vistas con prompt base y nombres`);
}

const defaults = multiviewPrompts("", 8);
assert.equal(defaults.length, 8);
assert.ok(defaults[0].includes("character turnaround"));
console.log("✔ prompt vacío usa el fallback de turnaround");

console.log("=== TESTS DE MULTIVISTA OK ===");
