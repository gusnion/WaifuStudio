// WaifuStudio — UniversalViewer: Visor Modular Unificado (M18-06)
// Qué hace: zoom 8x + drag pan, split slider compare, barra de herramientas y miniaturas dinámicas sin hueco negro.
// Qué no hace: no interactúa directamente con APIs del backend salvo a través de callbacks.

export class UniversalViewer {
  constructor(options = {}) {
    this.container = typeof options.container === "string" 
      ? document.querySelector(options.container) 
      : options.container;
    
    if (!this.container) {
      console.warn("UniversalViewer: container not found", options.container);
      return;
    }

    this.features = new Set(options.features || ["zoom", "thumbnails"]);
    this.callbacks = {
      onDescribe: options.onDescribe || null,
      onDownload: options.onDownload || null,
      onCompareToggle: options.onCompareToggle || null,
      onPagePrev: options.onPagePrev || null,
      onPageNext: options.onPageNext || null,
      onThumbSelect: options.onThumbSelect || null,
    };

    this.scale = 1;
    this.panX = 0;
    this.panY = 0;
    this.isPanning = false;
    this.panStart = { x: 0, y: 0 };

    this.compareActive = Boolean(options.compare);
    this.compareRatio = 0.5;
    this.compareDragging = false;
    this.beforeUrl = options.beforeUrl || "";
    this.afterUrl = options.afterUrl || "";

    this.currentMedia = { type: "image", url: "", alt: "" };
    this.thumbnails = [];
    this.selectedThumbIndex = -1;

    this.buildDOM();
    this.bindEvents();
  }

  buildDOM() {
    this.container.classList.add("universal-viewer");
    this.container.innerHTML = `
      <div class="uv-stage-wrap">
        <div class="uv-stage">
          <img class="uv-img hidden" alt="" draggable="false">
          <video class="uv-video hidden" controls preload="metadata"></video>
          <div class="uv-compare hidden">
            <div class="uv-compare-stage">
              <img class="uv-compare-before" alt="Antes" draggable="false">
              <img class="uv-compare-after" alt="Después" draggable="false">
            </div>
            <div class="uv-compare-handle" role="slider" tabindex="0" aria-label="Comparador" aria-valuemin="0" aria-valuemax="100" aria-valuenow="50">
              <span class="uv-compare-ratio">50%</span>
            </div>
          </div>
          <span class="uv-empty">Sin elemento seleccionado</span>
        </div>
      </div>
      <div class="uv-toolbar viewer-toolbar"></div>
      <div class="uv-thumbs image-thumbs"></div>
    `;

    this.stageWrap = this.container.querySelector(".uv-stage-wrap");
    this.stage = this.container.querySelector(".uv-stage");
    this.imgEl = this.container.querySelector(".uv-img");
    this.videoEl = this.container.querySelector(".uv-video");
    this.compareEl = this.container.querySelector(".uv-compare");
    this.compareBefore = this.container.querySelector(".uv-compare-before");
    this.compareAfter = this.container.querySelector(".uv-compare-after");
    this.compareHandle = this.container.querySelector(".uv-compare-handle");
    this.compareRatioEl = this.container.querySelector(".uv-compare-ratio");
    this.emptyEl = this.container.querySelector(".uv-empty");
    this.toolbar = this.container.querySelector(".uv-toolbar");
    this.thumbsEl = this.container.querySelector(".uv-thumbs");

    this.renderToolbar();
  }

