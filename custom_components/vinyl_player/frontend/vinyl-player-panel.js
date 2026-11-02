/*
 * Vinyl Player – Home Assistant panel
 *
 * Cover flow of your Discogs records + an animated turntable that plays the
 * album through Music Assistant. No build step, no dependencies.
 */

const VERSION = "0.1.0";
const DEG_PER_SEC = 200; // 33⅓ rpm
const WINDOW = 7; // covers rendered on each side of the centre
const ARM_SVG_H = 300; // tonearm SVG viewBox height
const ARM_PIVOT_Y = 40; // pivot inside the SVG
const ARM_TIP_Y = 276; // stylus inside the SVG
const ARM_LEN = ARM_TIP_Y - ARM_PIVOT_Y;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const norm = (s) =>
  String(s ?? "")
    .toLowerCase()
    .replace(/\(.*?\)|\[.*?\]/g, "")
    .split(" - ")[0]
    .replace(/[^\p{L}\p{N}]+/gu, "");
const sortKey = (s) => String(s ?? "").replace(/^(the|a|an|die|der|das)\s+/i, "").toLowerCase();
const hue = (id) => (Number(id) * 47) % 360;
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

const ICONS = {
  gear: "M12,15.5A3.5,3.5 0 0,1 8.5,12A3.5,3.5 0 0,1 12,8.5A3.5,3.5 0 0,1 15.5,12A3.5,3.5 0 0,1 12,15.5M19.43,12.97C19.47,12.65 19.5,12.33 19.5,12C19.5,11.67 19.47,11.34 19.43,11L21.54,9.37C21.73,9.22 21.78,8.95 21.66,8.73L19.66,5.27C19.54,5.05 19.27,4.96 19.05,5.05L16.56,6.05C16.04,5.66 15.5,5.32 14.87,5.07L14.5,2.42C14.46,2.18 14.25,2 14,2H10C9.75,2 9.54,2.18 9.5,2.42L9.13,5.07C8.5,5.32 7.96,5.66 7.44,6.05L4.95,5.05C4.73,4.96 4.46,5.05 4.34,5.27L2.34,8.73C2.21,8.95 2.27,9.22 2.46,9.37L4.57,11C4.53,11.34 4.5,11.67 4.5,12C4.5,12.33 4.53,12.65 4.57,12.97L2.46,14.63C2.27,14.78 2.21,15.05 2.34,15.27L4.34,18.73C4.46,18.95 4.73,19.03 4.95,18.95L7.44,17.94C7.96,18.34 8.5,18.68 9.13,18.93L9.5,21.58C9.54,21.82 9.75,22 10,22H14C14.25,22 14.46,21.82 14.5,21.58L14.87,18.93C15.5,18.67 16.04,18.34 16.56,17.94L19.05,18.95C19.27,19.03 19.54,18.95 19.66,18.73L21.66,15.27C21.78,15.05 21.73,14.78 21.54,14.63L19.43,12.97Z",
  search: "M9.5,3A6.5,6.5 0 0,1 16,9.5C16,11.11 15.41,12.59 14.44,13.73L14.71,14H15.5L20.5,19L19,20.5L14,15.5V14.71L13.73,14.44C12.59,15.41 11.11,16 9.5,16A6.5,6.5 0 0,1 3,9.5A6.5,6.5 0 0,1 9.5,3M9.5,5C7,5 5,7 5,9.5C5,12 7,14 9.5,14C12,14 14,12 14,9.5C14,7 12,5 9.5,5Z",
  close: "M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z",
  vol: "M14,3.23V5.29C16.89,6.15 19,8.83 19,12C19,15.17 16.89,17.84 14,18.7V20.77C18,19.86 21,16.28 21,12C21,7.72 18,4.14 14,3.23M16.5,12C16.5,10.23 15.5,8.71 14,7.97V16C15.5,15.29 16.5,13.76 16.5,12M3,9V15H7L12,20V4L7,9H3Z",
};
const icon = (name, size = 22) =>
  `<svg viewBox="0 0 24 24" width="${size}" height="${size}" aria-hidden="true"><path fill="currentColor" d="${ICONS[name]}"/></svg>`;

const TONEARM_SVG = `
<svg class="arm-svg" viewBox="0 0 60 ${ARM_SVG_H}" preserveAspectRatio="xMidYMin meet" aria-hidden="true">
  <defs>
    <linearGradient id="vp-chrome" x1="0" x2="1">
      <stop offset="0" stop-color="#8d939b"/><stop offset=".45" stop-color="#f4f6f8"/>
      <stop offset=".6" stop-color="#c9ced4"/><stop offset="1" stop-color="#6c7178"/>
    </linearGradient>
    <linearGradient id="vp-weight" x1="0" x2="1">
      <stop offset="0" stop-color="#2a2a2e"/><stop offset=".5" stop-color="#6b6b72"/><stop offset="1" stop-color="#202024"/>
    </linearGradient>
  </defs>
  <rect x="19" y="2" width="22" height="26" rx="4" fill="url(#vp-weight)"/>
  <rect x="27" y="26" width="6" height="14" fill="url(#vp-chrome)"/>
  <rect x="27.2" y="40" width="5.6" height="214" rx="2.8" fill="url(#vp-chrome)"/>
  <path d="M27.4 250 L32.6 250 L37 262 L23 262 Z" fill="url(#vp-chrome)"/>
  <rect x="21" y="260" width="18" height="18" rx="2" fill="#1d1d21" stroke="#555" stroke-width=".8"/>
  <rect x="35" y="262" width="11" height="2.4" rx="1.2" fill="url(#vp-chrome)"/>
  <circle cx="30" cy="276" r="1.6" fill="#d7b46a"/>
</svg>`;

