// WaifuStudio — Estado Reactivo Global y Constantes
// Qué hace: exporta el objeto compartido state y constantes declarativas de la UI.
// Qué no hace: no interactúa directamente con el DOM ni emite peticiones de red.
// Dependencias: ninguna (almacén de datos reactivo en memoria).

const GROUP_LABELS = {
  hair: "Pelo",
  eyes: "Ojos",
  face: "Cara",
  body: "Cuerpo",
  outfit: "Vestuario",
  expression: "Expresión",
  accessories: "Accesorios",
  setting: "Entorno",
  action: "Acción",
  meta: "Meta",
};

const ZONE_LABELS = {
  quality: "Calidad/meta",
  safety: "Safety",
  subject: "Sujeto",
  character: "Personaje",
  general: "General",
};

const ZONE_ORDER = ["quality", "safety", "subject", "character", "general"];

const GENERAL_SUBCATS = [
  "rasgos",
  "ropa",
  "accesorios",
  "accion",
  "poses",
  "poses_sexuales",
  "poses_sexys",
  "expresion",
  "expresiones_nsfw",
  "camara",
  "fondo",
  "other",
];

const GENERAL_SUBCAT_LABELS = {
  rasgos: "Rasgos",
  ropa: "Ropa",
  accesorios: "Accesorios",
  accion: "Acción/Pose",
  poses: "Poses",
  poses_sexuales: "Poses sexuales",
  poses_sexys: "Poses sexys",
  expresion: "Expresión",
  expresiones_nsfw: "Expresiones NSFW",
  camara: "Cámara",
  fondo: "Fondo/Escena",
  other: "Otros",
};

const GENERAL_SUBCAT_FALLBACK = "other";

const PAGE_SIZE = 6;
const IMAGE_PAGE_SIZE = 5;
const VIDEO_PAGE_SIZE = 5;
const VIDEO_FPS = 16;
const H3_FPS = 24;
const H3_FRAME_BASE = 5;
const H3_FRAME_STEP = 17;

const H3_PROMPT_TEMPLATE = [
  "integrated_multimodal_description:",
  "overall_soundscape:",
  "non_diegetic_music: None",
].join("\n");

const H3_TEMPLATE_PORTRAIT = [
  "integrated_multimodal_description: A cinematic close-up shot of an anime woman with detailed silver hair gently fluttering in the wind, soft golden hour sunlight illuminating her face with delicate rim lighting, serene expression, subtle handheld camera movement, continuous single-take shot, no jump cuts.",
  "overall_soundscape: Soft gentle breeze rustling in the background, distant ambient nature sounds. No dialogue.",
  "non_diegetic_music: Gentle acoustic guitar and warm melancholic piano melody.",
].join("\n");

const H3_TEMPLATE_WALK = [
  "integrated_multimodal_description: A medium shot of an anime character slowly walking along a sunlit coastal promenade, gentle sea breeze moving their light jacket, soft cinematic lighting, smooth slow dolly forward camera tracking, continuous single-take shot, no jump cuts.",
  "overall_soundscape: Rhythmic footsteps on smooth stone pavement, distant gentle ocean waves and wind. No dialogue.",
  "non_diegetic_music: Nostalgic anime instrumental piano theme.",
].join("\n");

const H3_TEMPLATE_ACTION = [
  "integrated_multimodal_description: A dynamic full-body anime sequence, character landing gracefully and turning with flowing hair, volumetric lighting streaks, fast but smooth tracking camera pan, high energy motion, continuous single-take shot, no jump cuts.",
  "overall_soundscape: Swoosh of fast movement, crisp landing impact foley, rush of air. No dialogue.",
  "non_diegetic_music: Energetic anime synthwave beat with driving percussion.",
].join("\n");

