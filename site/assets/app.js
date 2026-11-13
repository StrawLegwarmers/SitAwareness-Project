/* ──────────────────────────────────────────────────────────────────────────
   Situational Awareness Project: everything the website does.
   Plain JavaScript, no framework. It only READS the JSON files that
   pipeline/export.py writes into site/data/. It never talks to an AI.

   Addresses (the part after #):
     #/geo                      Geopolitical, latest day, first page (Overview)
     #/geo/europe               the Europe page, latest day
     #/geo/2026-11-09/europe    the Europe page on 9 November
     #/geo/2026-11-09/europe/c-poland   ...scrolled to Poland
     #/cyber/threats            Cyber, "IoCs and Vulnerabilities"
     #/geo/2026-11-07..2026-11-11/europe  five days combined into one view
     #/toolkit                  OSINT links
     #/sources                  every source and how it's doing
     #/opencti                  how to connect OpenCTI, with the feed addresses
     #/watch                    your watchlist (kept in this browser only)
   Which pages exist, and what each shows, comes from "pages:" in config/<site>/site.yaml.
   ────────────────────────────────────────────────────────────────────────── */
"use strict";

const SITES = ["geo", "cyber", "markets"];                  // the sidebar, top to bottom
const S = { index: null, site: "geo", date: null, page: null, day: null, days: {}, q: "", cache: new Map() };
const $ = (id) => document.getElementById(id);
const view = $("view");
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const RANGE_RE = /^(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})$/;      // #/geo/2026-11-07..2026-11-11/europe

const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;   // the visitor turned animations off

