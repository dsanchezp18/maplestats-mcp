/* MapleStats MCP website: tool search, tabs, copy buttons, atlas filters.

   The search is the server's own: search-index.json holds the BM25 index
   search_tools builds (same tokens, k1, b and result count, written by
   scripts/build_site.py), and tokenize() below is a port of
   src/maplestats_mcp/shared/search.py for the query side.

   tokenize() and rank() come first and touch no page, so node can load this
   file (tests/test_site.py checks it ranks as the server does). Each page
   feature after them starts in its own try/catch: one that fails leaves the
   others working. */

(() => {
  "use strict";

  /* ---------- Tokenizer: a port of shared/search.py ---------- */

  function fold(word) {
    if (word.length > 4 && word.endsWith("aux")) return word.slice(0, -3) + "al";
    if (word.length > 4 && (word.endsWith("eux") || word.endsWith("oux"))) return word.slice(0, -1);
    if (word.length > 3 && word.endsWith("s") && !/(ss|us|is)$/.test(word)) return word.slice(0, -1);
    return word;
  }

  // What Python's str.casefold() changes beyond toLowerCase(), for the Latin
  // and Greek text that can reach the index: "Straße" (and "STRASSE") is
  // "strasse" on the server, a final sigma is a sigma, and an iota subscript
  // is an iota. The others casefold treats apart are Cherokee and archaic
  // Cyrillic letters, which no docstring here uses.
  const CASEFOLD = { "ß": "ss", "ς": "σ", "\u0345": "ι" };

  // search.py's STOP_WORDS: French function words, without accents.
  const STOP_WORDS = new Set(
    (
      "au aux avec ce ces cette dans de des du en est et la le les ou par pour " +
      "quel quelle quelles quels que qui sur un une"
    ).split(" "),
  );

  function tokenize(text) {
    // Like search.py: NFKD leaves the ligatures whole, so fold them first.
    // casefold turns the iota subscript inside a letter into an iota too
    // (ᾳ is "αι"), so it is split out (NFD) before it is folded.
    const folded = text
      .toLowerCase()
      .replace(/œ/g, "oe")
      .replace(/æ/g, "ae")
      .normalize("NFD")
      .replace(/[ßς\u0345]/g, (c) => CASEFOLD[c]);
    const plain = folded.normalize("NFKD").replace(/\p{M}/gu, "");
    return (plain.match(/[\p{L}\p{N}]{2,}/gu) || []).filter((w) => !STOP_WORDS.has(w)).map(fold);
  }

  /* ---------- Ranking ---------- */

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

  // Under node there is no page: hand over the search and stop.
  if (typeof document === "undefined") {
    if (typeof module === "object" && module.exports) module.exports = { tokenize, rank };
    return;
  }

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
      // "searchable": plan_query is always listed, so search_tools ranks the others.
      top: (n, total) => `Top ${n} of ${total} searchable tools, ranked by the same BM25 index search_tools uses.`,
      few: (n, total) =>
        `${n} of ${total} searchable tools ${n === 1 ? "matches" : "match"}, ranked by the same BM25 index search_tools uses.`,
      none: "No tool matches. Try a broader term, or the agency's name.",
      offline: "The search index did not load. Open the Tools page instead.",
      tools: (n) => `${n} ${n === 1 ? "tool" : "tools"}`,
      matches: (n) => `${n} ${n === 1 ? "match" : "matches"}`,
      first: (n) => `First ${n} matches`,
      cut: (n) => `Beyond the top ${n}: search_tools would not return these.`,
    },
    fr: {
      copy: "Copier",
      copied: "Copié",
      selected: "Sélectionné, faites Ctrl+C",
      top: (n, total) => `Les ${n} premiers des ${total} outils indexés, classés par le même index BM25 que search_tools.`,
      few: (n, total) =>
        `${n} des ${total} outils indexés ${n === 1 ? "correspond" : "correspondent"}, classés par le même index BM25 que search_tools.`,
      none: "Aucun outil ne correspond. Essayez un terme plus large ou le nom de l'organisme.",
      offline: "L'index de recherche n'a pas été chargé. Ouvrez plutôt la page Outils.",
      // French counts 0 and 1 as singular.
      tools: (n) => `${n} ${n <= 1 ? "outil" : "outils"}`,
      matches: (n) => `${n} ${n <= 1 ? "résultat" : "résultats"}`,
      first: (n) => `Les ${n} premiers résultats`,
      cut: (n) => `Au-delà des ${n} premiers : search_tools ne les renverrait pas.`,
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

  // One feature failing (a missing element, an old browser) must not stop
  // the ones after it.
  const feature = (name, init) => {
    try {
      init();
    } catch (error) {
      if (window.console) console.error(`site.js: ${name} did not start`, error);
    }
  };

  /* ---------- Index loading and result rendering ---------- */

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

  // Tool summaries are the server's English docstrings; a French page marks them.
  const summaryLang = lang === "fr" ? ' lang="en"' : "";

  function resultItem(entry, n, modules, query) {
    const [name, module, summary] = entry;
    const source = (modules[module] || [module, module])[lang === "en" ? 0 : 1];
    return (
      `<li><a href="${pages}tools.html#t-${name}"><span class="r-rank">${n}</span>` +
      `<span class="r-name">${highlight(name, query).replace(/_/g, "_<wbr>")}</span>` +
      `<span class="r-src">${escapeHtml(source)}</span>` +
      `<span class="r-sum"${summaryLang}>${highlight(summary, query)}</span></a></li>`
    );
  }

  function debounce(fn, ms) {
    let timer;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), ms);
    };
  }

  /* ---------- Light / dark switch ---------- */

  feature("theme switch", () => {
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
  });

  /* ---------- Hero search ---------- */

  feature("search", () => {
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
          status.textContent = "";
          return;
        }
        try {
          const { index, modules } = await loadIndex();
          if (asked !== query) return;
          const hits = rank(index, query).slice(0, index.top);
          const total = index.len.length;
          list.innerHTML = hits.map((i, k) => resultItem(index.tools[i], k + 1, modules, query)).join("");
          // The status is the live region: it says how many came back ("Top
          // 5" only when there were 5 to show), or that none did.
          if (!hits.length) status.textContent = T.none;
          else if (hits.length < index.top) status.textContent = T.few(hits.length, total);
          else status.textContent = T.top(index.top, total);
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
      // The first results are rendered at build time, so the index (some
      // 150 KB) is fetched only once the reader comes near the box: on focus,
      // or when it scrolls into view. It then re-ranks so matched words are marked.
      let warmed = false;
      const warm = () => {
        if (warmed) return;
        warmed = true;
        loadIndex().then(run, () => {
          warmed = false;
        });
      };
      input.addEventListener("focus", warm);
      if ("IntersectionObserver" in window) {
        const seen = new IntersectionObserver((entries) => {
          if (entries.some((entry) => entry.isIntersecting)) {
            seen.disconnect();
            warm();
          }
        });
        seen.observe(box);
      } else {
        warm();
      }
    });
  });

  /* ---------- Tabs ---------- */

  feature("tabs", () => {
    document.querySelectorAll("[data-tabs]").forEach((group) => {
      const tabs = Array.from(group.querySelector('[role="tablist"]').querySelectorAll('[role="tab"]'));
      const key = group.dataset.tabs ? `maplestats:${group.dataset.tabs}` : null;

      // A choice by click or by arrow key is kept for the next page.
      const select = (tab, focus, keep) => {
        tabs.forEach((t) => {
          const on = t === tab;
          t.setAttribute("aria-selected", String(on));
          t.tabIndex = on ? 0 : -1;
          const panel = document.getElementById(t.getAttribute("aria-controls"));
          if (panel) panel.hidden = !on;
        });
        if (focus) tab.focus();
        if (keep && key) store.set(key, tab.dataset.key || "");
      };

      tabs.forEach((tab, i) => {
        tab.addEventListener("click", () => select(tab, false, true));
        tab.addEventListener("keydown", (event) => {
          const moves = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 };
          if (!(event.key in moves)) return;
          event.preventDefault();
          select(tabs[(moves[event.key] + tabs.length) % tabs.length], true, true);
        });
      });

      // Every panel is visible in the HTML (so a page without scripts shows
      // them all); starting the tabs hides all but the saved or first one.
      const saved = key && store.get(key);
      const initial =
        (saved && tabs.find((t) => t.dataset.key === saved)) ||
        tabs.find((t) => t.getAttribute("aria-selected") === "true") ||
        tabs[0];
      if (initial) select(initial, false, false);
    });
  });

  /* ---------- Show more ---------- */

  // The block is whole in the HTML; it is cut here, so without scripts the
  // reader still sees all of it.
  feature("show more", () => {
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
  });

  /* ---------- On this page ---------- */

  // The contents list is open in the HTML, so without scripts it shows in
  // full. Here it stays open beside the article on wide screens, starts
  // closed above it on narrow ones, and marks the section being read.
  feature("contents", () => {
    const toc = document.querySelector("[data-toc]");
    if (!toc) return;
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
  });

  /* ---------- Copy buttons ---------- */

  feature("copy buttons", () => {
    // A screen reader is not reliably told when a focused button's text
    // changes, so the outcome also goes to one polite live region.
    let said = null;
    const say = (text) => {
      if (!said) {
        said = document.createElement("p");
        said.className = "sr";
        said.setAttribute("role", "status");
        document.body.append(said);
      }
      said.textContent = "";
      setTimeout(() => {
        said.textContent = text;
      }, 50);
    };
    document.querySelectorAll("[data-copy-target]").forEach((button) => {
      const label = button.textContent;
      button.addEventListener("click", async () => {
        const target = document.getElementById(button.dataset.copyTarget);
        if (!target) return;
        const text = target.innerText.replace(/\n$/, "");
        try {
          await navigator.clipboard.writeText(text);
          button.textContent = T.copied;
          say(T.copied);
        } catch {
          const range = document.createRange();
          range.selectNodeContents(target);
          const selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
          button.textContent = T.selected;
          say(T.selected);
        }
        setTimeout(() => {
          button.textContent = label;
        }, 1600);
      });
    });
  });

  /* ---------- Tool atlas ---------- */

  feature("tool atlas", () => {
    const atlas = document.querySelector("[data-atlas]");
    if (!atlas) return;
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
    // The most tools the atlas lists for one query.
    const LIMIT = 60;

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
        if (shown >= LIMIT) break;
      }
      if (!shown) {
        const none = document.createElement("p");
        none.className = "none";
        none.textContent = T.none;
        results.append(none);
      }
      // At the limit there are usually more matches than shown; say so.
      status.textContent = shown >= LIMIT ? T.first(shown) : T.matches(shown);
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
  });

  // The home page's prompt: types each recorded question, resolves the tool
  // call, then shows the answer with its figures, and moves to the next
  // question every few seconds. Hovering or focusing it, or the Pause button,
  // stops the rotation (after finishing the answer on screen); the buttons
  // below jump to a question. It rests on the first answer, with no motion,
  // for anyone who prefers reduced motion.
  (function askDemo() {
    var root = document.querySelector("[data-ask]");
    var data = root && root.querySelector("[data-ask-examples]");
    if (!root || !data) return;
    var examples;
    try {
      examples = JSON.parse(data.textContent);
    } catch (e) {
      return;
    }
    var stage = root.querySelector("[data-ask-stage]");
    var title = root.querySelector("[data-ask-title]");
    var tabs = Array.prototype.slice.call(root.querySelectorAll("[data-ask-tab]"));
    var toggle = root.querySelector("[data-ask-pause]");
    var calling = root.getAttribute("data-calling");
    var motion = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
    var still = !!(motion && motion.matches);
    var hold = 8000;
    var index = 0;
    var timers = [];
    var userPaused = false;
    var hovering = false;

    function later(fn, ms) {
      timers.push(window.setTimeout(fn, ms));
    }

    function clear() {
      timers.forEach(window.clearTimeout);
      timers = [];
    }

    function el(tag, cls, text) {
      var node = document.createElement(tag);
      node.className = cls;
      if (text) node.textContent = text;
      return node;
    }

    // The tool line and the answer, filled into `into`.
    function fill(into, ex, animate) {
      var tool = el("p", "ask-tool done" + (animate ? " ask-in" : ""));
      tool.appendChild(el("span", "ask-spin"));
      tool.appendChild(document.createTextNode(calling + " "));
      tool.appendChild(el("code", "", ex.tool));
      into.appendChild(tool);
      var a = el("p", "ask-a" + (animate ? " ask-in" : ""));
      a.innerHTML = ex.html;
      into.appendChild(a);
      if (ex.code) {
        var rows = el("ul", "ask-rows" + (animate ? " ask-in" : ""));
        ex.code.split("\n").forEach(function (line) {
          var parts = line.split("  ");
          var li = document.createElement("li");
          li.appendChild(el("span", "", parts[0]));
          li.appendChild(el("b", "", parts.slice(1).join("  ")));
          rows.appendChild(li);
        });
        into.appendChild(rows);
      }
      into.appendChild(el("p", "ask-src" + (animate ? " ask-in" : ""), ex.cite));
    }

    // The window is as tall as its tallest example, so the page below does
    // not move as the questions change.
    function fit() {
      var probe = el("div", "ask-stage");
      probe.style.cssText =
        "position:absolute;visibility:hidden;pointer-events:none;min-height:0;width:" +
        stage.clientWidth +
        "px";
      root.appendChild(probe);
      var tallest = 0;
      examples.forEach(function (ex) {
        probe.innerHTML = "";
        var q = el("p", "ask-q");
        q.appendChild(el("span", "ask-prompt", "\u203a"));
        q.appendChild(document.createTextNode(ex.user));
        probe.appendChild(q);
        fill(probe, ex, false);
        tallest = Math.max(tallest, probe.scrollHeight);
      });
      root.removeChild(probe);
      // A few pixels of slack: text can wrap a line differently once it is on screen.
      stage.style.minHeight = tallest + 16 + "px";
    }

    function mark(i) {
      tabs.forEach(function (tab, k) {
        tab.classList.toggle("on", k === i);
        tab.setAttribute("aria-pressed", k === i ? "true" : "false");
        var mark = tab.querySelector("i");
        mark.style.transition = "none";
        mark.style.width = "0";
      });
    }

    // Wait `ms`, then move on, with the current tab's bar filling meanwhile.
    function rotate(ms) {
      if (still || userPaused || hovering) return;
      var bar = tabs[index].querySelector("i");
      bar.style.transition = "none";
      bar.style.width = "0";
      void bar.offsetWidth;
      bar.style.transition = "width " + ms + "ms linear";
      bar.style.width = "100%";
      later(function () {
        show(index + 1, false);
      }, ms);
    }

    // `instant` shows the finished answer at once, without typing.
    function show(n, instant) {
      clear();
      index = (n + examples.length) % examples.length;
      var ex = examples[index];
      stage.innerHTML = "";
      title.textContent = ex.client;
      mark(index);
      var q = el("p", "ask-q");
      var typed = el("span", "");
      q.appendChild(el("span", "ask-prompt", "\u203a"));
      q.appendChild(typed);
      stage.appendChild(q);
      if (still || instant) {
        typed.textContent = ex.user;
        fill(stage, ex, false);
        rotate(hold);
        return;
      }
      var at = 0;
      (function type() {
        at += 1;
        typed.textContent = ex.user.slice(0, at);
        if (at < ex.user.length) {
          later(type, 22);
          return;
        }
        later(function () {
          var tool = el("p", "ask-tool ask-in");
          tool.appendChild(el("span", "ask-spin"));
          tool.appendChild(document.createTextNode(calling + " "));
          tool.appendChild(el("code", "", ex.tool));
          stage.appendChild(tool);
        }, 350);
        later(function () {
          stage.innerHTML = "";
          stage.appendChild(q);
          fill(stage, ex, true);
        }, 1300);
      })();
      rotate(hold);
    }

    // Stop rotating; the answer on screen is finished, not cut off.
    function hush() {
      clear();
      show(index, true);
      tabs[index].querySelector("i").style.width = "0";
    }

    function resume() {
      if (!userPaused && !hovering) rotate(hold / 2);
    }

    tabs.forEach(function (tab, i) {
      tab.addEventListener("click", function () {
        stage.setAttribute("aria-live", "polite");
        show(i, hovering || userPaused);
      });
    });
    if (toggle) {
      toggle.addEventListener("click", function () {
        userPaused = !userPaused;
        toggle.setAttribute("aria-pressed", userPaused ? "true" : "false");
        toggle.textContent = toggle.getAttribute(userPaused ? "data-play" : "data-pause");
        if (userPaused) hush();
        else resume();
      });
    }
    root.addEventListener("pointerenter", function (event) {
      if (event.pointerType !== "mouse" || still) return;
      hovering = true;
      hush();
    });
    root.addEventListener("pointerleave", function (event) {
      if (event.pointerType !== "mouse" || still) return;
      hovering = false;
      resume();
    });
    root.addEventListener("focusin", function () {
      if (still) return;
      hovering = true;
      hush();
    });
    root.addEventListener("focusout", function (event) {
      if (still || root.contains(event.relatedTarget)) return;
      hovering = false;
      resume();
    });
    if (motion) {
      var onMotion = function (event) {
        still = event.matches;
        if (still) hush();
        else resume();
      };
      if (motion.addEventListener) motion.addEventListener("change", onMotion);
      else if (motion.addListener) motion.addListener(onMotion);
    }
    window.addEventListener("resize", fit);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(fit);
    fit();
    show(0, false);
  })();
})();
