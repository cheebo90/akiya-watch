/* Akiya Watch — client. Decrypts data.enc in the browser (AES-GCM, PBKDF2-SHA256), then renders. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const store = {
  get(k, d) { try { const v = localStorage.getItem("aw:" + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("aw:" + k, JSON.stringify(v)); } catch {} },
  del(k) { try { localStorage.removeItem("aw:" + k); } catch {} },
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtAud = (n, yen) => (n == null && yen === 0) ? "Gratis" : n == null ? "—" : n === 0 ? "Gratis" : "A$" + Math.round(n).toLocaleString("en-AU");
const fmtYen = (n) => n == null ? "" : n === 0 ? "¥0 (無償)" : "¥" + Math.round(n).toLocaleString("ja-JP");
const fmtNum = (n, d = 0) => n == null ? "—" : Number(n).toLocaleString("it-IT", { maximumFractionDigits: d });

const PREFS = [["hokkaido","Hokkaido","北海道"],["aomori","Aomori","青森県"],["iwate","Iwate","岩手県"],["miyagi","Miyagi","宮城県"],["akita","Akita","秋田県"],["yamagata","Yamagata","山形県"],["fukushima","Fukushima","福島県"],["ibaraki","Ibaraki","茨城県"],["tochigi","Tochigi","栃木県"],["gunma","Gunma","群馬県"],["saitama","Saitama","埼玉県"],["chiba","Chiba","千葉県"],["tokyo","Tokyo","東京都"],["kanagawa","Kanagawa","神奈川県"],["niigata","Niigata","新潟県"],["toyama","Toyama","富山県"],["ishikawa","Ishikawa","石川県"],["fukui","Fukui","福井県"],["yamanashi","Yamanashi","山梨県"],["nagano","Nagano","長野県"],["gifu","Gifu","岐阜県"],["shizuoka","Shizuoka","静岡県"],["aichi","Aichi","愛知県"],["mie","Mie","三重県"],["shiga","Shiga","滋賀県"],["kyoto","Kyoto","京都府"],["osaka","Osaka","大阪府"],["hyogo","Hyogo","兵庫県"],["nara","Nara","奈良県"],["wakayama","Wakayama","和歌山県"],["tottori","Tottori","鳥取県"],["shimane","Shimane","島根県"],["okayama","Okayama","岡山県"],["hiroshima","Hiroshima","広島県"],["yamaguchi","Yamaguchi","山口県"],["tokushima","Tokushima","徳島県"],["kagawa","Kagawa","香川県"],["ehime","Ehime","愛媛県"],["kochi","Kochi","高知県"],["fukuoka","Fukuoka","福岡県"],["saga","Saga","佐賀県"],["nagasaki","Nagasaki","長崎県"],["kumamoto","Kumamoto","熊本県"],["oita","Oita","大分県"],["miyazaki","Miyazaki","宮崎県"],["kagoshima","Kagoshima","鹿児島県"],["okinawa","Okinawa","沖縄県"]];
const PREF = Object.fromEntries(PREFS.map(([s, en, ja]) => [s, { en, ja }]));
const TYPE = { house: ["Casa", "#2f6b4a"], akiya: ["Akiya bank", "#b7862b"], apartment: ["Appartamento", "#3f5f9a"], land: ["Terreno", "#8a6d5a"],
  building: ["Edificio intero", "#7a3f8f"], commercial: ["Commerciale", "#b14a3a"] };
const SOURCE = { lifull: "LIFULL Akiya Bank", athome: "athome", suumo: "SUUMO", akiyabank: "Akiya bank pubblica", yahoo: "Yahoo! 不動産" };
const EXTRA_IT = { "物件名": "Nome", "地目": "Categoria terreno", "都市計画": "Piano urbanistico", "現況": "Stato attuale", "引き渡し状況": "Consegna", "備考": "Note", "小学校": "Scuola elementare", "中学校": "Scuola media" };
const PAGE = 60;
/* Ask the source's own image service for a sharper version when it has one (SUUMO resizes on request). */
function sized(u, w) {
  if (u.startsWith("enc:")) return BLANK + "#" + u;  // encrypted photo: decrypted by the observer below
  try {
    const url = new URL(u);
    if (url.pathname.endsWith("/resizeImage")) {
      w = Math.min(w, 1024);  // SUUMO answers bigger sizes with a "NO IMAGE" picture
      url.searchParams.set("w", w); url.searchParams.set("h", Math.round(w * 3 / 4));
      return url.toString();
    }
    if (url.hostname.endsWith("yimg.jp") && url.pathname.includes("/bld_image/")) {
      w = Math.min(w, 1024);
      url.searchParams.set("w", w); url.searchParams.set("h", Math.round(w * 3 / 4));
      return url.toString();
    }
    return u.replace(/resized-bukken-\d+x\d+-/, w > 600 ? "resized-bukken-1124x836-" : "resized-bukken-562x418-");
  } catch { return u; }
}
const RETIRED = new Set(["athome", "lifull"]);

let DATA = null, VIEW = "list", shown = PAGE, map = null, cluster = null;
const favs = new Set(store.get("favs", []));
const seen = new Set(store.get("seen", []));
const DEFAULT_FILTERS = { maxAud: 80000, type: [], pref: [], minBuild: "", minLand: "", maxWalk: "", builtAfter: "", q: "", withPhotos: false, hideSeen: false, newOnly: false, tenant: "all", noRebuild: "all", freeOnly: false, places: [], nearKm: 20 };
let F = { ...DEFAULT_FILTERS, ...store.get("filters", {}) };
const ASSUME_DEFAULT = { rentPerM2: "", buyCostPct: 8, taxPct: 1.0, mgmtPct: 8, maintAud: 800, vacancyPct: 10 };
let A = { ...ASSUME_DEFAULT, ...store.get("assume", {}) };

/* ---------------------------------------------------------------- crypto */
const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
async function decrypt(blob, pass) {
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(pass), "PBKDF2", false, ["deriveKey"]);
  const key = await crypto.subtle.deriveKey({ name: "PBKDF2", salt: b64(blob.salt), iterations: blob.iter, hash: "SHA-256" },
    base, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
  const gz = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(blob.iv) }, key, b64(blob.ct));
  const stream = new Blob([gz]).stream().pipeThrough(new DecompressionStream("gzip"));
  return JSON.parse(await new Response(stream).text());
}

/* photos cut from akiya-bank PDFs are stored encrypted next to the app (12-byte IV + AES-GCM WebP) */
const BLANK = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";
let PHOTO_KEY = null;
const photoCache = new Map();
function photoKey(pass) {
  PHOTO_KEY = crypto.subtle.importKey("raw", new TextEncoder().encode(pass), "PBKDF2", false, ["deriveKey"]).then((base) =>
    crypto.subtle.deriveKey({ name: "PBKDF2", salt: new TextEncoder().encode("akiya-watch-photos-v1"), iterations: 250000, hash: "SHA-256" },
      base, { name: "AES-GCM", length: 256 }, false, ["decrypt"]));
}
function loadEnc(ref) {
  if (!photoCache.has(ref)) {
    photoCache.set(ref, (async () => {
      const r = await fetch(ref.slice(4));
      if (!r.ok) throw new Error(r.status);
      const buf = new Uint8Array(await r.arrayBuffer());
      const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: buf.slice(0, 12) }, await PHOTO_KEY, buf.slice(12));
      return URL.createObjectURL(new Blob([plain], { type: "image/webp" }));
    })());
  }
  return photoCache.get(ref);
}
/* banners, ads and buttons sneak in as "photos": drop images with a banner/icon shape once loaded */
function badShape(img) {
  const w = img.naturalWidth, h = img.naturalHeight;
  return w > 1 && h > 1 && (w < 150 || h < 100 || w / h > 2.3 || h / w > 2.3);
}
function nextPhoto(img) {  // card: try the listing's next photo, else show the "photo on the original site" link
  let rest = [];
  try { rest = JSON.parse(img.dataset.rest || "[]"); } catch {}
  if (rest.length) { img.dataset.rest = JSON.stringify(rest.slice(1)); img.src = sized(rest[0], 480); }
  else img.parentNode.classList.add("nophoto");
}
document.addEventListener("load", (e) => {
  const t = e.target;
  if (t.tagName !== "IMG" || t.src.startsWith("data:") || !badShape(t)) return;
  if (t.closest(".ph")) nextPhoto(t);
  else if (t.closest(".gallery")) t.remove();
}, true);