// ── Icons ─────────────────────────────────────────────────────────────────
// Line icons drawn as inline SVG, so the site still loads nothing from elsewhere.
// Most are from Tabler Icons (https://tabler.io/icons, MIT licence, see NOTICE.md). The continents are our own
// rough outlines: recognisable, not cartographic. A page picks one with "icon:" in site.yaml.
const ICONS = {
  dashboard: '<path d="M5 4h4a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1M5 16h4a1 1 0 0 1 1 1v2a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-2a1 1 0 0 1 1-1M15 12h4a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-4a1 1 0 0 1-1-1v-6a1 1 0 0 1 1-1M15 4h4a1 1 0 0 1 1 1v2a1 1 0 0 1-1 1h-4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1"/>',
  world: '<path d="M3 12a9 9 0 1 0 18 0a9 9 0 0 0-18 0M3.6 9h16.8M3.6 15h16.8M11.5 3a17 17 0 0 0 0 18M12.5 3a17 17 0 0 1 0 18"/>',
  brief: '<path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2zM9 9h1M9 13h6M9 17h6"/>',
  plane: '<path d="M16 10h4a2 2 0 0 1 0 4h-4l-4 7H9l2-7H7l-2 2H2l2-4l-2-4h3l2 2h4L9 3h3z"/>',
  fingerprint: '<path d="M18.9 7a8 8 0 0 1 1.1 5v1a6 6 0 0 0 .8 3M8 11a4 4 0 0 1 8 0v1a10 10 0 0 0 2 6M12 11v2a14 14 0 0 0 2.5 8M8 15a18 18 0 0 0 1.8 6M4.9 19a22 22 0 0 1-.9-7v-1a8 8 0 0 1 12-6.95"/>',
  flask: '<path d="M9 3h6M10 9h4M10 3v6L6 20a.7.7 0 0 0 .5 1h11a.7.7 0 0 0 .5-1L14 9V3"/>',
  broadcast: '<path d="M18.364 19.364a9 9 0 1 0-12.728 0M15.536 16.536a5 5 0 1 0-7.072 0M11 13a1 1 0 1 0 2 0a1 1 0 1 0-2 0"/>',
  tool: '<path d="M7 10h3V7L6.5 3.5a6 6 0 0 1 8 8l6 6a2 2 0 0 1-3 3l-6-6a6 6 0 0 1-8-8L7 10"/>',
  rss: '<path d="M4 19a1 1 0 1 0 2 0a1 1 0 1 0-2 0M4 4a16 16 0 0 1 16 16M4 11a9 9 0 0 1 9 9"/>',
  link: '<path d="M9 15l6-6M11 6l.463-.536a5 5 0 0 1 7.071 7.072l-.534.464M13 18l-.397.534a5.068 5.068 0 0 1-7.127 0a4.972 4.972 0 0 1 0-7.071l.524-.463"/>',
  copy: '<path d="M7 9.667A2.667 2.667 0 0 1 9.667 7h8.666A2.667 2.667 0 0 1 21 9.667v8.666A2.667 2.667 0 0 1 18.333 21H9.667A2.667 2.667 0 0 1 7 18.333zM4.012 16.737A2 2 0 0 1 3 15V5c0-1.1.9-2 2-2h10c.75 0 1.158.385 1.5 1"/>',
  dot: '<circle cx="12" cy="12" r="3"/>',
  "info-circle": '<path d="M3 12a9 9 0 1 0 18 0a9 9 0 0 0-18 0M12 9h.01M11 12h1v4h1"/>',
  chart: '<path d="M3 3v18h18"/><path d="M7 14l4-4 3 3 6-7"/>',
  bank: '<path d="M3 21h18M5 21v-9M9.5 21v-9M14.5 21v-9M19 21v-9M2.5 9.5 12 4l9.5 5.5z"/>',
  file: '<path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2zM9 13h6M9 17h4"/>',
  book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5zM4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/>',
  eye: '<path d="M10 12a2 2 0 1 0 4 0a2 2 0 0 0-4 0"/><path d="M21 12c-2.4 4-5.4 6-9 6c-3.6 0-6.6-2-9-6c2.4-4 5.4-6 9-6c3.6 0 6.6 2 9 6"/>',
  list: '<path d="M9 6h11M9 12h11M9 18h11M5 6v.01M5 12v.01M5 18v.01"/>',
  cards: '<path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z"/>',
  briefcase: '<path d="M3 9a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 13a20 20 0 0 0 18 0"/>',
  "north-america": '<path d="M1.5 6 3.5 3.8 7 3 10 3.6 12 2.4 15 2.2 15.5 4.5 17 5.6 17.5 3.5 20.5 3.8 22 6 19.5 8.5 17.5 9.8 16.6 12 17.2 14.8 16 14.6 14.4 13.4 12.6 13.8 12.4 15.6 13.8 16.4 13.4 17.6 15.5 20.5 14.8 21 11.2 18.6 8.4 15 6.8 11.6 5 9 3.6 8.2 2.5 8.8Z"/>',
  "latin-america": '<path d="M4.2 1.4 6 2.4 8.5 4.2 11 3.2 13.5 3.6 15.5 4.6 18 5.8 20.8 8.2 21.4 10.4 19.6 13.2 17.6 14.6 16.2 17.2 14 18.6 12.8 21.2 11.6 22.6 11 20.6 10.8 17.4 10.4 14 8.4 11.4 7.2 9.2 7.4 6.8 6.8 5.4 5.6 3.6 3.8 2.2Z"/>',
  europe: '<path d="M3 17.6 2.8 14 5.8 13 6.4 10.6 9.4 9.2 11 8 11.4 5 13.8 2.6 18 1.8 16.2 4.6 14.8 7.8 17.2 7.4 21.6 8 21.8 12 18.6 13.2 17.6 16.4 15.8 15.2 14.6 15 15.2 18.2 13.8 18.8 12.2 15.6 9.6 15 7 17.8ZM6.4 8.4 6.8 4.6 8.8 5 8.6 8.2Z"/>',
  mena: '<path d="M1.5 8.6 5 7.2 9 6.8 12 7.6 14 7.6 15 6.2 17 5.4 19.5 5.2 22.4 6.8 22.6 10 20.6 10.6 21.8 12.2 22.6 13.4 20.6 15.6 17.6 17.4 16.2 16.2 15.2 13.2 14.2 11 13.4 12.8 8 13.2 3.5 13 1.5 12Z"/>',
  africa: '<path d="M5.5 6.5 7.5 3.6 10.5 2.6 13.5 3 15 4.2 17.5 4.6 19 7.2 21.8 8.2 20.2 11 18.4 12.4 18.4 15.4 16.4 18.6 14.2 21.4 12.4 21.6 11.4 18.6 11 15.4 10.2 12.6 8.2 12.2 5.4 11.4 3.2 9.4 3.4 7.6ZM19.6 16.2 20.6 15.4 20.8 17.6 19.8 18.8Z"/>',
  asia: '<path d="M1.5 5.4 5 3 10 2.2 16 2.2 21 3 22.6 5.4 20.6 6.6 19.6 9 18 10.6 17.6 12.6 16 13.6 15.4 16 14.6 13.8 13.4 12.6 12.2 13.2 11.2 15.8 9.6 12.4 7.8 11.2 5 10.6 3 9 1.5 7.4ZM20.8 8.6 22 7.6 21.8 9.6 20.6 10.8ZM14.6 18.6 17.4 17 20.4 17.4 21.6 19.6 20 21.8 16.8 21.6 14.4 20.4Z"/>',
};
const icon = (name, cls = "ic") => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"
  stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ICONS.dot}</svg>`;
// Pages without an "icon:" in site.yaml (and files from before 7c) get one by their id.
const PAGE_ICON = { geo: { overview: "dashboard", global: "world", europe: "europe", namerica: "north-america", asia: "asia",
  mena: "mena", latam: "latin-america", africa: "africa", brief: "brief" },
  cyber: { brief: "brief", industry: "briefcase", threats: "fingerprint", vendor: "flask", global: "broadcast" } };

// The title "decodes" once when the site opens: letters scramble, then lock in left to right.
function decodeTitle() {
  const el = $("brand-title"), text = el.textContent, glyphs = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#%&*/<>";
  if (REDUCED) return;
  const start = performance.now();
  let last = 0;
  const step = (now) => {
    if (now - last > 45) {
      last = now;
      let out = "", done = true;
      for (let i = 0; i < text.length; i++) {
        if (text[i] === " " || now - start >= 250 + i * 38) out += text[i];
        else { done = false; out += glyphs[Math.floor(Math.random() * glyphs.length)]; }
      }
      el.textContent = out;
      if (done) return;
    }
    requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// ── Small helpers ──────────────────────────────────────────────────────────

// Escape text before putting it in the page, so a headline can never inject HTML.
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Reports contain links written by export.py as [Outlet](https://...). Turn only those into <a>.
const md = (text) => esc(text).replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
  (m, label, url) => `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`);

// Only allow ordinary web links. A feed could (by mistake or on purpose) give a link like
// "javascript:..." that would run code when clicked; those become a harmless "#".
const safeUrl = (u) => (/^https?:\/\//i.test(String(u || "")) ? esc(u) : "#");
const ext = (url, label) => `<a href="${safeUrl(url)}" target="_blank" rel="noopener noreferrer">${label}</a>`;

const plural = (n, word) => `${esc(n)} ${n === 1 ? word : /[^aeiou]y$/.test(word) ? word.slice(0, -1) + "ies" : word + "s"}`;  // story→stories, day→days

function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return d.toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) + " UTC";
}

function fmtShort(ymd) {       // "Wed 11 Nov 2026", for the date picker
  const d = new Date(ymd + "T12:00:00Z");
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).replace(",", "");
}

function fmtDate(ymd) {
  const d = new Date(ymd + "T12:00:00Z");
  return d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
}

// "2026-11-08" -> "Sun 8 Nov"
const fmtDayShort = (ymd) => (DATE_RE.test(String(ymd || "").slice(0, 10)) ? new Date(String(ymd).slice(0, 10) + "T12:00:00Z")
  .toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }) : esc(ymd));
const addDays = (ymd, n) => new Date(Date.parse(ymd + "T12:00:00Z") + n * 864e5).toISOString().slice(0, 10);
const daysBetween = (a, b) => Math.round((Date.parse(b + "T12:00:00Z") - Date.parse(a + "T12:00:00Z")) / 864e5) + 1;
const fmtDM = (ymd) => new Date(ymd + "T12:00:00Z").toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

// The span a brief covers: normally just its own day; on catch-up days (Monday) Friday to Monday;
// or any range you pick in the calendar.
function period(day) {
  if (day.range) {
    const { from, to } = day.range, between = `between ${fmtDM(from)} and ${fmtDM(to)}`;
    return { start: from, multi: true, isRange: true, label: "in this period", since: between, recent: between,
             range: `${fmtDate(from)} to ${fmtDate(to)}`, days: daysBetween(from, to) };
  }
  const w = day.window || { days: 1, start: day.date };
  if (w.days <= 1) return { start: day.date, multi: false, label: "today", since: "today", recent: "in the last day" };
  const dow = new Date(w.start + "T12:00:00Z").toLocaleDateString("en-GB", { weekday: "long", timeZone: "UTC" });
  const span = (d) => new Date(d + "T12:00:00Z").toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" });
  return { start: w.start, multi: true, label: `since ${dow}`, since: `since ${dow}`, recent: `since ${dow}`,
           range: `${span(w.start)} to ${span(day.date)}`, days: w.days };
}

async function getJSON(url) {
  if (S.cache.has(url)) return S.cache.get(url);
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  const data = await r.json();
  S.cache.set(url, data);
  return data;
}

// Wrap search matches in <mark>, touching only text (never inside tags or links' addresses).
function highlight(root, q) {
  if (!q) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const hits = [];
  while (walker.nextNode()) if (walker.currentNode.nodeValue.toLowerCase().includes(q)) hits.push(walker.currentNode);
  for (const node of hits) {
    const text = node.nodeValue, lower = text.toLowerCase(), frag = document.createDocumentFragment();
    let i = 0, j;
    while ((j = lower.indexOf(q, i)) !== -1) {
      frag.append(text.slice(i, j));
      const m = document.createElement("mark");
      m.textContent = text.slice(j, j + q.length);
      frag.append(m);
      i = j + q.length;
    }
    frag.append(text.slice(i));
    node.replaceWith(frag);
  }
}

// ── Building blocks ───────────────────────────────────────────────────────

// new: first seen · updated: new facts reported · covered: more outlets, nothing new · unchanged: quiet
const STATUS = { new: "New", updated: "Updated", covered: "More coverage", unchanged: "Still tracked" };
const KIND = { opinion: "Opinion", analysis: "Analysis" };
const live = (s) => s.status !== "unchanged";                         // shown as a card
const fresh = (s) => s.status === "new" || s.status === "updated";   // new facts, not just more coverage
const where = (s) => s.region || s.group;      // the region a story is ABOUT (older files: its outlets' region)

// ── Things this browser remembers (never sent anywhere) ──────────────────
const mem = {
  get(k, d) { try { const v = JSON.parse(localStorage.getItem(k)); return v ?? d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
};
// "New since your last visit" was removed (less clutter): forget what it stored in this browser.
try { localStorage.removeItem("sap-seen"); } catch (e) {}
// Watchlist: words you follow (a country, a person, a company). Matching ignores case.
// A word matches at the start of a word: "Iran" finds "Iranian" but not "Tirana".
S.watch = mem.get("sap-watch", []);
const watchRe = (w) => new RegExp(`(?<![\\p{L}\\p{N}])${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`, "iu");
const watchHit = (text) => S.watch.filter((w) => watchRe(w).test(String(text || "")));
function watchHits(s) {
  if (!S.watch.length) return [];
  return watchHit([s.title, ...s.reports.map((r) => r.text), ...s.articles.map((a) => a.title)].join(" \n "));
}
S.compact = mem.get("sap-view", "cards") === "list";
S.cards = new Map();                   // story id -> [story, its day], for "Copy with sources"

// Countries: names, tiers and counts come from config/geo/countries.yaml via export.py.
const cname = (day, id) => (day.countries && day.countries[id] ? day.countries[id].name : id);
function countryLine(s, day) {
  if (!s.countries || !s.countries.length) return "";
  const scope = s.scope === "domestic" ? "Domestic" : "International";
  return `<p class="where"><span class="scope">${scope}</span> ${s.countries.map((c) => esc(cname(day, c))).join(" · ")}</p>`;
}
// The page that shows a region (the one whose "show" has group:<region>)
const regionPage = (day, region) => (pagesFor(day).find((p) => p.show.includes(`group:${region}`)) || {}).id;

// Opinion / analysis label. The outlet's own label, never the AI's judgement.
const kindTag = (a) => (KIND[a.kind] ? `<span class="kind ${esc(a.kind)}">${KIND[a.kind]}</span> ` : "");

function groupName(day, id) {
  return (day.groups.find((g) => g.id === id) || {}).name || id;
}

function headlineItem(a) {
  const tag = a.type === "state-media" ? ` · <span class="state-tag">state media</span>` : "";
  return `<li>${kindTag(a)}${ext(a.url, esc(a.title))}
    <span class="src">· ${esc(a.outlet)} · ${fmtTime(a.published)}${tag}</span></li>`;
}

// "On 12 Nov 2026, Reuters reported ..." Older files have no publication date: show the day collected.
function reportLine(r, P) {
  const text = r.published ? md(r.text) : (P.multi ? `<span class="muted">${esc(r.date.slice(5))}:</span> ` : "") + md(r.text);
  const also = (r.also || []).filter((x) => x.outlet);
  return `<li>${text}${also.length ? ` <span class="also">Also reported by ${also.map((x) =>
    `${ext(x.url, esc(x.outlet))}${x.published ? ` <span class="muted">(${esc(fmtDM(x.published.slice(0, 10)))})</span>` : ""}`).join(", ")}</span>` : ""}</li>`;
}

const regionLabel = (day, r) => (r === "global" ? "international outlets" : groupName(day, r));

// A story card: the wider story and the day's lead headline, the status in the corner, a thin
// line, then up to two reports ("On 13 Nov 2026, Reuters reported that ...") and one footer line.
// Everything else (more reports, dates mentioned, the original headlines) opens below on demand.
function card(s, day, showGroup) {
  S.cards.set(s.id, [s, day]);
  const P = period(day);
  const today = s.reports.filter((r) => r.date >= P.start);
  const earlier = s.reports.filter((r) => r.date < P.start);
  const active = live(s);
  const single = s.single_source ?? s.single_source_today;
  const stateOnly = s.state_media_only ?? s.state_media_only_today;
  const flags = [
    active && single ? `<span class="flag single" title="Only one outlet reported this ${P.label}">single source</span>` : "",
    active && stateOnly ? `<span class="flag state" title="Every source ${P.label} is government-controlled">state media only</span>` : "",
    ...watchHits(s).map((w) => `<span class="flag watch" title="On your watchlist">${icon("eye", "ic-s")}${esc(w)}</span>`),
  ].join("");

  let lead, shown = 0;
  if (today.length) {
    shown = Math.min(2, today.length);
    lead = `<ul class="reports">${today.slice(0, 2).map((r) => reportLine(r, P)).join("")}</ul>`;
  } else if (!active && earlier.length) {
    shown = 1;
    lead = `<ul class="reports">${reportLine(earlier[0], { multi: true })}</ul>`;
  } else if (s.status === "covered" && earlier.length) {
    shown = 1;
    lead = `<p class="muted small m0">More outlets covered this ${P.since}, with no new facts. Latest report:</p><ul class="reports">${reportLine(earlier[0], { multi: true })}</ul>`;
  } else {
    lead = `<p class="muted m0 small13">No checked report. See the original headlines below.</p>`;
  }
  // A story running since before this period: its wider story above the latest lead headline.
  // The button opens the earlier reporting, where the wider story's history is.
  const wider = s.label && s.label !== s.title && s.first_seen < P.start
    ? `<p class="wider"><span class="wider-tag">Wider story</span> <button type="button" class="wider-link" data-wider="${esc(s.id)}"
        title="Show the earlier reporting on this story (since ${esc(fmtDayShort(s.first_seen))})">${esc(s.label)}</button></p>` : "";
  const from = s.title_from && s.title_from.outlet ? ` title="Headline from ${esc(s.title_from.outlet)}"` : "";
  const dates = (s.dates || []).length ? `<p class="dates" title="Dates written in the articles themselves, found by code (not the AI)">Dates in the reporting: ${s.dates.map((d) =>
    `${esc(fmtDayShort(d.date))} <span class="muted">(${plural(d.outlets, "outlet")})</span>`).join(" · ")}</p>` : "";
  const more = [
    dates,
    today.length > 2 ? `<h4>All reports ${esc(P.label)}</h4><ul class="reports">${today.map((r) => reportLine(r, P)).join("")}</ul>` : "",
    earlier.length ? `<h4>Earlier reporting</h4><ul class="reports">${earlier.map((r) => reportLine(r, { multi: true })).join("")}</ul>` : "",
    `<h4>Original headlines</h4><ul class="heads">${s.articles.map(headlineItem).join("")}</ul>`,
  ].join("");
  const extra = s.reports.length - shown;
  const toggle = `${extra > 0 ? `${plural(extra, "more report")} · ` : ""}${plural(s.articles.length, "source")}`;
  const when = !active ? `last reported ${esc(fmtDayShort(s.last_updated))}` : s.first_seen < P.start ? `since ${esc(fmtDayShort(s.first_seen))}` : "";
  const place = showGroup ? esc(groupName(day, where(s))) : "";
  const n = (S.moreSeq = (S.moreSeq || 0) + 1);

  return `<article class="card ${esc(s.status)}${S.compact ? " compact" : ""}" data-story="${esc(s.id)}">
    <div class="card-head"><div class="head-main">${wider}<h3${from}>${esc(s.title)}</h3></div>
      <span class="status ${esc(s.status)}">● ${STATUS[s.status] || esc(s.status)}</span></div>
    <div class="card-rule" aria-hidden="true"></div>
    ${lead}
    <div class="card-foot">
      <button type="button" class="more-toggle" aria-expanded="false" aria-controls="more-${n}">${toggle}</button>
      ${place || when ? `<span class="since">${[place, when].filter(Boolean).join(" · ")}</span>` : ""}${flags}
      <span class="spacer"></span>
      <button type="button" class="copy" data-copy="${esc(s.id)}" aria-label="Copy with sources" title="Copy the reports with their sources, as plain text">${icon("copy", "ic-s")}</button>
    </div>
    <div class="more" id="more-${n}" hidden>${more}</div>
  </article>`;
}

// Open a card's "more" panel (the footer button does the same).
function openMore(cardEl, open = true) {
  const btn = cardEl && cardEl.querySelector(".more-toggle");
  const panel = btn && document.getElementById(btn.getAttribute("aria-controls"));
  if (!panel) return null;
  panel.hidden = !open;
  btn.setAttribute("aria-expanded", String(open));
  return panel;
}

// Plain text for pasting into a report or a chat: every sentence keeps its source link.
function storyText(s, day) {
  const plain = (t) => String(t || "").replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, "$1 <$2>");
  const place = [groupName(day, where(s)), ...(s.countries || []).map((c) => cname(day, c))].filter(Boolean).join(" · ");
  const P = period(day);
  const reps = s.reports.filter((r) => r.date >= P.start);
  const lines = [`${s.title}${place ? ` (${place})` : ""}`];
  if (s.label && s.label !== s.title) lines.push(`Wider story: ${s.label} (since ${fmtDayShort(s.first_seen)})`);
  lines.push("");
  for (const r of (reps.length ? reps : s.reports.slice(0, 3))) {
    lines.push(`- ${plain(r.text)}`);
    for (const x of r.also || []) lines.push(`  Also reported by ${x.outlet} <${x.url}>`);
  }
  lines.push("", "Sources:");
  for (const a of s.articles.slice(0, 12)) lines.push(`- ${a.outlet}: ${a.title} <${a.url}>`);
  lines.push("", `Collected automatically from public news feeds (${location.href.split("#")[0]}). Each sentence restates what one outlet reported; verify at source.`);
  return lines.join("\n");
}

// A polite announcement for screen readers ("Copied"), from the hidden live region in index.html.
function announce(text) {
  const el = $("announce");
  if (!el) return;
  el.textContent = "";
  setTimeout(() => { el.textContent = text; }, 50);
}

async function copyText(text, btn) {
  try { await navigator.clipboard.writeText(text); }
  catch (e) {
    const t = document.createElement("textarea");
    t.value = text; document.body.append(t); t.select();
    try { document.execCommand("copy"); } catch (e2) {}
    t.remove();
  }
  const old = btn.innerHTML;
  btn.textContent = "Copied";
  announce("Copied, with sources");
  setTimeout(() => { btn.innerHTML = old; }, 1500);
}

function listRows(items) {
  return items.map((a) => `<div class="row"><span class="src">${esc(a.outlet)}<br>${fmtTime(a.published)}</span>
    <span>${kindTag(a)}${ext(a.url, esc(a.title))}${a.similar ? ` <span class="muted">· and ${plural(a.similar, "similar headline")}</span>` : ""}</span></div>`).join("");
}

// A group of stories: the ones with new reporting as cards, the quiet ones folded away.
function storyGrid(day, stories, P, showGroup) {
  const active = [...stories.filter(fresh), ...stories.filter((s) => s.status === "covered")], quiet = stories.filter((s) => !live(s));
  let h = active.length ? `<div class="grid${S.compact ? " compact" : ""}">${active.map((s) => card(s, day, showGroup)).join("")}</div>`
                        : `<p class="muted">No new reporting ${P.since}.</p>`;
  if (quiet.length) h += `<details class="quiet"><summary>${plural(quiet.length, "story")} still tracked, no new reporting ${P.since}</summary>
    <div class="grid">${quiet.map((s) => card(s, day, showGroup)).join("")}</div></details>`;
  return h;
}

// ── Blocks: each returns {id, label, html}. A page is a list of blocks (config: pages → show). ──

const BLOCKS = {
  bluf(day) {
    if (!day.bluf.length) return null;
    return { html: `<section class="bluf" aria-label="Bottom line up front"><p class="bluf-label">BLUF</p><ul>${day.bluf.map((b) =>
      `<li><strong><button type="button" class="linklike" data-jump="${esc(b.story)}" title="Show this story">${esc(b.title)}</button>:</strong> ${md(b.text)}
       ${b.kind === "headline" ? `<span class="via">(headline)</span>` : ""}</li>`).join("")}</ul></section>` };
  },

  top(day, P) {
    const byId = Object.fromEntries(day.stories.map((s) => [s.id, s]));
    const top = day.top.map((id) => byId[id]).filter(Boolean);
    if (!top.length) return null;
    const byReach = top.some((s) => s.reach > 1);
    return { id: "sec-top", label: "Most reported", html: `<h2 id="sec-top">Most reported ${P.since} <span class="count">ranked by ${byReach ? "regions reporting it, then " : ""}number of outlets</span></h2>
      <div class="grid${S.compact ? " compact" : ""}">${top.map((s) => card(s, day, true)).join("")}</div>` };
  },

  // Global page: the stories reported by outlets in the most regions, wherever they happened.
  worldwide(day, P) {
    const byId = Object.fromEntries(day.stories.map((s) => [s.id, s]));
    const wide = (day.worldwide || []).map((id) => byId[id]).filter(Boolean);
    if (!wide.length) return null;
    return { id: "sec-worldwide", label: "Reported worldwide", html: `<h2 id="sec-worldwide">Reported worldwide ${P.since}
      <span class="count">ranked by how many regions' outlets reported it, then by outlets</span></h2>
      <p class="page-meta mb10">Each story also appears on the page of the region it is about.</p>
      <div class="grid${S.compact ? " compact" : ""}">${wide.map((s) => card(s, day, true)).join("")}</div>` };
  },

  // How much was collected, and how much of it the checks kept. Counted by the pipeline, not judged.
  quality(day, P) {
    const c = (day.stats || {}).coverage;
    if (!c) return null;
    const removed = day.stats.removed ?? 0, kept = c.kept ?? day.stats.reports ?? 0;
    const cell = (n, label, hint) => `<div class="q" title="${esc(hint)}"><span class="qn">${Number(n || 0).toLocaleString("en-GB")}</span><span class="ql">${esc(label)}</span></div>`;
    return { id: "sec-quality", label: "Collection", html: `<h2 id="sec-quality">Collection and checks <span class="count">${P.since}, counted by the pipeline</span></h2>
      <div class="quality">
        ${cell(c.articles, "news articles collected", "News articles from every feed (opinion, analysis and off-topic sections are kept apart)")}
        ${cell(c.reported_by_2, "events reported by 2+ outlets", "Groups of headlines about the same event, found by code before any AI")}
        ${cell(c.sent, "groups checked by the AI", "Groups reported by two or more outlets, or continuing a tracked story")}
        ${cell((c.new || 0) + (c.updated || 0), "stories with new reports", "New stories plus tracked stories with new facts")}
        ${cell(kept, "reports kept", "Sentences that passed every guardrail")}
        ${cell(removed, "sentences removed", "Sentences the guardrails rejected (see state/<site>/audit.json)")}
        ${cell(c.corroborated, "corroborations", "Another outlet reported facts already collected: added as 'also reported by'")}
        ${cell(c.waiting, "groups waiting", "Groups that didn't fit in this run's AI calls; they go first next run")}
      </div>
      ${c.failed_calls ? `<p class="small state-text">${plural(c.failed_calls, "AI call")} failed; their articles are retried on the next run.
        ${(c.errors || []).length ? `Last reason: ${esc(c.errors[c.errors.length - 1])}` : ""}</p>` : ""}
      ${c.skipped ? `<p class="small muted">${plural(c.skipped, "story")} proposed by the AI not created or extended by code (off-topic, too few articles, or not backed by the headlines). Details: <code>python pipeline/narratives.py --audit</code></p>` : ""}` };
  },

  stories(day, P) {
    let h = "";
    for (const g of day.groups) {
      const all = day.stories.filter((s) => where(s) === g.id);
      if (!all.length) continue;
      const name = day.groups.length > 1 ? esc(g.name) : "All stories";
      h += `<h2${h ? "" : ' id="sec-stories"'}>${name} <span class="count">${plural(all.filter(fresh).length, "story")} with new reporting ${P.since}</span></h2>${storyGrid(day, all, P, false)}`;
    }
    return { id: "sec-stories", label: "Stories", html: h || `<p class="muted" id="sec-stories">No stories yet.</p>` };
  },

  group(day, P, id) {
    const all = day.stories.filter((s) => where(s) === id);
    const c = BLOCKS.commentary(day, P, id);
    const C = day.countries;
    const inRegion = C ? Object.keys(C).filter((k) => C[k].region === id) : [];
    if (!inRegion.length) {      // Global, the Cyber site, and older files
      return { id: `sec-g-${id}`, label: "Stories", html: `<h2 id="sec-g-${esc(id)}">${id === "global" ? "Filed under Global" : "Stories"} <span class="count">${id === "global" ? "no single region: no country named, or countries in three or more regions" : `${plural(all.filter(fresh).length, "story")} with new reporting ${P.since}`}</span></h2>
        ${all.length ? storyGrid(day, all, P, false) : `<p class="muted">No stories tracked here yet.</p>`}${c ? c.html : ""}` };
    }
    // Each story goes under its first country that belongs to this region.
    const lead = (s) => (s.countries || []).find((k) => C[k] && C[k].region === id);
    const byCountry = {};
    for (const s of all) { const k = lead(s) || "_none"; (byCountry[k] = byCountry[k] || []).push(s); }
    const liveN = (k) => (byCountry[k] || []).filter(fresh).length;
    // A country gets its own block if it has stories, or is regional tier 1 (always shown).
    const shown = inRegion.filter((k) => byCountry[k] || C[k].regional === 1)
      .sort((a, b) => C[a].regional - C[b].regional || liveN(b) - liveN(a) || C[b].last24 - C[a].last24);
    const rest = inRegion.filter((k) => !shown.includes(k) && C[k].heads_total)
      .sort((a, b) => C[b].last24 - C[a].last24);

    // The headlines themselves live in a separate file, filled in by fillHeadlines().
    const heads = (k, open) => {
      const total = C[k].heads_total, shown = C[k].heads_shown ?? (C[k].heads || []).length;
      if (!total) return "";
      const note = total > shown ? `<p class="small muted">The newest ${shown} of ${total} ${P.multi ? P.since : "from the last 24 hours"}.</p>` : "";
      return `<details class="quiet heads"${open ? " open" : ""}><summary>Other headlines mentioning ${esc(C[k].name)} (${total})</summary>
        <div class="list mt8" data-heads="${esc(k)}"><div class="row"><span class="muted">Loading…</span></div></div>${note}</details>`;
    };
    const badges = (k) => `${C[k].regional < 3 ? `<span class="tier t${C[k].regional}" title="Regional tier, set in config/geo/countries.yaml">Tier ${C[k].regional}</span>` : ""}
      ${C[k].hotspot ? `<span class="hot" title="${C[k].last24} headlines in 24 hours; its usual share of the news would be about ${C[k].avg7}">Hotspot</span>` : ""}`;

    let h = `<nav class="jump" aria-label="Countries">${shown.map((k) => `<button type="button" data-goto="c-${esc(k)}">${esc(C[k].name)}${C[k].hotspot ? " ●" : ""}</button>`).join("")}
      ${rest.length ? `<button type="button" data-goto="c-more">More countries</button>` : ""}${c ? `<button type="button" data-goto="${c.id}">Opinion and analysis</button>` : ""}</nav>`;
    for (const k of shown) {
      const stories = byCountry[k] || [];
      h += `<section class="country" id="c-${esc(k)}"><h2>${esc(C[k].name)} ${badges(k)}
        <span class="count">${plural(liveN(k), "story")} with new reporting · ${plural(C[k].last24, "headline")} ${day.range ? "in this period" : "in 24h"}</span></h2>
        ${stories.length ? storyGrid(day, stories, P, false) : `<p class="muted">No story with new reporting ${P.since}.</p>`}
        ${heads(k, !stories.length && C[k].heads_total <= 4)}</section>`;
    }
    if (byCountry._none) h += `<section class="country"><h2>Other stories <span class="count">no country identified</span></h2>${storyGrid(day, byCountry._none, P, false)}</section>`;
    if (rest.length) h += `<section class="country" id="c-more"><h2>More countries <span class="count">mentioned in headlines, no story yet</span></h2>
      ${rest.map((k) => `<div id="c-${esc(k)}" class="more-country"><h3>${esc(C[k].name)} ${badges(k)}</h3>${heads(k, false)}</div>`).join("")}</section>`;
    // Multi-region stories live on Global; list the ones that involve this region.
    const elsewhere = day.stories.filter((s) => where(s) !== id && live(s) && (s.countries || []).some((k) => C[k] && C[k].region === id));
    if (elsewhere.length) h += `<section class="country"><h2>Involving this region, on other pages <span class="count">${plural(elsewhere.length, "story")}</span></h2>
      <ul class="mini">${elsewhere.map((s) => `<li><a href="${pageHref(regionPage(day, where(s)) || "")}">${esc(s.title)}</a>
        <span class="muted">· ${esc(groupName(day, where(s)))}</span></li>`).join("")}</ul></section>`;
    return { id: `sec-g-${id}`, label: "Stories", html: h + (c ? c.html : "") };
  },

  // Overview: every country mentioned in the last day, hotspots first, then by global tier.
  countries(day, P) {
    const C = day.countries;
    if (!C) return null;
    const list = Object.entries(C).filter(([, c]) => c.last24 || c.global === 1)
      .sort(([, a], [, b]) => (b.hotspot - a.hotspot) || (a.global - b.global) || (b.last24 - a.last24)).slice(0, 48);
    const anyHot = list.some(([, c]) => c.hotspot);
    return { id: "sec-countries", label: "Countries", html: `<h2 id="sec-countries">Countries in the news <span class="count">headlines ${day.range ? "in this period" : "in the last 24 hours"}${anyHot ? ", hotspots first" : ""}</span></h2>
      <div class="chips">${list.map(([k, c]) => `<a class="chip${c.hotspot ? " is-hot" : ""}${c.global === 1 ? " t1" : ""}" href="${pageHref((regionPage(day, c.region) || "") + `/c-${k}`)}"
        title="${c.hotspot ? `Hotspot: ${c.last24} headlines, usually about ${c.avg7}` : `Global tier ${c.global}`}">${esc(c.name)} <span class="n">${c.last24}</span></a>`).join("")}</div>
      ${anyHot ? "" : `<p class="small muted">Hotspots appear once the database holds a few days of history (a country with at least twice its usual number of headlines).</p>`}` };
  },

  regions(day, P) {
    const pages = pagesFor(day).filter((p) => p.show.some((b) => b.startsWith("group:")));
    const cards = pages.map((p) => {
      const ids = p.show.filter((b) => b.startsWith("group:")).map((b) => b.slice(6));
      const all = day.stories.filter((s) => ids.includes(where(s)));
      const act = all.filter(fresh);
      const n = act.filter((s) => s.status === "new").length;
      return `<section class="card region">
        <div class="card-top">${n ? `<span class="badge new">${n} new</span>` : ""}<span>${plural(act.length, "story")} with new reporting</span></div>
        <h3><a href="${pageHref(p.id)}">${esc(p.name)}</a></h3>
        ${act.length ? `<ul class="mini">${act.slice(0, 4).map((s) => `<li><span class="badge ${s.status}">${STATUS[s.status]}</span> ${esc(s.title)}
          <span class="muted">· ${plural(s.outlets_period ?? 0, "outlet")}</span></li>`).join("")}</ul>` : `<p class="muted small">No new reporting ${P.since}.</p>`}
        ${act.length > 4 ? `<a class="small" href="${pageHref(p.id)}">and ${act.length - 4} more →</a>` : ""}
      </section>`;
    });
    return { id: "sec-regions", label: "Regions", html: `<h2 id="sec-regions">Regions at a glance <span class="count">most reported first</span></h2>
      <div class="grid">${cards.join("")}</div>` };
  },

  // Opinion and analysis: shown, labelled, never turned into reports or counted.
  commentary(day, P, groupId) {
    const items = (day.commentary || []).filter((c) => !groupId || c.group === groupId);
    if (!items.length) return null;
    const id = `sec-comment${groupId ? "-" + groupId : ""}`;
    return { id, label: "Opinion and analysis", html: `<h2 id="${id}">Opinion and analysis <span class="count">${plural(items.length, "piece")}, labelled by the outlets themselves</span></h2>
      <p class="page-meta mb10">Commentary is collected but kept apart: it is never restated in a report and never counted as an outlet reporting a story.</p>
      <details class="quiet" ${items.length <= 6 ? "open" : ""}><summary>Show ${plural(items.length, "piece")}</summary>
      <div class="list mt10">${listRows(items)}</div></details>` };
  },

  // Many industries, so the block opens with a row of industry buttons (with counts),
  // and each industry shows its newest 12 headlines with the rest folded under "Show more".
  industries(day, P) {
    const inds = day.industries || [];
    if (!inds.length) return null;
    const byId = Object.fromEntries(day.stories.map((s) => [s.id, s]));
    const SHOW = 12;
    let html = inds.length > 1 ? `<nav class="jump" aria-label="Industries">${inds.map((ind) =>
      `<button type="button" data-goto="sec-ind-${esc(ind.id)}">${esc(ind.name)} <span class="n">${ind.items.length}</span></button>`).join("")}</nav>` : "";
    html += inds.map((ind) => {
      const cards = ind.stories.map((id) => byId[id]).filter(Boolean);
      let h = `<h2 id="sec-ind-${esc(ind.id)}">${esc(ind.name)} <span class="count">${plural(ind.items.length, "headline")} from all sources ${P.recent}</span></h2>`;
      if (cards.length) h += `<h3 class="sub">Stories</h3><div class="grid">${cards.map((s) => card(s, day, false)).join("")}</div>`;
      if (!ind.items.length) return h + `<p class="muted">Nothing matched ${P.since}. Keywords are in <code>config/cyber/industries.yaml</code>.</p>`;
      h += `<h3 class="sub">Matching headlines, from every source</h3><div class="list">${listRows(ind.items.slice(0, SHOW))}</div>`;
      if (ind.items.length > SHOW) h += `<details class="quiet"><summary>Show ${ind.items.length - SHOW} more</summary>
        <div class="list mt8">${listRows(ind.items.slice(SHOW))}</div></details>`;
      return h;
    }).join("");
    return { id: inds.length > 1 ? "sec-industries" : `sec-ind-${inds[0].id}`, label: inds.length > 1 ? "Industries" : inds[0].name,
             html: `<div id="sec-industries"></div>${html}` };
  },

  vulns(day, P) {
    const v = day.vulns;
    if (!v) return null;
    const nvd = (cve) => `https://nvd.nist.gov/vuln/detail/${encodeURIComponent(cve)}`;
    let h = `<h2 id="sec-vulns">Exploited vulnerabilities <span class="count">CISA KEV and CVEs in the news</span></h2>
      <h3 class="sub">Added to CISA's Known Exploited Vulnerabilities catalog ${P.recent}</h3>`;
    h += v.kev_new.length ? `<div class="list">${v.kev_new.map((k) => `<div class="row"><span class="src">${ext(nvd(k.cve), esc(k.cve))}<br>added ${esc(k.date_added)}</span>
        <span><strong>${esc(k.vendor)} ${esc(k.product)}</strong>: ${esc(k.name)}${k.ransomware === "Known" ? ` <span class="flag state">known ransomware use</span>` : ""}
        <span class="small muted">${esc(k.description)} Federal fix deadline ${esc(k.due_date)}.</span></span></div>`).join("")}</div>`
      : `<p class="muted">Nothing added ${P.since}.</p>`;
    h += `<h3 class="sub">CVEs mentioned in the news ${P.recent}</h3>`;
    h += v.in_news.length ? `<div class="list">${v.in_news.map((c) => `<div class="row"><span class="src">${ext(nvd(c.cve), esc(c.cve))}<br>${plural(c.outlets, "outlet")}</span>
        <span>${c.kev ? `<span class="flag state">exploited (KEV since ${esc(c.kev.date_added)})</span> <strong>${esc(c.kev.vendor)} ${esc(c.kev.product)}</strong><br>` : ""}
        ${c.articles.map((a) => `${ext(a.url, esc(a.title))} <span class="muted">(${esc(a.outlet)})</span>`).join("<br>")}</span></div>`).join("")}</div>`
      : `<p class="muted">No CVE numbers in the news ${P.since}.</p>`;
    return { id: "sec-vulns", label: "Exploited vulnerabilities", html: h };
  },

  iocs(day) {
    const io = day.iocs;
    if (!io) return null;
    let h = `<h2 id="sec-iocs">New IOCs <span class="count">${plural(io.total, "indicator")}, defanged, never clickable</span></h2>`;
    if (!io.total) return { id: "sec-iocs", label: "New IOCs", html: h + `<p class="muted">No new indicators in this period.</p>` };
    h += `<p class="page-meta mb12">From the indicator lists that vendors publish in their research reports, plus tracker feeds.
      Every value is defanged (<code>example[.]com</code>, <code>hxxp://</code>), so nothing here is a working link.
      ${io.csv ? `<a href="${esc(io.csv)}" download>Download all as CSV</a>` : ""}
      ${io.csvs ? `CSV per day: ${io.csvs.map((c) => `<a href="${esc(c.url)}" download>${esc(fmtDM(c.date))}</a>`).join(" · ")}` : ""}</p>`;
    h += `<div class="grid">${io.groups.map((g) => `<section class="card ioc">
      <div class="card-top"><span class="badge ${g.kind === "report" ? "updated" : "unchanged"}">${g.kind === "report" ? "Research report" : "Tracker"}</span><span>${esc(g.source)}</span></div>
      <h3>${g.url ? ext(g.url, esc(g.title)) : esc(g.title)}</h3>
      <p class="muted m0 small13">${Object.entries(g.counts).map(([t, n]) => `${n} ${esc(t)}`).join(" · ")}</p>
      <details class="more"><summary>Show indicators</summary>${Object.entries(g.items).map(([t, vals]) =>
        `<h4>${esc(t.toUpperCase())}</h4><pre class="iocs">${vals.map(esc).join("\n")}</pre>`).join("")}</details>
    </section>`).join("")}</div>`;
    return { id: "sec-iocs", label: "New IOCs", html: h };
  },

  // ── Markets ──
  // A quiet line under the page header (top: true puts it above the "on this page" buttons).
  disclaimer() {
    return { top: true, html: `<p class="page-note" role="note">${icon("info-circle", "ic-s")}What outlets and official bodies published, collected
      and linked; the AI only restates reported facts, each with its source, and figures come from official data. Not investment advice.</p>` };
  },

  // Official rates and prices, read by code (pipeline/markets_data.py). A value that couldn't be
  // fetched says so; it is never shown as zero or as an older number.
  rates(day) {
    const m = day.markets;
    if (!m) return null;
    const id = "sec-rates", rows = m.rates || [];
    let h = `<h2 id="${id}">Rates and prices <span class="count">official data${m.generated ? `, read ${esc(fmtTime(m.generated))}` : ""}</span></h2>`;
    if (!rows.length) return { id, label: "Rates and prices", html: h + `<p class="muted">Not collected in this run.</p>` };
    const minus = (x) => (x < 0 ? "−" : "+");
    const decimals = (v) => Math.min(4, Math.max(2, (String(v).split(".")[1] || "").length));
    const value = (r) => (r.unit === "%" ? `${r.value.toFixed(decimals(r.value))}%` : r.unit.startsWith("$") ? `$${r.value.toFixed(2)}` : String(r.value));
    const change = (r) => {
      if (r.change == null) return "";
      if (Math.abs(r.change) < 1e-9) return "unchanged";
      if (r.unit === "%") return `${minus(r.change)}${Math.abs(Math.round(r.change * 100))} bp`;
      if (r.unit.startsWith("$")) return `${minus(r.change)}${Math.abs(r.change).toFixed(2)} (${minus(r.change)}${Math.abs(r.change / r.previous * 100).toFixed(1)}%)`;
      return `${minus(r.change)}${Math.abs(r.change).toFixed(decimals(r.value))}`;
    };
    let group = "", body = "";
    for (const r of rows) {
      if (r.group !== group) { group = r.group; body += `<tr class="grp"><th colspan="4" scope="colgroup">${esc(group)}</th></tr>`; }
      const unit = r.unit === "%" ? "" : r.unit.startsWith("$") ? ` <span class="muted">${esc(r.unit)}</span>` : "";
      body += r.value == null
        ? `<tr><th scope="row">${esc(r.name)}</th><td colspan="2" class="muted">not available (${esc(r.error || "no data")})</td><td>${ext(r.url, esc(r.source))}</td></tr>`
        : `<tr><th scope="row">${esc(r.name)}</th><td class="num">${esc(value(r))}${unit}${r.stale ? ` <span class="flag single" title="Older than a week">stale</span>` : ""}</td>
            <td class="num" title="${r.previous_date ? `From ${esc(r.previous)} on ${esc(fmtDM(r.previous_date))}` : ""}">${esc(change(r))}</td>
            <td>${esc(fmtDM(r.date))} · ${ext(r.url, esc(r.source))}</td></tr>`;
    }
    h += `<div class="table-wrap"><table class="rates"><thead><tr><th scope="col">Rate or price</th><th scope="col" class="num">Latest</th>
      <th scope="col" class="num">Change</th><th scope="col">Date and source</th></tr></thead><tbody>${body}</tbody></table></div>
      <p class="page-meta mt8">Each value is the latest its source has published, for the date shown; the change is from the source's
      previous value (bp = basis points, hundredths of a percentage point). Exchange rates are the ECB's daily reference rates, not market
      closes. Stock index levels are licensed data and are not shown.</p>`;
    return { id, label: "Rates and prices", html: h };
  },

  calendar(day) {
    const c = (day.markets || {}).calendar;
    if (!c) return null;
    const id = "sec-calendar", ev = c.events || [];
    let h = `<h2 id="${id}">The next 7 days <span class="count">central bank decisions, US data releases, Treasury auctions</span></h2>`;
    if (!ev.length) h += `<p class="muted">Nothing scheduled in the calendars read.</p>`;
    const days = [...new Set(ev.map((e) => e.date))];
    h += days.map((d) => `<h3 class="sub">${esc(fmtDayShort(d))}</h3><div class="list">${ev.filter((e) => e.date === d).map((e) =>
      `<div class="row"><span class="src">${esc(e.time || "")}${e.time ? "<br>" : ""}${esc(e.kind)}</span>
        <span>${esc(e.title)} <span class="muted">· ${ext(e.url, esc(e.source))}</span></span></div>`).join("")}</div>`).join("");
    h += `<p class="page-meta mt8">Dates and times as the publishers list them (US releases in Eastern time). No forecasts or consensus
      numbers. Central bank dates come from <code>config/markets/calendar.yaml</code>${c.central_banks_until ? `, entered up to ${esc(fmtDM(c.central_banks_until))} ${esc(c.central_banks_until.slice(0, 4))}` : ""}.
      ${(c.problems || []).length ? `Not read this time: ${c.problems.map(esc).join("; ")}.` : ""}</p>`;
    return { id, label: "Calendar", html: h };
  },

  filings(day) {
    const f = (day.markets || {}).filings;
    if (!f) return null;
    const id = "sec-filings";
    let h = `<h2 id="${id}">Company filings <span class="count">SEC 8-K current reports by US-listed companies, last day</span></h2>`;
    if (!f.configured) return { id, label: "Company filings", html: h + `<p class="muted">Not collected: set the <code>SEC_CONTACT_EMAIL</code>
      repository secret (the SEC asks every automated request for a contact address). See the Markets documentation.</p>` };
    if (f.error) return { id, label: "Company filings", html: h + `<p class="muted">SEC EDGAR could not be read in this run (${esc(f.error)}).</p>` };
    const groups = f.groups || [];
    h += `<p class="page-meta mb12">${plural(f.listed || 0, "filing")} by listed companies (of ${esc(f.read || 0)} read), by the kind of event the
      company reports. Shown as filed: open the filing for what it says. Companies without a ticker (funds, private issuers) are left out.</p>`;
    if (groups.length > 1) h += `<nav class="jump" aria-label="Filing types">${groups.map((g) =>
      `<button type="button" data-goto="f-${esc(g.item.replace(".", "-"))}">${esc(g.label)} <span class="n">${g.filings.length}</span></button>`).join("")}</nav>`;
    const SHOW = 15;
    const rowsOf = (list) => list.map((x) => `<div class="row"><span class="src">${esc(x.ticker)}<br>${esc(fmtDM(x.filed))}</span>
      <span>${ext(x.url, esc(x.company))} <span class="muted">· ${esc(x.form)} · items ${esc(x.items.join(", "))}</span></span></div>`).join("");
    h += groups.map((g) => `<h3 class="sub" id="f-${esc(g.item.replace(".", "-"))}">${esc(g.label)} <span class="count">Item ${esc(g.item)} · ${g.filings.length}</span></h3>
      <div class="list">${rowsOf(g.filings.slice(0, SHOW))}</div>${g.filings.length > SHOW ? `<details class="quiet"><summary>Show ${g.filings.length - SHOW} more</summary>
      <div class="list mt8">${rowsOf(g.filings.slice(SHOW))}</div></details>` : ""}`).join("") || `<p class="muted">No filings of these kinds in the last day.</p>`;
    return { id, label: "Company filings", html: h };
  },

  // Geopolitical stories about market topics (oil, sanctions, tariffs...), linked to their page.
  geolinks(day) {
    const g = (day.markets || {}).geo || [];
    if (!g.length) return null;
    const geo = S.days.geo;
    const href = (s) => (geo ? hrefFor("geo", regionPage(geo, s.region) || pagesFor(geo)[0].id) : "#/geo");
    return { id: "sec-geolinks", label: "From the Geopolitical brief", html: `<h2 id="sec-geolinks">From the Geopolitical brief
      <span class="count">${plural(g.length, "story")} mentioning energy, trade, sanctions and other market topics</span></h2>
      <ul class="mini">${g.map((s) => `<li><a href="${href(s)}">${esc(s.title)}</a> <span class="muted">· ${s.label && s.label !== s.title ? `${esc(s.label)} · ` : ""}${plural(s.outlets_period || 0, "outlet")} · ${esc((s.terms || []).join(", "))}</span></li>`).join("")}</ul>` };
  },

  // Cyber: material cybersecurity incidents US-listed companies disclosed to the SEC (Markets data).
  secincidents(day) {
    const x = day.sec_incidents;
    if (!x) return null;
    const id = "sec-secinc";
    let h = `<h2 id="${id}">Incidents disclosed to the SEC <span class="count">8-K Item 1.05, material cybersecurity incidents, last day</span></h2>`;
    if (!x.configured) return { id, label: "SEC disclosures", html: h + `<p class="muted">Not collected: needs the <code>SEC_CONTACT_EMAIL</code> secret (see the Markets documentation).</p>` };
    if (x.error) return { id, label: "SEC disclosures", html: h + `<p class="muted">SEC EDGAR could not be read in this run (${esc(x.error)}).</p>` };
    h += x.filings.length ? `<div class="list">${x.filings.map((f) => `<div class="row"><span class="src">${esc(f.ticker)}<br>${esc(fmtDM(f.filed))}</span>
      <span>${ext(f.url, esc(f.company))} <span class="muted">· ${esc(f.form)} · items ${esc(f.items.join(", "))}</span></span></div>`).join("")}</div>`
      : `<p class="muted">None filed in the last day.</p>`;
    return { id, label: "SEC disclosures", html: h };
  },

  list(day, P, section) {
    const list = (day.lists || []).find((l) => l.id === section);
    if (!list) return null;
    const id = `sec-list-${section}`;
    return { id, label: list.name, html: `<h2 id="${id}">${esc(list.name)} <span class="count">${plural(list.items.length, "headline")} from the last ${plural(list.days || 1, "day")}, straight from the feeds</span></h2>
      ${list.items.length ? `<div class="list">${listRows(list.items)}</div>` : `<p class="muted">No headlines in this period.</p>`}` };
  },
};