const CSS = `
:host {
  --vp-bg: radial-gradient(1200px 700px at 50% -10%, #2b2a33 0%, #141318 55%, #0b0b0e 100%);
  --vp-fg: #f2efe9; --vp-dim: #a6a2ab; --vp-accent: #e0a04a; --vp-accent2: #ff6b3d;
  --vp-panel: rgba(28,27,33,.92); --vp-line: rgba(255,255,255,.09);
  display: block; height: 100%; color: var(--vp-fg); background: #0b0b0e;
  font-family: var(--paper-font-body1_-_font-family, "Helvetica Neue", Roboto, system-ui, sans-serif);
  -webkit-tap-highlight-color: transparent;
}
* { box-sizing: border-box; }
button { font: inherit; color: inherit; }
.app { position: relative; height: 100%; min-height: 100vh; min-height: 100dvh; display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto; background: var(--vp-bg); overflow: hidden; user-select: none; }
header { display: flex; align-items: center; gap: 8px; padding: 8px 12px; height: 56px; }
header h1 { font-size: 18px; font-weight: 600; letter-spacing: .04em; margin: 0 8px 0 0; white-space: nowrap; }
header h1 span { color: var(--vp-accent); }
.spacer { flex: 1; }
.search { display: flex; align-items: center; gap: 6px; background: rgba(255,255,255,.07);
  border: 1px solid var(--vp-line); border-radius: 999px; padding: 4px 10px; min-width: 0; flex: 0 1 260px; color: var(--vp-dim); }
.search input { background: none; border: 0; outline: 0; color: var(--vp-fg); width: 100%; font-size: 14px; }
select.sort { background: rgba(255,255,255,.07); border: 1px solid var(--vp-line); color: var(--vp-fg);
  border-radius: 999px; padding: 6px 10px; font-size: 13px; }
select.sort option { color: #000; }
.iconbtn { background: none; border: 0; padding: 8px; border-radius: 50%; cursor: pointer; display: grid; place-items: center; color: var(--vp-dim); }
.iconbtn:hover { color: var(--vp-fg); background: rgba(255,255,255,.08); }
:host([narrow]) header h1 { display: none; }

/* ---------- cover flow ---------- */
.flow { position: relative; display: flex; flex-direction: column; min-height: 220px; }
.stage { position: relative; flex: 1; perspective: 1100px; perspective-origin: 50% 40%; touch-action: pan-y; cursor: grab; outline: none; }
.stage.drag { cursor: grabbing; }
.item { position: absolute; left: 50%; top: 44%; width: var(--s); height: var(--s);
  margin: calc(var(--s) / -2) 0 0 calc(var(--s) / -2); transform-style: preserve-3d; will-change: transform; }
.cover { position: absolute; inset: 0; background: #222 center / cover no-repeat; border-radius: 2px;
  box-shadow: 0 10px 30px rgba(0,0,0,.55); overflow: hidden; display: grid; place-items: center; text-align: center; padding: 10%; }
.cover .ph { font-size: calc(var(--s) * .075); line-height: 1.2; font-weight: 600; color: rgba(255,255,255,.9); text-shadow: 0 1px 3px rgba(0,0,0,.4); }
.cover .ph small { display: block; font-weight: 400; opacity: .8; margin-top: .4em; }
.cover::after { content: ""; position: absolute; inset: 0; background: linear-gradient(115deg, rgba(255,255,255,.14), transparent 38%); pointer-events: none; }
.reflect { position: absolute; left: 0; right: 0; top: calc(100% + 2px); height: 100%; background: inherit;
  background-position: center; background-size: cover; transform: scaleY(-1); opacity: .28;
  -webkit-mask-image: linear-gradient(to top, rgba(0,0,0,.9), transparent 45%); mask-image: linear-gradient(to top, rgba(0,0,0,.9), transparent 45%); pointer-events: none; }
.item .shade { position: absolute; inset: 0; background: #000; opacity: var(--shade, 0); pointer-events: none; border-radius: 2px; }
.caption { text-align: center; padding: 0 16px 4px; min-height: 52px; pointer-events: none; }
.caption .artist { color: var(--vp-dim); font-size: 14px; letter-spacing: .03em; }
.caption .title { font-size: 19px; font-weight: 600; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.caption .meta { color: var(--vp-dim); font-size: 12px; margin-top: 2px; opacity: .8; }
.scrub { width: min(520px, calc(100% - 48px)); margin: 0 auto 6px; display: block; accent-color: var(--vp-accent); opacity: .55; }
.scrub:hover, .scrub:active { opacity: 1; }
.empty { position: absolute; inset: 0; display: grid; place-items: center; color: var(--vp-dim); text-align: center; padding: 24px; }
.hint { color: var(--vp-dim); font-size: 12px; text-align: center; opacity: .7; height: 16px; }

/* ---------- turntable ---------- */
.deck { display: grid; justify-items: center; padding: 6px 16px 14px; gap: 8px; }
.plinth { position: relative; width: min(100%, 640px, 60vh); aspect-ratio: 1.45; border-radius: 18px;
  background: linear-gradient(160deg, #3a3940 0%, #232227 45%, #19181c 100%);
  box-shadow: 0 30px 60px rgba(0,0,0,.6), inset 0 1px 0 rgba(255,255,255,.12), inset 0 -2px 0 rgba(0,0,0,.6); }
.plinth::before { content: ""; position: absolute; inset: 0; border-radius: inherit; pointer-events: none;
  background: repeating-linear-gradient(90deg, rgba(255,255,255,.012) 0 1px, transparent 1px 3px); }
.platter-wrap { position: absolute; border-radius: 50%; }
.platter { position: absolute; inset: 0; border-radius: 50%;
  background: radial-gradient(circle, #1b1b1f 0 66%, #101012 66.5% 93%, transparent 93.2%),
    repeating-conic-gradient(#d9dce0 0 1.6deg, #6e7278 1.6deg 3.2deg);
  box-shadow: 0 8px 22px rgba(0,0,0,.7), 0 0 0 2px #0d0d0f; will-change: transform; }
.platter .disc { position: absolute; inset: 1.5%; transition: opacity .35s, transform .35s; }
.platter .disc.hidden { opacity: 0; transform: scale(1.08); }
.sheen { position: absolute; inset: 1.5%; border-radius: 50%; pointer-events: none; opacity: 0; transition: opacity .4s;
  background: conic-gradient(from 20deg, transparent 0 8%, rgba(255,255,255,.10) 13%, transparent 19%, transparent 50%, rgba(255,255,255,.08) 63%, transparent 70%); }
.sheen.on { opacity: 1; }
.spindle { position: absolute; left: 50%; top: 50%; width: 3.2%; height: 3.2%; margin: -1.6% 0 0 -1.6%; border-radius: 50%;
  background: radial-gradient(circle at 35% 35%, #fff, #9aa0a6 55%, #4b4f55); box-shadow: 0 1px 2px rgba(0,0,0,.6); }
.disc { border-radius: 50%; position: relative;
  background:
    radial-gradient(circle, transparent 0 33%, rgba(255,255,255,.035) 33.5% 38%, transparent 38.5% 95%, rgba(255,255,255,.05) 95.5% 98.5%, transparent 99%),
    repeating-radial-gradient(circle, #0c0c0d 0 1px, #19191b 1.4px 2.3px), #111;
  box-shadow: 0 4px 14px rgba(0,0,0,.55), inset 0 0 0 1px rgba(255,255,255,.04); }
.disc .label { position: absolute; inset: 33.5%; border-radius: 50%; background: #333 center / cover no-repeat; box-shadow: 0 0 0 1px rgba(0,0,0,.6); }
.disc .label::after { content: ""; position: absolute; left: 50%; top: 50%; width: 9%; height: 9%; margin: -4.5% 0 0 -4.5%; border-radius: 50%; background: #0b0b0e; }
.arm-base { position: absolute; border-radius: 50%;
  background: radial-gradient(circle at 40% 35%, #f3f4f6, #a7acb3 45%, #5a5e64 75%, #2c2e31);
  box-shadow: 0 6px 12px rgba(0,0,0,.6); }
.arm-rest { position: absolute; width: 4%; height: 3%; border-radius: 3px; background: #2b2b30; box-shadow: inset 0 1px 0 rgba(255,255,255,.15), 0 2px 4px rgba(0,0,0,.5); }
.arm { position: absolute; transform-origin: 50% var(--pivot); pointer-events: none; will-change: transform; z-index: 3; }
.arm-inner { width: 100%; height: 100%; transform-origin: 50% var(--pivot); transition: transform .35s ease, filter .35s ease;
  filter: drop-shadow(2px 4px 2px rgba(0,0,0,.55)); }
.arm.lifted .arm-inner { transform: scale(1.035); filter: drop-shadow(7px 12px 5px rgba(0,0,0,.45)); }
.arm.wobble .arm-inner { animation: wobble 1.8s ease-in-out infinite; }
@keyframes wobble { 0%,100% { transform: rotate(0deg); } 50% { transform: rotate(-.7deg); } }
.arm-svg { width: 100%; height: 100%; display: block; overflow: visible; }
.startstop { position: absolute; left: 3.5%; bottom: 5%; width: 14%; aspect-ratio: 1.5; border-radius: 8px; border: 0; cursor: pointer;
  background: linear-gradient(#3b3b42, #26262b); box-shadow: 0 3px 0 #0e0e10, 0 5px 10px rgba(0,0,0,.5), inset 0 1px 0 rgba(255,255,255,.12);
  color: var(--vp-dim); font-size: clamp(9px, 1.9cqw, 13px); font-weight: 700; letter-spacing: .14em; display: grid; place-items: center; }
.startstop:active { transform: translateY(2px); box-shadow: 0 1px 0 #0e0e10, 0 2px 4px rgba(0,0,0,.5); }
.startstop .led { width: 6px; height: 6px; border-radius: 50%; background: #3a1a12; margin-top: 3px; box-shadow: inset 0 0 2px #000; }
.startstop.on .led { background: var(--vp-accent2); box-shadow: 0 0 8px var(--vp-accent2); }
.startstop:disabled { opacity: .45; cursor: default; }
.plinth { container-type: inline-size; }
.badge { position: absolute; left: 3.5%; top: 5%; font-size: clamp(8px, 1.6cqw, 11px); letter-spacing: .3em; color: rgba(255,255,255,.28); font-weight: 700; }
.strobe { position: absolute; width: 1.6%; aspect-ratio: 1; border-radius: 50%; background: #3a1a12; }
.strobe.on { background: #ff3b1f; box-shadow: 0 0 10px #ff3b1f; }
.fader { position: absolute; right: 3.5%; top: 36%; height: 54%; width: 6%; touch-action: none; cursor: ns-resize; outline: none; }
.fader .track { position: absolute; left: 50%; top: 0; bottom: 0; width: 4px; margin-left: -2px; border-radius: 2px; background: #0c0c0e; box-shadow: inset 0 1px 2px #000, 0 1px 0 rgba(255,255,255,.08); }
.fader .fill { position: absolute; left: 50%; bottom: 0; width: 4px; margin-left: -2px; border-radius: 2px; background: var(--vp-accent); opacity: .7; }
.fader .knob { position: absolute; left: -30%; width: 160%; height: 14%; margin-top: -7%; border-radius: 3px;
  background: linear-gradient(#5b5b63, #2b2b31 48%, #1a1a1e 52%, #3b3b42); box-shadow: 0 3px 6px rgba(0,0,0,.6), inset 0 1px 0 rgba(255,255,255,.2); }
.fader .knob::after { content: ""; position: absolute; left: 15%; right: 15%; top: 50%; height: 1px; background: var(--vp-accent); }
.fader-label { position: absolute; right: 3.5%; top: 27%; width: 6%; display: grid; place-items: center; color: rgba(255,255,255,.35); }
.fader-label svg { width: 70%; height: auto; }
.now { text-align: center; min-height: 40px; max-width: 640px; }
.now .track { font-size: 15px; font-weight: 600; }
.now .track .pos { color: var(--vp-accent); margin-right: 8px; font-variant-numeric: tabular-nums; }
.now .sub { color: var(--vp-dim); font-size: 12px; margin-top: 2px; }

/* ---------- effects layer ---------- */
.fx { position: absolute; inset: 0; pointer-events: none; z-index: 20; }
.fx > * { position: absolute; }
.fx-sleeve { background: #222 center / cover no-repeat; box-shadow: 0 12px 30px rgba(0,0,0,.6); border-radius: 2px; }

/* ---------- sheet ---------- */
.sheet { position: absolute; inset: 0; z-index: 30; display: none; }
.sheet.open { display: block; }
.sheet .scrim { position: absolute; inset: 0; background: rgba(0,0,0,.5); }
.sheet .body { position: absolute; right: 0; top: 0; bottom: 0; width: min(520px, 100%); background: var(--vp-panel);
  backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px); border-left: 1px solid var(--vp-line); display: flex; flex-direction: column; user-select: text; }
.sheet .head { display: flex; align-items: center; padding: 8px 8px 0 16px; }
.sheet .head h2 { margin: 0; font-size: 17px; flex: 1; }
.tabs { display: flex; gap: 4px; padding: 8px 12px; border-bottom: 1px solid var(--vp-line); overflow-x: auto; }
.tabs button { background: none; border: 0; padding: 8px 12px; border-radius: 999px; cursor: pointer; color: var(--vp-dim); white-space: nowrap; }
.tabs button.on { background: rgba(224,160,74,.16); color: var(--vp-accent); }
.content { padding: 16px; overflow: auto; flex: 1; font-size: 14px; line-height: 1.5; }
.content h3 { font-size: 13px; text-transform: uppercase; letter-spacing: .08em; color: var(--vp-dim); margin: 18px 0 8px; }
.content h3:first-child { margin-top: 0; }
.content code, .content .mono { font-family: ui-monospace, Menlo, monospace; font-size: 12px; background: rgba(255,255,255,.06); padding: 2px 6px; border-radius: 4px; word-break: break-all; }
.content ol { padding-left: 20px; } .content li { margin: 4px 0; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin: 8px 0; }
.field { flex: 1; min-width: 140px; background: rgba(255,255,255,.06); border: 1px solid var(--vp-line); color: var(--vp-fg); border-radius: 8px; padding: 8px 10px; font: inherit; }
.btn { background: rgba(255,255,255,.08); border: 1px solid var(--vp-line); border-radius: 8px; padding: 8px 14px; cursor: pointer; white-space: nowrap; }
.btn.primary { background: var(--vp-accent); color: #1a1205; border-color: transparent; font-weight: 600; }
.btn:disabled { opacity: .5; cursor: default; }
.tags { width: 100%; border-collapse: collapse; }
.tags td { padding: 8px 4px; border-bottom: 1px solid var(--vp-line); vertical-align: middle; }
.tags td.t { font-family: ui-monospace, Menlo, monospace; font-size: 12px; word-break: break-all; width: 34%; }
.tags .mini { width: 34px; height: 34px; border-radius: 2px; background: #333 center / cover; display: inline-block; vertical-align: middle; margin-right: 8px; }
.muted { color: var(--vp-dim); }
.pill { display: inline-block; padding: 2px 8px; border-radius: 999px; background: rgba(224,160,74,.16); color: var(--vp-accent); font-size: 12px; }
.toast { position: absolute; left: 50%; bottom: 24px; transform: translate(-50%, 30px); opacity: 0; transition: .3s; z-index: 40;
  background: #2b2a31; border: 1px solid var(--vp-line); padding: 10px 16px; border-radius: 10px; max-width: calc(100% - 32px); box-shadow: 0 10px 30px rgba(0,0,0,.5); }
.toast.show { transform: translate(-50%, 0); opacity: 1; }
@media (max-height: 560px) and (orientation: landscape) {
  .app { grid-template-rows: auto minmax(0, 1fr); grid-template-columns: minmax(0, 1fr) auto; }
  header { grid-column: 1 / -1; }
  .deck { align-content: center; }
  .plinth { width: min(46vw, 120vh); }
}
@media (prefers-reduced-motion: reduce) { .arm.wobble .arm-inner { animation: none; } }
`;

class VinylPlayerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.all = [];
    this.list = [];
    this.pos = 0;
    this.target = 0;
    this.items = new Map();
    this.tracks = new Map();
    this.info = null;
    this.query = "";
    this.sort = this._load("sort") || "artist";
    this.deck = {
      releaseId: null, // record on the platter
      mode: "empty", // empty | loaded | playing | runout
      angle: 0,
      speed: 0,
      targetSpeed: 0,
      arm: 0,
      armTween: null,
      busy: false,
    };
    this._wantId = null;
    this._raf = null;
    this._last = 0;
    this._vol = null;
    this._sheetTab = "collection";
  }

  /* ---------------- HA plumbing ---------------- */
  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (this._menu) this._menu.hass = hass;
    if (first && this.isConnected) this._init();
    this._onHass();
  }
  get hass() {
    return this._hass;
  }
  set narrow(v) {
    this._narrow = v;
    this.toggleAttribute("narrow", !!v);
    if (this._menu) {
      this._menu.narrow = v;
      this._menu.style.display = v ? "" : "none";
    }
  }
  set panel(p) {
    this._panel = p;
  }
  set route(r) {
    this._route = r;
  }

  connectedCallback() {
    if (!this._built) this._build();
    if (this._hass) this._init();
    this._ro?.observe(this.$(".plinth"));
    this._ro?.observe(this.$(".stage"));
  }

  disconnectedCallback() {
    this._ro?.disconnect();
    if (this._unsub) {
      this._unsub.then((u) => u && u()).catch(() => {});
      this._unsub = null;
    }
    this._inited = false;
    cancelAnimationFrame(this._raf);
    this._raf = null;
  }

  $(sel) {
    return this.shadowRoot.querySelector(sel);
  }

  _load(key) {
    try {
      return localStorage.getItem(`vinyl-player:${key}`);
    } catch (e) {
      return null;
    }
  }
  _store(key, v) {
    try {
      localStorage.setItem(`vinyl-player:${key}`, v);
    } catch (e) {
      /* private mode */
    }
  }

  ws(type, data = {}) {
    return this._hass.callWS({ type: `vinyl_player/${type}`, ...data });
  }

  async _init() {
    if (this._inited || !this._hass) return;
    this._inited = true;
    const params = new URLSearchParams(location.search);
    this._deepLink = params.get("release");
    try {
      this._unsub = this._hass.connection.subscribeMessage((m) => this._onInfo(m), {
        type: "vinyl_player/subscribe",
      });
      await this._loadCollection();
    } catch (err) {
      this._toast(`Vinyl Player: ${err.message || err}`);
    }
  }

  async _loadCollection() {
    const res = await this.ws("collection");
    this.all = res.releases || [];
    this._applyFilter(true);
  }

  /* ---------------- build DOM ---------------- */
  _build() {
    this._built = true;
    this.shadowRoot.innerHTML = `
      <style>${CSS}</style>
      <div class="app">
        <header>
          <ha-menu-button></ha-menu-button>
          <h1>Vinyl <span>Player</span></h1>
          <label class="search">${icon("search", 18)}<input type="search" placeholder="Search artist or album" aria-label="Search"></label>
          <select class="sort" aria-label="Sort">
            <option value="artist">Artist</option><option value="title">Album</option>
            <option value="year">Year</option><option value="added">Recently added</option>
          </select>
          <div class="spacer"></div>
          <button class="iconbtn settings" title="Settings">${icon("gear")}</button>
        </header>
        <section class="flow">
          <div class="stage" tabindex="0" aria-label="Record shelf. Use arrow keys to browse, Enter to play."></div>
          <div class="caption"><div class="artist"></div><div class="title"></div><div class="meta"></div></div>
          <input class="scrub" type="range" min="0" max="0" value="0" aria-label="Browse collection">
        </section>
        <section class="deck">
          <div class="plinth">
            <div class="badge">VINYL&nbsp;·&nbsp;33⅓</div>
            <div class="platter-wrap">
              <div class="platter"><div class="disc hidden"><div class="label"></div></div></div>
              <div class="sheen"></div>
              <div class="spindle"></div>
            </div>
            <div class="strobe"></div>
            <div class="arm-rest"></div>
            <div class="arm-base"></div>
            <div class="arm lifted"><div class="arm-inner">${TONEARM_SVG}</div></div>
            <button class="startstop" disabled><span class="ss-text">START</span><span class="led"></span></button>
            <div class="fader-label">${icon("vol")}</div>
            <div class="fader" role="slider" tabindex="0" aria-label="Volume" aria-valuemin="0" aria-valuemax="100">
              <div class="track"></div><div class="fill"></div><div class="knob"></div>
            </div>
          </div>
          <div class="now"><div class="track"></div><div class="sub"></div></div>
        </section>
        <div class="fx"></div>
        <div class="sheet">
          <div class="scrim"></div>
          <div class="body">
            <div class="head"><h2>Vinyl Player</h2><button class="iconbtn close" title="Close">${icon("close")}</button></div>
            <div class="tabs">
              <button data-tab="collection">Collection</button>
              <button data-tab="tags">NFC tags</button>
              <button data-tab="shortcut">iPhone Shortcut</button>
              <button data-tab="album">This album</button>
            </div>
            <div class="content"></div>
          </div>
        </div>
        <div class="toast"></div>
      </div>`;

    this._menu = this.$("ha-menu-button");
    this._menu.style.display = this._narrow ? "" : "none";
    if (this._hass) this._menu.hass = this._hass;
    this._menu.narrow = this._narrow;

    const search = this.$(".search input");
    search.addEventListener("input", () => {
      this.query = search.value.trim().toLowerCase();
      this._applyFilter();
    });
    const sort = this.$("select.sort");
    sort.value = this.sort;
    sort.addEventListener("change", () => {
      this.sort = sort.value;
      this._store("sort", this.sort);
      this._applyFilter();
    });
    const scrub = this.$(".scrub");
    scrub.addEventListener("input", () => {
      this.target = Number(scrub.value);
      this._kick();
    });

    this._bindStage();
    this._bindFader();
    this.$(".startstop").addEventListener("click", () => this._startStop());
    this.$(".platter-wrap").addEventListener("click", () => this._focusOnDeckRecord());
    this.$(".settings").addEventListener("click", () => this._openSheet());
    this.$(".sheet .scrim").addEventListener("click", () => this._closeSheet());
    this.$(".sheet .close").addEventListener("click", () => this._closeSheet());
    this.shadowRoot.querySelectorAll(".tabs button").forEach((b) =>
      b.addEventListener("click", () => {
        this._sheetTab = b.dataset.tab;
        this._renderSheet();
      })
    );

    this._ro = new ResizeObserver(() => this._layout());
    this._audio = new Audio();
    this._audio.preload = "auto";
  }

  /* ---------------- collection / filter ---------------- */
  _applyFilter(initial = false) {
    const keep = this.list[Math.round(this.pos)]?.id;
    const q = this.query;
    let list = q
      ? this.all.filter((r) => `${r.artist} ${r.title} ${r.year ?? ""} ${r.label ?? ""}`.toLowerCase().includes(q))
      : this.all.slice();
    const by = {
      artist: (a, b) => sortKey(a.artist).localeCompare(sortKey(b.artist)) || (a.year ?? 9999) - (b.year ?? 9999),
      title: (a, b) => sortKey(a.title).localeCompare(sortKey(b.title)),
      year: (a, b) => (a.year ?? 9999) - (b.year ?? 9999) || sortKey(a.artist).localeCompare(sortKey(b.artist)),
      added: (a, b) => String(b.added ?? "").localeCompare(String(a.added ?? "")),
    }[this.sort];
    list.sort(by);
    this.list = list;
    this.byId = new Map(this.all.map((r) => [r.id, r]));

    let idx = 0;
    const want = initial ? Number(this._deepLink) || this.info?.state?.release_id || keep : keep;
    if (want != null) {
      const i = list.findIndex((r) => r.id === Number(want));
      if (i >= 0) idx = i;
    }
    this.pos = this.target = idx;
    for (const el of this.items.values()) el.remove();
    this.items.clear();
    const scrub = this.$(".scrub");
    scrub.max = Math.max(0, list.length - 1);
    scrub.style.visibility = list.length > 12 ? "visible" : "hidden";
    this._renderFlow();
    this._renderEmpty();
  }

  _renderEmpty() {
    const stage = this.$(".stage");
    let empty = stage.querySelector(".empty");
    if (this.list.length) {
      empty?.remove();
      return;
    }
    if (!empty) {
      empty = document.createElement("div");
      empty.className = "empty";
      stage.append(empty);
    }
    const i = this.info;
    empty.innerHTML = this.query
      ? `No records match “${esc(this.query)}”.`
      : i?.syncing
      ? `Exporting your Discogs collection & caching covers…<br><small>This can take a few minutes for big collections.</small>`
      : i?.sync_error
      ? `Discogs sync failed: ${esc(i.sync_error)}`
      : `No records yet. Open settings → Collection → Sync now.`;
  }

  /* ---------------- cover flow ---------------- */
  _layout() {
    const stage = this.$(".stage");
    const sw = stage.clientWidth;
    const sh = stage.clientHeight;
    this.S = Math.max(90, Math.min(sh * 0.7, sw * 0.44, 420));
    stage.style.setProperty("--s", `${this.S}px`);
    this._layoutDeck();
    this._renderFlow();
    this._renderDeck();
  }

  _coverStyle(r) {
    return r.cover
      ? `background-image:url("${String(r.cover).replace(/["\\\n\r]/g, (c) => encodeURIComponent(c))}")`
      : `background-image:linear-gradient(135deg, hsl(${hue(r.id)} 45% 38%), hsl(${(hue(r.id) + 60) % 360} 55% 18%))`;
  }

  _makeItem(i) {
    const r = this.list[i];
    const el = document.createElement("div");
    el.className = "item";
    el.dataset.i = i;
    const style = this._coverStyle(r);
    el.innerHTML = `<div class="cover" style="${esc(style)}">${
      r.cover ? "" : `<div class="ph">${esc(r.title)}<small>${esc(r.artist)}</small></div>`
    }<div class="shade"></div></div><div class="reflect" style="${esc(style)}"></div>`;
    this.$(".stage").append(el);
    return el;
  }

  _renderFlow() {
    if (!this.S || !this.list.length) return;
    const n = this.list.length;
    const lo = Math.max(0, Math.floor(this.pos) - WINDOW);
    const hi = Math.min(n - 1, Math.ceil(this.pos) + WINDOW);
    for (const [i, el] of this.items) {
      if (i < lo || i > hi) {
        el.remove();
        this.items.delete(i);
      }
    }
    const S = this.S;
    const gap = S * 0.62;
    const spacing = S * 0.27;
    const depth = S * 0.55;
    for (let i = lo; i <= hi; i++) {
      let el = this.items.get(i);
      if (!el) {
        el = this._makeItem(i);
        this.items.set(i, el);
      }
      const o = i - this.pos;
      const a = clamp(o, -1, 1);
      const x = a * gap + (o - a) * spacing;
      const z = -Math.abs(a) * depth;
      const ry = -a * 68;
      el.style.transform = `translate3d(${x}px,0,${z}px) rotateY(${ry}deg)`;
      el.style.zIndex = String(1000 - Math.round(Math.abs(o) * 10));
      el.style.setProperty("--shade", (Math.min(Math.abs(o), 4) * 0.12).toFixed(3));
    }
    const ci = Math.round(this.pos);
    if (ci !== this._captionIdx) {
      this._captionIdx = ci;
      const r = this.list[ci];
      this.$(".caption .artist").textContent = r?.artist ?? "";
      this.$(".caption .title").textContent = r?.title ?? "";
      this.$(".caption .meta").textContent = r ? [r.year, r.format].filter(Boolean).join(" · ") : "";
      this.$(".scrub").value = ci;
      if (this.$(".sheet").classList.contains("open") && this._sheetTab === "album") this._renderSheet();
    }
  }

  _bindStage() {
    const stage = this.$(".stage");
    let drag = null;
    stage.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      stage.setPointerCapture(e.pointerId);
      drag = { x: e.clientX, y: e.clientY, t: performance.now(), pos: this.pos, moved: false, vx: 0, lx: e.clientX, lt: performance.now(), item: e.target.closest?.(".item") };
    });
    stage.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const dx = e.clientX - drag.x;
      if (!drag.moved && Math.abs(dx) > 6) {
        drag.moved = true;
        stage.classList.add("drag");
      }
      if (!drag.moved) return;
      const now = performance.now();
      const dt = Math.max(1, now - drag.lt);
      drag.vx = 0.8 * ((e.clientX - drag.lx) / dt) + 0.2 * drag.vx;
      drag.lx = e.clientX;
      drag.lt = now;
      this.pos = this.target = clamp(drag.pos - dx / (this.S * 0.45), -0.4, this.list.length - 0.6);
      this._renderFlow();
    });
    const end = (e) => {
      if (!drag) return;
      stage.classList.remove("drag");
      const d = drag;
      drag = null;
      if (!d.moved) {
        const item = d.item;
        if (!item || !item.isConnected) return;
        const i = Number(item.dataset.i);
        if (i === Math.round(this.pos) && Math.abs(this.pos - i) < 0.15) this._select(this.list[i]);
        else {
          this.target = i;
          this._kick();
        }
        return;
      }
      const fling = clamp((-d.vx * 1000) / (this.S * 0.45), -40, 40); // covers / second
      this.target = clamp(Math.round(this.pos + fling * 0.28), 0, this.list.length - 1);
      this._kick();
    };
    stage.addEventListener("pointerup", end);
    stage.addEventListener("pointercancel", end);
    let wheelAcc = 0;
    stage.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        wheelAcc += Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
        if (Math.abs(wheelAcc) > 40) {
          this.target = clamp(this.target + Math.sign(wheelAcc), 0, this.list.length - 1);
          wheelAcc = 0;
          this._kick();
        }
      },
      { passive: false }
    );
    stage.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight") this.target = clamp(this.target + 1, 0, this.list.length - 1);
      else if (e.key === "ArrowLeft") this.target = clamp(this.target - 1, 0, this.list.length - 1);
      else if (e.key === "Enter" || e.key === " ") this._select(this.list[Math.round(this.pos)]);
      else return;
      e.preventDefault();
      this._kick();
    });
  }

  _scrollTo(id) {
    const i = this.list.findIndex((r) => r.id === id);
    if (i < 0) return false;
    this.target = i;
    this._kick();
    return true;
  }

  _focusOnDeckRecord() {
    if (this.deck.releaseId != null) this._scrollTo(this.deck.releaseId);
  }

  /* ---------------- animation loop ---------------- */
  _kick() {
    if (this._raf) return;
    this._last = performance.now();
    this._raf = requestAnimationFrame((t) => this._tick(t));
  }

  _tick(t) {
    const dt = Math.min(0.05, (t - this._last) / 1000);
    this._last = t;
    let busy = false;

    // cover flow easing
    if (Math.abs(this.target - this.pos) > 0.0005) {
      this.pos += (this.target - this.pos) * Math.min(1, dt * 9);
      if (Math.abs(this.target - this.pos) < 0.0005) this.pos = this.target;
      this._renderFlow();
      busy = true;
    }

    // platter physics
    const d = this.deck;
    if (d.speed !== d.targetSpeed) {
      const acc = d.targetSpeed > d.speed ? 420 : 160;
      d.speed = d.targetSpeed > d.speed ? Math.min(d.targetSpeed, d.speed + acc * dt) : Math.max(d.targetSpeed, d.speed - acc * dt);
    }
    if (d.speed > 0) {
      d.angle = (d.angle + d.speed * dt) % 360;
      busy = true;
    }

    // tonearm
    if (d.armTween) {
      const tw = d.armTween;
      const p = clamp((t - tw.start) / tw.dur, 0, 1);
      d.arm = tw.from + (tw.to - tw.from) * ease(p);
      if (p >= 1) {
        d.armTween = null;
        tw.resolve();
      }
      busy = true;
    } else if (d.mode === "playing") {
      const target = this._progressAngle();
      if (target != null) d.arm += (target - d.arm) * Math.min(1, dt * 2);
      busy = true;
    }

    this._renderDeck();
    this._raf = busy ? requestAnimationFrame((tt) => this._tick(tt)) : null;
  }

  /* ---------------- turntable ---------------- */
  _layoutDeck() {
    const pl = this.$(".plinth");
    const W = pl.clientWidth;
    const H = pl.clientHeight;
    if (!W || !H) return;
    const D = H * 0.88;
    const C = { x: W * 0.06 + D / 2, y: H / 2 };
    const P = { x: W * 0.835, y: H * 0.17 };
    const dist = Math.hypot(P.x - C.x, P.y - C.y);
    const L = dist * 1.015;
    this.geo = { W, H, D, C, P, L };

    const wrap = this.$(".platter-wrap");
    Object.assign(wrap.style, { width: `${D}px`, height: `${D}px`, left: `${C.x - D / 2}px`, top: `${C.y - D / 2}px` });
    const bs = H * 0.15;
    Object.assign(this.$(".arm-base").style, { width: `${bs}px`, height: `${bs}px`, left: `${P.x - bs / 2}px`, top: `${P.y - bs / 2}px` });
    const strobe = this.$(".strobe");
    Object.assign(strobe.style, { left: `${C.x - D / 2 - W * 0.005}px`, top: `${C.y + D * 0.42}px` });

    // tonearm SVG scaled so its pivot sits on P and the stylus is L away.
    const scale = L / ARM_LEN;
    const aw = 60 * scale;
    const ah = ARM_SVG_H * scale;
    const arm = this.$(".arm");
    arm.style.setProperty("--pivot", `${ARM_PIVOT_Y * scale}px`);
    Object.assign(arm.style, { width: `${aw}px`, height: `${ah}px`, left: `${P.x - aw / 2}px`, top: `${P.y - ARM_PIVOT_Y * scale}px` });
    const rest = this.$(".arm-rest");
    Object.assign(rest.style, { left: `${P.x - W * 0.02}px`, top: `${P.y + L * 0.62}px` });

    // Angles where the stylus is on the lead-in groove and on the run-out groove.
    const angleFor = (r) => {
      let best = 0;
      let bestErr = Infinity;
      for (let a = 0; a <= 70; a += 0.05) {
        const rad = (a * Math.PI) / 180;
        const tx = P.x - L * Math.sin(rad);
        const ty = P.y + L * Math.cos(rad);
        const err = Math.abs(Math.hypot(tx - C.x, ty - C.y) - r);
        if (err < bestErr) {
          bestErr = err;
          best = a;
        }
        if (Math.hypot(tx - C.x, ty - C.y) < r * 0.6) break;
      }
      return best;
    };
    this.armStart = angleFor(D * 0.97 * 0.47);
    this.armEnd = angleFor(D * 0.97 * 0.2);
  }

  _renderDeck() {
    const d = this.deck;
    const platter = this.$(".platter");
    if (!platter) return;
    platter.style.transform = `rotate(${d.angle}deg)`;
    this.$(".arm").style.transform = `rotate(${d.arm}deg)`;
    this.$(".strobe").classList.toggle("on", d.speed > 0);
  }

  _setDeckRecord(id, visible = true) {
    const disc = this.$(".platter .disc");
    const r = id != null ? this.byId?.get(id) : null;
    this.deck.releaseId = id;
    const label = disc.querySelector(".label");
    label.setAttribute("style", r ? this._coverStyle(r) : "");
    disc.classList.toggle("hidden", !(visible && id != null));
    this.$(".sheen").classList.toggle("on", visible && id != null);
    this._updateButton();
    this._updateNow();
  }

  _armTo(angle, dur) {
    return new Promise((resolve) => {
      const d = this.deck;
      if (d.armTween) d.armTween.resolve();
      d.armTween = { from: d.arm, to: angle, start: performance.now(), dur: Math.max(1, dur), resolve };
      this._kick();
    });
  }

  _lift(on) {
    this.$(".arm").classList.toggle("lifted", on);
  }

  _spin(on) {
    this.deck.targetSpeed = on ? DEG_PER_SEC : 0;
    this._kick();
  }

  _updateButton() {
    const b = this.$(".startstop");
    const d = this.deck;
    const playing = d.mode === "playing" || d.mode === "runout";
    b.disabled = d.busy || (!playing && d.releaseId == null && !this.list.length);
    b.classList.toggle("on", playing);
    b.querySelector(".ss-text").textContent = playing ? "STOP" : "START";
    b.title = playing ? "Lift the tonearm and stop" : "Play the record in the centre";
  }

  _progressAngle() {
    const p = this._albumProgress();
    if (p == null) return null;
    return this.armStart + (this.armEnd - this.armStart) * clamp(p, 0, 1);
  }

  _playerState() {
    const id = this.info?.player;
    return id ? this._hass?.states[id] : null;
  }

  _currentTrack() {
    const st = this._playerState();
    const tracks = this.tracks.get(this.deck.releaseId);
    if (!st || !tracks?.length) return { idx: -1, tracks };
    const title = st.attributes.media_title;
    if (title !== this._lastTitle) {
      this._lastTitle = title;
      const n = norm(title);
      let idx = tracks.findIndex((t) => norm(t.title) === n);
      if (idx < 0 && n.length >= 4) idx = tracks.findIndex((t) => { const m = norm(t.title); return m.length >= 4 && (m.startsWith(n) || n.startsWith(m)); });
      if (idx >= 0) this._lastIdx = idx;
      else if (this._lastIdx != null && this._lastIdx < tracks.length - 1 && this._prevTitle) this._lastIdx += 1;
      this._prevTitle = title;
    }
    return { idx: this._lastIdx ?? -1, tracks };
  }

  _albumProgress() {
    const st = this._playerState();
    if (!st) return null;
    const a = st.attributes;
    let pos = Number(a.media_position) || 0;
    const dur = Number(a.media_duration) || 0;
    if (st.state === "playing" && a.media_position_updated_at) {
      pos += (Date.now() - Date.parse(a.media_position_updated_at)) / 1000;
    }
    const { idx, tracks } = this._currentTrack();
    if (!tracks?.length || idx < 0) {
      // Unknown tracklist: creep along the current track only.
      return dur ? clamp(pos / dur, 0, 1) * 0.15 : 0;
    }
    const known = tracks.filter((t) => t.duration).map((t) => t.duration);
    const avg = known.length ? known.reduce((x, y) => x + y, 0) / known.length : dur || 240;
    const lens = tracks.map((t, i) => (i === idx && dur ? dur : t.duration || avg));
    const total = lens.reduce((x, y) => x + y, 0);
    const before = lens.slice(0, idx).reduce((x, y) => x + y, 0);
    return (before + clamp(pos, 0, lens[idx])) / total;
  }

  _updateNow() {
    const r = this.deck.releaseId != null ? this.byId?.get(this.deck.releaseId) : null;
    const trackEl = this.$(".now .track");
    const sub = this.$(".now .sub");
    if (!r) {
      trackEl.innerHTML = "";
      sub.textContent = this.list.length ? "Tap the record in the centre to put it on the turntable" : "";
      return;
    }
    const st = this._playerState();
    const { idx, tracks } = this._currentTrack();
    const mode = this.deck.mode;
    let line = "";
    if (mode === "runout") line = `<span class="pos">◌</span>Run-out groove`;
    else if (mode === "playing" && st) {
      const t = idx >= 0 ? tracks[idx] : null;
      const side = t?.position ? `<span class="pos">${esc(t.position)}</span>` : "";
      line = `${side}${esc(st.attributes.media_title || "…")}`;
      if (st.state === "paused") line += ` <span class="muted">(paused)</span>`;
    } else if (mode === "loaded") line = `<span class="muted">Needle up</span>`;
    trackEl.innerHTML = line;
    sub.textContent = `${r.artist} — ${r.title}${r.year ? ` (${r.year})` : ""}`;
  }

  _bindFader() {
    const f = this.$(".fader");
    const setFromY = (y) => {
      const rect = f.getBoundingClientRect();
      const v = clamp(1 - (y - rect.top) / rect.height, 0, 1);
      this._setVolume(v);
    };
    let dragging = false;
    f.addEventListener("pointerdown", (e) => {
      dragging = true;
      this._volDrag = true;
      f.setPointerCapture(e.pointerId);
      setFromY(e.clientY);
    });
    f.addEventListener("pointermove", (e) => dragging && setFromY(e.clientY));
    const up = () => {
      dragging = false;
      setTimeout(() => (this._volDrag = false), 800);
    };
    f.addEventListener("pointerup", up);
    f.addEventListener("pointercancel", up);
    f.addEventListener("keydown", (e) => {
      const step = { ArrowUp: 0.05, ArrowRight: 0.05, ArrowDown: -0.05, ArrowLeft: -0.05 }[e.key];
      if (step == null) return;
      e.preventDefault();
      this._setVolume(clamp((this._vol ?? 0.3) + step, 0, 1));
    });
  }

  _setVolume(v) {
    this._vol = v;
    this._renderVolume(v);
    clearTimeout(this._volTimer);
    this._volTimer = setTimeout(() => this.ws("volume", { volume: Math.round(v * 100) / 100 }).catch((e) => this._toast(e.message)), 120);
  }

  _renderVolume(v) {
    const pct = `${(clamp(v, 0, 1) * 100).toFixed(1)}%`;
    this.$(".fader .knob").style.top = `calc(100% - ${pct})`;
    this.$(".fader .fill").style.height = pct;
    this.$(".fader").setAttribute("aria-valuenow", Math.round(v * 100));
  }

  /* ---------------- state sync ---------------- */
  _onHass() {
    if (!this._built || !this.info) return;
    const st = this._playerState();
    if (st && !this._volDrag) {
      const v = st.attributes.volume_level;
      if (typeof v === "number" && v !== this._vol) {
        this._vol = v;
        this._renderVolume(v);
      }
    }
    if (st !== this._lastPlayerState) {
      this._lastPlayerState = st;
      this._lift(!(this.deck.mode === "playing" && st?.state === "playing") && this.deck.mode !== "runout");
      this._updateNow();
      if (this.deck.mode === "playing") this._kick();
    }
  }

  _onInfo(msg) {
    const first = !this.info;
    const prevCount = this.info?.count;
    const prevSync = this.info?.last_sync;
    this.info = msg;
    if (msg.kind === "collection" && (msg.count !== prevCount || msg.last_sync !== prevSync) && !first) {
      this._loadCollection().catch(() => {});
    }
    if (!this.list.length) this._renderEmpty();
    if (this.$(".sheet").classList.contains("open")) this._renderSheet();
    this._syncDeck(msg.state || {}, first);
    this._onHass();
  }

  async _syncDeck(s, first) {
    const d = this.deck;
    if (d.busy) return;
    if (first) {
      if (s.phase === "playing" || s.phase === "runout") {
        await this._waitForCollection();
        this._setDeckRecord(s.release_id);
        d.mode = "playing";
        d.speed = d.targetSpeed = DEG_PER_SEC;
        d.arm = this._progressAngle() ?? this.armStart;
        this._lift(false);
        this._ensureTracks(s.release_id);
        this._kick();
      } else if (s.last_release_id) {
        await this._waitForCollection();
        this._setDeckRecord(s.last_release_id);
        d.mode = "loaded";
      }
      this._updateButton();
      return;
    }
    if (s.phase === "playing" && s.release_id !== this._wantId) {
      // Started elsewhere: NFC tag, Apple Shortcut, automation, other device.
      await this._waitForCollection();
      const inList = this._scrollTo(s.release_id);
      if (inList) await sleep(700);
      await this._loadAndPlay(s.release_id, { fromFlow: inList, callPlay: false });
    } else if (s.phase === "runout" && d.mode === "playing") {
      this._runout(s.runout_mode);
    } else if (s.phase === "idle" && d.mode === "playing") {
      await this._needleUp();
    }
  }

  _waitForCollection() {
    if (this.byId?.size) return Promise.resolve();
    return new Promise((resolve) => {
      const t0 = Date.now();
      const iv = setInterval(() => {
        if (this.byId?.size || Date.now() - t0 > 8000) {
          clearInterval(iv);
          resolve();
        }
      }, 100);
    });
  }

  async _ensureTracks(id) {
    if (id == null || this.tracks.has(id)) return;
    this.tracks.set(id, []);
    try {
      const res = await this.ws("release", { release_id: id });
      this.tracks.set(id, res.tracks || []);
      this._lastTitle = undefined;
      this._lastIdx = undefined;
      this._updateNow();
    } catch (e) {
      this.tracks.delete(id);
    }
  }

  /* ---------------- the show ---------------- */
  _unlockAudio() {
    if (this._audioUnlocked || this.info?.runout_mode !== "browser") return;
    this._audioUnlocked = true;
    this._audio.src = this.info.runout_sound;
    this._audio.muted = true;
    this._audio.play().then(() => {
      this._audio.pause();
      this._audio.currentTime = 0;
      this._audio.muted = false;
    }).catch(() => (this._audio.muted = false));
  }

  _select(r) {
    if (!r || this.deck.busy) return;
    this._unlockAudio();
    if (this.deck.releaseId === r.id && this.deck.mode === "playing") {
      this._toast(`${r.title} is already spinning`);
      return;
    }
    this._loadAndPlay(r.id, { fromFlow: true, callPlay: true });
  }

  async _startStop() {
    const d = this.deck;
    if (d.busy) return;
    this._unlockAudio();
    if (d.mode === "playing" || d.mode === "runout") {
      this._wantId = null;
      this.ws("stop").catch((e) => this._toast(e.message));
      await this._needleUp();
    } else if (d.releaseId != null) {
      await this._loadAndPlay(d.releaseId, { fromFlow: false, callPlay: true, keepRecord: true });
    } else {
      this._select(this.list[Math.round(this.pos)]);
    }
  }

  async _needleUp() {
    const d = this.deck;
    d.mode = "loaded";
    this.$(".arm").classList.remove("wobble");
    this._lift(true);
    this._updateButton();
    this._updateNow();
    await sleep(300);
    await this._armTo(0, 1300);
    this._spin(false);
  }

  async _clearDeck() {
    const d = this.deck;
    if (d.releaseId == null) return;
    if (d.mode === "playing" || d.mode === "runout" || d.arm > 1) {
      d.mode = "loaded";
      this.$(".arm").classList.remove("wobble");
      this._lift(true);
      await sleep(250);
      await this._armTo(0, 800);
    }
    this._spin(false);
    const disc = this.$(".platter .disc");
    disc.classList.add("hidden");
    this.$(".sheen").classList.remove("on");
    await sleep(380);
    d.speed = d.targetSpeed = 0;
    this._setDeckRecord(null, false);
  }

  _recordRect() {
    const wrap = this.$(".platter-wrap").getBoundingClientRect();
    const inset = wrap.width * 0.015;
    return { left: wrap.left + inset, top: wrap.top + inset, width: wrap.width - 2 * inset, height: wrap.height - 2 * inset };
  }

  _makeDisc(r) {
    const disc = document.createElement("div");
    disc.className = "disc";
    const label = document.createElement("div");
    label.className = "label";
    label.setAttribute("style", this._coverStyle(r));
    disc.append(label);
    return disc;
  }

  async _flyOut(r) {
    const idx = this.list.findIndex((x) => x.id === r.id);
    const item = this.items.get(idx);
    const fx = this.$(".fx");
    const app = this.$(".app").getBoundingClientRect();
    const target = this._recordRect();
    const disc = this._makeDisc(r);

    if (!item || this.$(".plinth").clientWidth === 0) {
      return this._dropIn(r);
    }
    const c = item.querySelector(".cover").getBoundingClientRect();
    const size = c.width * 0.96;
    const sleeve = document.createElement("div");
    sleeve.className = "fx-sleeve";
    sleeve.setAttribute("style", this._coverStyle(r));
    Object.assign(sleeve.style, { left: `${c.left - app.left}px`, top: `${c.top - app.top}px`, width: `${c.width}px`, height: `${c.height}px` });
    Object.assign(disc.style, {
      left: `${c.left - app.left + c.width * 0.02}px`,
      top: `${c.top - app.top + c.height * 0.02}px`,
      width: `${size}px`,
      height: `${size}px`,
    });
    fx.append(disc, sleeve);
    item.style.visibility = "hidden";

    const out = c.width * 0.6;
    // 1. slide the record out of its sleeve
    await disc.animate(
      [{ transform: "translate(0,0) rotate(0deg)" }, { transform: `translate(${out}px,0) rotate(50deg)` }],
      { duration: 700, easing: "cubic-bezier(.25,.8,.25,1)", fill: "forwards" }
    ).finished;

    // 2. fly down onto the platter, sleeve goes back on the shelf
    disc.style.zIndex = "2";
    const cx = c.left + c.width * 0.02 + size / 2;
    const cy = c.top + c.height * 0.02 + size / 2;
    const dx = target.left + target.width / 2 - cx;
    const dy = target.top + target.height / 2 - cy;
    const s = target.width / size;
    sleeve.animate([{ opacity: 1 }, { opacity: 1, offset: 0.5 }, { opacity: 0 }], { duration: 600, fill: "forwards" }).finished.then(() => {
      item.style.visibility = "";
      sleeve.remove();
    });
    const landing = 50 + 290;
    await disc.animate(
      [
        { transform: `translate(${out}px,0) rotate(50deg) scale(1)` },
        { transform: `translate(${out + (dx - out) * 0.5}px,${dy * 0.42}px) rotate(200deg) scale(${(1 + s) / 2 * 1.08})`, offset: 0.55 },
        { transform: `translate(${dx}px,${dy}px) rotate(${landing}deg) scale(${s})` },
      ],
      { duration: 1000, easing: "cubic-bezier(.45,0,.25,1)", fill: "forwards" }
    ).finished;
    this.deck.angle = landing % 360;
    this._renderDeck();
    this._setDeckRecord(r.id);
    // let the platter disc fade-in transition be skipped
    const pd = this.$(".platter .disc");
    pd.style.transition = "none";
    pd.classList.remove("hidden");
    void pd.offsetWidth;
    pd.style.transition = "";
    disc.remove();
    item.style.visibility = "";
  }

  async _dropIn(r) {
    this._setDeckRecord(r.id, false);
    await sleep(30);
    this._setDeckRecord(r.id, true);
    await sleep(380);
  }

  async _loadAndPlay(id, { fromFlow = true, callPlay = true, keepRecord = false } = {}) {
    const d = this.deck;
    if (d.busy) return;
    const r = this.byId?.get(id);
    if (!r) {
      if (!callPlay) {
        d.mode = "playing";
        this._toast("Playing a record that isn't in the loaded collection");
      }
      return;
    }
    d.busy = true;
    this._wantId = id;
    this._updateButton();
    let playPromise = null;
    try {
      if (!(keepRecord && d.releaseId === id)) {
        await this._clearDeck();
        if (fromFlow) await this._flyOut(r);
        else await this._dropIn(r);
      } else if (d.arm > 1) {
        this._lift(true);
        await this._armTo(0, 600);
      }
      this._ensureTracks(id);
      if (callPlay) playPromise = this.ws("play", { release_id: id });
      this._spin(true);
      await sleep(550);
      await this._armTo(this.armStart, 1100);
      d.mode = "playing";
      this._lastTitle = undefined;
      this._lastIdx = 0;
      await sleep(250);
      this._lift(false);
      if (playPromise) await playPromise;
    } catch (err) {
      this._toast(`Couldn't play: ${err.message || err}`);
      d.busy = false;
      this._wantId = null;
      await this._needleUp();
    } finally {
      d.busy = false;
      this._updateButton();
      this._updateNow();
      this._onHass();
    }
  }

  async _runout(mode) {
    const d = this.deck;
    if (d.mode === "runout") return;
    d.mode = "runout";
    this._updateButton();
    this._updateNow();
    this._lift(false);
    if (Math.abs(d.arm - this.armEnd) > 0.5) await this._armTo(this.armEnd, 1200);
    this.$(".arm").classList.add("wobble");
    if (mode === "browser" && this.info?.runout_sound) {
      try {
        if (!this._audio.src) this._audio.src = this.info.runout_sound;
        this._audio.currentTime = 0;
        await this._audio.play();
      } catch (e) {
        /* autoplay blocked */
      }
    }
    // Locked groove for a few revolutions, then the auto-return lifts the arm.
    await sleep(4600);
    if (d.mode !== "runout") return;
    this.$(".arm").classList.remove("wobble");
    this._lift(true);
    await sleep(350);
    await this._armTo(0, 1700);
    this._spin(false);
    d.mode = "loaded";
    this._wantId = null;
    this._updateButton();
    this._updateNow();
  }

  /* ---------------- settings sheet ---------------- */
  _openSheet(tab) {
    if (tab) this._sheetTab = tab;
    this.$(".sheet").classList.add("open");
    this._renderSheet();
  }
  _closeSheet() {
    this.$(".sheet").classList.remove("open");
    if (this.info?.state?.learning) this.ws("learn_tag", { release_id: null }).catch(() => {});
  }

  _renderSheet() {
    const root = this.$(".sheet .content");
    this.shadowRoot.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === this._sheetTab));
    const i = this.info || {};
    const center = this.list[Math.round(this.pos)];
    const active = this.shadowRoot.activeElement;
    if (active && root.contains(active) && active.tagName === "INPUT") return; // don't clobber typing
    const isAdmin = this._hass?.user?.is_admin;

    if (this._sheetTab === "collection") {
      root.innerHTML = `
        <h3>Discogs</h3>
        <p>Account <b>${esc(i.username)}</b> · <span class="pill">${i.count ?? 0} records</span></p>
        <p class="muted">Last export: ${i.last_sync ? new Date(i.last_sync).toLocaleString() : "never"}</p>
        ${i.sync_error ? `<p style="color:#ff8a65">Last sync failed: ${esc(i.sync_error)}</p>` : ""}
        <div class="row"><button class="btn primary" data-act="sync" ${i.syncing || !isAdmin ? "disabled" : ""}>${i.syncing ? "Syncing…" : "Sync now"}</button></div>
        <p class="muted">The export is written to <code>/config/vinyl_player/collection.json</code> and covers are cached in
        <code>/config/vinyl_player/covers/</code>. You can also create the export with <code>scripts/discogs_export.py</code>.</p>
        <h3>Playback</h3>
        <p>Speaker: <code>${esc(i.player)}</code><br>End-of-record sound: <b>${esc(i.runout_mode)}</b></p>
        <p class="muted">Change speaker, filters and sound under Settings → Devices &amp; services → Vinyl Player → Configure.
        Like real vinyl there is no skipping: shuffle and repeat are switched off and the panel only offers volume and stop.</p>
        <p class="muted">v${VERSION}</p>`;
    } else if (this._sheetTab === "tags") {
      const tags = Object.entries(i.tags || {});
      const learning = i.state?.learning;
      root.innerHTML = `
        <h3>Link a tag to “${esc(center?.title ?? "—")}”</h3>
        ${learning ? `<p class="pill">Waiting for a tag scan… hold your phone to the tag now.</p>
          <div class="row"><button class="btn" data-act="learn-cancel">Cancel</button></div>` : `
        <div class="row">
          <button class="btn primary" data-act="learn" ${center ? "" : "disabled"}>Scan tag to link</button>
          <span class="muted">uses the Home Assistant app's NFC tags</span>
        </div>
        <div class="row">
          <input class="field" id="tagid" placeholder="…or type a tag ID / Shortcut name, e.g. abbey-road">
          <button class="btn" data-act="add" ${center ? "" : "disabled"}>Link</button>
        </div>`}
        <h3>Linked tags (${tags.length})</h3>
        ${tags.length ? `<table class="tags">${tags
          .map(([tag, m]) => {
            const r = this.byId?.get(m.release_id);
            return `<tr><td class="t">${esc(tag)}</td><td>${r ? `<span class="mini" style="${esc(this._coverStyle(r))}"></span>` : ""}${esc(m.name)}</td>
              <td style="white-space:nowrap"><button class="btn" data-act="play" data-id="${m.release_id}">▶</button>
              <button class="btn" data-act="unlink" data-tag="${esc(tag)}">✕</button></td></tr>`;
          })
          .join("")}</table>` : `<p class="muted">No tags yet.</p>`}
        <p class="muted">Tags scanned with the Home Assistant Companion app fire a <code>tag_scanned</code> event – the linked
        record is put on the turntable automatically. Unknown tags fire <code>vinyl_player_unknown_tag</code>.</p>`;
    } else if (this._sheetTab === "shortcut") {
      const url = i.webhook_url || `https://<your-ha-url>/api/webhook/${i.webhook_id}`;
      const exampleTag = Object.keys(i.tags || {})[0] || "abbey-road";
      root.innerHTML = `
        <h3>Webhook</h3>
        <div class="row"><span class="mono" style="flex:1">${esc(url)}</span><button class="btn" data-act="copy" data-text="${esc(url)}">Copy</button></div>
        <p class="muted">Keep this URL private – anyone who has it can start a record.</p>
        <h3>Option A – no Shortcut needed (recommended)</h3>
        <ol>
          <li>In the Home Assistant iPhone app: Settings → Tags → <b>Write tag</b> (or Settings → Tags → + in the HA web UI).</li>
          <li>Here: browse to the album, tap <b>NFC tags → Scan tag to link</b>, scan the tag.</li>
          <li>From now on touching the tag with your iPhone starts the record — the panel animates along.</li>
        </ol>
        <h3>Option B – Apple Shortcut</h3>
        <ol>
          <li>Shortcuts app → <b>New Shortcut</b> named <b>Play Vinyl</b>, with “Receive <b>Text</b> input from <b>Shortcuts</b>”.</li>
          <li>Add <b>Get Contents of URL</b>: URL <code>${esc(url)}</code>, Method <b>POST</b>, Request Body <b>JSON</b>, field <code>tag</code> (Text) = <i>Shortcut Input</i>.</li>
          <li>Add <b>Open URLs</b>: <code>${esc(i.panel_deeplink)}</code> (opens this panel in the HA app).</li>
          <li>Automation tab → <b>New Automation → NFC</b> → Scan your tag, name it e.g. <code>${esc(exampleTag)}</code> → Run Immediately.</li>
          <li>Action: <b>Run Shortcut “Play Vinyl”</b> with input text <code>${esc(exampleTag)}</code>.</li>
          <li>Link that same name here under <b>NFC tags</b> (type it into the tag ID field).</li>
        </ol>
        <p class="muted">Test from a terminal:<br><code>curl -X POST -H 'Content-Type: application/json' -d '{"tag":"${esc(exampleTag)}"}' ${esc(url)}</code></p>`;
    } else {
      root.innerHTML = center ? `
        <h3>${esc(center.artist)} — ${esc(center.title)}</h3>
        <p class="muted">${esc([center.year, center.format, center.label].filter(Boolean).join(" · "))}</p>
        <h3>Music Assistant match</h3>
        <p class="muted">By default the album is searched by artist + title (e.g. on Apple Music). If the wrong version plays,
        paste a Music Assistant URI (e.g. <code>apple_music://album/1441164426</code>) or a better search text.</p>
        <div class="row"><input class="field" id="override" value="${esc(center.override || "")}" placeholder="${esc(center.title)}">
        <button class="btn primary" data-act="override" data-id="${center.id}">Save</button></div>
        <div class="row"><a class="btn" style="text-decoration:none" target="_blank" rel="noopener" href="https://www.discogs.com/release/${center.id}">Open on Discogs</a></div>`
        : `<p class="muted">No album selected.</p>`;
    }

    root.querySelectorAll("[data-act]").forEach((el) =>
      el.addEventListener("click", () => this._sheetAction(el.dataset.act, el.dataset, root))
    );
  }

  async _sheetAction(act, data, root) {
    const center = this.list[Math.round(this.pos)];
    try {
      if (act === "sync") await this.ws("sync");
      else if (act === "learn") await this.ws("learn_tag", { release_id: center.id });
      else if (act === "learn-cancel") await this.ws("learn_tag", { release_id: null });
      else if (act === "add") {
        const tag = root.querySelector("#tagid").value.trim();
        if (!tag) return this._toast("Enter a tag ID first");
        await this.ws("set_tag", { tag_id: tag, release_id: center.id });
        this._toast(`Linked “${tag}” to ${center.title}`);
      } else if (act === "unlink") await this.ws("set_tag", { tag_id: data.tag, release_id: null });
      else if (act === "play") {
        this._closeSheet();
        const id = Number(data.id);
        const inList = this._scrollTo(id);
        if (inList) await sleep(600);
        await this._loadAndPlay(id, { fromFlow: inList, callPlay: true });
      } else if (act === "copy") {
        await navigator.clipboard.writeText(data.text);
        this._toast("Copied");
      } else if (act === "override") {
        const v = root.querySelector("#override").value.trim();
        await this.ws("set_override", { release_id: Number(data.id), media_id: v || null });
        const r = this.byId.get(Number(data.id));
        if (r) r.override = v || null;
        this._toast("Saved");
      }
    } catch (err) {
      this._toast(err.message || String(err));
    }
    if (act !== "play") {
      root.querySelector("input")?.blur();
      this._renderSheet();
    }
  }

  _toast(text) {
    const t = this.$(".toast");
    if (!t) return;
    t.textContent = text;
    t.classList.add("show");
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => t.classList.remove("show"), 3200);
  }
}

if (!customElements.get("vinyl-player-panel")) customElements.define("vinyl-player-panel", VinylPlayerPanel);