function hydrate(img) {
  const s = img.getAttribute("src") || "";
  const at = s.indexOf("#enc:");
  if (at < 0 || !PHOTO_KEY) return;
  loadEnc(s.slice(at + 1)).then((u) => { if (img.getAttribute("src") === s) img.src = u; })
    .catch(() => img.dispatchEvent(new Event("error")));
}
new MutationObserver((muts) => {
  for (const m of muts) {
    if (m.type === "attributes") { if (m.target.tagName === "IMG") hydrate(m.target); continue; }
    for (const n of m.addedNodes) {
      if (n.nodeType !== 1) continue;
      if (n.tagName === "IMG") hydrate(n);
      n.querySelectorAll?.("img").forEach(hydrate);
    }
  }
}).observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ["src"] });

async function unlock(pass, remember) {
  const msg = $("#lock-msg");
  msg.textContent = "Sblocco in corso…";
  let blob;
  try {
    const r = await fetch("data.enc", { cache: "no-cache" });
    if (!r.ok) throw new Error(r.status);
    blob = await r.json();
  } catch (e) {
    msg.textContent = "Dati non ancora disponibili: il primo aggiornamento deve ancora finire.";
    return false;
  }
  try {
    DATA = await decrypt(blob, pass);
  } catch {
    msg.textContent = "Passphrase sbagliata.";
    store.del("pass");
    return false;
  }
  if (remember) store.set("pass", pass);
  photoKey(pass);
  boot();
  return true;
}

/* ---------------------------------------------------------------- derived values */
function yieldOf(p, rentYenMonth) {
  const rent = rentYenMonth ?? (A.rentPerM2 && p.building_m2 ? A.rentPerM2 * p.building_m2 : null);
  if (!rent || !p.price_yen) return null;
  const annual = rent * 12;
  const cost = p.price_yen * (1 + A.buyCostPct / 100);
  const net = annual * (1 - A.vacancyPct / 100) * (1 - A.mgmtPct / 100) - p.price_yen * (A.taxPct / 100) - A.maintAud / DATA.aud_per_jpy;
  return { gross: annual / p.price_yen * 100, net: net / cost * 100, rent };
}
const rents = store.get("rents", {});
const ppm = (p) => p.price_yen && (p.building_m2 || p.land_m2) ? p.price_yen / (p.building_m2 || p.land_m2) : null;
let NEW_KEYS = new Set();
const isNew = (p) => (p._new ??= (p.keys || []).some((k) => NEW_KEYS.has(k)) || daysSince(p.first_seen) <= 2);
const daysSince = (d) => (Date.now() - new Date(d).getTime()) / 864e5;
/* macro-regions, prefectures by importance (population, main cities) */
const REGIONS = [
  ["hokkaido", "Hokkaido", "北海道", ["hokkaido"]],
  ["tohoku", "Tohoku", "東北", ["miyagi", "fukushima", "aomori", "iwate", "yamagata", "akita"]],
  ["kanto", "Kanto (Tokyo)", "関東", ["tokyo", "kanagawa", "saitama", "chiba", "ibaraki", "tochigi", "gunma"]],
  ["chubu", "Chubu (Nagoya)", "中部", ["aichi", "shizuoka", "niigata", "nagano", "gifu", "ishikawa", "toyama", "yamanashi", "fukui"]],
  ["kansai", "Kansai (Osaka, Kyoto)", "関西", ["osaka", "hyogo", "kyoto", "mie", "shiga", "nara", "wakayama"]],
  ["chugoku", "Chugoku (Hiroshima)", "中国", ["hiroshima", "okayama", "yamaguchi", "shimane", "tottori"]],
  ["shikoku", "Shikoku", "四国", ["ehime", "kagawa", "tokushima", "kochi"]],
  ["kyushu", "Kyushu e Okinawa", "九州・沖縄", ["fukuoka", "kumamoto", "kagoshima", "okinawa", "nagasaki", "oita", "miyazaki", "saga"]],
];
const prefName = (s) => PREF[s] ? PREF[s].en : s;

/* ---------------------------------------------------------------- filtering */
function filtered() {
  const q = F.q.trim().toLowerCase();
  const list = DATA.properties.filter((p) => {
    if (VIEW === "favs" && !favs.has(p.id)) return false;
    if (VIEW === "new" && !isNew(p)) return false;
    if (VIEW !== "favs") {
      if (p.active === false) return false;
      if (p.links.every((l) => RETIRED.has(l.source))) return false;  // sources switched off (no photos, blocked)
      if (F.maxAud && p.price_aud != null && p.price_aud > F.maxAud) return false;
      if (F.type.length && !F.type.includes(p.type)) return false;
      if (F.pref.length && !F.pref.includes(p.prefecture)) return false;
      if (F.places?.length && !F.places.some((t) => tagMatches(t, p))) return false;
      if (F.minBuild && (p.building_m2 || 0) < +F.minBuild) return false;
      if (F.minLand && (p.land_m2 || 0) < +F.minLand) return false;
      if (F.maxWalk && (p.walk_min == null || p.walk_min > +F.maxWalk)) return false;
      if (F.builtAfter && (p.year_built || 0) < +F.builtAfter) return false;
      if (F.withPhotos && !p.images?.length) return false;
      if (F.newOnly && !p.new_build) return false;
      const tri = (v, has) => v === "all" || !v || (v === "hide" ? !has : has);
      if (!tri(F.tenant, p.tenant)) return false;
      if (!tri(F.noRebuild, p.no_rebuild)) return false;
      if (F.freeOnly && p.price_yen !== 0) return false;
      if (F.hideSeen && seen.has(p.id)) return false;
      if (q && !(`${p.title} ${p.address} ${prefName(p.prefecture)} ${p.access} ${p.layout}`.toLowerCase().includes(q))) return false;
    }
    return true;
  });
  const s = $("#sort").value;
  const key = {
    new: (p) => -p._t,
    price: (p) => p.price_yen ?? 1e15,
    price_desc: (p) => -(p.price_yen ?? 0),
    ppm: (p) => ppm(p) ?? 1e15,
    yield: (p) => -(yieldOf(p, rents[p.id])?.net ?? -1e9),
    declared: (p) => -(p.yield_pct ?? -1),
    size: (p) => -(p.building_m2 ?? 0),
  }[s];
  return list.sort((a, b) => key(a) - key(b));
}

function activeFilterCount() {
  let n = 0;
  if (F.maxAud !== DEFAULT_FILTERS.maxAud) n++;
  for (const k of ["type", "pref"]) if (F[k].length) n++;
  if (F.places?.length) n++;
  for (const k of ["minBuild", "minLand", "maxWalk", "builtAfter", "q"]) if (F[k]) n++;
  if (F.withPhotos) n++; if (F.hideSeen) n++; if (F.newOnly) n++; if (F.tenant && F.tenant !== "all") n++; if (F.noRebuild && F.noRebuild !== "all") n++; if (F.freeOnly) n++;
  return n;
}

