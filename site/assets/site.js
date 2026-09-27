/* MapleStats MCP website: tool search, tabs, copy buttons, atlas filters.

   The search is the server's own: search-index.json holds the BM25 index
   search_tools builds (same tokens, k1, b and result count, written by
   scripts/build_site.py), and tokenize() below is a port of
   src/maplestats_mcp/shared/search.py for the query side. */

(() => {
  "use strict";

  const doc = document.documentElement;
  const lang = doc.lang === "fr" ? "fr" : "en";
  const root = doc.dataset.root || "";
  // Pages sit next to the current one (fr/ links to fr/); assets are under root.
  const pages = doc.dataset.pages ?? root;
  const T = {
    en: {
      copy: "Copy",
      copied: "Copied",
      selected: "Selected, press Ctrl+C",
      top: (n, total) => `Top ${n} of ${total} tools, ranked by the same BM25 index search_tools uses.`,
      none: "No tool matches. Try a broader term, or the agency's name.",
      offline: "The search index did not load. Open the Tools page instead.",
      tools: (n) => `${n} ${n === 1 ? "tool" : "tools"}`,
      matches: (n) => `${n} ${n === 1 ? "match" : "matches"}`,
      cut: (n) => `Beyond the top ${n}: search_tools would not return these.`,
    },
    fr: {
      copy: "Copier",
      copied: "Copié",
      selected: "Sélectionné, faites Ctrl+C",
      top: (n, total) => `Les ${n} premiers sur ${total} outils, classés par le même index BM25 que search_tools.`,
      none: "Aucun outil ne correspond. Essayez un terme plus large ou le nom de l'organisme.",
      offline: "L'index de recherche n'a pas été chargé. Ouvrez plutôt la page Outils.",
      tools: (n) => `${n} ${n === 1 ? "outil" : "outils"}`,
      matches: (n) => `${n} ${n === 1 ? "résultat" : "résultats"}`,
      cut: (n) => `Au-delà des ${n} premiers : search_tools ne les renverrait pas.`,
    },
  }[lang];

  const store = {
    get(key) {
      try {
        return localStorage.getItem(key);
      } catch {
        return null;
      }
    },
    set(key, value) {
      try {
        localStorage.setItem(key, value);
      } catch {
        /* private mode or blocked storage: the choice is simply not kept */
      }
    },
  };

  /* ---------- Light / dark switch ---------- */

  const themeLabels = {
    en: { dark: "Dark", light: "Light", toDark: "Switch to dark mode", toLight: "Switch to light mode" },
    fr: { dark: "Sombre", light: "Clair", toDark: "Passer au mode sombre", toLight: "Passer au mode clair" },
  }[lang];
  const systemDark = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  const currentTheme = () => doc.dataset.theme || (systemDark && systemDark.matches ? "dark" : "light");

  document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
    const label = button.querySelector("[data-theme-label]");
    const show = () => {
      const dark = currentTheme() === "dark";
      // The button names the mode it switches to.
      label.textContent = dark ? themeLabels.light : themeLabels.dark;
      button.setAttribute("aria-label", dark ? themeLabels.toLight : themeLabels.toDark);
    };
    button.addEventListener("click", () => {
      const next = currentTheme() === "dark" ? "light" : "dark";
      doc.dataset.theme = next;
      store.set("maplestats:theme", next);
      show();
    });
    if (systemDark && systemDark.addEventListener) systemDark.addEventListener("change", show);
    button.hidden = false;
    show();
  });

  /* ---------- Tokenizer: a port of shared/search.py ---------- */

  function fold(word) {
    if (word.length > 4 && word.endsWith("aux")) return word.slice(0, -3) + "al";
    if (word.length > 4 && (word.endsWith("eux") || word.endsWith("oux"))) return word.slice(0, -1);
    if (word.length > 3 && word.endsWith("s") && !/(ss|us|is)$/.test(word)) return word.slice(0, -1);
    return word;
  }

  function tokenize(text) {
    // Like search.py: NFKD leaves the ligatures whole, so fold them first.
    const folded = text.toLowerCase().replace(/œ/g, "oe").replace(/æ/g, "ae");
    const plain = folded.normalize("NFKD").replace(/\p{M}/gu, "");
    return (plain.match(/[\p{L}\p{N}]{2,}/gu) || []).map(fold);
  }

  /* ---------- Index and ranking ---------- */

  let loading = null;

  function loadIndex() {
    if (!loading) {
      const get = (name) =>
        fetch(`${root}assets/${name}`).then((r) => {
          if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
          return r.json();
        });
      loading = Promise.all([get("search-index.json"), get("modules.json")]).then(([index, modules]) => ({
        index,
        modules,
      }));
      loading.catch(() => {
        loading = null;
      });
    }
    return loading;
  }

  // Mirrors fastmcp's _BM25Index.query term for term, including the order
  // of operations, so ties and scores come out as they do on the server.
  function rank(index, query) {
    const n = index.len.length;
    const scores = new Float64Array(n);
    for (const token of tokenize(query)) {
      const posting = index.post[token];
      if (!posting) continue;
      const df = posting.length / 2;
      const idf = Math.log((n - df + 0.5) / (df + 0.5) + 1.0);
      for (let j = 0; j < posting.length; j += 2) {
        const i = posting[j];
        const tf = posting[j + 1];
        const numerator = tf * (index.k1 + 1);
        const denominator = tf + index.k1 * (1 - index.b + (index.b * index.len[i]) / index.avg);
        scores[i] += (idf * numerator) / denominator;
      }
    }
    const hits = [];
    for (let i = 0; i < n; i++) if (scores[i] > 0) hits.push(i);
    return hits.sort((a, b) => scores[b] - scores[a] || a - b);
  }

  function escapeHtml(text) {
    return text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  // Wraps the words of `text` whose folded token the query contains.
  function highlight(text, query) {
    const wanted = new Set(tokenize(query));
    return text
      .split(/([\p{L}\p{N}]+)/u)
      .map((part, i) => {
        if (i % 2 === 0) return escapeHtml(part);
        const [token] = tokenize(part);
        return token && wanted.has(token) ? `<mark>${escapeHtml(part)}</mark>` : escapeHtml(part);
      })
      .join("");
  }

  function resultItem(entry, n, modules, query) {
    const [name, module, summary] = entry;
    const source = (modules[module] || [module, module])[lang === "en" ? 0 : 1];
    return (
      `<li><a href="${pages}tools.html#t-${name}"><span class="r-rank">${n}</span>` +
      `<span class="r-name">${highlight(name, query).replace(/_/g, "_<wbr>")}</span>` +
      `<span class="r-src">${escapeHtml(source)}</span>` +
      `<span class="r-sum">${highlight(summary, query)}</span></a></li>`
    );
  }

  function debounce(fn, ms) {
    let timer;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), ms);
    };
  }

  /* ---------- Hero search ---------- */

  document.querySelectorAll("[data-live-search]").forEach((box) => {
    const input = box.querySelector("input");
    const list = box.querySelector("[data-results]");
    const status = box.querySelector("[data-status]");
    let asked = "";

    const run = async () => {
      const query = input.value.trim();
      asked = query;
      if (!query) {
        list.innerHTML = "";
        return;
      }
      try {
        const { index, modules } = await loadIndex();
        if (asked !== query) return;
        const hits = rank(index, query).slice(0, index.top);
        list.innerHTML = hits.length
          ? hits.map((i, k) => resultItem(index.tools[i], k + 1, modules, query)).join("")
          : `<li class="empty">${T.none}</li>`;
        status.textContent = T.top(index.top, index.len.length);
      } catch {
        status.textContent = T.offline;
      }
    };

    input.addEventListener("input", debounce(run, 60));
    box.querySelectorAll("[data-q]").forEach((button) =>
      button.addEventListener("click", () => {
        input.value = button.dataset.q;
        run();
      }),
    );
    // The first results are rendered at build time; re-rank once the index
    // arrives so the matched words are marked.
    loadIndex().then(run, () => {});
  });

  /* ---------- Tabs ---------- */

  document.querySelectorAll("[data-tabs]").forEach((group) => {
    const tabs = Array.from(group.querySelector('[role="tablist"]').querySelectorAll('[role="tab"]'));
    const key = group.dataset.tabs ? `maplestats:${group.dataset.tabs}` : null;

    const select = (tab, focus) => {
      tabs.forEach((t) => {
        const on = t === tab;
        t.setAttribute("aria-selected", String(on));
        t.tabIndex = on ? 0 : -1;
        const panel = document.getElementById(t.getAttribute("aria-controls"));
        if (panel) panel.hidden = !on;
      });
      if (focus) tab.focus();
    };

    tabs.forEach((tab, i) => {
      tab.addEventListener("click", () => {
        select(tab, false);
        if (key) store.set(key, tab.dataset.key || "");
      });
      tab.addEventListener("keydown", (event) => {
        const moves = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 };
        if (!(event.key in moves)) return;
        event.preventDefault();
        select(tabs[(moves[event.key] + tabs.length) % tabs.length], true);
      });
    });

    const saved = key && store.get(key);
    const initial = saved && tabs.find((t) => t.dataset.key === saved);
    if (initial) select(initial, false);
  });

  /* ---------- Show more ---------- */

  // The block is whole in the HTML; it is cut here, so without scripts the
  // reader still sees all of it.
  document.querySelectorAll("[data-more]").forEach((box) => {
    const button = box.querySelector("[data-more-label]");
    if (!button) return;
    const set = (collapsed) => {
      box.toggleAttribute("data-collapsed", collapsed);
      button.setAttribute("aria-expanded", String(!collapsed));
      button.textContent = collapsed ? button.dataset.moreLabel : button.dataset.lessLabel;
    };
    button.addEventListener("click", () => {
      const collapse = !box.hasAttribute("data-collapsed");
      set(collapse);
      // Collapsing a long script can leave the reader below it.
      if (collapse && box.getBoundingClientRect().top < 0) box.scrollIntoView({ block: "start" });
    });
    set(true);
    button.hidden = false;
  });

  /* ---------- On this page ---------- */

  // The contents list is open in the HTML, so without scripts it shows in
  // full. Here it stays open beside the article on wide screens, starts
  // closed above it on narrow ones, and marks the section being read.
  const toc = document.querySelector("[data-toc]");
  if (toc) {
    const box = toc.querySelector("details");
    const summary = box && box.querySelector("summary");
    const wide = window.matchMedia("(min-width: 1241px)");
    const fit = () => {
      if (box) box.open = wide.matches;
    };
    fit();
    if (wide.addEventListener) wide.addEventListener("change", fit);
    if (summary) {
      summary.addEventListener("click", (event) => {
        if (wide.matches) event.preventDefault();
      });
    }
    const links = Array.from(toc.querySelectorAll('a[href^="#"]'));
    const targets = links.map((a) => document.getElementById(decodeURIComponent(a.hash.slice(1))));
    links.forEach((a) =>
      a.addEventListener("click", () => {
        if (box && !wide.matches) box.open = false;
      }),
    );
    let queued = false;
    const mark = () => {
      queued = false;
      const line = window.innerHeight * 0.3;
      let current = -1;
      targets.forEach((el, i) => {
        if (el && el.getBoundingClientRect().top <= line) current = i;
      });
      // At the very bottom the last short sections can never reach the line.
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) {
        current = targets.length - 1;
      }
      links.forEach((a, i) => {
        if (i === current) a.setAttribute("aria-current", "location");
        else a.removeAttribute("aria-current");
      });
    };
    const queue = () => {
      if (!queued) {
        queued = true;
        window.requestAnimationFrame(mark);
      }
    };
    window.addEventListener("scroll", queue, { passive: true });
    window.addEventListener("resize", queue);
    mark();
  }

  /* ---------- Copy buttons ---------- */

  document.querySelectorAll("[data-copy-target]").forEach((button) => {
    const label = button.textContent;
    button.addEventListener("click", async () => {
      const target = document.getElementById(button.dataset.copyTarget);
      if (!target) return;
      const text = target.innerText.replace(/\n$/, "");
      try {
        await navigator.clipboard.writeText(text);
        button.textContent = T.copied;
      } catch {
        const range = document.createRange();
        range.selectNodeContents(target);
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
        button.textContent = T.selected;
      }
      setTimeout(() => {
        button.textContent = label;
      }, 1600);
    });
  });

  /* ---------- Tool atlas ---------- */

  const atlas = document.querySelector("[data-atlas]");
  if (atlas) {
    const input = document.getElementById("atlas-q");
    const status = atlas.querySelector("[data-atlas-status]");
    const groups = atlas.querySelector("[data-atlas-groups]");
    const results = atlas.querySelector("[data-atlas-results]");
    const chips = Array.from(atlas.querySelectorAll(".chip[data-level]"));
    const indexLinks = Array.from(atlas.querySelectorAll(".atlas-index li[data-level]"));
    const tools = new Map();
    const levelOf = new Map();
    const homes = new Map();
    let level = "all";
    let asked = "";

    atlas.querySelectorAll("details.tool").forEach((el) => {
      const name = el.dataset.tool;
      tools.set(name, el);
      levelOf.set(name, el.closest(".mod").dataset.level);
      const home = document.createComment(name);
      el.before(home);
      homes.set(name, home);
    });

    const restore = () => {
      tools.forEach((el, name) => {
        homes.get(name).after(el);
        el.querySelector(".t-rank")?.remove();
      });
    };

    const countVisible = () => {
      let n = 0;
      tools.forEach((_, name) => {
        if (level === "all" || levelOf.get(name) === level) n++;
      });
      return n;
    };

    const apply = async () => {
      const query = input.value.trim();
      asked = query;
      atlas.querySelectorAll(".mod").forEach((section) => {
        section.hidden = level !== "all" && section.dataset.level !== level;
      });
      indexLinks.forEach((li) => {
        li.hidden = level !== "all" && li.dataset.level !== level;
      });
      if (!query) {
        restore();
        results.hidden = true;
        groups.hidden = false;
        status.textContent = T.tools(countVisible());
        return;
      }
      let loaded;
      try {
        loaded = await loadIndex();
      } catch {
        status.textContent = T.offline;
        return;
      }
      if (asked !== query) return;
      const { index } = loaded;
      restore();
      results.replaceChildren();
      groups.hidden = true;
      results.hidden = false;
      let shown = 0;
      for (const i of rank(index, query)) {
        const name = index.tools[i][0];
        const el = tools.get(name);
        if (!el || (level !== "all" && levelOf.get(name) !== level)) continue;
        if (shown === index.top) {
          const cut = document.createElement("p");
          cut.className = "label top-cut";
          cut.textContent = T.cut(index.top);
          results.append(cut);
        }
        shown++;
        const badge = document.createElement("span");
        badge.className = "t-rank";
        badge.textContent = String(shown);
        el.querySelector("summary .t-name").before(badge);
        results.append(el);
        if (shown >= 60) break;
      }
      if (!shown) {
        const none = document.createElement("p");
        none.className = "none";
        none.textContent = T.none;
        results.append(none);
      }
      status.textContent = T.matches(shown);
    };

    input.addEventListener("input", debounce(apply, 80));
    chips.forEach((chip) =>
      chip.addEventListener("click", () => {
        level = chip.dataset.level;
        chips.forEach((c) => c.setAttribute("aria-pressed", String(c === chip)));
        apply();
      }),
    );

    const openFromHash = () => {
      const id = decodeURIComponent(location.hash.slice(1));
      const el = id && document.getElementById(id);
      if (el && el.tagName === "DETAILS") el.open = true;
    };
    window.addEventListener("hashchange", openFromHash);
    openFromHash();
    status.textContent = T.tools(countVisible());
  }
})();