// ── Pages and the sidebar ─────────────────────────────────────────────────

// Older files have no "pages": show everything on one page, as before.
function pagesFor(day) {
  if (day.pages && day.pages.length) return day.pages;
  const show = ["bluf", "top", "stories", "industries", "vulns", "iocs", ...(day.lists || []).map((l) => `list:${l.id}`)];
  return [{ id: "brief", name: "Brief", show }];
}

// A link to a page of either site, keeping the current date when that site has it.
function hrefFor(site, page) {
  const info = S.index.sites[site];
  const d = S.range ? `/${S.range.from}..${S.range.to}` : info && info.dates.includes(S.date) ? `/${S.date}` : "";
  return `#/${site}${d}/${page}`;
}
const pageHref = (id) => hrefFor(S.site, id);

function renderBlock(day, P, name) {
  const [kind, arg] = name.split(":");
  const fn = BLOCKS[kind];
  return fn ? fn(day, P, arg) : null;
}

// One sidebar for everything: Geopolitical pages, Cyber pages, then the Toolkit.
function renderSidebar() {
  let h = "";
  for (const site of SITES) {
    const day = S.days[site];
    if (!day) continue;
    // No counts next to pages (less clutter); the page itself says what's new.
    h += `<p class="side-label">${esc(S.index.sites[site].label)}</p>`;
    h += pagesFor(day).map((p) => {
      const here = S.site === site && S.page === p.id && !S.q.trim();
      return `<a href="${hrefFor(site, p.id)}"${here ? ' aria-current="page"' : ""}>${icon(p.icon || (PAGE_ICON[site] || {})[p.id])}
        <span class="label">${esc(p.name)}</span></a>`;
    }).join("");
  }
  const fails = (S.index && S.index.sources_failing) || 0;      // the one warning kept: a small dot
  h += `<p class="side-label">Yours</p>` + `<a href="#/watch"${S.site === "watch" ? ' aria-current="page"' : ""}>${icon("eye")}<span class="label">Watchlist</span></a>`;
  h += `<p class="side-label">Reference</p>` + [["toolkit", "Toolkit", "tool", ""],
    ["sources", "Sources", "rss", fails ? `<span class="dot bad" role="img" aria-label="${fails} failing" title="${plural(fails, "feed")} failing"></span>` : ""],
    ["opencti", "OpenCTI", "link", ""]].map(([id, name, ic, n]) =>
    `<a href="#/${id}"${S.site === id ? ' aria-current="page"' : ""}>${icon(ic)}<span class="label">${name}</span>${n}</a>`).join("");
  const day = S.days[S.site] || S.days.geo;
  if (day) {
    const removed = day.stats.removed ?? day.stats.removed_today ?? 0;
    h += `<p class="side-status">Updated ${esc(fmtTime(day.generated))}<br>${plural(day.stats.sources, "source")} · ${plural(removed, "sentence")} removed by checks</p>`;
  }
  $("sidebar").innerHTML = h;
}