/* ---------------------------------------------------------------- rendering */
function card(p) {
  const [tname] = TYPE[p.type] || [p.type];
  const img = p.images?.[0] && sized(p.images[0], 480);
  const drop = p.price_history?.length && p.price_history.at(-1)[1] > p.price_yen;
  const bits = [tname, prefName(p.prefecture)];
  if (p.building_m2) bits.push(`${fmtNum(p.building_m2)} m² casa`);
  if (p.land_m2) bits.push(`${fmtNum(p.land_m2)} m² terreno`);
  if (p.layout) bits.push(p.layout);
  if (p.year_built) bits.push(String(p.year_built));
  if (p.walk_min != null) bits.push(`${p.walk_min}′ stazione`);
  if (p.subtype && !["中古一戸建て", "中古マンション"].includes(p.subtype)) bits.push(p.subtype);
  return `<article class="card ${seen.has(p.id) ? "seen" : ""}" data-id="${p.id}">
    <div class="ph">${img ? `<img loading="lazy" referrerpolicy="no-referrer" src="${esc(img)}" alt="" data-rest="${esc(JSON.stringify((p.images || []).slice(1, 6)))}" onerror="nextPhoto(this)">` : ""}<a class="orig" target="_blank" rel="noopener" href="${esc(p.links[0].url)}">Foto sul sito originale ↗</a></div>
    <button class="fav ${favs.has(p.id) ? "on" : ""}" data-fav="${p.id}" aria-label="Preferito">${favs.has(p.id) ? "★" : "☆"}</button>
    <div class="body">
      <div class="price">${fmtAud(p.price_aud, p.price_yen)}<small>${fmtYen(p.price_yen)}</small></div>
      <div class="meta">${bits.map(esc).join(" · ")}</div>
      <div class="addr">${esc(p.address)}</div>
      <div class="badges">
        ${isNew(p) ? '<span class="badge new">Nuovo</span>' : ""}
        ${p.yield_pct ? `<span class="badge yield">Rend. ${p.yield_pct.toFixed(1)}%</span>` : ""}
        ${p.tenant ? '<span class="badge warn" title="Venduto con l\'inquilino dentro (オーナーチェンジ): investimento, non ci puoi abitare">Con inquilino</span>' : ""}
        ${p.no_rebuild ? '<span class="badge bad" title="再建築不可: se demolita non si può ricostruire">Non ricostruibile</span>' : ""}
        ${p.new_build ? '<span class="badge">Nuova costruzione</span>' : ""}
        ${drop ? '<span class="badge drop">Prezzo ribassato</span>' : ""}
        ${p.active === false ? '<span class="badge gone">Non più online</span>' : ""}
        ${p.links.map((l) => `<span class="badge">${esc(SOURCE[l.source] || l.source)}</span>`).join("")}
      </div>
    </div></article>`;
}

function render() {
  const list = filtered();
  $("#result-count").textContent = `${list.length.toLocaleString("it-IT")} immobili`;
  const fc = activeFilterCount();
  $("#filter-count").hidden = !fc; $("#filter-count").textContent = fc;
  const nNew = DATA.properties.filter((p) => p.active !== false && isNew(p)).length;
  $("#new-count").hidden = !nNew; $("#new-count").textContent = nNew;
  $("#fav-count").hidden = !favs.size; $("#fav-count").textContent = favs.size;
  if (VIEW === "map") return renderMap(list);
  const cards = $("#cards");
  if (!list.length) {
    cards.innerHTML = `<div class="empty">${VIEW === "favs" ? "Nessun preferito: tocca ☆ su un annuncio per salvarlo." : "Nessun immobile con questi filtri."}</div>`;
    $("#more").hidden = true; return;
  }
  cards.innerHTML = list.slice(0, shown).map(card).join("");
  $("#more").hidden = list.length <= shown;
}

/* place search (Mapbox geocoding, Japan only): names in romaji and kanji */
async function geoSearch(q) {
  const u = `https://api.mapbox.com/geocoding/v5/mapbox.places/${encodeURIComponent(q)}.json?country=jp&language=en,ja` +
    `&types=region,district,place,locality,neighborhood,poi&limit=6&access_token=${MAPBOX_TOKEN}`;
  const r = await fetch(u);
  if (!r.ok) throw new Error("geocoding " + r.status);
  const j = await r.json();
  return (j.features || []).map((f) => ({
    name: f.text_en || f.text, ja: f.text_ja || "", full: f.place_name_en || f.place_name,
    lat: f.center[1], lng: f.center[0], bbox: f.bbox ? [[f.bbox[1], f.bbox[0]], [f.bbox[3], f.bbox[2]]] : null,
  }));
}
/* ---- location tags (like realestate.com.au): regions, prefectures and places, several at once ---- */
function tagMatches(t, p) {
  if (t.k === "pref") return p.prefecture === t.v;
  if (t.k === "region") return (REGIONS.find((r) => r[0] === t.v)?.[3] || []).includes(p.prefecture);
  if (t.k === "bbox") return !!p.latlng && p.latlng[0] >= t.b[0] && p.latlng[0] <= t.b[2] && p.latlng[1] >= t.b[1] && p.latlng[1] <= t.b[3];
  if (p.latlng) return kmBetween(p.latlng, [t.lat, t.lng]) <= (+F.nearKm || 20);
  return !!(t.ja && (p.address || "").includes(t.ja));
}
const tagKey = (t) => t.k + ":" + (t.v || (t.b ? t.b.map((x) => x.toFixed(3)).join(",") : `${t.lat.toFixed(3)},${t.lng.toFixed(3)}`));
function localSuggestions(q) {
  const s = q.toLowerCase(), hit = (...xs) => xs.some((x) => x && x.toLowerCase().includes(s));
  const out = [];
  for (const [id, name, ja] of REGIONS) if (hit(name, ja, id)) out.push({ k: "region", v: id, label: name.split(" (")[0], sub: `${ja} · zona` });
  for (const [slug, en, ja] of PREFS) if (hit(en, ja, slug)) out.push({ k: "pref", v: slug, label: en, sub: `${ja} · prefettura` });
  return out.slice(0, 5);
}
/* tag input: chips + text field + suggestions. get()/set(tags) read and write the tag list */
function tagSearch(root, { get, set, placeholder }) {
  root.classList.add("tagbox");
  root.innerHTML = `<div class="tag-field"><span class="tags"></span><input type="search" autocomplete="off" placeholder="${esc(placeholder)}" aria-label="${esc(placeholder)}"></div><ul class="suggest" hidden></ul>`;
  const field = root.querySelector(".tag-field"), tagsEl = root.querySelector(".tags"), input = root.querySelector("input"), list = root.querySelector("ul");
  let items = [], sel = 0, t = null, seq = 0;
  const draw = () => {
    tagsEl.innerHTML = get().map((x, i) => `<span class="tag">${esc(x.label)}<button type="button" data-rm="${i}" aria-label="Togli ${esc(x.label)}">×</button></span>`).join("");
    input.placeholder = get().length ? "Aggiungi un altro luogo…" : placeholder;
  };
  const close = () => { list.hidden = true; items = []; };
  const show = () => {
    list.innerHTML = items.length ? items.map((x, i) => `<li data-i="${i}" class="${i === sel ? "on" : ""}"><b>${esc(x.label)}</b><small>${esc(x.sub || "")}</small></li>`).join("")
      : `<li class="none">Nessun luogo trovato</li>`;
    list.hidden = false;
  };
  const pick = (x) => {
    if (!x) return;
    const have = get();
    if (!have.some((y) => tagKey(y) === tagKey(x))) set([...have, x]);
    input.value = ""; close(); draw(); input.focus();
  };
  input.addEventListener("input", () => {
    clearTimeout(t);
    const q = input.value.trim(), my = ++seq;
    if (!q) return close();
    items = localSuggestions(q); sel = 0; show();  // regions and prefectures right away
    if (q.length < 2) return;
    t = setTimeout(async () => {
      let geo = [];
      try { geo = await geoSearch(q); } catch {}
      if (my !== seq) return;
      const places = geo.map((g) => ({ k: "place", label: g.name, ja: g.ja, lat: g.lat, lng: g.lng, sub: [g.ja !== g.name ? g.ja : "", g.full].filter(Boolean).join(" · ") }));
      items = [...localSuggestions(q), ...places].slice(0, 8); sel = 0; show();
    }, 250);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" && items.length) { e.preventDefault(); sel = (sel + 1) % items.length; show(); }
    else if (e.key === "ArrowUp" && items.length) { e.preventDefault(); sel = (sel - 1 + items.length) % items.length; show(); }
    else if (e.key === "Enter") { e.preventDefault(); if (!list.hidden) pick(items[sel]); }
    else if (e.key === "Escape") close();
    else if (e.key === "Backspace" && !input.value && get().length) { set(get().slice(0, -1)); draw(); }
  });
  list.addEventListener("mousedown", (e) => {  // before the field loses focus
    const li = e.target.closest("li[data-i]");
    if (li) { e.preventDefault(); pick(items[+li.dataset.i]); }
  });
  tagsEl.addEventListener("click", (e) => {
    const b = e.target.closest("[data-rm]");
    if (b) { e.stopPropagation(); const v = get().slice(); v.splice(+b.dataset.rm, 1); set(v); draw(); input.focus(); }
  });
  field.addEventListener("click", () => input.focus());
  input.addEventListener("blur", () => setTimeout(close, 150));
  draw();
  return { draw };
}
const kmBetween = (a, b) => {
  const R = 6371, dLat = (b[0] - a[0]) * Math.PI / 180, dLng = (b[1] - a[1]) * Math.PI / 180;
  const x = Math.sin(dLat / 2) ** 2 + Math.cos(a[0] * Math.PI / 180) * Math.cos(b[0] * Math.PI / 180) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
};

