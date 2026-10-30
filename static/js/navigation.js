// Navegación sin importar main.js (evita el ciclo de módulos y la doble inicialización).
export function switchTab(tab) {
  if (!tab) return;
  window.dispatchEvent(new CustomEvent("waifu:switch-tab", { detail: { tab } }));
}
