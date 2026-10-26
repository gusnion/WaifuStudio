const THEME_KEY = "waifu.theme";

function applyTheme(theme) {
  const value = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = value;
  const icon = document.getElementById("theme-toggle-icon");
  if (icon) icon.textContent = value === "light" ? "☀" : "◐";
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", value === "light" ? "#f6f7fb" : "#14151a");
}

export function initTheme() {
  const button = document.getElementById("btn-theme-toggle");
  if (!button) return;
  let theme = localStorage.getItem(THEME_KEY);
  if (theme !== "light" && theme !== "dark") theme = "dark";
  applyTheme(theme);
  button.addEventListener("click", () => {
    theme = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    localStorage.setItem(THEME_KEY, theme);
    applyTheme(theme);
  });
}