/* Mapbox raster styles: English names (romaji in Japan). Public token, restricted in Mapbox to this site. */
const MAPBOX_TOKEN = "pk.eyJ1IjoiaGVucnkiLCJhIjoiY213NjlwYWZiMGhpczJ6cHdtcTMwN3JhOSJ9.S77NzfXqlMR-gvXberEsjw";
function mapboxLayer(style) {
  return L.tileLayer(`https://api.mapbox.com/styles/v1/mapbox/${style}/tiles/512/{z}/{x}/{y}{r}?access_token=${MAPBOX_TOKEN}`, {
    tileSize: 512, zoomOffset: -1, maxZoom: 20,
    attribution: '<b>mapbox</b> © <a href="https://www.mapbox.com/about/maps/" target="_blank" rel="noopener">Mapbox</a> © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> <a href="https://www.mapbox.com/map-feedback/" target="_blank" rel="noopener"><b>Improve this map</b></a>',
  });
}

/* label above each dot: compact price + type */
const SHORT_TYPE = { house: "Casa", akiya: "Akiya", apartment: "Appart.", land: "Terreno", building: "Edificio", commercial: "Comm." };
function shortAud(p) {
  if (p.price_yen === 0) return "Gratis";
  const n = p.price_aud;
  if (n == null) return p.price_yen ? "¥" + Math.round(p.price_yen / 1e4) + "万" : "—";
  if (n >= 1e6) return "A$" + (n / 1e6).toFixed(n < 1e7 ? 1 : 0).replace(/\.0$/, "") + "M";
  if (n >= 1e4) return "A$" + Math.round(n / 1e3) + "k";
  if (n >= 1e3) return "A$" + (n / 1e3).toFixed(1).replace(/\.0$/, "") + "k";
  return "A$" + Math.round(n);
}

function renderMap(list) {
  if (!map) {
    map = L.map("map", { preferCanvas: true }).setView([36.2, 138.2], 5);
    // map styles without API key, Latin-script (romaji) labels; the choice is remembered
    const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
    const esri = (name, o = {}) => L.tileLayer(ESRI + name + "/MapServer/tile/{z}/{y}/{x}",
      { maxZoom: 19, attribution: "Tiles © Esri — Esri, HERE, Garmin, Maxar, © OpenStreetMap", ...o });
    const labels = () => esri("Reference/World_Boundaries_and_Places", { pane: "overlayPane" });
    const styles = {
      "Mapbox stradale": mapboxLayer("streets-v12"),
      "Mapbox satellite": mapboxLayer("satellite-streets-v12"),
      "Mapbox outdoor": mapboxLayer("outdoors-v12"),
      "Stradale": esri("World_Street_Map"),
      "Satellite": L.layerGroup([esri("World_Imagery"), labels()]),
      "Topografica": esri("World_Topo_Map"),
      "OpenStreetMap (kanji)": L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }),
    };
    const pick = "Mapbox stradale";  // always opens on Mapbox streets; other styles from the layer switcher
    styles[pick].addTo(map);
    L.control.layers(styles, null, { position: "topright" }).addTo(map);
    // the same location tags as in the filters, applied right away
    const Search = L.Control.extend({ options: { position: "topleft" }, onAdd() {
      const box = L.DomUtil.create("div", "map-search");
      L.DomEvent.disableClickPropagation(box); L.DomEvent.disableScrollPropagation(box);
      mapTags = tagSearch(box, { placeholder: "Cerca zone, prefetture, città…", get: () => F.places || [],
        set: (v) => { F = { ...F, places: v }; store.set("filters", F); shown = PAGE; render(); } });
      return box;
    } });
    const sc = new Search().addTo(map).getContainer(); sc.parentNode.prepend(sc);  // above the zoom buttons
    // after the user pans or zooms: offer to search only inside the visible area
    const redo = L.DomUtil.create("button", "map-redo", map.getContainer());
    redo.id = "map-redo"; redo.type = "button"; redo.textContent = "↻ Cerca in questa zona";
    L.DomEvent.disableClickPropagation(redo);
    map.on("movestart", () => { if (!autoMove) redo.dataset.user = "1"; });
    map.on("moveend", () => { if (redo.dataset.user) redo.classList.add("show"); delete redo.dataset.user; });
    redo.onclick = () => {
      const b = map.getBounds();
      const tag = { k: "bbox", label: "Area della mappa", b: [b.getSouth(), b.getWest(), b.getNorth(), b.getEast()] };
      F = { ...F, places: [tag] }; store.set("filters", F); shown = PAGE;
      keepView = true; redo.classList.remove("show"); mapTags?.draw(); render();
    };
    // Esri unreachable: switch to OpenStreetMap so the map is never blank
    // a style that doesn't load (Mapbox token/quota, Esri down) gives way: Mapbox -> Esri, Esri -> OpenStreetMap
    const fallback = (name) => {
      const to = name.startsWith("Mapbox") ? "Stradale" : "OpenStreetMap (kanji)";
      if (map.hasLayer(styles[to])) return;
      Object.values(styles).forEach((l) => map.removeLayer(l));
      styles[to].addTo(map);
    };
    for (const [name, l] of Object.entries(styles)) {
      if (name.startsWith("OpenStreetMap")) continue;
      let errs = 0;
      (l.getLayers ? l.getLayers() : [l]).forEach((t) => {
        t.on("tileerror", () => { if (++errs === 8 && map.hasLayer(t)) fallback(name); });
      });
    }
  }
  map.invalidateSize();
  setTimeout(() => map.invalidateSize(), 50);
  // same results as last time (e.g. a property card was just closed): keep zoom, position and the side list as they are
  const sig = list.length + "|" + list.map((p) => p.id).join(",");
  if (cluster && sig === mapSig) {
    if (keepView) { keepView = false; $("#map-redo")?.classList.remove("show"); }
    $$(".ml-item", $("#ml-items")).forEach((el) => el.classList.toggle("seen", seen.has(el.dataset.id)));
    return;
  }
  mapSig = sig;
  if (cluster) map.removeLayer(cluster);
  const markers = [], stacked = {};
  for (const p of list) {
    if (!p.latlng) continue;
    const color = (TYPE[p.type] || [, "#555"])[1];
    // many listings share the same point (town centre): spread them on a small spiral so each dot can be tapped
    const k = p.latlng[0].toFixed(5) + "," + p.latlng[1].toFixed(5), n = stacked[k] = (stacked[k] || 0) + 1;
    const r = n > 1 ? 0.0006 * Math.sqrt(n - 1) : 0, a = (n - 1) * 2.4;
    const pos = [p.latlng[0] + r * Math.sin(a), p.latlng[1] + r * Math.cos(a) * 1.2];
    const m = L.marker(pos, { riseOnHover: true, icon: L.divIcon({ className: "pin", iconSize: [14, 14], iconAnchor: [7, 7],
      html: `<span class="pin-label" style="--c:${color}"><b>${shortAud(p)}</b><i>${esc(SHORT_TYPE[p.type] || "")}</i></span><div class="dot" data-pid="${p.id}" style="background:${color}"></div>` }) });
    m.prop = p;
    m.bindPopup(() => mapPopup(p), { minWidth: 260, maxWidth: 280, className: "pop" });
    markers.push(m);
  }
  // grouped with counts at the starting view; from the first zoom step every property is a dot
  // "search this area" keeps the view the user chose; any other change of results re-centres the map
  if (keepView) keepView = false;
  else if (markers.length) { autoMove = true; map.fitBounds(L.latLngBounds(markers.map((m) => m.getLatLng())), { padding: [30, 30], maxZoom: 12, animate: false }); autoMove = false; }
  $("#map-redo")?.classList.remove("show");
  const z0 = map.getZoom();
  cluster = L.markerClusterGroup({ chunkedLoading: true, maxClusterRadius: 50, spiderfyOnMaxZoom: false,
    // inside a searched zone (location tags) every property is its own dot right away
    disableClusteringAtZoom: F.places?.length ? 1 : Math.min(z0 + 1, 13) });
  cluster.addLayers(markers);
  map.addLayer(cluster);
  mapMarkers = markers;
  if (!map._listHooked) {
    map.on("moveend", renderMapList);
    const zc = () => map.getContainer().classList.toggle("far", map.getZoom() < 11);
    map.on("zoomend", zc); zc();
    map.on("popupopen", (e) => { popId = e.popup._source?.prop?.id || null; markListItem(true); });
    map.on("popupclose", () => { popId = null; markListItem(false); });
    map._listHooked = true;
  }
  renderMapList();
  const missing = list.length - markers.length;
  $("#result-count").textContent = `${list.length.toLocaleString("it-IT")} immobili` + (missing ? ` (${missing} senza posizione)` : "");
}

