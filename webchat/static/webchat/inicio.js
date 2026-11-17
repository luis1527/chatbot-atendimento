/* Página inicial: gera o QR code do link do Telegram (qrcodejs, no navegador). */
(function () {
  "use strict";

  function gerar() {
    var alvo = document.getElementById("qrcode");
    if (!alvo) return;
    var link = alvo.getAttribute("data-link");
    if (typeof window.QRCode !== "function") {
      alvo.classList.add("qr__codigo--falhou");
      alvo.textContent = "Não foi possível gerar o QR code. Use o link abaixo.";
      return;
    }
    new window.QRCode(alvo, {
      text: link,
      width: 184,
      height: 184,
      colorDark: "#111827",
      colorLight: "#ffffff",
      correctLevel: window.QRCode.CorrectLevel.M
    });
    // A biblioteca coloca um "title" com o link; o rótulo acessível já está no contêiner.
    alvo.removeAttribute("title");
    var img = alvo.querySelector("img");
    if (img) img.alt = "";
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", gerar);
  } else {
    gerar();
  }
})();