  renderToolbar() {
    this.toolbar.innerHTML = "";

    if (this.features.has("zoom")) {
      const btnResetZoom = document.createElement("button");
      btnResetZoom.type = "button";
      btnResetZoom.textContent = "1:1";
      btnResetZoom.title = "Restablecer zoom (o doble clic)";
      btnResetZoom.addEventListener("click", () => this.resetZoom());
      this.toolbar.appendChild(btnResetZoom);
    }

    if (this.features.has("compare")) {
      const btnCompare = document.createElement("button");
      btnCompare.type = "button";
      btnCompare.textContent = "Comparar";
      btnCompare.setAttribute("aria-pressed", String(this.compareActive));
      btnCompare.addEventListener("click", () => {
        this.setCompareActive(!this.compareActive);
        btnCompare.setAttribute("aria-pressed", String(this.compareActive));
        btnCompare.textContent = this.compareActive ? "Cerrar comparación" : "Comparar";
        if (this.callbacks.onCompareToggle) {
          this.callbacks.onCompareToggle(this.compareActive);
        }
      });
      this.btnCompare = btnCompare;
      this.toolbar.appendChild(btnCompare);
    }

    if (this.features.has("describe")) {
      const btnDescribe = document.createElement("button");
      btnDescribe.type = "button";
      btnDescribe.textContent = "Describir";
      btnDescribe.addEventListener("click", () => {
        if (this.callbacks.onDescribe) this.callbacks.onDescribe(this.currentMedia);
      });
      this.toolbar.appendChild(btnDescribe);
    }

    if (this.features.has("download")) {
      const btnDownload = document.createElement("button");
      btnDownload.type = "button";
      btnDownload.textContent = "Descargar";
      btnDownload.addEventListener("click", () => {
        if (this.callbacks.onDownload) this.callbacks.onDownload(this.currentMedia);
        else if (this.currentMedia.url) {
          const a = document.createElement("a");
          a.href = this.currentMedia.url;
          a.download = "";
          a.click();
        }
      });
      this.toolbar.appendChild(btnDownload);
    }

    if (this.features.has("thumbnails")) {
      const btnToggleThumbs = document.createElement("button");
      btnToggleThumbs.type = "button";
      btnToggleThumbs.textContent = "Miniaturas";
      btnToggleThumbs.setAttribute("aria-pressed", "true");
      btnToggleThumbs.addEventListener("click", () => {
        const isHidden = this.thumbsEl.classList.toggle("hidden");
        btnToggleThumbs.setAttribute("aria-pressed", String(!isHidden));
      });
      this.toolbar.appendChild(btnToggleThumbs);
    }

    if (this.features.has("pager")) {
      const pager = document.createElement("div");
      pager.className = "viewer-pager";
      pager.innerHTML = `
        <button type="button" class="uv-pager-prev" aria-label="Anterior">‹</button>
        <span class="uv-pager-info">1 de 1</span>
        <button type="button" class="uv-pager-next" aria-label="Siguiente">›</button>
      `;
      const prev = pager.querySelector(".uv-pager-prev");
      const next = pager.querySelector(".uv-pager-next");
      prev.addEventListener("click", () => this.callbacks.onPagePrev && this.callbacks.onPagePrev());
      next.addEventListener("click", () => this.callbacks.onPageNext && this.callbacks.onPageNext());
      this.pagerInfo = pager.querySelector(".uv-pager-info");
      this.toolbar.appendChild(pager);
    }
  }