/* side list: the properties inside the current map view, in the chosen sort order, loaded as you scroll */
let keepView = false, autoMove = false, mapTags = null, mapMarkers = [], mlInView = [], mlShown = 0, mapSig = "";
function mapItem(p) {
  const bits = [(TYPE[p.type] || [p.type])[0]];
  if (p.building_m2) bits.push(`${fmtNum(p.building_m2)} m² casa`);
  if (p.land_m2) bits.push(`${fmtNum(p.land_m2)} m² terreno`);
  if (p.layout) bits.push(p.layout);
  if (p.year_built) bits.push(String(p.year_built));
  const img = p.images?.[0] && sized(p.images[0], 320);
  return `<div class="ml-item ${seen.has(p.id) ? "seen" : ""}" data-id="${p.id}">
    <div class="ph">${img ? `<img loading="lazy" referrerpolicy="no-referrer" src="${esc(img)}" alt="" data-rest="${esc(JSON.stringify((p.images || []).slice(1, 6)))}" onerror="nextPhoto(this)">` : ""}</div>
    <div class="t"><div class="price">${fmtAud(p.price_aud, p.price_yen)}<small>${fmtYen(p.price_yen)}</small></div>
      <div class="meta">${bits.map(esc).join(" · ")}</div><div class="addr" title="${esc(p.address || "")}">${esc(p.address_ro || p.address || "")}</div>
      ${p.tenant || p.no_rebuild ? `<div class="flags">${p.tenant ? '<span class="badge warn">Con inquilino</span>' : ""}${p.no_rebuild ? '<span class="badge bad">Non ricostruibile</span>' : ""}</div>` : ""}
      <div class="more">
        ${p.title ? `<div class="ttl" title="${esc(p.title)}">${esc(p.title_ro || p.title)}</div>` : ""}
        ${p.access ? `<div>🚉 ${esc(p.access_ro || p.access)}</div>` : p.walk_min != null ? `<div>🚉 ${p.walk_min}′ a piedi</div>` : ""}
        ${p.price_yen && p.building_m2 ? `<div>${fmtYen(Math.round(p.price_yen / p.building_m2))}/m² casa</div>` : ""}
        <div class="src">${[...new Set((p.links || []).map((l) => SOURCE[l.source] || l.source))].map((x) => `<span class="badge">${esc(x)}</span>`).join(" ")}</div>
      </div></div></div>`;
}
function mapPopup(p) {
  const bits = [];
  if (p.building_m2) bits.push(`${fmtNum(p.building_m2)} m² casa`);
  if (p.land_m2) bits.push(`${fmtNum(p.land_m2)} m² terreno`);
  if (p.layout) bits.push(p.layout);
  if (p.year_built) bits.push(String(p.year_built));
  if (p.walk_min != null) bits.push(`${p.walk_min}′ stazione`);
  const img = p.images?.[0] && sized(p.images[0], 480);
  const srcs = [...new Set((p.links || []).map((l) => SOURCE[l.source] || l.source))].join(" · ");
  return `<a class="pop-card" href="#/p/${p.id}">
    ${img ? `<div class="ph"><img referrerpolicy="no-referrer" src="${esc(img)}" alt="" data-rest="${esc(JSON.stringify((p.images || []).slice(1, 6)))}" onerror="nextPhoto(this)"></div>` : ""}
    <div class="pop-body">
      <div class="price">${fmtAud(p.price_aud, p.price_yen)} <small>${fmtYen(p.price_yen)}</small></div>
      <div class="muted">${esc((TYPE[p.type] || [p.type])[0])} · ${esc(prefName(p.prefecture))}</div>
      ${bits.length ? `<div>${bits.map(esc).join(" · ")}</div>` : ""}
      <div class="addr">${esc(p.address_ro || p.address || "")}</div>
      ${p.tenant || p.no_rebuild ? `<div class="flags">${p.tenant ? '<span class="badge warn">Con inquilino</span>' : ""}${p.no_rebuild ? '<span class="badge bad">Non ricostruibile</span>' : ""}</div>` : ""}
      <div class="pop-foot"><span class="muted">${esc(srcs)}</span><span class="open">Apri scheda →</span></div>
    </div></a>`;
}
let popId = null;
function markListItem(scroll) {  // the property whose map popup is open stands out in the side list
  $$(".ml-item.hl").forEach((x) => x.classList.remove("hl"));
  const it = popId && $(`.ml-item[data-id="${popId}"]`);
  if (it) { it.classList.add("hl"); if (scroll) it.scrollIntoView({ block: "nearest", behavior: "smooth" }); }
}
function renderMapList() {
  if (!map || VIEW !== "map") return;
  const b = map.getBounds();
  mlInView = mapMarkers.filter((m) => b.contains(m.getLatLng())).map((m) => m.prop);
  mlShown = 0;
  $("#ml-count").textContent = `${mlInView.length.toLocaleString("it-IT")} in questa zona`;
  $("#ml-items").innerHTML = mlInView.length ? "" : `<div class="empty">Nessun immobile in questa parte della mappa.</div>`;
  $("#ml-items").scrollTop = 0;
  moreMapList();
  markListItem(true);
}
function moreMapList() {
  if (mlShown >= mlInView.length) return;
  const next = mlInView.slice(mlShown, mlShown + 30);
  mlShown += next.length;
  $("#ml-items").insertAdjacentHTML("beforeend", next.map(mapItem).join(""));
}
function initMapResize() {
  const wrap = $(".map-wrap"), bar = $("#ml-resize");
  const set = (w) => {
    w = Math.max(300, Math.min(w, innerWidth - 320));
    wrap.style.setProperty("--ml-w", w + "px");
    return w;
  };
  set(store.get("mlWidth", 380));
  let x0 = 0, w0 = 0;
  const move = (e) => { set(w0 + e.clientX - x0); map && map.invalidateSize(); };
  const up = () => {
    document.removeEventListener("pointermove", move); document.removeEventListener("pointerup", up);
    document.body.classList.remove("resizing");
    store.set("mlWidth", $(".map-list").getBoundingClientRect().width);
    map && map.invalidateSize(); renderMapList();
  };
  bar.addEventListener("pointerdown", (e) => {
    e.preventDefault(); x0 = e.clientX; w0 = $(".map-list").getBoundingClientRect().width;
    document.body.classList.add("resizing");
    document.addEventListener("pointermove", move); document.addEventListener("pointerup", up);
  });
  bar.addEventListener("dblclick", () => { store.set("mlWidth", set(380)); map && map.invalidateSize(); });
}
function initMapList() {
  initMapResize();
  const box = $("#ml-items");
  const nearEnd = (el) => el.scrollHeight - el.scrollTop - el.clientHeight < 400;
  box.addEventListener("scroll", () => { if (nearEnd(box)) moreMapList(); });
  window.addEventListener("scroll", () => {  // phones: the list flows with the page
    if (VIEW === "map" && innerHeight + scrollY > document.body.scrollHeight - 400) moreMapList();
  }, { passive: true });
  box.addEventListener("click", (e) => { const it = e.target.closest(".ml-item"); if (it) location.hash = "#/p/" + it.dataset.id; });
  // the whole pin (dot + price label) of the hovered property stands out on the map
  const hl = (id, on) => document.querySelectorAll(`.dot[data-pid="${id}"]`).forEach((d) => (d.closest(".pin") || d).classList.toggle("hl", on));
  box.addEventListener("mouseover", (e) => { const it = e.target.closest(".ml-item"); if (it) hl(it.dataset.id, true); });
  box.addEventListener("mouseout", (e) => { const it = e.target.closest(".ml-item"); if (it) hl(it.dataset.id, false); });
}

