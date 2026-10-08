// WaifuStudio — Sistema Universal de Ayuda Contextual (?) con Tooltips Flotantes (M18-05)
// Qué hace: renderiza popovers informativos al interactuar con .btn-help o elementos con data-help.
// Qué no hace: no almacena estado persistente.

let activeTooltipEl = null;

export function showTooltip(target, text) {
  hideTooltip();
  if (!text) return;

  const tooltip = document.createElement("div");
  tooltip.className = "tooltip-popover";
  tooltip.setAttribute("role", "tooltip");
  tooltip.textContent = text;
  document.body.appendChild(tooltip);
  activeTooltipEl = tooltip;

  const targetRect = target.getBoundingClientRect();
  const tipRect = tooltip.getBoundingClientRect();

  // Posicionar centrado encima o debajo según espacio
  let top = targetRect.top - tipRect.height - 8;
  if (top < 10) {
    top = targetRect.bottom + 8;
  }
  let left = targetRect.left + (targetRect.width / 2) - (tipRect.width / 2);
  if (left < 10) left = 10;
  if (left + tipRect.width > window.innerWidth - 10) {
    left = window.innerWidth - tipRect.width - 10;
  }

  tooltip.style.top = `${Math.round(top)}px`;
  tooltip.style.left = `${Math.round(left)}px`;
  requestAnimationFrame(() => {
    if (activeTooltipEl === tooltip) {
      tooltip.classList.add("visible");
    }
  });
}

export function hideTooltip() {
  if (activeTooltipEl) {
    activeTooltipEl.remove();
    activeTooltipEl = null;
  }
}

export function initTooltipHelp(root = document) {
  const helpButtons = root.querySelectorAll(".btn-help, [data-help]");
  helpButtons.forEach((btn) => {
    const text = btn.dataset.help || btn.getAttribute("title");
    if (!text) return;
    if (btn.getAttribute("title")) {
      btn.dataset.help = text;
      btn.removeAttribute("title");
    }

    btn.addEventListener("mouseenter", () => showTooltip(btn, btn.dataset.help));
    btn.addEventListener("mouseleave", () => hideTooltip());
    btn.addEventListener("focus", () => showTooltip(btn, btn.dataset.help));
    btn.addEventListener("blur", () => hideTooltip());
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (activeTooltipEl) {
        hideTooltip();
      } else {
        showTooltip(btn, btn.dataset.help);
      }
    });
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".btn-help, [data-help]")) {
      hideTooltip();
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      hideTooltip();
    }
  });
  window.addEventListener("scroll", hideTooltip, true);
  window.addEventListener("resize", hideTooltip);
}
