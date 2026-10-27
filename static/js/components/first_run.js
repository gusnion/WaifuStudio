const DISMISS_KEY = "waifu.first_run.dismissed";
const RETRY_MS = 5000;
const MAX_ATTEMPTS = 12;
let attempt = 0;
let timer = null;

function renderFirstRun(data) {
  const box = document.getElementById("first-run-banner");
  if (!box) return;
  if (data.ready || sessionStorage.getItem(DISMISS_KEY) === "1") {
    box.classList.add("hidden");
    return;
  }
  box.replaceChildren();
  const title = document.createElement("strong");
  title.textContent = "First-run check: missing setup";
  const intro = document.createElement("span");
  intro.textContent = " Resolve these items before the first image:";
  const list = document.createElement("ul");
  for (const item of data.items || []) {
    if (item.ok || !item.required) continue;
    const li = document.createElement("li");
    li.textContent = `${item.label}: ${item.detail}`;
    list.appendChild(li);
  }
  const dismiss = document.createElement("button");
  dismiss.type = "button";
  dismiss.textContent = "Dismiss";
  dismiss.addEventListener("click", () => {
    sessionStorage.setItem(DISMISS_KEY, "1");
    box.classList.add("hidden");
  });
  box.append(title, intro, list, dismiss);
  box.classList.remove("hidden");
}

export async function initFirstRun() {
  if (sessionStorage.getItem(DISMISS_KEY) === "1") return;
  attempt = 0;
  const probe = async () => {
    try {
      const response = await fetch("/api/first-run", { cache: "no-store" });
      if (!response.ok) return;
      const data = await response.json();
      if (data.ready) {
        renderFirstRun(data);
        return;
      }
      if (attempt < MAX_ATTEMPTS) {
        attempt += 1;
        timer = setTimeout(probe, RETRY_MS);
        return;
      }
      renderFirstRun(data);
    } catch {
      if (attempt < MAX_ATTEMPTS) {
        attempt += 1;
        timer = setTimeout(probe, RETRY_MS);
      }
      // El chequeo es informativo; no bloquea el arranque.
    }
  };
  timer = setTimeout(probe, 2000);
}

export function stopFirstRunTimer() {
  if (timer) clearTimeout(timer);
  timer = null;
}
