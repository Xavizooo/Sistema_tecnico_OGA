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
})();
