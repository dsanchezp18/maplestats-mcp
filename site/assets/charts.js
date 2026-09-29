/* Starts each [data-chart] SVG's entrance animation (site/assets/charts.css)
 * once 30% of it is on screen, and counts up every [data-count] number inside
 * a chart or a [data-counters] list at the same moment. The final numbers are
 * already in the page, so without JavaScript, without IntersectionObserver,
 * or with reduced motion, they simply show. No dependencies, no modules. */
(function () {
  "use strict";

  var still = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // "1,610,458" or "1 610 458": count up in the same format, keeping the
  // page's own thousands separator.
  function countUp(el) {
    var text = el.textContent;
    var digits = text.replace(/\D/g, "");
    var sep = (text.match(/\d(\D)\d{3}(?!\d)/) || [])[1] || "";
    var target = parseInt(digits, 10);
    if (still || !target || target < 10) return;
    var start = null;
    var duration = 1400;
    function format(n) {
      var s = String(n);
      return sep ? s.replace(/\B(?=(\d{3})+(?!\d))/g, sep) : s;
    }
    function frame(now) {
      if (start === null) start = now;
      var t = Math.min((now - start) / duration, 1);
      var eased = 1 - Math.pow(1 - t, 3);
      el.textContent = format(Math.round(target * eased));
      if (t < 1) {
        window.requestAnimationFrame(frame);
      } else {
        el.textContent = text;
      }
    }
    el.textContent = format(0);
    window.requestAnimationFrame(frame);
  }

  function play(target) {
    target.classList.add("play");
    Array.prototype.forEach.call(target.querySelectorAll("[data-count]"), countUp);
  }

  // The square's inscriptions: the build can only estimate text widths, so
  // the browser measures each one and sets the font size that fills its
  // path with normal letter spacing. textLength then closes the last
  // fraction of a pixel. Without JavaScript the build's estimate stands.
  function fitInscriptions() {
    var bands = {};
    Array.prototype.forEach.call(
      document.querySelectorAll(".square text.sq-script, .square text.sq-script-2"),
      function (text) {
        var tp = text.querySelector("textPath");
        var path = tp && document.getElementById((tp.getAttribute("href") || "").slice(1));
        if (!path || !path.getTotalLength) return;
        var target = path.getTotalLength();
        tp.removeAttribute("textLength");
        var size = parseFloat(window.getComputedStyle(text).fontSize);
        var natural = text.getComputedTextLength();
        if (!natural || !size) return;
        var key = text.getAttribute("data-band") || "";
        (bands[key] = bands[key] || []).push({
          text: text,
          tp: tp,
          target: target,
          fit: (size * target) / natural,
        });
      }
    );
    // A band's two halves share the smaller fitted size, so the top and
    // bottom lettering match; textLength spaces the shorter one out.
    Object.keys(bands).forEach(function (key) {
      var size = Math.min.apply(
        null,
        bands[key].map(function (half) {
          return half.fit;
        })
      );
      bands[key].forEach(function (half) {
        half.text.style.fontSize = size.toFixed(2) + "px";
        half.tp.setAttribute("textLength", half.target.toFixed(1));
      });
    });
  }

  // The inscriptions turn by SMIL, which ignores the reduced-motion
  // preference: remove the animation for anyone who asked for less, now or
  // later. Offscreen squares are paused so they do not run for nothing.
  function stillInscriptions() {
    var query = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)");
    function stop() {
      Array.prototype.forEach.call(document.querySelectorAll(".square animate"), function (a) {
        a.parentNode.removeChild(a);
      });
    }
    if (query && query.matches) stop();
    if (query && query.addEventListener) {
      query.addEventListener("change", function (event) {
        if (event.matches) stop();
      });
    }
    if (!("IntersectionObserver" in window)) return;
    var watcher = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        var svg = entry.target;
        if (!svg.pauseAnimations) return;
        if (entry.isIntersecting) svg.unpauseAnimations();
        else svg.pauseAnimations();
      });
    });
    Array.prototype.forEach.call(document.querySelectorAll("svg.square"), function (svg) {
      watcher.observe(svg);
    });
  }

  function start() {
    stillInscriptions();
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(fitInscriptions);
    } else {
      fitInscriptions();
    }
    var targets = Array.prototype.slice.call(
      document.querySelectorAll("[data-chart], [data-counters]")
    );
    if (!("IntersectionObserver" in window)) {
      targets.forEach(function (target) {
        target.classList.add("play");
      });
      return;
    }
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting && entry.intersectionRatio >= 0.3) {
            play(entry.target);
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.3 }
    );
    targets.forEach(function (target) {
      observer.observe(target);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