  bindEvents() {
    // Zoom con rueda
    this.stageWrap.addEventListener("wheel", (e) => {
      if (!this.currentMedia.url && !this.compareActive) return;
      e.preventDefault();
      const delta = e.deltaY < 0 ? 1.2 : 0.83;
      const newScale = Math.min(8, Math.max(1, this.scale * delta));
      this.scale = newScale;
      if (this.scale <= 1) {
        this.panX = 0;
        this.panY = 0;
      }
      this.applyTransform();
    }, { passive: false });

    // Drag Pan con Pointer Events (mouse, touch, stylus)
    this.stageWrap.addEventListener("pointerdown", (e) => {
      if (e.target.closest(".uv-compare-handle")) return;
      if (this.scale <= 1) return;
      if (e.button !== 0 && e.pointerType === "mouse") return;
      e.preventDefault();
      this.isPanning = true;
      this.panStart = { x: e.clientX - this.panX, y: e.clientY - this.panY };
      this.stageWrap.classList.add("panning");
      if (this.stageWrap.setPointerCapture) {
        this.stageWrap.setPointerCapture(e.pointerId);
      }
    });

    this.stageWrap.addEventListener("pointermove", (e) => {
      if (!this.isPanning) return;
      e.preventDefault();
      this.panX = e.clientX - this.panStart.x;
      this.panY = e.clientY - this.panStart.y;
      this.applyTransform();
    });

    const endStagePan = () => {
      if (this.isPanning) {
        this.isPanning = false;
        this.stageWrap.classList.remove("panning");
      }
    };
    this.stageWrap.addEventListener("pointerup", endStagePan);
    this.stageWrap.addEventListener("pointercancel", endStagePan);

    // Reset o toggle zoom con doble clic
    this.stageWrap.addEventListener("dblclick", () => {
      if (this.scale > 1) {
        this.resetZoom();
      } else {
        this.scale = 2.5;
        this.applyTransform();
      }
    });

    // Accesibilidad teclado en el handle del comparador
    this.compareHandle.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        const delta = e.key === "ArrowLeft" ? -0.02 : 0.02;
        this.compareRatio = Math.max(0.01, Math.min(0.99, this.compareRatio + delta));
        this.updateCompareSplit();
      } else if (e.key === "Home" || e.key === "End") {
        e.preventDefault();
        this.compareRatio = e.key === "Home" ? 0.01 : 0.99;
        this.updateCompareSplit();
      }
    });

    // Compare handle drag con Pointer Events y pointer capture
    this.compareHandle.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 && e.pointerType === "mouse") return;
      e.preventDefault();
      e.stopPropagation();
      this.compareDragging = true;
      if (this.compareHandle.setPointerCapture) {
        this.compareHandle.setPointerCapture(e.pointerId);
      }
    });

    this.compareHandle.addEventListener("pointermove", (e) => {
      if (!this.compareDragging) return;
      e.preventDefault();
      this.updateCompareDrag(e.clientX);
    });

    const endCompareDrag = () => {
      this.compareDragging = false;
    };
    this.compareHandle.addEventListener("pointerup", endCompareDrag);
    this.compareHandle.addEventListener("pointercancel", endCompareDrag);

    // ResizeObserver para la tira de miniaturas
    if ("ResizeObserver" in window) {
      this.resizeObserver = new ResizeObserver(() => {
        this.fitThumbnails();
      });
      this.resizeObserver.observe(this.thumbsEl);
    }
  }

  applyTransform() {
    this.stage.style.transform = `translate(${this.panX}px, ${this.panY}px) scale(${this.scale})`;
    this.stageWrap.classList.toggle("zoomed", this.scale > 1);
  }

  resetZoom() {
    this.scale = 1;
    this.panX = 0;
    this.panY = 0;
    this.applyTransform();
  }

  setMedia(item = {}) {
    this.currentMedia = item;
    this.resetZoom();

    if (!item || !item.url) {
      this.imgEl.classList.add("hidden");
      this.videoEl.classList.add("hidden");
      if (!this.compareActive) this.emptyEl.classList.remove("hidden");
      return;
    }

    this.emptyEl.classList.add("hidden");
    if (this.compareActive) {
      this.imgEl.classList.add("hidden");
      this.videoEl.classList.add("hidden");
      return;
    }

    if (item.type === "video") {
      this.imgEl.classList.add("hidden");
      this.videoEl.src = item.url;
      this.videoEl.classList.remove("hidden");
    } else {
      this.videoEl.classList.add("hidden");
      this.imgEl.src = item.url;
      this.imgEl.alt = item.alt || "";
      this.imgEl.classList.remove("hidden");
    }
  }

  setCompareUrls(beforeUrl, afterUrl) {
    this.beforeUrl = beforeUrl;
    this.afterUrl = afterUrl;
    this.compareBefore.src = beforeUrl || "";
    this.compareAfter.src = afterUrl || "";
    this.updateCompareSplit();
  }

  setCompareActive(active) {
    this.compareActive = Boolean(active);
    if (this.compareActive) {
      this.imgEl.classList.add("hidden");
      this.videoEl.classList.add("hidden");
      this.emptyEl.classList.add("hidden");
      this.compareEl.classList.remove("hidden");
      this.updateCompareSplit();
    } else {
      this.compareEl.classList.add("hidden");
      if (this.currentMedia && this.currentMedia.url) {
        this.setMedia(this.currentMedia);
      } else {
        this.emptyEl.classList.remove("hidden");
      }
    }
  }

  updateCompareDrag(clientX) {
    const rect = this.stage.getBoundingClientRect();
    if (rect.width <= 0) return;
    let ratio = (clientX - rect.left) / rect.width;
    ratio = Math.max(0.01, Math.min(0.99, ratio));
    this.compareRatio = ratio;
    this.updateCompareSplit();
  }

  updateCompareSplit() {
    const percent = Math.round(this.compareRatio * 100);
    this.compareAfter.style.clipPath = `inset(0 0 0 ${percent}%)`;
    this.compareHandle.style.left = `${percent}%`;
    this.compareHandle.setAttribute("aria-valuenow", String(percent));
    this.compareRatioEl.textContent = `${percent}%`;
  }

  setThumbnails(items = [], onSelect = null) {
    this.thumbnails = items;
    if (onSelect) this.callbacks.onThumbSelect = onSelect;
    this.thumbsEl.innerHTML = "";

    items.forEach((item, index) => {
      const img = document.createElement("img");
      img.className = "uv-thumb-item";
      img.src = item.thumb || item.url;
      img.alt = item.alt || `Item ${index + 1}`;
      img.title = item.title || "";
      img.addEventListener("click", () => {
        this.selectThumbnail(index);
        if (this.callbacks.onThumbSelect) this.callbacks.onThumbSelect(item, index);
      });
      this.thumbsEl.appendChild(img);
    });

    this.fitThumbnails();
  }

  selectThumbnail(index) {
    this.selectedThumbIndex = index;
    const allThumbs = this.thumbsEl.querySelectorAll(".uv-thumb-item");
    allThumbs.forEach((th, i) => th.classList.toggle("active", i === index));
  }

  fitThumbnails() {
    const containerWidth = this.thumbsEl.clientWidth;
    const items = this.thumbsEl.querySelectorAll(".uv-thumb-item");
    if (!items.length || containerWidth <= 0) return;

    // Calcular tamaño óptimo para llenar el contenedor sin dejar hueco a la derecha
    const gap = 8;
    const minWidth = 72;
    const count = items.length;
    
    // Cuántos caben holgadamente en una fila
    const fitCount = Math.max(1, Math.floor((containerWidth + gap) / (minWidth + gap)));
    let calculatedWidth;
    if (count < fitCount) {
      const availableWidth = containerWidth - ((count - 1) * gap);
      calculatedWidth = Math.min(88, Math.max(minWidth, Math.floor(availableWidth / count)));
    } else {
      const availableWidth = containerWidth - ((fitCount - 1) * gap);
      calculatedWidth = Math.max(minWidth, Math.floor(availableWidth / fitCount));
    }

    items.forEach((item) => {
      item.style.width = `${calculatedWidth}px`;
      item.style.height = `${calculatedWidth}px`;
      item.style.flexShrink = "0";
    });
  }

  destroy() {
    if (this.resizeObserver) {
      this.resizeObserver.disconnect();
    }
  }
}
