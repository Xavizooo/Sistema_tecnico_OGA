(function () {
  "use strict";

  function passwordTarget(button) {
    return document.getElementById(button.dataset.passwordToggle || "");
  }

  document.querySelectorAll("[data-password-toggle]").forEach(function (button) {
    button.addEventListener("click", function () {
      var input = passwordTarget(button);
      if (!input) return;
      var showing = input.type === "text";
      input.type = showing ? "password" : "text";
      button.setAttribute("aria-label", showing ? "Mostrar contraseña" : "Ocultar contraseña");
      button.setAttribute("title", showing ? "Mostrar contraseña" : "Ocultar contraseña");
      if (!button.querySelector("svg")) button.textContent = showing ? "VER" : "OCULTAR";
    });
  });

  document.querySelectorAll("[data-generate-password]").forEach(function (button) {
    button.addEventListener("click", function () {
      var target = document.getElementById(button.dataset.generatePassword || "");
      if (!target) return;
      var alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%*-_";
      var bytes = new Uint32Array(18);
      window.crypto.getRandomValues(bytes);
      var password = Array.from(bytes, function (value) {
        return alphabet[value % alphabet.length];
      }).join("");
      target.value = password;
      target.type = "text";
      var confirmId = button.dataset.confirmTarget;
      if (confirmId) {
        var confirmation = document.getElementById(confirmId);
        if (confirmation) confirmation.value = password;
      }
      target.focus();
      target.select();
    });
  });

  document.querySelectorAll("form[data-confirm-password]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      var password = form.querySelector("input[name='password']");
      var confirmation = form.querySelector("#password_confirm, [data-password-confirm]");
      if (password && confirmation && password.value !== confirmation.value) {
        event.preventDefault();
        confirmation.setCustomValidity("Las contraseñas no coinciden.");
        confirmation.reportValidity();
      }
    });
    var confirmation = form.querySelector("#password_confirm, [data-password-confirm]");
    if (confirmation) {
      confirmation.addEventListener("input", function () {
        confirmation.setCustomValidity("");
      });
    }
  });

  function setupRotatingCopy() {
    var target = document.getElementById("loginRotatingText");
    if (!target) return;
    var messages = [
      "Donde la eficiencia encuentra la grandeza.",
      "Menos clics, más eficiencia.",
      "Optimiza tu jornada.",
      "Menos burocracia, más agilidad."
    ];
    var index = 0;
    setInterval(function () {
      index = (index + 1) % messages.length;
      target.style.opacity = "0";
      target.style.transform = "translateY(6px)";
      setTimeout(function () {
        target.textContent = messages[index];
        target.style.transition = "opacity .35s ease, transform .35s ease";
        target.style.opacity = "1";
        target.style.transform = "translateY(0)";
      }, 180);
    }, 2600);
  }

  function setupInteractiveTilt() {
    var shell = document.querySelector(".login-cinematic .login-shell");
    if (!shell || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    shell.addEventListener("mousemove", function (event) {
      var rect = shell.getBoundingClientRect();
      var px = (event.clientX - rect.left) / rect.width;
      var py = (event.clientY - rect.top) / rect.height;
      var rx = (0.5 - py) * 3.5;
      var ry = (px - 0.5) * 4.5;
      shell.style.transform = "perspective(1400px) rotateX(" + rx.toFixed(2) + "deg) rotateY(" + ry.toFixed(2) + "deg)";
    });
    shell.addEventListener("mouseleave", function () {
      shell.style.transform = "perspective(1400px) rotateX(0deg) rotateY(0deg)";
    });
  }

  function setupParticles() {
    var canvas = document.getElementById("loginParticles");
    if (!canvas) return;
    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var ctx = canvas.getContext("2d");
    if (!ctx) return;
    var particles = [];
    var width = 0;
    var height = 0;
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var maxParticles = reduce ? 24 : 70;

    function resize() {
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      canvas.style.width = width + "px";
      canvas.style.height = height + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      initParticles();
    }

    function random(min, max) {
      return Math.random() * (max - min) + min;
    }

    function initParticles() {
      particles = [];
      for (var i = 0; i < maxParticles; i += 1) {
        particles.push({
          x: random(0, width),
          y: random(0, height),
          r: random(1, 3.3),
          vx: random(-0.25, 0.25),
          vy: random(-0.2, 0.2),
          alpha: random(0.25, 0.85)
        });
      }
    }

    function drawLink(a, b, distance) {
      var opacity = (1 - distance / 120) * 0.18;
      if (opacity <= 0) return;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.strokeStyle = "rgba(88, 146, 255, " + opacity.toFixed(3) + ")";
      ctx.lineWidth = 1;
      ctx.stroke();
    }

    function animate() {
      ctx.clearRect(0, 0, width, height);
      for (var i = 0; i < particles.length; i += 1) {
        var p = particles[i];
        p.x += p.vx;
        p.y += p.vy;
        if (p.x < -20) p.x = width + 20;
        if (p.x > width + 20) p.x = -20;
        if (p.y < -20) p.y = height + 20;
        if (p.y > height + 20) p.y = -20;

        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(90, 149, 255, " + p.alpha.toFixed(3) + ")";
        ctx.shadowBlur = 14;
        ctx.shadowColor = "rgba(90, 149, 255, 0.18)";
        ctx.fill();
        ctx.shadowBlur = 0;

        for (var j = i + 1; j < particles.length; j += 1) {
          var q = particles[j];
          var dx = p.x - q.x;
          var dy = p.y - q.y;
          var dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < 120) drawLink(p, q, dist);
        }
      }
      window.requestAnimationFrame(animate);
    }

    resize();
    window.addEventListener("resize", resize);
    window.requestAnimationFrame(animate);
  }

  setupRotatingCopy();
  setupInteractiveTilt();
  setupParticles();
})();
