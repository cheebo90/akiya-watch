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
      url.searchParams.set("w", w); url.searchParams.set("h", Math.round(w * 3 / 4));
      return url.toString();
    }
    if (url.hostname.endsWith("yimg.jp") && url.pathname.includes("/bld_image/")) {
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
const DEFAULT_FILTERS = { maxAud: 80000, type: [], pref: [], minBuild: "", minLand: "", maxWalk: "", builtAfter: "", q: "", withPhotos: false, hideSeen: false, newOnly: false, withYield: false, freeOnly: false };
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
      if (F.minBuild && (p.building_m2 || 0) < +F.minBuild) return false;
      if (F.minLand && (p.land_m2 || 0) < +F.minLand) return false;
      if (F.maxWalk && (p.walk_min == null || p.walk_min > +F.maxWalk)) return false;
      if (F.builtAfter && (p.year_built || 0) < +F.builtAfter) return false;
      if (F.withPhotos && !p.images?.length) return false;
      if (F.newOnly && !p.new_build) return false;
      if (F.withYield && !p.yield_pct) return false;
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
  for (const k of ["minBuild", "minLand", "maxWalk", "builtAfter", "q"]) if (F[k]) n++;
  if (F.withPhotos) n++; if (F.hideSeen) n++; if (F.newOnly) n++; if (F.withYield) n++; if (F.freeOnly) n++;
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
    <div class="ph">${img ? `<img loading="lazy" referrerpolicy="no-referrer" src="${esc(img)}" alt="" onerror="this.parentNode.classList.add('nophoto')">` : ""}<a class="orig" target="_blank" rel="noopener" href="${esc(p.links[0].url)}">Foto sul sito originale ↗</a></div>
    <button class="fav ${favs.has(p.id) ? "on" : ""}" data-fav="${p.id}" aria-label="Preferito">${favs.has(p.id) ? "★" : "☆"}</button>
    <div class="body">
      <div class="price">${fmtAud(p.price_aud, p.price_yen)}<small>${fmtYen(p.price_yen)}</small></div>
      <div class="meta">${bits.map(esc).join(" · ")}</div>
      <div class="addr">${esc(p.address)}</div>
      <div class="badges">
        ${isNew(p) ? '<span class="badge new">Nuovo</span>' : ""}
        ${p.yield_pct ? `<span class="badge yield">Rend. ${p.yield_pct.toFixed(1)}%</span>` : ""}
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

function renderMap(list) {
  if (!map) {
    map = L.map("map", { preferCanvas: true }).setView([36.2, 138.2], 5);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap" }).addTo(map);
    cluster = L.markerClusterGroup({ chunkedLoading: true, maxClusterRadius: 50 });
    map.addLayer(cluster);
  }
  setTimeout(() => map.invalidateSize(), 50);
  cluster.clearLayers();
  const markers = [];
  for (const p of list) {
    if (!p.latlng) continue;
    const color = (TYPE[p.type] || [, "#555"])[1];
    const m = L.marker(p.latlng, { icon: L.divIcon({ className: "", html: `<div class="dot" style="background:${color}"></div>`, iconSize: [14, 14] }) });
    m.bindPopup(`<b>${fmtAud(p.price_aud, p.price_yen)}</b> ${fmtYen(p.price_yen)}<br>${esc((TYPE[p.type] || [p.type])[0])} · ${esc(p.address)}<br><a href="#/p/${p.id}">Apri scheda</a>`);
    markers.push(m);
  }
  cluster.addLayers(markers);
  if (markers.length) map.fitBounds(cluster.getBounds(), { padding: [30, 30], maxZoom: 12 });
  const missing = list.length - markers.length;
  $("#result-count").textContent = `${list.length.toLocaleString("it-IT")} immobili` + (missing ? ` (${missing} senza posizione)` : "");
}

/* ---------------------------------------------------------------- detail */
function openDetail(id) {
  const p = DATA.properties.find((x) => x.id === id || x.keys?.includes(id));
  if (!p) return;
  seen.add(p.id); store.set("seen", [...seen]);
  const imgs = p.images || [];
  const rows = [
    ["Prezzo", `${fmtAud(p.price_aud, p.price_yen)} · ${fmtYen(p.price_yen)}`],
    ["Tipo", (TYPE[p.type] || [p.type])[0] + (p.subtype ? ` (${p.subtype})` : "") + (p.new_build ? " · nuova costruzione" : "")],
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
  d.querySelectorAll(".gallery img").forEach((im) => im.addEventListener("click", () => openViewer(imgs, +im.dataset.i)));
  $("#d-fav", d).onclick = (e) => { toggleFav(p.id); e.target.textContent = favs.has(p.id) ? "★" : "☆"; };
  d.addEventListener("close", () => { if (location.hash.startsWith("#/p/")) history.replaceState(null, "", "#"); render(); }, { once: true });
  if (!d.open) d.showModal();
}

/* full-screen photo viewer: arrows, swipe, keyboard, Esc to close */
function openViewer(imgs, start) {
  let i = start;
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
  };
  v.querySelector(".v-close").onclick = () => v.close();
  v.querySelector(".v-prev").onclick = () => { i--; show(); };
  v.querySelector(".v-next").onclick = () => { i++; show(); };
  v.addEventListener("keydown", (e) => { if (e.key === "ArrowLeft") { i--; show(); } if (e.key === "ArrowRight") { i++; show(); } });
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

function toggleFav(id) {
  favs.has(id) ? favs.delete(id) : favs.add(id);
  store.set("favs", [...favs]);
}

/* ---------------------------------------------------------------- filters UI */
function initFilters() {
  const form = $("#filter-form");
  const sel = form.elements.pref;
  sel.innerHTML = PREFS.map(([s, en, ja]) => `<option value="${s}">${en} ${ja}</option>`).join("");
  const out = form.querySelector(".range output");
  const write = () => {
    form.elements.maxAud.value = F.maxAud; out.textContent = fmtAud(F.maxAud);
    $$("input[name=type]", form).forEach((c) => (c.checked = F.type.includes(c.value)));
    [...sel.options].forEach((o) => (o.selected = F.pref.includes(o.value)));
    for (const k of ["minBuild", "minLand", "maxWalk", "builtAfter", "q"]) form.elements[k].value = F[k];
    form.elements.withPhotos.checked = F.withPhotos; form.elements.hideSeen.checked = F.hideSeen;
    form.elements.newOnly.checked = F.newOnly; form.elements.withYield.checked = F.withYield; form.elements.freeOnly.checked = F.freeOnly;
  };
  form.elements.maxAud.addEventListener("input", (e) => (out.textContent = fmtAud(+e.target.value)));
  $("#btn-filters").onclick = () => { write(); $("#filters").showModal(); };
  $("#reset-filters").onclick = () => { F = { ...DEFAULT_FILTERS }; write(); };
  form.addEventListener("submit", (e) => {
    if (e.submitter?.value !== "apply") return;
    F = {
      maxAud: +form.elements.maxAud.value,
      type: $$("input[name=type]:checked", form).map((c) => c.value),
      pref: [...sel.selectedOptions].map((o) => o.value),
      minBuild: form.elements.minBuild.value, minLand: form.elements.minLand.value,
      maxWalk: form.elements.maxWalk.value, builtAfter: form.elements.builtAfter.value,
      q: form.elements.q.value, withPhotos: form.elements.withPhotos.checked, hideSeen: form.elements.hideSeen.checked,
      newOnly: form.elements.newOnly.checked, withYield: form.elements.withYield.checked, freeOnly: form.elements.freeOnly.checked,
    };
    store.set("filters", F); shown = PAGE; render();
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
  $(".toolbar").hidden = v === "settings";
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
  window.addEventListener("hashchange", route);
  setView("list");
  route();
}

$("#lock-form").addEventListener("submit", (e) => { e.preventDefault(); unlock($("#pass").value, $("#remember").checked); });
const saved = store.get("pass", null);
if (saved) unlock(saved, true);
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