/* ---------------------------------------------------------------- detail */
function openDetail(id) {
  const p = DATA.properties.find((x) => x.id === id || x.keys?.includes(id));
  if (!p) return;
  seen.add(p.id); store.set("seen", [...seen]);
  const imgs = uniquePhotos(p.images || []);
  const rows = [
    ["Prezzo", `${fmtAud(p.price_aud, p.price_yen)} · ${fmtYen(p.price_yen)}`],
    ["Tipo", (TYPE[p.type] || [p.type])[0] + (p.subtype ? ` (${p.subtype})` : "") + (p.new_build ? " · nuova costruzione" : "")],
    ...(p.tenant ? [["Inquilino", "Venduto con l'inquilino dentro (オーナーチェンジ): è un investimento, di norma non ci puoi andare ad abitare finché c'è il contratto"]] : []),
    ...(p.no_rebuild ? [["Ricostruzione", "再建築不可: il terreno non confina con una strada a norma, se demolisci la casa non puoi ricostruirla. Prezzo basso per questo, mutuo difficile"]] : []),
    ...(p.yield_pct ? [["Rendimento dichiarato", `${p.yield_pct.toFixed(2)}% lordo (dal venditore: da verificare)`]] : []),
    ["Prefettura", p.prefecture ? `${prefName(p.prefecture)} (${PREF[p.prefecture]?.ja || ""})` : "—"],
    ["Indirizzo", p.address],
    ["Superficie casa", p.building_m2 ? `${fmtNum(p.building_m2, 1)} m²` : "—"],
    ["Terreno", p.land_m2 ? `${fmtNum(p.land_m2, 1)} m²` : "—"],
    ["Pianta", p.layout || "—"],
    ["Anno di costruzione", p.year_built ? `${p.year_built} (${new Date().getFullYear() - p.year_built} anni)` : "—"],
    ["Prezzo al m²", ppm(p) ? `${fmtAud(ppm(p) * DATA.aud_per_jpy)} · ${fmtYen(ppm(p))}` : "—"],
    ["Trasporti", p.access || "—"],
    ["Visto la prima volta", new Date(p.first_seen).toLocaleDateString("it-IT")],
  ];
  for (const [k, v] of Object.entries(p.extra || {})) if (EXTRA_IT[k] && v && typeof v === "string") rows.push([EXTRA_IT[k], v]);
  const hist = (p.price_history || []).map(([d, y]) => `<li>${new Date(d).toLocaleDateString("it-IT")}: ${fmtYen(y)} → ${fmtYen(p.price_yen)}</li>`).join("");
  const gmaps = p.latlng ? `https://www.google.com/maps/search/?api=1&query=${p.latlng[0]},${p.latlng[1]}` : `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(p.address)}`;
  const tr = (u) => `https://translate.google.com/translate?sl=ja&tl=it&u=${encodeURIComponent(u)}`;
  const rentDefault = rents[p.id] ?? (p.yield_pct && p.price_yen ? Math.round(p.price_yen * p.yield_pct / 100 / 12)
    : A.rentPerM2 && p.building_m2 ? Math.round(A.rentPerM2 * p.building_m2) : "");
  const d = $("#detail");
  d.innerHTML = `<form method="dialog">
    <header class="sheet-head"><h2>${fmtAud(p.price_aud, p.price_yen)} <span class="muted" style="font-weight:400;font-size:14px">${esc((TYPE[p.type] || [p.type])[0])} · ${esc(prefName(p.prefecture))}</span></h2>
      <div><button type="button" class="btn ghost" id="d-fav">${favs.has(p.id) ? "★" : "☆"}</button><button class="btn ghost" value="close" aria-label="Chiudi">✕</button></div></header>
    ${imgs.length ? `<div class="gallery">${imgs.map((u, i) => `<img loading="lazy" referrerpolicy="no-referrer" src="${esc(sized(u, 1024))}" data-i="${i}" alt="Foto ${i + 1} di ${imgs.length}" onerror="this.remove()">`).join("")}</div>
      <div class="gallery-count">${imgs.length} foto · tocca per ingrandire</div>` : `<div class="noimg">Nessuna foto: guarda l'annuncio originale</div>`}
    <div class="sheet-body">
      ${p.title ? `<p style="margin:0">${esc(p.title)}</p>` : ""}
      <div class="links">
        ${p.links.map((l) => `<a class="btn" target="_blank" rel="noopener" href="${esc(l.url)}">${esc(SOURCE[l.source] || l.source)} ↗</a><a class="btn ghost" target="_blank" rel="noopener" href="${tr(l.url)}">Traduci</a>`).join("")}
        <a class="btn ghost" target="_blank" rel="noopener" href="${gmaps}">Google Maps ↗</a>
      </div>
      <dl class="kv">${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
      ${hist ? `<h3>Storico prezzo</h3><ul>${hist}</ul>` : ""}
      <h3>Rendimento stimato</h3>
      <div class="calc">
        <div class="grid2">
          <label class="field">Affitto mensile atteso (¥)<input id="rent" type="number" inputmode="numeric" value="${esc(rentDefault)}" placeholder="es. 45000"></label>
          <label class="field">Equivale a<output id="rent-aud">—</output></label>
        </div>
        <div class="grid2"><div>Lordo<br><output id="y-gross">—</output></div><div>Netto stimato<br><output id="y-net">—</output></div></div>
        <p class="note">Netto = affitto × (1 − sfitto ${A.vacancyPct}%) × (1 − gestione ${A.mgmtPct}%) − tasse ${A.taxPct}% del prezzo − manutenzione A$${A.maintAud}/anno, diviso per prezzo + costi d'acquisto ${A.buyCostPct}%. Sono ipotesi tue, che puoi cambiare in ⚙︎. Non è una consulenza finanziaria.</p>
      </div>
    </div></form>`;
  const upd = () => {
    const v = +$("#rent", d).value || null;
    if (v) rents[p.id] = v; else delete rents[p.id];
    store.set("rents", rents);
    const y = yieldOf(p, v);
    $("#rent-aud", d).textContent = v ? fmtAud(v * DATA.aud_per_jpy) + "/mese" : "—";
    $("#y-gross", d).textContent = y ? y.gross.toFixed(1) + "%" : "—";
    $("#y-net", d).textContent = y ? y.net.toFixed(1) + "%" : "—";
  };
  $("#rent", d).addEventListener("input", upd); upd();
  d.querySelectorAll(".gallery img").forEach((im) => im.addEventListener("click", () => {
    const ok = [...d.querySelectorAll(".gallery img")];  // photos dropped as banners/broken are not in the viewer
    openViewer(ok.map((x) => imgs[+x.dataset.i]), Math.max(0, ok.indexOf(im)));
  }));
  $("#d-fav", d).onclick = (e) => { toggleFav(p.id); e.target.textContent = favs.has(p.id) ? "★" : "☆"; };
  d.addEventListener("close", () => { if (location.hash.startsWith("#/p/")) history.replaceState(null, "", "#"); render(); }, { once: true });
  if (!d.open) d.showModal();
}

/* full-screen photo viewer: arrows, swipe, keyboard, Esc to close */
/* same photo listed twice (different sizes/params) would need two clicks to move on: keep one */
function samePhotoKey(u) {
  if (u.startsWith("enc:")) return u;
  try {
    const x = new URL(u, location.href);
    if (x.searchParams.get("src")) return x.searchParams.get("src");
    for (const k of ["w", "h", "fmt", "q"]) x.searchParams.delete(k);
    return x.origin + x.pathname.replace(/resized-bukken-\d+x\d+-/, "") + x.search;
  } catch { return u; }
}
function uniquePhotos(list) {
  const seen = new Set();
  return list.filter((u) => { const k = samePhotoKey(u); if (seen.has(k)) return false; seen.add(k); return true; });
}
function openViewer(imgs, start) {
  const first = imgs[start];
  imgs = uniquePhotos(imgs);
  let i = Math.max(0, imgs.indexOf(first));
  const v = document.createElement("dialog");
  v.className = "viewer";
  v.innerHTML = `<img referrerpolicy="no-referrer" alt="">
    <button class="v-close" aria-label="Chiudi">✕</button>
    <button class="v-prev" aria-label="Foto precedente">‹</button><button class="v-next" aria-label="Foto successiva">›</button>
    <div class="v-count"></div>`;
  const img = v.querySelector("img");
  const show = () => {
    i = (i + imgs.length) % imgs.length;
    img.src = sized(imgs[i], 1600);
    v.querySelector(".v-count").textContent = `${i + 1} / ${imgs.length}`;
    // load the next and previous photo in the background, so moving on is instant
    for (const d of [1, -1, 2]) { const u = imgs[(i + d + imgs.length) % imgs.length]; if (u && !u.startsWith("enc:")) new Image().src = sized(u, 1600); }
  };
  v.querySelector(".v-close").onclick = () => v.close();
  v.querySelector(".v-prev").onclick = () => { i--; show(); };
  v.querySelector(".v-next").onclick = () => { i++; show(); };
  // keyboard on the whole page while the viewer is open (focus may be anywhere)
  const onKey = (e) => {
    if (e.key === "ArrowLeft") { e.preventDefault(); e.stopPropagation(); i--; show(); }
    else if (e.key === "ArrowRight") { e.preventDefault(); e.stopPropagation(); i++; show(); }
  };
  document.addEventListener("keydown", onKey, true);
  v.addEventListener("close", () => document.removeEventListener("keydown", onKey, true));
  let x0 = null;
  img.addEventListener("touchstart", (e) => (x0 = e.touches[0].clientX), { passive: true });
  img.addEventListener("touchend", (e) => {
    if (x0 === null) return;
    const dx = e.changedTouches[0].clientX - x0; x0 = null;
    if (Math.abs(dx) > 40) { i += dx < 0 ? 1 : -1; show(); }
  });
  v.addEventListener("close", () => v.remove());
  document.body.appendChild(v);
  show();
  v.showModal();
}

/* clicking the dimmed area around a card or the filters closes it (the ✕ still works) */
document.addEventListener("click", (e) => {
  const d = e.target;
  if (d.tagName !== "DIALOG" || !d.open || d.classList.contains("viewer")) return;
  const r = d.getBoundingClientRect();
  if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) d.close();
});

function toggleFav(id) {
  favs.has(id) ? favs.delete(id) : favs.add(id);
  store.set("favs", [...favs]);
}

/* ---------------------------------------------------------------- filters UI */
function initFilters() {
  const form = $("#filter-form");
  const box = $("#regions");
  const prefBoxes = () => $$("input[name=pref]", box);
  const drawRegions = (selected) => {
    const n = {};
    for (const p of DATA?.properties || []) if (p.active !== false) n[p.prefecture] = (n[p.prefecture] || 0) + 1;
    const fmt = (x) => (x || 0).toLocaleString("it-IT");
    box.innerHTML = REGIONS.map(([r, name, ja, prefs]) => {
      const tot = prefs.reduce((a, s) => a + (n[s] || 0), 0);
      const open = prefs.some((s) => selected.includes(s)) && prefs.length > 1;
      return `<div class="region ${open ? "open" : ""}" data-r="${r}">
        <div class="region-head">
          <label class="rcheck"><input type="checkbox" data-region="${r}"><span><b>${name}</b> <small class="muted">${ja}</small></span></label>
          <span class="rcount muted">${fmt(tot)}</span>
          ${prefs.length > 1 ? `<button type="button" class="rtoggle" aria-label="Mostra prefetture di ${name}" aria-expanded="${open}">▾</button>` : ""}
        </div>
        <div class="chips region-prefs" ${prefs.length > 1 ? "" : "hidden"}>${prefs.map((s) => `<label><input type="checkbox" name="pref" value="${s}" ${selected.includes(s) ? "checked" : ""}><span>${PREF[s].en} <small>${PREF[s].ja} · ${fmt(n[s])}</small></span></label>`).join("")}</div>
      </div>`;
    }).join("");
    syncRegions();
  };
  const syncRegions = () => {
    const names = [];
    for (const el of $$(".region", box)) {
      const boxes = $$("input[name=pref]", el), on = boxes.filter((c) => c.checked).length;
      const rc = el.querySelector("[data-region]");
      rc.checked = on === boxes.length; rc.indeterminate = on > 0 && on < boxes.length;
      const reg = REGIONS.find((x) => x[0] === el.dataset.r);
      if (on === boxes.length) names.push(reg[1].split(" (")[0]);
      else boxes.filter((c) => c.checked).forEach((c) => names.push(PREF[c.value].en));
    }
    $("#zone-summary").textContent = names.length ? (names.length > 4 ? `${names.slice(0, 3).join(", ")} +${names.length - 3}` : names.join(", ")) : "Tutto il Giappone";
  };
  box.addEventListener("change", (e) => {
    const r = e.target.dataset.region;
    if (r) $$(`.region[data-r="${r}"] input[name=pref]`, box).forEach((c) => (c.checked = e.target.checked));
    syncRegions();
  });
  box.addEventListener("click", (e) => {
    const t = e.target.closest(".rtoggle");
    if (!t) return;
    const el = t.closest(".region");
    el.classList.toggle("open");
    t.setAttribute("aria-expanded", el.classList.contains("open"));
  });
  const out = form.querySelector(".range output");
  let tags = (F.places || []).slice();  // applied with "Mostra risultati"
  const placeBox = tagSearch($("#place-tags"), { placeholder: "Cerca zone, prefetture, città… es. Kyushu, Beppu, 渋谷",
    get: () => tags, set: (v) => { tags = v; $("#near-row").hidden = !tags.some((x) => x.k === "place"); } });
  const write = () => {
    tags = (F.places || []).slice(); placeBox.draw(); form.elements.nearKm.value = String(F.nearKm || 20);
    $("#near-row").hidden = !tags.some((x) => x.k === "place");
    $("#zones").open = F.pref.length > 0;
    form.elements.maxAud.value = F.maxAud; out.textContent = fmtAud(F.maxAud);
    $$("input[name=type]", form).forEach((c) => (c.checked = F.type.includes(c.value)));
    drawRegions(F.pref);
    for (const k of ["minBuild", "minLand", "maxWalk", "builtAfter", "q"]) form.elements[k].value = F[k];
    form.elements.withPhotos.checked = F.withPhotos; form.elements.hideSeen.checked = F.hideSeen;
    form.elements.newOnly.checked = F.newOnly; form.elements.tenant.value = F.tenant || "all"; form.elements.noRebuild.value = F.noRebuild || "all"; form.elements.freeOnly.checked = F.freeOnly;
  };
  form.elements.maxAud.addEventListener("input", (e) => (out.textContent = fmtAud(+e.target.value)));
  $("#btn-filters").onclick = () => { write(); $("#filters").showModal(); };
  $("#reset-filters").onclick = () => { F = { ...DEFAULT_FILTERS }; write(); };
  form.addEventListener("submit", (e) => {
    if (e.submitter?.value !== "apply") return;
    F = {
      maxAud: +form.elements.maxAud.value,
      type: $$("input[name=type]:checked", form).map((c) => c.value),
      pref: prefBoxes().filter((c) => c.checked).map((c) => c.value),
      minBuild: form.elements.minBuild.value, minLand: form.elements.minLand.value,
      maxWalk: form.elements.maxWalk.value, builtAfter: form.elements.builtAfter.value,
      q: form.elements.q.value, withPhotos: form.elements.withPhotos.checked, hideSeen: form.elements.hideSeen.checked,
      newOnly: form.elements.newOnly.checked, tenant: form.elements.tenant.value, noRebuild: form.elements.noRebuild.value, freeOnly: form.elements.freeOnly.checked,
      places: tags, nearKm: +form.elements.nearKm.value || 20,
    };
    store.set("filters", F); shown = PAGE; mapTags?.draw(); render();
  });
}

function renderSettings() {
  const last = DATA.runs?.at(-1);
  const src = last ? Object.entries(last.sources || {}).map(([s, v]) => `<li>${esc(SOURCE[s] || s)}: ${fmtNum(v.found)} annunci${v.blocked ? " (bloccato dalla protezione anti-bot del sito)" : v.completed === false ? " (giro incompleto)" : ""}</li>`).join("") : "";
  const warn = (last?.warnings || []).map((w) => `<li>⚠️ ${esc(w)}</li>`).join("");
  $("#view-settings").innerHTML = `
    <section><h3>Ipotesi per il rendimento</h3>
      <div class="grid2">
        ${[["rentPerM2", "Affitto stimato (¥/m² al mese)", "lascia vuoto se non sai"], ["buyCostPct", "Costi d'acquisto (% prezzo)"], ["taxPct", "Tasse annue (% prezzo)"], ["mgmtPct", "Gestione (% affitto)"], ["maintAud", "Manutenzione (A$/anno)"], ["vacancyPct", "Sfitto (%)"]]
          .map(([k, l, ph]) => `<label class="field">${l}<input type="number" step="any" data-a="${k}" value="${esc(A[k])}" placeholder="${ph || ""}"></label>`).join("")}
      </div>
      <p class="note">L'affitto al m² serve per ordinare per rendimento anche gli immobili dove non hai inserito un affitto. Sono stime grezze: verifica sempre con un'agenzia locale.</p>
    </section>
    <section><h3>Ultimo aggiornamento</h3>
      <p>${last ? new Date(last.at).toLocaleString("it-IT") : "—"} · ${fmtNum(DATA.count)} immobili · 1 A$ = ¥${fmtNum(1 / DATA.aud_per_jpy, 1)}</p>
      <ul>${src}${warn}</ul>
    </section>
    <section><h3>Dispositivo</h3>
      <p><button class="btn" id="forget">Dimentica passphrase</button></p>
    </section>`;
  $$("[data-a]").forEach((i) => i.addEventListener("change", () => {
    A[i.dataset.a] = i.value === "" ? "" : +i.value; store.set("assume", A);
  }));
  $("#forget").onclick = () => { store.del("pass"); location.reload(); };
}

/* ---------------------------------------------------------------- boot */
function setView(v) {
  VIEW = v; shown = PAGE;
  $$(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
  $("#view-list").hidden = !["list", "new", "favs"].includes(v);
  $("#view-map").hidden = v !== "map";
  $("#view-settings").hidden = v !== "settings";
  $(".toolbar").hidden = v === "settings" || v === "map";
  // on the map the sort menu lives in the side list header; elsewhere back in the toolbar
  const sortLabel = $("#sort").closest("label");
  (v === "map" ? $("#ml-sort") : $(".toolbar")).appendChild(sortLabel);
  if (v === "settings") renderSettings(); else render();
}

function route() {
  const m = location.hash.match(/^#\/p\/(.+)$/);
  if (m) openDetail(decodeURIComponent(m[1]));
}

function boot() {
  NEW_KEYS = new Set(DATA.new_keys || []);
  for (const p of DATA.properties) p._t = new Date(p.first_seen).getTime();
  $("#lock").hidden = true; $("#app").hidden = false;
  const last = DATA.runs?.at(-1);
  $("#stats").textContent = `${fmtNum(DATA.count)} immobili · agg. ${new Date(DATA.generated).toLocaleDateString("it-IT")} · 1 A$ = ¥${fmtNum(1 / DATA.aud_per_jpy, 1)}`;
  $("#sort").value = store.get("sort", "new");
  $("#sort").onchange = () => { store.set("sort", $("#sort").value); shown = PAGE; render(); };
  $$(".tabs button").forEach((b) => (b.onclick = () => setView(b.dataset.view)));
  $("#more").onclick = () => { shown += PAGE; render(); };
  $("#cards").addEventListener("click", (e) => {
    if (e.target.closest("a.orig")) return;  // let the link open the source site
    const f = e.target.closest("[data-fav]");
    if (f) { e.stopPropagation(); toggleFav(f.dataset.fav); render(); return; }
    const c = e.target.closest(".card");
    if (c) location.hash = "#/p/" + c.dataset.id;
  });
  initFilters();
  initMapList();
  window.addEventListener("hashchange", route);
  setView("list");
  route();
}

$("#lock-form").addEventListener("submit", (e) => { e.preventDefault(); unlock($("#pass").value, $("#remember").checked); });
const saved = store.get("pass", null);
if (saved) unlock(saved, true);
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
