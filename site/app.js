(function () {
  "use strict";
  var DATA_URL = "data/data.json";
  var MAP_URL = "data/ireland-map.json";
  var SITKA_URL = "data/sitka-grid.json";
  var ALLOWED_LINK_HOSTS = [
    "epa.ie", "irishtimes.com", "irishexaminer.com", "smartwatermagazine.com",
    "sustainabilityonline.net", "farmersjournal.ie", "donegallive.ie",
    "fisheriesireland.ie", "catchments.ie", "agriland.ie", "europa.eu",
    "bnm.ie", "leinsterexpress.ie", "data.gov.ie", "ucc.ie", "mapsvg.com", "cloudflare.com", "dataprotection.ie"
  ];
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
  function checkData(d) {
    if (!d || !Array.isArray(d.polluters) || !Array.isArray(d.sources)) throw new Error("bad shape");
    d.polluters.forEach(function (p) {
      if (typeof p.id !== "string" || typeof p.name !== "string") throw new Error("bad polluter");
      if (!num(p.points.water, 0, 25) || !num(p.points.air, 0, 10) || !num(p.points.habitat, 0, 15)) throw new Error("bad points: " + p.id);
      p.sites.forEach(function (x) { if (!num(x.lat, 51, 55.6) || !num(x.lng, -11, -5.3)) throw new Error("bad site: " + p.id); });
    });
    return d;
  }
  var MAP = null, W = 0, H = 0, AREAS = [];
  function merc(lat) { return Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)); }
  function proj(lng, lat) {
    var g = MAP.geo_bounds;
    return [(lng - g.west) / (g.east - g.west) * W,
            (merc(g.north) - merc(lat)) / (merc(g.north) - merc(g.south)) * H];
  }
  function decodeRing(str, unit) {
    var n = str.split(",").map(Number), pts = [], x = 0, y = 0;
    for (var i = 0; i + 1 < n.length; i += 2) {
      if (i === 0) { x = n[0]; y = n[1]; } else { x += n[i]; y += n[i + 1]; }
      pts.push([x * unit, y * unit]);
    }
    return pts;
  }
  function inRing(x, y, pts) {
    var inside = false;
    for (var i = 0, j = pts.length - 1; i < pts.length; j = i++) {
      var xi = pts[i][0], yi = pts[i][1], xj = pts[j][0], yj = pts[j][1];
      if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }
  function areaAt(lng, lat) {
    var xy = proj(lng, lat);
    for (var i = 0; i < AREAS.length; i++) {
      if (AREAS[i].rings.some(function (r) { return inRing(xy[0], xy[1], r); })) return AREAS[i];
    }
    return null;
  }
  function checkMap(m) {
    if (!m || !Array.isArray(m.areas) || !num(m.width, 100, 2000) || !num(m.height, 100, 2000) || !num(m.unit, 0.01, 1)) throw new Error("bad map");
    m.areas.forEach(function (a) {
      if (!/^(IE-[A-Z]{1,2}|GB-NIR)$/.test(a.id) || typeof a.name !== "string") throw new Error("bad area");
      a.rings.forEach(function (r) { if (!/^-?\d{1,5}(,-?\d{1,5})*$/.test(r)) throw new Error("bad ring"); });
    });
    return m;
  }
  var P = [], SOURCES = {}, sectorFilter = "All", countyFilter = null, selected = null;
  var svg, markers, tip, board, rowEls = {}, countyEls = {}, sitkaLayer;
  function drawBaseMap() {
    svg = document.getElementById("map");
    svg.setAttribute("viewBox", "-6 -6 " + (W + 12).toFixed(0) + " " + (H + 12).toFixed(0));
    var grid = s("g", { "class": "sea-grid" }, svg);
    for (var lat = 52; lat <= 55; lat++) {
      var y = proj(-8, lat)[1];
      s("line", { x1: -6, x2: W + 6, y1: y, y2: y }, grid);
      s("text", { x: -2, y: y - 3, "class": "grid-label" }, grid).textContent = lat + "°N";
    }
    for (var lng = -10; lng <= -6; lng++) {
      var x = proj(lng, 53)[0];
      s("line", { x1: x, x2: x, y1: -6, y2: H + 6 }, grid);
      s("text", { x: x + 3, y: H + 2, "class": "grid-label" }, grid).textContent = Math.abs(lng) + "°W";
    }
    var land = s("g", { "class": "counties" }, svg);
    AREAS.forEach(function (a) {
      var d = a.rings.map(function (r) { return "M" + r.map(function (p) { return p[0].toFixed(1) + "," + p[1].toFixed(1); }).join("L") + "Z"; }).join("");
      var ni = a.id === "GB-NIR";
      var el = s("path", { "class": "county" + (ni ? " ni" : ""), d: d }, land);
      s("title", {}, el).textContent = a.name;
      if (!ni) {
        el.setAttribute("tabindex", "0");
        el.setAttribute("role", "button");
        el.addEventListener("click", function () { setCounty(countyFilter === a.id ? null : a.id); });
        el.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setCounty(countyFilter === a.id ? null : a.id); } });
        countyEls[a.id] = el;
      }
    });
    var ni = AREAS.filter(function (a) { return a.id === "GB-NIR"; })[0];
    if (ni) { var c = proj(-6.75, 54.62); s("text", { x: c[0], y: c[1], "class": "ni-label", "text-anchor": "middle" }, svg).textContent = "N. IRELAND"; }
    sitkaLayer = s("g", { "class": "sitka", "aria-hidden": "true" }, svg);
    markers = s("g", {}, svg);
    tip = document.getElementById("tip");
    var legend = document.getElementById("legend");
    [["Critical 50+", "crit"], ["High 35–49", "high"], ["Elevated 22–34", "elev"], ["Watch <22", "watch"]].forEach(function (l) {
      legend.appendChild(h("span", null, [h("i", { "class": "bg-" + l[1] }), l[0]]));
    });
    legend.appendChild(h("span", { "class": "legend-note", text: "County shading = worst score in that county. Click a county to filter." }));
  }
  var SITKA_STEPS = [50, 200, 500, 1000];
  function checkSitka(g) {
    if (!g || !Array.isArray(g.cells) || g.cells.length > 8000 || !g.origin || !g.cell) throw new Error("bad sitka grid");
    if (!num(g.origin.lat, 51, 52) || !num(g.origin.lng, -11, -10) || !num(g.cell.dlat, 0.01, 0.2) || !num(g.cell.dlng, 0.01, 0.3)) throw new Error("bad sitka grid");
    g.cells.forEach(function (c) { if (!Array.isArray(c) || !num(c[0], 0, 80) || !num(c[1], 0, 90) || !num(c[2], 1, 3000)) throw new Error("bad sitka cell"); });
    return g;
  }
  function drawSitka(g) {
    g.cells.forEach(function (c) {
      var lng0 = g.origin.lng + c[0] * g.cell.dlng, lat0 = g.origin.lat + c[1] * g.cell.dlat;
      var a = proj(lng0, lat0 + g.cell.dlat), b = proj(lng0 + g.cell.dlng, lat0);
      var step = SITKA_STEPS.filter(function (t) { return c[2] >= t; }).length + 1;
      s("rect", { x: a[0].toFixed(1), y: a[1].toFixed(1), width: (b[0] - a[0]).toFixed(1), height: (b[1] - a[1]).toFixed(1), "class": "s" + step }, sitkaLayer);
    });
    var legend = document.getElementById("legend");
    var keyEl = h("div", { "class": "sitka-key", hidden: "hidden" });
    var swatches = h("span", { "class": "sitka-swatches" }, ["Hectares per square: "]);
    ["under 50", "50–199", "200–499", "500–999", "1,000+"].forEach(function (label, i) {
      swatches.appendChild(h("span", null, [h("i", { "class": "sw s" + (i + 1) }), label]));
    });
    keyEl.appendChild(swatches);
    var url = safeUrl(g.source_url);
    keyEl.appendChild(h("p", null, [
      "Coillte forest where Sitka spruce is the main species, added up in squares of about 5 km (" + Math.round(g.total_ha).toLocaleString("en-IE") + " ha in total). Source: ",
      url ? h("a", { href: url, rel: "noopener noreferrer", text: g.source }) : g.source,
      ", fetched " + g.fetched + "."
    ]));
    var btn = h("button", { type: "button", "class": "chip sitka-toggle", "aria-pressed": "false", text: "Show Sitka spruce plantations" });
    btn.addEventListener("click", function () {
      var on = btn.getAttribute("aria-pressed") !== "true";
      btn.setAttribute("aria-pressed", String(on));
      btn.textContent = on ? "Hide Sitka spruce plantations" : "Show Sitka spruce plantations";
      sitkaLayer.setAttribute("class", "sitka" + (on ? " on" : ""));
      [keyEl, document.getElementById("sitka-about")].forEach(function (el) {
        if (!el) return;
        if (on) el.removeAttribute("hidden"); else el.setAttribute("hidden", "hidden");
      });
    });
    legend.insertBefore(keyEl, legend.firstChild);
    legend.insertBefore(btn, legend.firstChild);
  }
  function inCounty(p) { return !countyFilter || p.counties.indexOf(countyFilter) >= 0; }
  function visible(p) { return (sectorFilter === "All" || p.sector === sectorFilter) && inCounty(p); }
  function shadeCounties() {
    Object.keys(countyEls).forEach(function (id) {
      var worst = -1, n = 0;
      P.forEach(function (p) { if (p.counties.indexOf(id) >= 0 && (sectorFilter === "All" || p.sector === sectorFilter)) { n++; worst = Math.max(worst, scoreOf(p)); } });
      var el = countyEls[id], name = AREAS.filter(function (a) { return a.id === id; })[0].name;
      el.setAttribute("class", "county" + (worst >= 0 ? " heat-" + tierOf(worst)[1] : "") + (countyFilter === id ? " active" : ""));
      el.setAttribute("aria-label", name + (n ? ": " + n + " polluter" + (n > 1 ? "s" : "") + ", worst score " + Math.round(worst) : ": no polluters listed") + (countyFilter === id ? ", selected" : ""));
      el.setAttribute("aria-pressed", String(countyFilter === id));
    });
  }
  function setCounty(id) {
    countyFilter = id;
    var box = document.getElementById("countyfilter"); clear(box);
    if (id) {
      var name = AREAS.filter(function (a) { return a.id === id; })[0].name;
      var b = h("button", { type: "button", "class": "chip county-chip", "aria-pressed": "true", text: "Co. " + name + " ✕" });
      b.setAttribute("aria-label", "Clear county filter (" + name + ")");
      b.addEventListener("click", function () { setCounty(null); });
      box.appendChild(b);
      var first = P.filter(visible).sort(function (a, b) { return scoreOf(b) - scoreOf(a); })[0];
      if (first) selected = first.id;
    }
    render();
  }
  function drawMarkers() {
    clear(markers);
    P.slice().sort(function (a, b) { return scoreOf(a) - scoreOf(b); }).forEach(function (p) {
      var sc = scoreOf(p), t = tierOf(sc), col = tierColor(t[1]);
      var dim = !visible(p);
      p.sites.forEach(function (site, i) {
        var xy = proj(site.lng, site.lat), r = (3 + sc / 9) * 1.15;
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
    var list = P.filter(visible)
      .sort(function (a, b) { return scoreOf(b) - scoreOf(a); });
    clear(board);
    if (!list.length) board.appendChild(h("li", { "class": "empty", text: "No polluters match these filters." }));
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
    var back = h("button", { type: "button", "class": "back-to-board", text: "↑ Back to the scoreboard" });
    back.addEventListener("click", function () {
      var row = rowEls[selected];
      (row && row.parentNode ? row : document.getElementById("board")).scrollIntoView({ behavior: smooth(), block: "center" });
      if (row) row.focus({ preventScroll: true });
    });
    box.appendChild(back);
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
    var n = Object.keys(SOURCES).length;
    document.getElementById("srccount").textContent = n + " source" + (n === 1 ? "" : "s") + " · show all";
  }
  function revealSource(hash, scroll) {
    if (!/^#src-\d+$/.test(hash || "")) return;
    var li = document.getElementById(hash.slice(1));
    if (!li) return;
    document.getElementById("srcbox").open = true;
    Array.prototype.forEach.call(document.querySelectorAll("ol.srcs li.hit"), function (x) { x.classList.remove("hit"); });
    li.classList.add("hit");
    if (scroll) li.scrollIntoView({ block: "center" });
  }
  document.addEventListener("click", function (e) {
    var a = e.target.closest ? e.target.closest('a[href^="#src-"]') : null;
    if (a) revealSource(a.getAttribute("href"), false);
  });
  window.addEventListener("hashchange", function () { revealSource(location.hash, true); });
  var narrow = window.matchMedia ? window.matchMedia("(max-width: 980px)") : null;
  function smooth() { return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"; }
  function select(id) {
    selected = id; render();
    if (narrow && narrow.matches) document.querySelector(".dossier").scrollIntoView({ behavior: smooth(), block: "start" });
  }
  function render() { renderBoard(); shadeCounties(); drawMarkers(); renderDossier(); }
  function start(d, m, sitka) {
    checkData(d);
    MAP = checkMap(m); W = MAP.width; H = MAP.height;
    AREAS = MAP.areas.map(function (a) { return { id: a.id, name: a.name, rings: a.rings.map(function (r) { return decodeRing(r, MAP.unit); }) }; });
    d.sources.forEach(function (x) { SOURCES[x.id] = x; });
    P = d.polluters.map(function (p) {
      p.counties = [];
      p.sites.forEach(function (x) { var a = areaAt(x.lng, x.lat); if (a && p.counties.indexOf(a.id) < 0) p.counties.push(a.id); });
      p.pts = { climate: climatePts(p.co2_tonnes), water: p.points.water, air: p.points.air, enforce: enforcePts(p.enforcement), habitat: p.points.habitat };
      return p;
    });
    var top = P.slice().sort(function (a, b) { return scoreOf(b) - scoreOf(a); })[0];
    selected = top ? top.id : null;
    document.getElementById("reviewed").textContent = d.last_reviewed || "unknown";
    drawBaseMap(); buildControls(); buildRows(); renderSources(); render(); revealSource(location.hash, true);
    if (sitka) {
      try { drawSitka(checkSitka(sitka)); } catch (e) { if (window.console) console.error(e); }
    }
  }
  function fail(err) {
    var b = document.getElementById("board"); clear(b);
    b.appendChild(h("li", { "class": "empty", text: "The scoreboard data could not be loaded. Try refreshing the page." }));
    if (window.console) console.error(err);
  }
  document.addEventListener("DOMContentLoaded", function () {
    function get(url) { return fetch(url, { credentials: "same-origin" }).then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }); }
    Promise.all([get(DATA_URL), get(MAP_URL), get(SITKA_URL).catch(function () { return null; })])
      .then(function (res) { start(res[0], res[1], res[2]); }).catch(fail);
  });
})();
