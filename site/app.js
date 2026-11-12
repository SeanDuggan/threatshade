/* Threatshade polluter scoreboard.
 * Security notes:
 *  - All data from data/data.json is rendered with textContent or DOM APIs, never innerHTML.
 *  - Source links must be https:// and on an allowlisted host (checked again here, defence in depth).
 *  - No inline styles or scripts, so the Content-Security-Policy can forbid both.
 */
(function () {
  "use strict";

  var DATA_URL = "data/data.json";
  var ALLOWED_LINK_HOSTS = [
    "epa.ie", "irishtimes.com", "irishexaminer.com", "smartwatermagazine.com",
    "sustainabilityonline.net", "farmersjournal.ie", "donegallive.ie",
    "fisheriesireland.ie", "catchments.ie", "agriland.ie", "europa.eu",
    "bnm.ie", "leinsterexpress.ie"
  ];

  /* ---------- small DOM helpers ---------- */
  var NS = "http://www.w3.org/2000/svg";
  function h(tag, attrs, children) {
    var e = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === "class") e.className = attrs[k];
      else if (k === "text") e.textContent = attrs[k];
      else e.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { if (c != null) e.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return e;
  }
  function s(tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (parent) parent.appendChild(e);
    return e;
  }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }

  function safeUrl(u) {
    try {
      var url = new URL(u);
      if (url.protocol !== "https:") return null;
      var host = url.hostname.toLowerCase();
      var ok = ALLOWED_LINK_HOSTS.some(function (a) { return host === a || host.slice(-(a.length + 1)) === "." + a; });
      return ok ? url.href : null;
    } catch (e) { return null; }
  }
  function num(v, lo, hi) { return typeof v === "number" && isFinite(v) && v >= lo && v <= hi; }

  /* ---------- scoring ---------- */
  var CATS = [
    { k: "climate", label: "Climate", max: 30 },
    { k: "water", label: "Water", max: 25 },
    { k: "air", label: "Air & odour", max: 10 },
    { k: "enforce", label: "Enforcement", max: 20 },
    { k: "habitat", label: "Habitat", max: 15 }
  ];
  var TOP_EMITTER = 12300000;
  function climatePts(t) {
    if (!t) return 0;
    var x = (Math.log10(t) - 4) / (Math.log10(TOP_EMITTER) - 4);
    return Math.max(0, Math.min(1, x)) * 30;
  }
  function enforcePts(e) {
    var v = (e.nps === "current" ? 10 : e.nps === "past" ? 5 : 0) +
      Math.min(15, 3 * e.prosecutions) + Math.min(4, 2 * e.stop_orders) + (e.big_fine ? 6 : 0);
    return Math.min(20, v);
  }
  var weights = { climate: 1, water: 1, air: 1, enforce: 1, habitat: 1 };
  function scoreOf(p) {
    var n = 0, d = 0;
    CATS.forEach(function (c) { n += p.pts[c.k] * weights[c.k]; d += c.max * weights[c.k]; });
    return d ? n / d * 100 : 0;
  }
  function tierOf(v) { return v >= 50 ? ["Critical", "crit"] : v >= 35 ? ["High", "high"] : v >= 22 ? ["Elevated", "elev"] : ["Watch", "watch"]; }
  function tierColor(cls) { return getComputedStyle(document.documentElement).getPropertyValue("--" + cls).trim(); }
  function fmtT(t) { return t >= 1e6 ? (t / 1e6).toFixed(2).replace(/0$/, "") + " Mt" : Math.round(t).toLocaleString("en-IE") + " t"; }
  function badgesOf(p) {
    var b = [];
    if (p.enforcement.nps === "current") b.push(["On EPA watchlist", true]);
    if (p.flags.raw_sewage) b.push(["Raw sewage", true]);
    if (p.co2_tonnes >= 1000000) b.push(["Carbon heavyweight", false]);
    if (p.enforcement.prosecutions >= 2) b.push(["Repeat offender", true]);
    if (p.enforcement.big_fine) b.push(["Six-figure penalty", true]);
    if (p.flags.rising) b.push(["Emissions rising", false]);
    if (p.points.habitat >= 12 && p.sector !== "Land use") b.push(["Next to protected waters", false]);
    (p.extra_badges || []).forEach(function (x) { b.push([x.label, !!x.alert]); });
    return b;
  }

  /* ---------- basic shape check on load (the build pipeline validates fully) ---------- */
  function checkData(d) {
    if (!d || !Array.isArray(d.polluters) || !Array.isArray(d.sources)) throw new Error("bad shape");
    d.polluters.forEach(function (p) {
      if (typeof p.id !== "string" || typeof p.name !== "string") throw new Error("bad polluter");
      if (!num(p.points.water, 0, 25) || !num(p.points.air, 0, 10) || !num(p.points.habitat, 0, 15)) throw new Error("bad points: " + p.id);
      p.sites.forEach(function (x) { if (!num(x.lat, 51, 55.6) || !num(x.lng, -11, -5.3)) throw new Error("bad site: " + p.id); });
    });
    return d;
  }

  /* ---------- map geometry (hand-traced outline, approximate) ---------- */
  var COAST = [[-7.37,55.38],[-7.03,55.20],[-6.95,55.17],[-6.65,55.21],[-6.15,55.23],[-6.04,55.08],[-5.80,54.86],[-5.70,54.80],[-5.82,54.72],[-5.92,54.63],[-5.67,54.67],[-5.53,54.64],[-5.44,54.46],[-5.47,54.33],[-5.61,54.26],[-5.66,54.22],[-5.89,54.21],[-5.90,54.10],[-6.00,54.06],[-6.07,54.02],[-6.19,54.04],[-6.15,53.98],[-6.38,54.00],[-6.24,53.86],[-6.22,53.79],[-6.25,53.72],[-6.18,53.61],[-6.10,53.58],[-6.09,53.52],[-6.15,53.45],[-6.04,53.37],[-6.20,53.34],[-6.09,53.27],[-6.09,53.20],[-6.06,53.14],[-5.99,52.96],[-6.13,52.80],[-6.22,52.64],[-6.20,52.56],[-6.33,52.35],[-6.40,52.34],[-6.34,52.25],[-6.36,52.17],[-6.59,52.17],[-6.79,52.21],[-6.93,52.12],[-6.98,52.25],[-6.99,52.15],[-7.15,52.16],[-7.54,52.05],[-7.62,52.08],[-7.72,51.95],[-7.85,51.95],[-8.00,51.83],[-8.25,51.79],[-8.32,51.75],[-8.53,51.60],[-8.71,51.62],[-8.95,51.53],[-9.10,51.55],[-9.37,51.48],[-9.82,51.45],[-9.60,51.62],[-9.85,51.55],[-9.45,51.68],[-10.15,51.58],[-9.60,51.87],[-10.35,51.90],[-9.80,52.10],[-10.48,52.10],[-10.15,52.27],[-9.75,52.27],[-9.93,52.42],[-9.67,52.52],[-9.37,52.58],[-9.10,52.62],[-8.63,52.66],[-9.10,52.67],[-9.48,52.63],[-9.93,52.56],[-9.65,52.68],[-9.44,52.85],[-9.43,53.00],[-9.27,53.15],[-8.93,53.14],[-9.05,53.27],[-9.30,53.24],[-9.85,53.32],[-10.23,53.40],[-10.02,53.49],[-9.85,53.61],[-9.80,53.76],[-9.53,53.80],[-10.00,53.90],[-10.25,53.97],[-10.10,54.22],[-9.83,54.34],[-9.35,54.32],[-9.22,54.21],[-8.96,54.29],[-8.47,54.27],[-8.45,54.47],[-8.28,54.48],[-8.11,54.65],[-8.46,54.57],[-8.44,54.63],[-8.79,54.65],[-8.75,54.71],[-8.45,54.77],[-8.56,54.82],[-8.43,54.98],[-8.28,55.15],[-7.98,55.22],[-7.63,55.27],[-7.55,55.25],[-7.53,55.09],[-7.45,55.13],[-7.45,55.28]];
  var BORDER = [[-7.25,55.05],[-7.32,54.99],[-7.47,54.83],[-7.70,54.70],[-7.83,54.55],[-8.09,54.48],[-8.17,54.43],[-7.88,54.29],[-7.55,54.12],[-7.23,54.18],[-7.05,54.25],[-6.97,54.40],[-6.85,54.29],[-6.65,54.15],[-6.61,54.07],[-6.42,54.05],[-6.30,54.10],[-6.27,54.07]];
  var LON0 = -10.75, LAT0 = 55.55, K = 150, CX = Math.cos(53.4 * Math.PI / 180);
  function proj(lng, lat) { return [(lng - LON0) * CX * K + 10, (LAT0 - lat) * K + 10]; }
  var W = Math.round((-5.25 - LON0) * CX * K + 20), H = Math.round((LAT0 - 51.30) * K + 20);

  /* ---------- app ---------- */
  var P = [], SOURCES = {}, sectorFilter = "All", selected = null;
  var svg, markers, tip, board, rowEls = {};

  function drawBaseMap() {
    svg = document.getElementById("map");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    var grid = s("g", { "class": "sea-grid" }, svg);
    for (var lat = 52; lat <= 55; lat++) {
      var y = proj(0, lat)[1];
      s("line", { x1: 0, x2: W, y1: y, y2: y }, grid);
      s("text", { x: 4, y: y - 3, "class": "grid-label" }, grid).textContent = lat + "°N";
    }
    for (var lng = -10; lng <= -6; lng++) {
      var x = proj(lng, 0)[0];
      s("line", { x1: x, x2: x, y1: 0, y2: H }, grid);
      s("text", { x: x + 3, y: H - 6, "class": "grid-label" }, grid).textContent = Math.abs(lng) + "°W";
    }
    function path(pts, close) { return "M" + pts.map(function (c) { return proj(c[0], c[1]).map(function (v) { return v.toFixed(1); }).join(","); }).join("L") + (close ? "Z" : ""); }
    s("path", { "class": "island", d: path(COAST, true) }, svg);
    s("path", { "class": "border", d: path(BORDER, false) }, svg);
    var nl = proj(-6.75, 54.68);
    s("text", { x: nl[0], y: nl[1], "class": "ni-label", "text-anchor": "middle" }, svg).textContent = "N. IRELAND";
    markers = s("g", {}, svg);
    tip = document.getElementById("tip");

    var legend = document.getElementById("legend");
    [["Critical 50+", "crit"], ["High 35–49", "high"], ["Elevated 22–34", "elev"], ["Watch <22", "watch"]].forEach(function (l) {
      legend.appendChild(h("span", null, [h("i", { "class": "bg-" + l[1] }), l[0]]));
    });
  }

  function drawMarkers() {
    clear(markers);
    P.slice().sort(function (a, b) { return scoreOf(a) - scoreOf(b); }).forEach(function (p) {
      var sc = scoreOf(p), t = tierOf(sc), col = tierColor(t[1]);
      var dim = sectorFilter !== "All" && p.sector !== sectorFilter;
      p.sites.forEach(function (site, i) {
        var xy = proj(site.lng, site.lat), r = 3 + sc / 9;
        var g = s("g", { "class": "marker " + t[1] + (dim ? " dim" : "") + (p.id === selected ? " sel" : ""), tabindex: dim ? -1 : 0, role: "button", "aria-label": p.name + ", " + site.name + ", score " + Math.round(sc) }, markers);
        s("circle", { "class": "ring", cx: xy[0], cy: xy[1], r: r, stroke: col }, g);
        s("circle", { "class": "dot", cx: xy[0], cy: xy[1], r: r, fill: col }, g);
        if (p.id === selected && i === 0) s("text", { x: xy[0] + r + 4, y: xy[1] + 3 }, g).textContent = p.name;
        g.addEventListener("click", function () { select(p.id); });
        g.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(p.id); } });
        g.addEventListener("mouseenter", function () {
          clear(tip);
          tip.appendChild(h("b", { text: p.name }));
          tip.appendChild(h("br")); tip.appendChild(document.createTextNode(site.name));
          tip.appendChild(h("br")); tip.appendChild(h("span", { "class": "mono", text: Math.round(sc) + " / 100 · " + t[0] }));
          var box = svg.getBoundingClientRect(), k = box.width / W;
          tip.style.left = Math.min(box.width - 200, xy[0] * k + 16) + "px";
          tip.style.top = (xy[1] * k - 8) + "px";
          tip.style.opacity = 1;
        });
        g.addEventListener("mouseleave", function () { tip.style.opacity = 0; });
      });
    });
  }

  function buildControls() {
    var sectors = ["All"];
    P.forEach(function (p) { if (sectors.indexOf(p.sector) < 0) sectors.push(p.sector); });
    var chips = document.getElementById("chips");
    sectors.forEach(function (sec) {
      var b = h("button", { type: "button", "class": "chip", id: "chip-" + sec.replace(/\W+/g, "-").toLowerCase(), "aria-pressed": String(sec === sectorFilter), text: sec });
      b.addEventListener("click", function () {
        sectorFilter = sec;
        Array.prototype.forEach.call(chips.children, function (c) { c.setAttribute("aria-pressed", String(c.textContent === sec)); });
        render();
      });
      chips.appendChild(b);
    });
    var sliders = document.getElementById("sliders");
    CATS.forEach(function (c) {
      var out = h("output", { id: "o-" + c.k, text: "×1.0" });
      var input = h("input", { type: "range", id: "w-" + c.k, min: "0", max: "3", step: "0.5", value: "1" });
      input.addEventListener("input", function () { weights[c.k] = +input.value; out.textContent = "×" + (+input.value).toFixed(1); render(); });
      sliders.appendChild(h("label", { "for": "w-" + c.k }, [h("span", { text: c.label }), out, input]));
    });
    document.getElementById("reset").addEventListener("click", function () {
      CATS.forEach(function (c) { weights[c.k] = 1; document.getElementById("w-" + c.k).value = 1; document.getElementById("o-" + c.k).textContent = "×1.0"; });
      render();
    });
  }

  function buildRows() {
    board = document.getElementById("board");
    P.forEach(function (p) {
      var li = h("li", { "class": "row", id: "row-" + p.id, role: "option", tabindex: "0" });
      li.addEventListener("click", function () { select(p.id); });
      li.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(p.id); } });
      rowEls[p.id] = li;
    });
  }

  function renderBoard() {
    var first = {};
    Object.keys(rowEls).forEach(function (id) { if (rowEls[id].parentNode) first[id] = rowEls[id].getBoundingClientRect().top; });
    var list = P.filter(function (p) { return sectorFilter === "All" || p.sector === sectorFilter; })
      .sort(function (a, b) { return scoreOf(b) - scoreOf(a); });
    clear(board);
    if (!list.length) board.appendChild(h("li", { "class": "empty", text: "No polluters in this sector." }));
    list.forEach(function (p, i) {
      var sc = scoreOf(p), t = tierOf(sc), li = rowEls[p.id];
      li.setAttribute("aria-selected", String(p.id === selected));
      clear(li);
      var meta = p.sector;
      if (p.co2_tonnes) meta += " · " + (p.co2_estimated ? "≈" + fmtT(p.co2_tonnes) + " CO₂/yr (est.)" : fmtT(p.co2_tonnes) + " CO₂" + (p.co2_year && p.co2_year !== 2025 ? " (" + p.co2_year + ")" : ""));
      var fill = h("span", { "class": "bg-" + t[1] }); fill.style.width = sc.toFixed(1) + "%";
      var badges = h("div", { "class": "badges" }, badgesOf(p).map(function (b) { return h("span", { "class": "badge" + (b[1] ? " hot" : ""), text: b[0] }); }));
      li.appendChild(h("div", { "class": "rank", text: String(i + 1) }));
      li.appendChild(h("div", { "class": "who" }, [h("b", { text: p.name }), h("span", { "class": "meta", text: meta }), h("div", { "class": "bar" }, [fill]), badges]));
      li.appendChild(h("div", { "class": "score" }, [h("b", { "class": "c-" + t[1], text: String(Math.round(sc)) }), h("small", { "class": "c-" + t[1], text: t[0] })]));
      board.appendChild(li);
    });
    document.getElementById("count").textContent = list.length + " ranked";
    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!reduce) list.forEach(function (p) {
      var li = rowEls[p.id]; if (first[p.id] === undefined) return;
      var dy = first[p.id] - li.getBoundingClientRect().top; if (!dy) return;
      li.style.transition = "none"; li.style.transform = "translateY(" + dy + "px)";
      requestAnimationFrame(function () { requestAnimationFrame(function () { li.style.transition = "transform .45s cubic-bezier(.2,.7,.2,1)"; li.style.transform = ""; }); });
    });
  }

  function renderDossier() {
    var p = P.filter(function (x) { return x.id === selected; })[0];
    var box = document.getElementById("dossier"); clear(box);
    if (!p) return;
    var sc = scoreOf(p), t = tierOf(sc);
    var rank = P.slice().sort(function (a, b) { return scoreOf(b) - scoreOf(a); }).indexOf(p) + 1;
    var cats = h("div", { "class": "cats" }, CATS.map(function (c) {
      var v = p.pts[c.k], fill = h("span"); fill.style.width = (v / c.max * 100).toFixed(1) + "%";
      var label = h("span", { text: c.label });
      if (weights[c.k] !== 1) label.appendChild(h("span", { "class": "weight-tag mono", text: "×" + weights[c.k] }));
      return h("div", { "class": "cat" }, [label, h("div", { "class": "track" }, [fill]), h("span", { "class": "v", text: v.toFixed(1) + " / " + c.max })]);
    }));
    var big = h("div", { "class": "big c-" + t[1] }, [String(Math.round(sc)), h("small", { text: " / 100" })]);
    box.appendChild(h("div", null, [
      h("h3", { text: p.name }),
      h("span", { "class": "tier bg-" + t[1], text: t[0].toUpperCase() + " · RANK " + rank + " OF " + P.length }),
      big, cats
    ]));
    var ev = h("ul", { "class": "evidence" }, p.evidence.map(function (e) {
      return h("li", null, [h("span", { "class": "d", text: e.date }), e.text + " ", h("a", { href: "#src-" + e.source, text: "[" + e.source + "]" })]);
    }));
    var right = h("div", null, [ev, h("div", { "class": "sites" }, [h("b", { text: "Mapped sites: " }), p.sites.map(function (x) { return x.name; }).join(" · ")])]);
    if (p.note) right.appendChild(h("div", { "class": "note", text: p.note }));
    box.appendChild(right);
  }

  function renderSources() {
    var ol = document.getElementById("srcs"); clear(ol);
    Object.keys(SOURCES).map(Number).sort(function (a, b) { return a - b; }).forEach(function (id) {
      var src = SOURCES[id], url = safeUrl(src.url);
      var li = h("li", { id: "src-" + id, value: String(id) });
      li.appendChild(url ? h("a", { href: url, rel: "noopener noreferrer", text: src.title }) : h("span", { text: src.title + " (link removed: not on allowlist)" }));
      ol.appendChild(li);
    });
  }

  function select(id) { selected = id; render(); }
  function render() { renderBoard(); drawMarkers(); renderDossier(); }

  function start(d) {
    checkData(d);
    d.sources.forEach(function (x) { SOURCES[x.id] = x; });
    P = d.polluters.map(function (p) {
      p.pts = { climate: climatePts(p.co2_tonnes), water: p.points.water, air: p.points.air, enforce: enforcePts(p.enforcement), habitat: p.points.habitat };
      return p;
    });
    var top = P.slice().sort(function (a, b) { return scoreOf(b) - scoreOf(a); })[0];
    selected = top ? top.id : null;
    document.getElementById("reviewed").textContent = d.last_reviewed || "unknown";
    drawBaseMap(); buildControls(); buildRows(); renderSources(); render();
  }

  function fail(err) {
    var b = document.getElementById("board"); clear(b);
    b.appendChild(h("li", { "class": "empty", text: "The scoreboard data could not be loaded. Try refreshing the page." }));
    if (window.console) console.error(err);
  }

  document.addEventListener("DOMContentLoaded", function () {
    fetch(DATA_URL, { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(start).catch(fail);
  });
})();