const H3_GUIDE_TEXT = [
  "Guía de prompt H3 (MiniMax Anime Standard):",
  "",
  "ESTRUCTURA DE TRES BLOQUES (OBLIGATORIA EN INGLÉS TÉCNICO):",
  H3_PROMPT_TEMPLATE,
  "",
  "REGLAS OFICIALES:",
  "1. Una sola toma continua sin cortes ni transiciones bruscas.",
  "2. Parámetros de cámara: close-up shot, medium shot, full body shot, low angle, slow pan, slow dolly in.",
  "3. Iluminación cinematográfica: volumetric lighting, golden hour sunlight, rim lighting, neon reflection.",
  "4. Sonido Foley & Ambiente: rustling leaves, subtle footsteps, distant ocean waves, soft rain.",
  "5. Diálogo: Declarar speaker y sintaxis <d>[Idioma] texto</d> (máx 2/3 de duración).",
  "6. Música no diegética: None o descripción instrumental (piano, acoustic guitar, anime synthwave).",
  "7. Referencias (Ref2VA): Identificar con <Picture 1>, <Picture 2>, etc.",
].join("\n");

const VIDEO_REF_LIMIT = 4;
const EDITOR_REF_LIMIT = 10;
const EDITOR_GALLERY_PAGE_SIZE = 5;
const UPSCALE_GALLERY_PAGE_SIZE = 5;
const GALLERY_PAGE_SIZE = 24;
const EDITOR_SIZE_MIN = 512;
const EDITOR_SIZE_MAX = 2048;
const EDITOR_SIZE_STEP = 16;
const PROMPT_TAGS_MAX = 120;

const STARTUP_DEFAULTS = {
  model: "one-obsession-anima-v40",
  steps: 30,
  cfg: 6,
  sampler: "euler",
  scheduler: "normal",
  width: 1024,
  height: 1024,
  seed: 42,
  preprompt: "anima_default",
  rating: "nsfw",
  negative:
    "worst quality, low quality, jpeg artifacts, child, teen, loli, young-looking, " +
    "blurry, mosaic censoring, bar censor, score_1, score_2, score_3, artist name",
  video_engine: "h3",
};

const SEED_RANDOM_KEY = "waifu.seed.random";
const SEED_RANDOM_MAX = 2147483647;

const OC_TRAIT_GROUPS = ["hair", "eyes", "face", "body"];

const TRAIN_PAGE = 24;
const TRAIN_MIN = 10;
const TRAIN_MAX = 50;
const TRAIN_TRIGGER_RE = /^[a-z0-9_-]{2,32}$/;

const state = {
  models: [],
  family: "anima",
  params: {
    samplers: [],
    schedulers: [],
    default_sampler: "euler",
    default_scheduler: "sgm_uniform",
  },
  formats: [],
  formatsById: {},
  negativeBase: "",
  negativeTouched: false,
  promptZones: {
    quality: [],
    safety: [],
    subject: [],
    character: [],
    general: {
      rasgos: [],
      ropa: [],
      accesorios: [],
      accion: [],
      poses: [],
      poses_sexuales: [],
      poses_sexys: [],
      expresion: [],
      expresiones_nsfw: [],
      camara: [],
      fondo: [],
      other: [],
    },
  },
  pendingEnhance: false,
  pendingMotion: false,
  pendingH3Prompt: false,
  videoNegativeTouched: false,
  videoVramHint: "",
  videoPresets: [],
  videoH3Profiles: [],
  videoH3Variants: [],
  videoH3Seconds: [],
  videoH3Resolutions: {},
  videoRefs: [],
  editorInstalled: false,
  editorRefs: [],
  editorBusy: false,
  editorResultUrl: null,
  editorGallery: {
    page: 1,
    total: 1,
    items: [],
  },
  upscalers: [],
  frameInterpolation: null,
  upscaleSources: [],
  upscaleSourceId: null,
  upscaleLocalFile: null,
  localFilesOriginalPaths: new Map(),
  upscaleGallery: {
    page: 1,
    total: 1,
    items: [],
  },
  upscaleCompareActive: false,
  upscaleCompareRatio: 0.5,
  upscaleCompareBeforeUrl: null,
  upscaleCompareAfterUrl: null,
  upscaleCompareSlot2: null,
  upscaleLastSourceUrl: null,
  upscaleLastSourceId: null,
  upscaleLastResultUrl: null,
  upscaleLastResultId: null,
  galleryTab: {
    page: 1,
    kind: "",
    q: "",
    items: [],
    total: 1,
  },
  imageViewer: {
    page: 1,
    total: 1,
    items: [],
    selectedId: null,
  },
  videoViewer: {
    page: 1,
    total: 1,
    items: [],
    selectedId: null,
  },
  activeJobId: null,
  busy: false,
  seedRandom: false,
  characters: [],
  activeCharacterId: null,
  ocSelectedTags: [],
  ocExtras: [],
  ocCatalogItems: [],
  ocEditingId: null,
  ocPrepromptDefault: "",
  characterRefs: [],
  ocSaveGenId: null,
  loras: [],
  loraControls: {},
  loraSelection: new Map(),
  loraLibrary: [],
  loraEditId: null,
  customPreprompts: [],
  trainCharacterId: null,
  trainItems: [],
  trainSelected: new Set(),
  trainOffset: 0,
  trainBusy: false,
  trainJobId: null,
};