function renderPage(day, page) {
  const P = period(day);
  const label = S.index.sites[day.site].label;
  const first = page.id === pagesFor(day)[0].id;
  const when = P.isRange ? `${fmtDM(day.range.from)} – ${fmtDate(day.range.to)}` : fmtDate(day.date);
  let h = `<p class="kicker">${esc(label)} · ${esc(when)}</p>
    <h1>${first ? `${esc(label)} ${P.isRange ? `· ${plural(P.days, "day")}` : P.multi ? "catch-up" : "brief"}` : esc(page.name)}</h1>
    ${P.isRange ? `<p class="catchup">This view combines <strong>${plural(day.range.files, "daily brief")}</strong> from ${esc(P.range)}. Counts and reports cover the whole period.</p>`
      : P.multi ? `<p class="catchup">Catch-up: this brief covers <strong>${esc(P.range)}</strong>, so nothing reported in between is missed.</p>` : ""}`;
  const meta = first ? `${plural(day.stories.filter(fresh).length, "story")} with new reporting ${P.since} · ${plural(day.stats.reports ?? day.stats.reports_today, "attributed report")}
      · ${plural(day.stats.sources, "source")} · updated ${fmtTime(day.generated)}` : `Updated ${fmtTime(day.generated)}`;
  h += `<div class="pagebar"><p class="page-meta">${meta}</p>
    <div class="viewswitch" role="group" aria-label="Show stories as">
      <button type="button" data-view="cards" aria-pressed="${!S.compact}" title="Cards">${icon("cards", "ic-s")}Cards</button>
      <button type="button" data-view="list" aria-pressed="${S.compact}" title="Compact list">${icon("list", "ic-s")}List</button></div></div>`;

  const all = page.show.map((b) => renderBlock(day, P, b)).filter(Boolean);
  const blocks = all.filter((b) => !b.top);
  h += all.filter((b) => b.top).map((b) => b.html).join("");
  const jumps = blocks.filter((b) => b.label);
  if (jumps.length > 2) h += `<nav class="jump" aria-label="On this page">${jumps.map((b) =>
    `<button type="button" data-goto="${esc(b.id)}">${esc(b.label)}</button>`).join("")}</nav>`;
  h += blocks.map((b) => b.html).join("") || `<p class="empty">Nothing on this page yet.</p>`;

  view.innerHTML = h;
  fold(view, `${day.site}:${page.id}`);
  wire();
  fillHeadlines(day);
  const removed = day.stats.removed ?? day.stats.removed_today;
  $("footer-stats").textContent = removed
    ? `${P.multi ? "In this period" : "Today"} the guardrails removed ${plural(removed, "AI-written sentence")} that failed the checks.` : "";
}

