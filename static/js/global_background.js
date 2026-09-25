(function () {
  "use strict";

  function setupGlobalParticles() {
    var canvas = document.getElementById("ogaGlobalParticles");
    if (!canvas || canvas.dataset.ready === "1") return;

    var ctx = canvas.getContext("2d");
    if (!ctx) return;

    canvas.dataset.ready = "1";

    var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var smallScreen = window.matchMedia("(max-width: 720px)").matches;
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var particles = [];
    var width = 0;
    var height = 0;
    var raf = null;
    var mouse = { x: -9999, y: -9999, active: false };
    var maxParticles = reduceMotion ? 20 : (smallScreen ? 34 : 68);
    var linkDistance = smallScreen ? 90 : 120;

    function random(min, max) {
      return Math.random() * (max - min) + min;
    }

    function createParticle() {
      return {
        x: random(0, width),
        y: random(0, height),
        r: random(1, 3.2),
        vx: random(-0.22, 0.22),
        vy: random(-0.18, 0.18),
        alpha: random(0.22, 0.82),
        pulse: random(0.004, 0.012),
        phase: random(0, Math.PI * 2)
      };
    }

    function buildParticles() {
      particles = [];
      for (var i = 0; i < maxParticles; i += 1) particles.push(createParticle());
    }

    function resize() {
      width = window.innerWidth;
      height = window.innerHeight;
      smallScreen = window.matchMedia("(max-width: 720px)").matches;
      maxParticles = reduceMotion ? 20 : (smallScreen ? 34 : 68);
      linkDistance = smallScreen ? 90 : 120;
      canvas.width = Math.max(1, Math.round(width * dpr));
      canvas.height = Math.max(1, Math.round(height * dpr));
      canvas.style.width = width + "px";
      canvas.style.height = height + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      buildParticles();
    }

    function drawLink(a, b, distance) {
      var opacity = (1 - distance / linkDistance) * 0.16;
      if (opacity <= 0) return;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.strokeStyle = "rgba(83, 143, 255, " + opacity.toFixed(3) + ")";
      ctx.lineWidth = 1;
      ctx.stroke();
    }

    function animate(time) {
      ctx.clearRect(0, 0, width, height);

      for (var i = 0; i < particles.length; i += 1) {
        var p = particles[i];

        if (!reduceMotion) {
          p.x += p.vx;
          p.y += p.vy;

          if (mouse.active) {
            var mdx = p.x - mouse.x;
            var mdy = p.y - mouse.y;
            var md = Math.sqrt(mdx * mdx + mdy * mdy);
            if (md > 0 && md < 120) {
              var force = (1 - md / 120) * 0.055;
              p.x += (mdx / md) * force;
              p.y += (mdy / md) * force;
            }
          }
        }

        if (p.x < -20) p.x = width + 20;
        if (p.x > width + 20) p.x = -20;
        if (p.y < -20) p.y = height + 20;
        if (p.y > height + 20) p.y = -20;

        var glow = Math.sin((time || 0) * p.pulse + p.phase) * 0.12;
        var alpha = Math.max(0.12, Math.min(0.95, p.alpha + glow));

        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(86, 148, 255, " + alpha.toFixed(3) + ")";
        ctx.shadowBlur = 12;
        ctx.shadowColor = "rgba(80, 140, 255, 0.16)";
        ctx.fill();
        ctx.shadowBlur = 0;

        for (var j = i + 1; j < particles.length; j += 1) {
          var q = particles[j];
          var dx = p.x - q.x;
          var dy = p.y - q.y;
          if (Math.abs(dx) > linkDistance || Math.abs(dy) > linkDistance) continue;
          var dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < linkDistance) drawLink(p, q, dist);
        }
      }

      raf = window.requestAnimationFrame(animate);
    }

    function stop() {
      if (raf) window.cancelAnimationFrame(raf);
      raf = null;
    }

    function start() {
      if (!raf) raf = window.requestAnimationFrame(animate);
    }

    window.addEventListener("resize", resize, { passive: true });
    window.addEventListener("mousemove", function (event) {
      mouse.x = event.clientX;
      mouse.y = event.clientY;
      mouse.active = true;
    }, { passive: true });
    window.addEventListener("mouseleave", function () {
      mouse.active = false;
    }, { passive: true });
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) stop();
      else start();
    });

    resize();
    start();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", setupGlobalParticles, { once: true });
  } else {
    setupGlobalParticles();
  }
})();
