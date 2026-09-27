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

  function start() {
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
