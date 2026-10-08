// WaifuStudio — ResolutionKit: Selector Dual de Orientación y Calidad (M18-07)
// Qué hace: calcula dimensiones exactas (width x height) según Orientación y Calidad.
// Qué no hace: no despacha llamadas de generación.

export const RESOLUTION_TABLE = {
  vertical: {
    sd: { width: 512, height: 896, label: "512×896 (SD)" },
    hd: { width: 768, height: 1344, label: "768×1344 (HD)" },
    fhd: { width: 832, height: 1472, label: "832×1472 (FHD)" },
    qhd: { width: 1024, height: 1792, label: "1024×1792 (QHD)" },
    "2k": { width: 1152, height: 2048, label: "1152×2048 (2K)" },
  },
  horizontal: {
    sd: { width: 896, height: 512, label: "896×512 (SD)" },
    hd: { width: 1344, height: 768, label: "1344×768 (HD)" },
    fhd: { width: 1472, height: 832, label: "1472×832 (FHD)" },
    qhd: { width: 1792, height: 1024, label: "1792×1024 (QHD)" },
    "2k": { width: 2048, height: 1152, label: "2048×1152 (2K)" },
  },
  square: {
    sd: { width: 512, height: 512, label: "512×512 (SD)" },
    hd: { width: 768, height: 768, label: "768×768 (HD)" },
    fhd: { width: 1024, height: 1024, label: "1024×1024 (FHD)" },
    qhd: { width: 1280, height: 1280, label: "1280×1280 (QHD)" },
    "2k": { width: 1536, height: 1536, label: "1536×1536 (2K)" },
  },
  h3_vertical: {
    sd: { width: 576, height: 1024, label: "576×1024 (SD)" },
    hd: { width: 720, height: 1280, label: "720×1280 (HD)" },
    fhd: { width: 1008, height: 1792, label: "1008×1792 (FHD)" },
    qhd: { width: 1080, height: 1920, label: "1080×1920 (QHD)" },
    "2k": { width: 1296, height: 2304, label: "1296×2304 (2K)" },
  },
  h3_horizontal: {
    sd: { width: 1024, height: 576, label: "1024×576 (SD)" },
    hd: { width: 1280, height: 720, label: "1280×720 (HD)" },
    fhd: { width: 1792, height: 1008, label: "1792×1008 (FHD)" },
    qhd: { width: 1920, height: 1080, label: "1920×1080 (QHD)" },
    "2k": { width: 2304, height: 1296, label: "2304×1296 (2K)" },
  },
};

export class ResolutionKit {
  constructor(options = {}) {
    const selOrient = options.orientationSelect ? options.orientationSelect.value : null;
    const selQual = options.qualitySelect ? options.qualitySelect.value : null;
    this.orientation = options.defaultOrientation || selOrient || "square";
    this.quality = options.defaultQuality || selQual || "fhd";
    this.widthInput = options.widthInput || null;
    this.heightInput = options.heightInput || null;
    this.badgeEl = options.badgeEl || null;
    this.onChange = options.onChange || null;

    this.orientationSelect = options.orientationSelect || null;
    this.qualitySelect = options.qualitySelect || null;

    if (this.orientationSelect && this.qualitySelect) {
      this.bindSelects();
    }
  }

  getDimensions(orientation = this.orientation, quality = this.quality) {
    const table = RESOLUTION_TABLE[orientation] || RESOLUTION_TABLE.vertical;
    const res = table[quality] || table.fhd;
    return { width: res.width, height: res.height, label: res.label };
  }

  setOrientation(val) {
    this.orientation = val;
    if (this.orientationSelect) this.orientationSelect.value = val;
    this.update();
  }

  setQuality(val) {
    this.quality = val;
    if (this.qualitySelect) this.qualitySelect.value = val;
    this.update();
  }

  syncFromDimensions(width, height) {
    const w = Number(width);
    const h = Number(height);
    if (!w || !h) return false;
    for (const [orientKey, quals] of Object.entries(RESOLUTION_TABLE)) {
      for (const [qualKey, dims] of Object.entries(quals)) {
        if (dims.width === w && dims.height === h) {
          this.orientation = orientKey;
          this.quality = qualKey;
          if (this.orientationSelect) this.orientationSelect.value = orientKey;
          if (this.qualitySelect) this.qualitySelect.value = qualKey;
          if (this.badgeEl) this.badgeEl.textContent = `${w} × ${h} (${dims.label})`;
          return true;
        }
      }
    }
    if (this.badgeEl) {
      this.badgeEl.textContent = `${w} × ${h} (Manual)`;
    }
    return false;
  }

  bindSelects() {
    this.orientationSelect.value = this.orientation;
    this.qualitySelect.value = this.quality;
    this.orientationSelect.addEventListener("change", (e) => {
      this.orientation = e.target.value;
      this.update();
    });
    this.qualitySelect.addEventListener("change", (e) => {
      this.quality = e.target.value;
      this.update();
    });
    this.update();
  }

  update() {
    const dims = this.getDimensions(this.orientation, this.quality);
    if (this.widthInput) this.widthInput.value = dims.width;
    if (this.heightInput) this.heightInput.value = dims.height;
    if (this.badgeEl) {
      this.badgeEl.textContent = `${dims.width} × ${dims.height} (${dims.label})`;
    }
    if (typeof this.onChange === "function") {
      this.onChange({
        orientation: this.orientation,
        quality: this.quality,
        width: dims.width,
        height: dims.height,
        label: dims.label,
      });
    }
  }
}