// ── Foldable sections ─────────────────────────────────────────────────────
// Every section heading (h2) and sub-heading (h3.sub) folds what follows it, up to the next
// heading of the same level. Your browser remembers what you folded (nothing is sent anywhere).
const FOLDED_KEY = "sap-folded";
let foldCount = 0;
function foldedSet() {
  try { return new Set(JSON.parse(localStorage.getItem(FOLDED_KEY) || "[]")); } catch (e) { return new Set(); }
}
function saveFolded(set) {
  try { localStorage.setItem(FOLDED_KEY, JSON.stringify([...set].slice(-300))); } catch (e) {}
}

function fold(root, prefix) {
  const folded = foldedSet();
  root.querySelectorAll("h2, h3.sub").forEach((h) => {
    const sub = h.matches("h3.sub");
    const body = document.createElement("div");
    body.className = "fold-body";
    let n = h.nextElementSibling;
    while (n && !(n.tagName === "H2" || n.matches("section.country") || (sub && n.matches("h3.sub")))) {
      const next = n.nextElementSibling;
      body.append(n);
      n = next;
    }
    if (!body.childElementCount) return;
    h.after(body);
    const name = (h.firstChild && h.firstChild.textContent || h.textContent).trim().slice(0, 60);
    const key = `${prefix}:${h.id || name}`;
    body.id = body.id || `fold-${++foldCount}`;
    // The heading stays a heading; a button inside it opens and closes the section (WAI-ARIA disclosure).
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "fold-btn";
    btn.setAttribute("aria-controls", body.id);
    if (h.querySelector("a, button")) {          // links can't go inside a button: a small button before them
      btn.classList.add("icon-only");
      btn.setAttribute("aria-label", `Show or hide: ${name}`);
      h.prepend(btn);
    } else {
      btn.append(...h.childNodes);
      h.append(btn);
    }
    h.classList.add("fold");
    const set = (closed) => { h.classList.toggle("closed", closed); body.hidden = closed; btn.setAttribute("aria-expanded", String(!closed)); };
    set(folded.has(key));
    btn.addEventListener("click", () => {
      const s = foldedSet(), closed = !h.classList.contains("closed");
      closed ? s.add(key) : s.delete(key);
      saveFolded(s);
      set(closed);
    });
    h._unfold = () => set(false);
  });
}

// Make sure something is visible: open every folded section around it.
function reveal(el) {
  for (let n = el; n && n !== view; n = n.parentElement) {
    if (n.classList && n.classList.contains("fold-body") && n.hidden) n.previousElementSibling._unfold?.();
  }
  if (el.classList && el.classList.contains("closed")) el._unfold?.();
}

function wire() {
  view.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", () => {
    const [s, day] = S.cards.get(b.dataset.copy) || [];
    if (s) copyText(storyText(s, day), b);
  }));
  view.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => {
    S.compact = b.dataset.view === "list";
    mem.set("sap-view", S.compact ? "list" : "cards");
    const y = window.scrollY;
    route().then(() => window.scrollTo(0, y));
  }));
  view.querySelectorAll("[data-goto]").forEach((b) => b.addEventListener("click", () => {
    const t = document.getElementById(b.dataset.goto);
    if (t) { reveal(t); t.scrollIntoView({ behavior: "smooth", block: "start" }); }
  }));
  // Clicking a BLUF title scrolls to its card and opens it.
  view.querySelectorAll("[data-jump]").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    const cards = view.querySelectorAll(`[data-story="${CSS.escape(a.dataset.jump)}"]`);
    const target = cards[cards.length - 1];
    if (target) { reveal(target); target.scrollIntoView({ behavior: "smooth", block: "start" }); openMore(target); }
  }));
  // A card's footer button: show or hide everything else about the story.
  view.querySelectorAll(".more-toggle").forEach((b) => b.addEventListener("click", () => {
    openMore(b.closest(".card"), b.getAttribute("aria-expanded") !== "true");
  }));
  // "Wider story": open this card's earlier reporting and bring it into view.
  view.querySelectorAll("[data-wider]").forEach((b) => b.addEventListener("click", () => {
    const more = openMore(b.closest(".card"));
    if (!more) return;
    const h = [...more.querySelectorAll("h4")].find((x) => x.textContent.startsWith("Earlier")) || more;
    h.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }));
}

