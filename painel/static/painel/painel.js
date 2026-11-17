/* Painel — funções usadas em todas as páginas.
 *  - fetch com CSRF
 *  - toggle Online/Ausente
 *  - polling do status: badge da fila, título piscando e bip quando entra conversa nova
 */
(function () {
  "use strict";

  function lerCookie(nome) {
    const m = document.cookie.match("(^|;)\\s*" + nome + "\\s*=\\s*([^;]+)");
    return m ? decodeURIComponent(m.pop()) : "";
  }

  async function api(url, opcoes) {
    opcoes = opcoes || {};
    const metodo = (opcoes.method || "GET").toUpperCase();
    const headers = { "X-Requested-With": "fetch", Accept: "application/json" };
    let body;
    if (metodo !== "GET") {
      headers["X-CSRFToken"] = lerCookie("csrftoken");
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(opcoes.dados || {});
    }
    let resp;
    try {
      resp = await fetch(url, { method: metodo, headers: headers, body: body, credentials: "same-origin" });
    } catch (e) {
      return { ok: false, erro: "Sem conexão com o servidor.", rede: true };
    }
    if (resp.redirected && resp.url.indexOf("/entrar/") !== -1) {
      window.location.href = resp.url; // sessão expirou
      return { ok: false, erro: "Sessão expirada." };
    }
    try {
      const dados = await resp.json();
      if (!resp.ok && dados.ok === undefined) dados.ok = false;
      return dados;
    } catch (e) {
      return { ok: false, erro: "Erro no servidor (" + resp.status + ")." };
    }
  }

  function toast(texto, tipo, html) {
    const caixa = document.getElementById("toasts");
    if (!caixa) return;
    const el = document.createElement("div");
    el.className = "toast " + (tipo || "");
    if (html) el.innerHTML = html; else el.textContent = texto;
    caixa.appendChild(el);
    setTimeout(function () { el.style.opacity = "0"; el.style.transition = "opacity .3s"; }, 4500);
    setTimeout(function () { el.remove(); }, 4900);
  }

  function escapar(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /* ---------------------------------------------------------- bip (Web Audio) */
  let audioCtx = null;
  function prepararAudio() {
    if (audioCtx) return;
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (Ctx) { try { audioCtx = new Ctx(); } catch (e) { audioCtx = null; } }
  }
  // Navegadores só liberam som depois de uma interação do usuário.
  ["click", "keydown", "touchstart"].forEach(function (ev) {
    document.addEventListener(ev, function () {
      prepararAudio();
      if (audioCtx && audioCtx.state === "suspended") audioCtx.resume();
    }, { once: true, passive: true });
  });
  function bip() {
    if (!audioCtx) return;
    try {
      const t = audioCtx.currentTime;
      [0, 0.18].forEach(function (atraso, i) {
        const osc = audioCtx.createOscillator();
        const ganho = audioCtx.createGain();
        osc.type = "sine";
        osc.frequency.value = i === 0 ? 880 : 1175;
        ganho.gain.setValueAtTime(0.0001, t + atraso);
        ganho.gain.exponentialRampToValueAtTime(0.25, t + atraso + 0.02);
        ganho.gain.exponentialRampToValueAtTime(0.0001, t + atraso + 0.16);
        osc.connect(ganho).connect(audioCtx.destination);
        osc.start(t + atraso);
        osc.stop(t + atraso + 0.18);
      });
    } catch (e) { /* sem som, tudo bem */ }
  }

  /* ------------------------------------------------------ título piscando */
  const tituloOriginal = document.title;
  let pisca = null;
  function piscarTitulo(qtd) {
    pararPisca();
    const alerta = "(" + qtd + ") Nova na fila";
    let alterna = false;
    pisca = setInterval(function () {
      document.title = alterna ? tituloOriginal : alerta;
      alterna = !alterna;
    }, 1000);
    document.title = alerta;
  }
  function pararPisca() {
    if (pisca) clearInterval(pisca);
    pisca = null;
    document.title = tituloOriginal;
  }
  window.addEventListener("focus", pararPisca);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) pararPisca(); });

  /* ------------------------------------------------------- toggle online */
  const toggle = document.getElementById("toggle-online");
  function pintarOnline(on) {
    if (!toggle) return;
    toggle.classList.toggle("ligado", !!on);
    toggle.querySelector(".rotulo-online").textContent = on ? "Online" : "Ausente";
  }
  if (toggle) {
    toggle.addEventListener("click", async function () {
      const novo = !toggle.classList.contains("ligado");
      pintarOnline(novo);
      const r = await api(toggle.dataset.url, { method: "POST", dados: { online: novo } });
      if (!r.ok) { pintarOnline(!novo); toast(r.erro || "Não foi possível mudar o status.", "erro"); }
      else toast(r.online ? "Você está Online." : "Você está Ausente.", "");
    });
  }

  /* -------------------------------------------------------- polling status */
  const badge = document.getElementById("badge-fila");
  let conhecidos = null; // ids da fila já vistos
  const ouvintes = [];

  function pintarBadge(n) {
    if (!badge) return;
    badge.textContent = n;
    badge.classList.toggle("vazio", !n);
  }

  async function checarStatus() {
    const r = await api(window.PAINEL.statusUrl);
    if (!r.ok) return;
    pintarBadge(r.fila);
    pintarOnline(r.online);
    const ids = r.fila_ids || [];
    if (conhecidos === null) {
      conhecidos = new Set(ids);
    } else {
      const novas = ids.filter(function (id) { return !conhecidos.has(id); });
      ids.forEach(function (id) { conhecidos.add(id); });
      if (novas.length) {
        bip();
        if (document.hidden || !document.hasFocus()) piscarTitulo(r.fila);
        toast("", "", "🔔 " + (novas.length > 1 ? novas.length + " novas conversas" : "Nova conversa") +
          " na fila. <a href=\"" + window.PAINEL.filaUrl + "\">Ver fila</a>");
      }
    }
    ouvintes.forEach(function (fn) { try { fn(r); } catch (e) { console.error(e); } });
  }

  let intervalo = 4000;
  function ciclo() {
    checarStatus().finally(function () {
      // Aba escondida: pergunta com menos frequência (economiza o servidor).
      setTimeout(ciclo, document.hidden ? intervalo * 3 : intervalo);
    });
  }
  ciclo();

  window.Painel = {
    api: api,
    toast: toast,
    escapar: escapar,
    bip: bip,
    aoStatus: function (fn) { ouvintes.push(fn); },
    atualizarStatus: checarStatus,
  };
})();