const LLM_STATUS_LABELS = {
  ready: ["LLM: listo", "is-ok"],
  loading: ["LLM: cargando…", "is-warn"],
  stopped: ["LLM: en espera", "is-warn"],
  offline: ["LLM: parado", "is-off"],
  unavailable: ["LLM: no instalado", "is-off"],
  foreign: ["LLM: puerto ocupado", "is-off"],
  local: ["LLM: local", "is-warn"],
};


const LIGHTBOX_MAX_SCALE = 8;
const LIGHTBOX_DRAG_CLICK_MS = 400;
const LIGHTBOX_DRAG_THRESHOLD = 4;

const COMPARE_MAX_SCALE = 8;
const COMPARE_DRAG_CLICK_MS = 400;
const COMPARE_DRAG_THRESHOLD = 4;

const PANEL_SECTIONS = {
  zones: true,
  params: false,
  loras: false,
  negative: false,
  ref: false,
};

export {
  GROUP_LABELS,
  ZONE_LABELS,
  ZONE_ORDER,
  GENERAL_SUBCATS,
  GENERAL_SUBCAT_LABELS,
  GENERAL_SUBCAT_FALLBACK,
  PAGE_SIZE,
  IMAGE_PAGE_SIZE,
  VIDEO_PAGE_SIZE,
  VIDEO_FPS,
  H3_FPS,
  H3_FRAME_BASE,
  H3_FRAME_STEP,
  H3_PROMPT_TEMPLATE,
  H3_TEMPLATE_PORTRAIT,
  H3_TEMPLATE_WALK,
  H3_TEMPLATE_ACTION,
  H3_GUIDE_TEXT,
  VIDEO_REF_LIMIT,
  EDITOR_REF_LIMIT,
  EDITOR_GALLERY_PAGE_SIZE,
  UPSCALE_GALLERY_PAGE_SIZE,
  GALLERY_PAGE_SIZE,
  EDITOR_SIZE_MIN,
  EDITOR_SIZE_MAX,
  EDITOR_SIZE_STEP,
  PROMPT_TAGS_MAX,
  STARTUP_DEFAULTS,
  SEED_RANDOM_KEY,
  SEED_RANDOM_MAX,
  OC_TRAIT_GROUPS,
  TRAIN_PAGE,
  TRAIN_MIN,
  TRAIN_MAX,
  TRAIN_TRIGGER_RE,
  LLM_STATUS_LABELS,
  LIGHTBOX_MAX_SCALE,
  LIGHTBOX_DRAG_CLICK_MS,
  LIGHTBOX_DRAG_THRESHOLD,
  COMPARE_MAX_SCALE,
  COMPARE_DRAG_CLICK_MS,
  COMPARE_DRAG_THRESHOLD,
  PANEL_SECTIONS,
  state,
};