// Per-country headlines come from their own file, downloaded only when a page needs them.
async function headlinesFor(day) {
  const files = Array.isArray(day.headlines) ? day.headlines : day.headlines ? [day.headlines] : [];
  if (!files.length) return null;
  const out = {};
  for (const f of files) {            // a date range has one file per day: merge them, newest first
    try {
      const h = await getJSON(f);
      for (const [k, idx] of Object.entries(h.by_country)) (out[k] = out[k] || []).push(...idx.map((i) => h.items[i]));
    } catch (e) { /* a missing day just has no extra headlines */ }
  }
  const cap = files.length > 1 ? 50 : 25;
  for (const k of Object.keys(out)) {
    const seen = new Set();
    out[k] = out[k].filter((a) => !seen.has(a.url) && seen.add(a.url)).sort((a, b) => (b.published || "").localeCompare(a.published || "")).slice(0, cap);
  }
  return out;
}

async function fillHeadlines(day) {
  const slots = view.querySelectorAll("[data-heads]");
  if (!slots.length) return;
  const C = day.countries || {};
  const byCountry = (await headlinesFor(day)) || {};
  slots.forEach((el) => {
    const items = byCountry[el.dataset.heads] || (C[el.dataset.heads] || {}).heads || [];   // older files kept them inline
    el.innerHTML = items.length ? listRows(items) : `<div class="row"><span class="muted">Couldn't load these headlines.</span></div>`;
  });
}

async function renderSearch(day, q) {
  const label = S.index.sites[day.site].label;
  const hay = (s) => [s.title, ...s.reports.map((r) => r.text), ...s.articles.map((a) => a.title + " " + a.outlet)].join(" ").toLowerCase();
  const stories = day.stories.filter((s) => hay(s).includes(q));
  const byCountry = (await headlinesFor(day)) || {};
  const seen = new Set(), heads = [];
  for (const a of [...day.stories.flatMap((s) => s.articles), ...(day.lists || []).flatMap((l) => l.items),
                   ...(day.industries || []).flatMap((i) => i.items), ...(day.commentary || []), ...Object.values(byCountry).flat()]) {
    if (!seen.has(a.url) && (a.title + " " + a.outlet).toLowerCase().includes(q)) { seen.add(a.url); heads.push(a); }
  }
  heads.sort((a, b) => (b.published || "").localeCompare(a.published || ""));
  let h = `<p class="kicker">${esc(label.toUpperCase())} · ${esc(fmtDate(day.date).toUpperCase())}</p>
    <h1>Search: “${esc(S.q.trim())}”</h1>
    <p class="page-meta">${plural(stories.length, "story")} and ${plural(heads.length, "headline")} across every ${esc(label)} page</p>`;
  if (stories.length) h += `<h2>Stories</h2><div class="grid${S.compact ? " compact" : ""}">${stories.map((s) => card(s, day, true)).join("")}</div>`;
  if (heads.length) h += `<h2>Headlines</h2><div class="list">${listRows(heads.slice(0, 150))}</div>`;
  if (!stories.length && !heads.length) h += `<p class="empty">Nothing matches on this day.</p>`;
  h += `<h2 id="sec-past">Earlier days <span class="count">stories from the last 30 daily briefs</span></h2>
    <div id="past"><button type="button" id="pastbtn">Search the last 30 days</button></div>`;
  view.innerHTML = h;
  wire();
  highlight(view, q);
  $("pastbtn").addEventListener("click", () => searchPast(day, q));
}

// Stories from the last 30 briefs, from a small index file (export.py), downloaded only when asked.
async function searchPast(day, q) {
  const box = $("past");
  box.innerHTML = `<p class="muted">Loading…</p>`;
  let idx;
  try { idx = await getJSON(`data/${day.site}/search-index.json`); }
  catch (e) { box.innerHTML = `<p class="muted">The search index isn't there yet: it is written by the next run of the pipeline.</p>`; return; }
  const hits = (idx.stories || []).filter((x) => `${x.t} ${x.l || ""} ${x.x || ""}`.toLowerCase().includes(q));
  if (!hits.length) { box.innerHTML = `<p class="empty">No story in the last ${plural((idx.dates || []).length, "day")} matches.</p>`; return; }
  const byDate = {};
  for (const x of hits) (byDate[x.d] = byDate[x.d] || []).push(x);
  box.innerHTML = Object.keys(byDate).sort().reverse().map((d) => `<h3 class="sub">${esc(fmtDate(d))}</h3><div class="list">${byDate[d].map((x) =>
    `<div class="row"><span class="src">${esc(STATUS[x.s] || "")}<br>${plural(x.o || 0, "outlet")}</span><span><a href="#/${esc(day.site)}/${esc(d)}/${esc(regionPage(day, x.g) || pagesFor(day)[0].id)}">${esc(x.t)}</a>
      ${x.x ? `<span class="small muted">${esc(x.x)}</span>` : ""}</span></div>`).join("")}</div>`).join("");
  highlight(box, q);
}

// ── Watchlist: words you follow, kept in this browser only ────────────────
async function renderWatch() {
  const terms = S.watch;
  let h = `<p class="kicker">YOURS · ${esc(dateLabel().toUpperCase())}</p><h1>Watchlist</h1>
    <p class="page-meta">Words you follow: a country, a person, a company, a place. Stories and headlines that mention them are collected here and
      marked on every page. Your list is kept in this browser only; nothing is sent anywhere.</p>
    <form id="watchform" class="watchform"><input type="search" id="watchterm" placeholder="Add a word, e.g. Sahel or Nvidia" maxlength="60"
      aria-label="Add a word to your watchlist" autocomplete="off"><button type="submit">Add</button></form>
    <div class="chips">${terms.map((t, i) => `<span class="chip">${esc(t)} <button type="button" class="x" data-unwatch="${i}" aria-label="Remove ${esc(t)}">×</button></span>`).join("")}</div>`;
  if (!terms.length) h += `<p class="empty">Nothing on your watchlist yet.</p>`;
  const lower = terms.map((t) => t.toLowerCase());
  const hit = (text) => watchHit(text).length > 0;
  for (const site of SITES) {
    const day = S.days[site];
    if (!day || !terms.length) continue;
    const stories = day.stories.filter((s) => live(s) && watchHits(s).length);
    const byCountry = site === "geo" ? (await headlinesFor(day)) || {} : {};
    const seen = new Set(day.stories.flatMap((s) => s.articles.map((a) => a.url))), heads = [];
    for (const a of [...(day.lists || []).flatMap((l) => l.items), ...(day.industries || []).flatMap((i) => i.items),
                     ...(day.commentary || []), ...Object.values(byCountry).flat()]) {
      if (!seen.has(a.url) && hit(a.title)) { seen.add(a.url); heads.push(a); }
    }
    heads.sort(newestFirst);
    const P = period(day);
    h += `<h2>${esc(S.index.sites[site].label)} <span class="count">${plural(stories.length, "story")} and ${plural(heads.length, "other headline")} ${P.since}</span></h2>`;
    h += stories.length ? `<div class="grid${S.compact ? " compact" : ""}">${stories.map((s) => card(s, day, true)).join("")}</div>` : `<p class="muted">No story mentions your words ${P.since}.</p>`;
    if (heads.length) h += `<h3 class="sub">Other headlines</h3><div class="list">${listRows(heads.slice(0, 80))}</div>`;
  }
  view.innerHTML = h;
  wire();
  for (const t of lower) highlight(view, t);
  $("watchform").addEventListener("submit", (e) => {
    e.preventDefault();
    const t = $("watchterm").value.trim().slice(0, 60);
    if (t.length >= 2 && !S.watch.some((w) => w.toLowerCase() === t.toLowerCase())) { S.watch.push(t); mem.set("sap-watch", S.watch); }
    route();
  });
  view.querySelectorAll("[data-unwatch]").forEach((b) => b.addEventListener("click", () => {
    S.watch.splice(Number(b.dataset.unwatch), 1);
    mem.set("sap-watch", S.watch);
    route();
  }));
}

function renderToolkit(tk, q) {
  const groups = (tk.groups || []).map((g) => ({ ...g, links: (g.links || []).filter((l) => !q || (l.name + " " + l.url).toLowerCase().includes(q)) }))
    .filter((g) => g.links.length);
  view.innerHTML = `<p class="kicker">REFERENCE</p><h1>Toolkit</h1>
    <p class="page-meta">Open-source research links. Nothing here is fetched or analysed. Edit them in <code>config/geo/toolkit.yaml</code>.</p>
    <h2 class="sr-only">Links</h2>
    <div class="grid toolkit mt22">${groups.map((g) => `<section class="card"><h3>${esc(g.title)}</h3><ul>${g.links.map((l) =>
      `<li>${ext(l.url, esc(l.name))}</li>`).join("")}</ul></section>`).join("")}</div>
    ${groups.length ? "" : `<p class="empty">Nothing matches.</p>`}`;
  highlight(view, q);
  $("footer-stats").textContent = "";
}

// ── Reference pages: Sources and OpenCTI ─────────────────────────────────────

// Your repository on GitHub ("owner/name"): from index.json, or worked out from the site's address.
function repo() {
  if (S.index && S.index.repo) return S.index.repo;
  const host = location.hostname.match(/^([^.]+)\.github\.io$/), first = location.pathname.split("/")[1];
  return host && first ? `${host[1]}/${first}` : null;
}
const issueUrl = (template, name, action) => {
  const r = repo();
  if (!r) return null;
  const q = new URLSearchParams({ template });
  if (name) { q.set("title", `Change source: ${name}`); q.set("name", name); }
  if (action) q.set("action", action);
  return `https://github.com/${r}/issues/new?${q}`;
};

const STATE_LABEL = { failing: "Failing", quiet: "Quiet this week", new: "Not fetched yet", ok: "Working", disabled: "Disabled", "no feed": "No feed (link only)" };
const STATE_ORDER = ["failing", "quiet", "new", "ok", "disabled", "no feed"];

function renderSources(data, q) {
  const all = data.sources || [], by = (st) => all.filter((x) => x.status === st);
  const shown = all.filter((x) => !q || `${x.name} ${x.where} ${x.feed}`.toLowerCase().includes(q));
  const add = issueUrl("add-source.yml");
  let h = `<p class="kicker">REFERENCE</p><h1>Sources</h1>
    <p class="page-meta">${plural(all.length, "source")} · ${by("ok").length} working · ${by("quiet").length} quiet this week ·
      ${by("failing").length} failing · ${by("disabled").length} disabled · checked ${fmtTime(data.generated)}</p>
    <div class="actions">${add ? `<a class="btn primary" href="${esc(add)}" target="_blank" rel="noopener noreferrer">Add a source</a>
      <a class="btn" href="${esc(issueUrl("change-source.yml"))}" target="_blank" rel="noopener noreferrer">Change a source</a>
      <span class="small muted">Opens a short form on GitHub. A robot checks the feed, updates the list and replies there.</span>`
      : `<span class="small muted">Add or change sources in <code>config/&lt;site&gt;/sources.yaml</code>, or with <code>python pipeline/manage_sources.py</code>.</span>`}</div>`;
  for (const st of STATE_ORDER) {
    const rows = shown.filter((x) => x.status === st);
    if (!rows.length) continue;
    h += `<h2 id="src-${st.replace(" ", "-")}">${STATE_LABEL[st]} <span class="count">${plural(rows.length, "source")}</span></h2><div class="list sources">${rows.map((x) => {
      const where = [S.index.sites[x.site] ? S.index.sites[x.site].label : x.site, x.where, x.type, x.lang].filter(Boolean).map(esc).join(" · ");
      const health = x.status === "failing" ? `<span class="state-tag">${esc(x.error || "error")}</span> · failed ${plural(x.fails, "run")} in a row${x.last_ok ? ` · last worked ${esc(fmtTime(x.last_ok))}` : ""}`
        : x.status === "disabled" || x.status === "no feed" ? esc(x.note || "") : `${plural(x.articles_7d, "article")} in 7 days${x.newest ? ` · newest ${esc(fmtTime(x.newest))}` : ""}`;
      const act = x.status === "disabled" ? "Enable" : x.status === "no feed" ? "" : "Disable";
      const link = act && issueUrl("change-source.yml", x.name, act);
      return `<div class="row"><span class="src"><span class="dot ${x.status.replace(" ", "-")}"></span>${esc(where)}</span>
        <span>${ext(x.feed, esc(x.name))} <span class="small muted">${health}</span></span>
        ${link ? `<a class="small" href="${esc(link)}" target="_blank" rel="noopener noreferrer">${act}</a>` : "<span></span>"}</div>`;
    }).join("")}</div>`;
  }
  if (!shown.length) h += `<p class="empty">No source matches.</p>`;
  view.innerHTML = h;
  fold(view, "ref:sources");
  highlight(view, q);
  $("footer-stats").textContent = "";
}

