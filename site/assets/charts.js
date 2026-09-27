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

  // The ring's inscriptions: the build can only estimate text widths, so
  // the browser measures each one and sets the font size that fills its
  // circle with normal letter spacing. textLength then closes the last
  // fraction of a pixel. Without JavaScript the build's estimate stands.
  function fitInscriptions() {
    Array.prototype.forEach.call(
      document.querySelectorAll(".ring text.ring-script, .ring text.ring-script-2"),
      function (text) {
        var tp = text.querySelector("textPath");
        var path = tp && document.getElementById((tp.getAttribute("href") || "").slice(1));
        if (!path || !path.getTotalLength) return;
        var target = path.getTotalLength();
        tp.removeAttribute("textLength");
        var size = parseFloat(window.getComputedStyle(text).fontSize);
        var natural = text.getComputedTextLength();
        if (!natural || !size) return;
        text.style.fontSize = (size * target / natural).toFixed(2) + "px";
        tp.setAttribute("textLength", target.toFixed(1));
      }
    );
  }

  function start() {
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