async function renderOpenCTI() {
  const base = new URL("feeds/", location.href.split("#")[0]).href;
  let info = null;
  try { info = await getJSON("feeds/index.json"); } catch (e) { /* feeds not built yet (they're made by the daily run) */ }
  const files = (info && info.files) || {};
  const FEEDS = [
    ["cyber.xml", "Cyber stories", "One item per story per day with new reporting: attributed sentences with source links, and the original headlines", "RSS Feed → a Report per item"],
    ["geo.xml", "Geopolitical stories", "The same for geopolitical stories, with region and countries (about 25 a day)", "RSS Feed → a Report per item"],
    ["iocs.csv", "IOCs", `Indicators from the last ${info ? info.days : 3} days, real values (${esc(((info && info.ioc_types) || []).join(", ") || "hashes, IPs, domains")})`, "CSV Feed + CSV mapper → observables"],
    ["vulnerabilities.csv", "Vulnerabilities", "CVEs added to CISA KEV, and CVEs in the news", "CSV Feed + CSV mapper → Vulnerabilities"],
    ["cyber-stix.json", "STIX 2.1 bundle", "Indicators (with patterns), malware families, research reports and vulnerabilities, in the standard format", "Import as a file (no mapper needed)"],
  ];
  const row = ([f, name, what, how]) => `<div class="row feedrow"><span class="src"><strong>${esc(name)}</strong><br>${files[f] ? esc(files[f].summary.replace(f, "").trim()) : "not built yet"}</span>
    <span>${esc(what)}<br><span class="small muted">In OpenCTI: ${esc(how)}</span>
    <span class="copyline"><code>${esc(base + f)}</code><button type="button" class="icon" data-copy="${esc(base + f)}" aria-label="Copy the address of ${esc(name)}">${icon("copy")}</button>
      <a class="small" href="feeds/${esc(f)}" download>Download</a></span></span></div>`;
  view.innerHTML = `<p class="kicker">REFERENCE</p><h1>OpenCTI</h1>
    <p class="page-meta">Connect an OpenCTI platform to this site. OpenCTI downloads these files on a schedule; this site never connects to it
      and holds no keys. Files rebuilt ${info ? esc(fmtTime(info.generated)) : "with every daily run"}.</p>
    <h2 id="oc-feeds">The feeds <span class="count">public addresses to paste into OpenCTI</span></h2>
    <div class="list">${FEEDS.map(row).join("")}</div>
    <p class="small muted">IOC values in the CSV and STIX files are real (refanged), so tools can use them; the pages of this site show them defanged.
      Full URLs are left out unless you add <code>url</code> to <code>ioc_types</code> in <code>config/feeds.yaml</code>.</p>

    <h2 id="oc-1">1. Create the author</h2>
    <ol class="steps"><li>In OpenCTI go to <em>Entities → Organizations</em> and create <strong>Situational Awareness Project</strong>.</li>
      <li>Use it as the <strong>default author</strong> in every feed below, with the marking <strong>TLP:CLEAR</strong> (everything comes from public sources).</li></ol>

    <h2 id="oc-2">2. Stories as Reports (RSS)</h2>
    <ol class="steps"><li><em>Integrations → Available</em> (older versions: <em>Data → Ingestion</em>) → create an <strong>RSS Feed</strong>.</li>
      <li>Address: the <strong>Cyber stories</strong> link above. Report type: <code>threat-report</code>. Author and marking from step 1.</li>
      <li>Create it, then choose <strong>Start</strong>. Repeat for <strong>Geopolitical stories</strong> if you want them.</li></ol>

    <h2 id="oc-3">3. IOCs as observables (CSV)</h2>
    <ol class="steps"><li>Download <code>iocs.csv</code> above and keep its first 100 lines as a test file.</li>
      <li><em>Data → Processing → CSV Mappers</em> → add <strong>SAP IOCs</strong>: comma separator, <em>header on the first line</em> ticked.</li>
      <li>Add these representations, each with <strong>Entity dynamic mapping</strong> (operator <em>Equal</em>), mapping column B to the value:</li></ol>
    <div class="list"><div class="row"><span class="src">IPv4 address</span><span>when column A equals <code>IPv4-Addr</code></span></div>
      <div class="row"><span class="src">Domain name</span><span>when column A equals <code>Domain-Name</code></span></div>
      <div class="row"><span class="src">File (×3)</span><span>when column C equals <code>SHA-256</code>, <code>SHA-1</code> or <code>MD5</code>: column B into that hash field</span></div>
      <div class="row"><span class="src">Optional</span><span>Description from column H (the report's title); an External reference from column I (its link)</span></div></div>
    <ol class="steps" start="4"><li>Press <strong>Test</strong> with the 100-line file and check each value came out as the right type.</li>
      <li>Create a <strong>CSV Feed</strong> with the <strong>IOCs</strong> address and the <strong>SAP IOCs</strong> mapper, every 6 hours, then <strong>Start</strong>.</li></ol>

    <h2 id="oc-4">4. Vulnerabilities (CSV)</h2>
    <ol class="steps"><li>A CSV mapper <strong>SAP vulnerabilities</strong> with one <strong>Vulnerability</strong> representation: Name from column A, Description from column F.</li>
      <li>A CSV Feed with the <strong>Vulnerabilities</strong> address and that mapper, then <strong>Start</strong>.</li></ol>

    <h2 id="oc-5">5. The STIX bundle</h2>
    <p>STIX 2.1 is the standard format for threat intelligence, so OpenCTI needs no mapper: download <code>cyber-stix.json</code> and upload it under
      <em>Data → Import</em> (or drag it onto the import screen). It holds indicators with detection patterns, the malware families they point to,
      one report per vendor publication, and vulnerabilities flagged when they're in CISA KEV. Every object keeps the same id from day to day,
      so importing again updates what's there instead of creating duplicates.</p>

    <h2 id="oc-6">6. Check it worked</h2>
    <ul class="steps"><li><em>Analyses → Reports</em>, filtered by the author: stories with their source links.</li>
      <li><em>Observations</em>: IP addresses, domains and files. <em>Arsenal → Vulnerabilities</em>: CVEs.</li>
      <li>A feed with errors: open its address in a browser on the OpenCTI network. If that fails too, it's a proxy or firewall rule.</li></ul>`;
  fold(view, "ref:opencti");
  view.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(b.dataset.copy); b.classList.add("done"); setTimeout(() => b.classList.remove("done"), 1500); }
    catch (e) { const c = b.previousElementSibling; const r = document.createRange(); r.selectNodeContents(c); getSelection().removeAllRanges(); getSelection().addRange(r); }
  }));
  $("footer-stats").textContent = "";
}

function renderEmpty(msg) {
  view.innerHTML = `<h1>No brief yet</h1><p class="muted">${msg}</p>`;
}

// Something didn't download (offline, or a file is missing): say so, and offer to try again.
function renderError(msg) {
  $("footer-stats").textContent = "";
  view.innerHTML = `<div class="error-box" role="alert"><p class="m0">${esc(msg)}</p>
    <button type="button" id="retry">Try again</button></div>`;
  $("retry").addEventListener("click", () => { S.cache.clear(); route(); });
}

// ── Routing: decide what to show from the address ─────────────────────────

// ── Date ranges ─────────────────────────────────────────────────────────────
// Several daily files merged into one "day" with the same shape, so every page works unchanged.
// It all happens in your browser: the site is still just static files.
const unionBy = (lists, key) => {
  const m = new Map();
  for (const l of lists) for (const x of l || []) if (!m.has(key(x))) m.set(key(x), x);
  return [...m.values()];
};
const newestFirst = (a, b) => (b.published || "").localeCompare(a.published || "");

function mergeDays(days, from, to) {
  const last = days[days.length - 1];
  const byId = new Map();
  for (const d of days) for (const s of d.stories) byId.set(s.id, s);         // the newest version wins
  const tracked = new Set(last.stories.map((s) => s.id));
  const stories = [...byId.values()].filter((s) => tracked.has(s.id) || s.last_updated >= from).map((s) => {
    const arts = s.articles.filter((a) => (a.added || "") >= from);
    const reps = s.reports.filter((r) => r.date >= from);
    const also = s.reports.flatMap((r) => (r.also || []).filter((x) => (x.date || "") >= from));
    const outlets = new Set([...arts.map((a) => a.outlet), ...reps.flatMap((r) => r.outlets || []), ...also.map((x) => x.outlet)]);
    const regions = new Set(arts.map((a) => a.region).filter(Boolean));
    return { ...s, status: s.first_seen >= from ? "new" : reps.length ? "updated" : s.last_updated >= from ? "covered" : "unchanged",
             outlets_period: outlets.size, articles_period: arts.length, single_source: outlets.size === 1,
             reach: regions.size || s.reach || 0, regions: regions.size ? [...regions].sort() : s.regions,
             state_media_only: arts.length > 0 && arts.every((a) => a.type === "state-media") };
  }).sort((a, b) => (b.reach || 0) - (a.reach || 0) || b.outlets_period - a.outlets_period || b.articles_period - a.articles_period || b.article_count - a.article_count);
  const active = stories.filter(fresh);
  const worldwide = last.worldwide ? stories.filter((s) => live(s) && (s.reach || 0) >= 3).slice(0, 12).map((s) => s.id) : undefined;
  const bluf = active.slice(0, 5).map((s) => {
    const r = s.reports.find((r) => r.date >= from);
    if (r) return { story: s.id, title: s.title, text: r.text, kind: "report" };
    const a = s.articles[0];
    return a ? { story: s.id, title: s.title, kind: "headline", text: `[${a.outlet}](${a.url}): ${a.title}` } : null;
  }).filter(Boolean);
  const lists = (last.lists || []).map((l) => ({ ...l, days: daysBetween(from, to),
    items: unionBy(days.map((d) => ((d.lists || []).find((x) => x.id === l.id) || {}).items), (x) => x.url).sort(newestFirst).slice(0, 150) }));
  const ids = new Set(stories.filter(live).map((s) => s.id));
  const industries = (last.industries || []).map((ind) => {
    const all = days.map((d) => (d.industries || []).find((x) => x.id === ind.id) || { items: [], stories: [] });
    return { ...ind, items: unionBy(all.map((x) => x.items), (x) => x.url).sort(newestFirst).slice(0, 100),
             stories: [...new Set(all.flatMap((x) => x.stories))].filter((id) => ids.has(id)) };
  });
  let vulns = null;
  if (last.vulns) {
    const news = new Map();
    for (const d of days) for (const c of (d.vulns || {}).in_news || []) {
      const m = news.get(c.cve) || { ...c, articles: [] };
      m.outlets = Math.max(m.outlets, c.outlets);
      m.kev = m.kev || c.kev;
      m.articles = unionBy([m.articles, c.articles], (a) => a.url).slice(0, 3);
      news.set(c.cve, m);
    }
    vulns = { kev_new: unionBy(days.map((d) => (d.vulns || {}).kev_new), (k) => k.cve).sort((a, b) => b.date_added.localeCompare(a.date_added)),
              in_news: [...news.values()].sort((a, b) => b.outlets - a.outlets || (a.kev ? 0 : 1) - (b.kev ? 0 : 1)).slice(0, 60) };
  }
  let iocs = null;
  if (last.iocs) {
    const groups = new Map();
    for (const d of days) for (const g of (d.iocs || {}).groups || []) {
      const key = `${g.source}|${g.url}|${g.title}`, m = groups.get(key) || { ...g, counts: {}, items: {} };
      for (const [t, vals] of Object.entries(g.items)) {
        m.items[t] = [...new Set([...(m.items[t] || []), ...vals])];
        m.counts[t] = Math.max(m.counts[t] || 0, g.counts[t] || 0, m.items[t].length);
      }
      groups.set(key, m);
    }
    const all = [...groups.values()];
    iocs = { groups: all, total: all.reduce((t, g) => t + Object.values(g.counts).reduce((a, b) => a + b, 0), 0), csv: null,
             csvs: days.filter((d) => d.iocs && d.iocs.csv).map((d) => ({ date: d.date, url: d.iocs.csv })) };
  }
  const commentary = unionBy(days.map((d) => d.commentary), (x) => x.url).sort(newestFirst);
  let countries = null;
  if (last.countries) {
    countries = {};
    for (const d of days) for (const [k, c] of Object.entries(d.countries || {})) {
      const m = countries[k] || { ...c, last24: 0, heads_total: 0, hotspot: false };
      Object.assign(m, { name: c.name, region: c.region, global: c.global, regional: c.regional, avg7: c.avg7 });
      m.last24 += c.last24 || 0;
      m.heads_total += c.heads_total || 0;
      m.heads_shown = Math.min(m.heads_total, 50);
      m.hotspot = m.hotspot || !!c.hotspot;
      countries[k] = m;
    }
  }
  return { ...last, date: to, window: { days: daysBetween(from, to), start: from }, range: { from, to, files: days.length },
           stories, top: active.slice(0, 5).map((s) => s.id), worldwide, bluf, lists, industries, vulns, iocs, commentary, countries,
           headlines: days.map((d) => d.headlines).filter(Boolean),
           stats: { sources: last.stats.sources, reports: stories.reduce((t, s) => t + s.reports.filter((r) => r.date >= from).length, 0),
                    removed: days.reduce((t, d) => t + (d.stats.removed ?? d.stats.removed_today ?? 0), 0),
                    coverage: sumCoverage(days.map((d) => d.stats.coverage).filter(Boolean)) } };
}

function sumCoverage(list) {
  if (!list.length) return null;
  const out = {};
  for (const c of list) for (const [k, v] of Object.entries(c)) if (typeof v === "number") out[k] = (out[k] || 0) + v;
  return out;
}

// Load both sites' brief (the sidebar shows both): one date, or a range merged into one view.
async function loadDays() {
  await Promise.all(SITES.map(async (site) => {
    const info = S.index.sites[site];
    if (!info || !info.dates.length) return;
    try {
      if (S.range) {
        const key = `range:${site}:${S.range.from}..${S.range.to}`;
        const dates = info.dates.filter((d) => d >= S.range.from && d <= S.range.to).sort();
        if (dates.length) {
          if (!S.cache.has(key)) S.cache.set(key, mergeDays(await Promise.all(dates.map((d) => getJSON(`data/${site}/${d}.json`))), S.range.from, S.range.to));
          S.days[site] = S.cache.get(key);
          return;
        }
      }
      const d = info.dates.includes(S.date) ? S.date : info.dates[0];
      S.days[site] = await getJSON(`data/${site}/${d}.json`);
    } catch (e) { delete S.days[site]; }
  }));
}

// ── The calendar ───────────────────────────────────────────────────────────
const CAL = { month: null, mode: "day", pick: null };
const MAX_RANGE = () => (S.index && S.index.max_range_days) || 14;
const availableDates = () => ((S.index.sites[S.index.sites[S.site] ? S.site : "geo"] || {}).dates || []);

function dateLabel() {
  return S.range ? `${fmtDM(S.range.from)} – ${fmtShort(S.range.to)}` : fmtShort(S.date);
}

function goSpec(spec) {
  $("calendar").hidden = true;
  $("datebtn").setAttribute("aria-expanded", "false");
  const site = S.index.sites[S.site] ? S.site : "geo";
  location.hash = `#/${site}/${spec}/${site === S.site ? S.page || "" : ""}`;
}

function renderCalendar() {
  const avail = new Set(availableDates()), max = MAX_RANGE();
  const [y, m] = CAL.month.split("-").map(Number);
  const first = new Date(Date.UTC(y, m - 1, 1));
  const lead = (first.getUTCDay() + 6) % 7;                        // weeks start on Monday
  const count = new Date(Date.UTC(y, m, 0)).getUTCDate();
  const sel = S.range || { from: S.date, to: S.date };
  let cells = "<span></span>".repeat(lead);
  for (let d = 1; d <= count; d++) {
    const ymd = `${CAL.month}-${String(d).padStart(2, "0")}`;
    const cls = [ymd >= sel.from && ymd <= sel.to ? "in" : "", ymd === sel.from || ymd === sel.to ? "end" : "", ymd === CAL.pick ? "pick" : ""].join(" ").trim();
    cells += `<button type="button" data-date="${ymd}" class="${cls}"${avail.has(ymd) ? "" : " disabled"} aria-label="${esc(fmtDate(ymd))}">${d}</button>`;
  }
  const month = first.toLocaleDateString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" });
  $("calendar").innerHTML = `
    <div class="cal-modes" role="group" aria-label="What to pick">
      <button type="button" data-mode="day" aria-pressed="${CAL.mode === "day"}">One day</button>
      <button type="button" data-mode="range" aria-pressed="${CAL.mode === "range"}">Several days</button></div>
    <div class="cal-head"><button type="button" data-move="-1" aria-label="Previous month">‹</button>
      <span>${esc(month)}</span><button type="button" data-move="1" aria-label="Next month">›</button></div>
    <div class="cal-grid">${["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"].map((d) => `<span class="dow">${d}</span>`).join("")}${cells}</div>
    <p class="cal-msg">${CAL.mode === "range" ? (CAL.pick ? `From ${esc(fmtDM(CAL.pick))}: now pick the last day.` : `Pick the first day, then the last (up to ${max} days).`)
      : "Days with a brief can be picked."}</p>
    <div class="cal-presets">${[[1, "Latest"], [3, "Last 3 days"], [5, "Last 5 days"], [7, "Last 7 days"], [max, `Last ${max} days`]]
      .map(([n, t]) => `<button type="button" data-preset="${n}">${t}</button>`).join("")}</div>`;
}

function calendarClick(e) {
  const b = e.target.closest("button");
  if (!b || b.disabled) return;
  e.stopPropagation();
  const dates = availableDates(), max = MAX_RANGE();
  if (b.dataset.mode) { CAL.mode = b.dataset.mode; CAL.pick = null; return renderCalendar(); }
  if (b.dataset.move) {
    const [y, m] = CAL.month.split("-").map(Number), d = new Date(Date.UTC(y, m - 1 + Number(b.dataset.move), 1));
    CAL.month = d.toISOString().slice(0, 7);
    return renderCalendar();
  }
  if (b.dataset.preset) {
    const n = Number(b.dataset.preset), to = dates[0];
    if (n <= 1) return goSpec(to);
    const oldest = dates[dates.length - 1], from = addDays(to, -(n - 1));
    return goSpec(`${from < oldest ? oldest : from}..${to}`);
  }
  if (b.dataset.date) {
    const d = b.dataset.date;
    if (CAL.mode === "day") return goSpec(d);
    if (!CAL.pick) { CAL.pick = d; return renderCalendar(); }
    let [from, to] = [CAL.pick, d].sort();
    if (daysBetween(from, to) > max) from = addDays(to, -(max - 1));     // keep downloads reasonable
    return goSpec(from === to ? to : `${from}..${to}`);
  }
}

function toggleCalendar(open) {
  const cal = $("calendar");
  open = open ?? cal.hidden;
  if (open) {
    CAL.month = (S.range ? S.range.to : S.date).slice(0, 7);
    CAL.mode = S.range ? "range" : "day";
    CAL.pick = null;
    renderCalendar();
  }
  cal.hidden = !open;
  $("datebtn").setAttribute("aria-expanded", String(open));
}

// ── Routing: decide what to show from the address ─────────────────────────

// The browser tab's title follows the page, so history, bookmarks and screen readers say where you are.
function setTitle(...parts) {
  document.title = [...parts.filter(Boolean), "Situational Awareness Project"].join(" · ");
}

// After moving to another page, put the keyboard focus at the top of the new page (not on the first load).
let routed = 0;
function focusPage() {
  if (routed++ === 0 || document.activeElement === $("search")) return;   // never while typing a search
  view.setAttribute("tabindex", "-1");
  view.focus({ preventScroll: true });
}

// Shown while files download (a range of 14 days can take a moment); only if it takes a while.
function loading(on) {
  clearTimeout(loading.t);
  view.setAttribute("aria-busy", String(on));
  if (on) loading.t = setTimeout(() => { view.innerHTML = `<p class="loading" role="status">Loading…</p>`; }, 250);
}

async function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const REFS = ["toolkit", "sources", "opencti", "watch"];           // pages without a date of their own
  const site = [...SITES, ...REFS].includes(parts[0]) ? parts[0] : "geo";
  const seg = parts[1] || "", rng = RANGE_RE.exec(seg), dated = DATE_RE.test(seg) || !!rng;
  const page = (dated ? parts[2] : parts[1]) || "";
  const anchor = (dated ? parts[3] : parts[2]) || "";        // e.g. c-poland: scroll to Poland
  const q = S.q.trim().toLowerCase();
  S.site = site;
  document.body.classList.remove("nav-open");
  $("menu").setAttribute("aria-expanded", "false");
  $("calendar").hidden = true;

  const ref = REFS.includes(site);
  const info = S.index && S.index.sites[ref ? "geo" : site];
  if (!ref && (!info || !info.dates.length)) return renderEmpty(`Run <code>python pipeline/export.py</code> to create the first brief.`);
  if (rng) {
    let [from, to] = [rng[1], rng[2]].sort();
    if (daysBetween(from, to) > MAX_RANGE()) from = addDays(to, -(MAX_RANGE() - 1));
    S.range = from === to ? null : { from, to };
    S.date = info.dates.find((d) => d <= to) || info.dates[0];
    if (!S.range) S.date = info.dates.includes(to) ? to : S.date;
  } else if (!ref || !S.date) {
    S.range = null;
    S.date = info && info.dates.includes(seg) ? seg : info ? info.dates[0] : null;
  }
  loading(true);
  try {
    await loadDays();
  } finally {
    loading(false);
  }

  if (ref) {
    $("datenav").hidden = true;
    S.page = site;
    renderSidebar();
    try {
      if (site === "toolkit") renderToolkit(await getJSON("data/toolkit.json"), q);
      else if (site === "sources") renderSources(await getJSON("data/sources.json"), q);
      else if (site === "watch") await renderWatch();
      else await renderOpenCTI();
    } catch (e) { renderError(`This page's file couldn't be loaded.`); }
    setTitle({ toolkit: "Toolkit", sources: "Sources", watch: "Watchlist", opencti: "OpenCTI" }[site]);
    focusPage();
    window.scrollTo(0, 0);
    return;
  }
  $("datenav").hidden = false;
  $("datebtn").textContent = dateLabel();
  const dates = info.dates, oldest = dates[dates.length - 1], latest = dates[0];
  $("prev").disabled = (S.range ? S.range.from : S.date) <= oldest;   // dates are newest first
  $("next").disabled = (S.range ? S.range.to : S.date) >= latest;

  S.day = S.days[site];
  if (!S.day) {
    renderSidebar();
    return renderError(`This brief couldn't be loaded. Check your connection and try again.`);
  }
  const pages = pagesFor(S.day);
  const current = pages.find((p) => p.id === page) || pages[0];
  S.page = current.id;
  renderSidebar();
  setTitle(q ? `Search “${S.q.trim()}”` : current.name, S.index.sites[site].label, dateLabel());
  if (q) return renderSearch(S.day, q);
  renderPage(S.day, current);
  focusPage();
  const target = anchor && document.getElementById(anchor);
  if (target) { reveal(target); target.scrollIntoView({ block: "start" }); } else window.scrollTo(0, 0);
}

// ‹ and ›: one day back or forward, or the whole range shifted by its own length.
function goDate(offset) {
  const dates = S.index.sites[S.site].dates;
  if (S.range) {
    const span = daysBetween(S.range.from, S.range.to);
    const to = offset > 0 ? addDays(S.range.from, -1) : addDays(S.range.to, span);
    const end = to > dates[0] ? dates[0] : to;
    return goSpec(`${addDays(end, -(span - 1))}..${end}`);
  }
  const i = dates.indexOf(S.date) + offset;
  if (i >= 0 && i < dates.length) goSpec(dates[i]);
}

// ── Start ─────────────────────────────────────────────────────────────────

$("datebtn").addEventListener("click", (e) => { e.stopPropagation(); toggleCalendar(); });
$("calendar").addEventListener("click", calendarClick);
document.addEventListener("click", (e) => { if (!$("calendar").hidden && !e.target.closest("#calendar")) toggleCalendar(false); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("calendar").hidden) { toggleCalendar(false); $("datebtn").focus(); } });
$("prev").addEventListener("click", () => goDate(+1));
$("next").addEventListener("click", () => goDate(-1));
let timer;
$("search").addEventListener("input", (e) => { clearTimeout(timer); timer = setTimeout(() => { S.q = e.target.value; route(); }, 150); });
$("theme").addEventListener("click", () => {
  const dark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === "dark"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = dark ? "light" : "dark";
  try { localStorage.setItem("sap-theme", document.documentElement.dataset.theme); } catch (e) {}
});
// Phones: the sidebar opens and closes with the menu button.
$("menu").addEventListener("click", () => {
  const open = document.body.classList.toggle("nav-open");
  $("menu").setAttribute("aria-expanded", String(open));
});
window.addEventListener("hashchange", route);
// "Skip to the brief" (index.html): moves the focus to the page without changing the address.
$("skip").addEventListener("click", (e) => { e.preventDefault(); view.setAttribute("tabindex", "-1"); view.focus(); });

(async () => {
  decodeTitle();
  try { S.index = await getJSON("data/index.json"); }
  catch (e) { S.index = { sites: {} }; }
  route();
})();
