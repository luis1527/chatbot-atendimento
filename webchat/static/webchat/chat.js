/*
 * Chat do site ("Chat teste").
 *
 * O navegador envia o que o visitante digita/clica para /api/chat/enviar/;
 * o motor do bot grava a mensagem do cliente e as respostas no banco, e
 * este script busca as novidades por polling (/api/chat/mensagens/?depois=<id>).
 * Respostas de atendentes humanos chegam pelo mesmo polling.
 *
 * JS puro, sem build. Todo texto vindo do servidor é escapado antes de virar HTML.
 */
(function () {
  "use strict";

  var INTERVALO_POLLING = 2000;
  var INTERVALO_ERRO = 5000;

  var raiz = document.getElementById("chat");
  if (!raiz) return;

  var urls = {
    iniciar: raiz.getAttribute("data-url-iniciar"),
    enviar: raiz.getAttribute("data-url-enviar"),
    mensagens: raiz.getAttribute("data-url-mensagens"),
    nova: raiz.getAttribute("data-url-nova")
  };
  var limite = parseInt(raiz.getAttribute("data-limite"), 10) || 1000;

  var el = {
    lista: document.getElementById("lista-mensagens"),
    rolagem: document.getElementById("conteudo"),
    digitando: document.getElementById("digitando"),
    aviso: document.getElementById("chat-aviso"),
    form: document.getElementById("form-envio"),
    campo: document.getElementById("campo-texto"),
    botaoEnviar: document.getElementById("botao-enviar"),
    statusTexto: document.getElementById("chat-status-texto"),
    statusPonto: document.getElementById("chat-status-ponto"),
    avatarTopo: raiz.querySelector(".chat__avatar"),
    modal: document.getElementById("modal-nome"),
    formNome: document.getElementById("form-nome"),
    campoNome: document.getElementById("campo-nome"),
    pularNome: document.getElementById("pular-nome"),
    menuBotao: document.getElementById("menu-botao"),
    menuLista: document.getElementById("menu-lista"),
    acaoNova: document.getElementById("acao-nova")
  };

  var estado = {
    iniciado: false,
    ultimoId: 0,
    vistos: {},            // id -> true (evita duplicar mensagens)
    ultimaConversa: null,  // para separar visualmente conversas diferentes
    pendentes: [],         // bolhas otimistas do cliente ainda não confirmadas
    enviando: false,
    buscando: false,
    timer: null,
    geracao: 0             // muda ao limpar a tela; respostas antigas são ignoradas
  };

  // ---------------------------------------------------------------------
  // Utilidades
  // ---------------------------------------------------------------------
  function lerCookie(nome) {
    var partes = document.cookie ? document.cookie.split(";") : [];
    for (var i = 0; i < partes.length; i++) {
      var p = partes[i].trim();
      if (p.indexOf(nome + "=") === 0) return decodeURIComponent(p.substring(nome.length + 1));
    }
    return "";
  }

  function csrf() {
    return lerCookie("csrftoken") || raiz.getAttribute("data-csrf") || "";
  }

  function requisicao(metodo, url, corpo) {
    var opcoes = {
      method: metodo,
      credentials: "same-origin",
      headers: { "Accept": "application/json", "X-Requested-With": "XMLHttpRequest" }
    };
    if (metodo !== "GET") {
      opcoes.headers["Content-Type"] = "application/json";
      opcoes.headers["X-CSRFToken"] = csrf();
      opcoes.body = JSON.stringify(corpo || {});
    }
    return fetch(url, opcoes).then(function (resp) {
      return resp.json().catch(function () { return {}; }).then(function (dados) {
        if (!resp.ok || dados.ok === false) {
          var erro = new Error(dados.erro || ("Erro " + resp.status));
          erro.status = resp.status;
          throw erro;
        }
        return dados;
      });
    });
  }

  function escapar(texto) {
    return String(texto)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  // Markdown simples: *negrito*, **negrito**, _itálico_ e links. Escapa antes.
  function formatarTrecho(texto) {
    var h = escapar(texto);
    h = h.replace(/\*\*([^*\n]+?)\*\*/g, "<strong>$1</strong>");
    h = h.replace(/(^|[^\w*])\*([^*\n]+?)\*(?=[^\w*]|$)/g, "$1<strong>$2</strong>");
    h = h.replace(/(^|[^\w])_([^_\n]+?)_(?=[^\w]|$)/g, "$1<em>$2</em>");
    return h;
  }

  function formatar(texto) {
    var regexUrl = /https?:\/\/[^\s<>"']+[^\s<>"'.,;:!?)\]]/g;
    var saida = "";
    var ultimo = 0;
    var m;
    texto = String(texto || "");
    while ((m = regexUrl.exec(texto)) !== null) {
      saida += formatarTrecho(texto.slice(ultimo, m.index));
      var url = escapar(m[0]);
      saida += '<a href="' + url + '" target="_blank" rel="noopener noreferrer">' + url + "</a>";
      ultimo = m.index + m[0].length;
    }
    saida += formatarTrecho(texto.slice(ultimo));
    return saida;
  }

  function pertoDoFim() {
    var r = el.rolagem;
    return r.scrollHeight - r.scrollTop - r.clientHeight < 120;
  }

  function rolarParaFim() {
    el.rolagem.scrollTop = el.rolagem.scrollHeight;
  }

  var timerAviso = null;
  function mostrarAviso(texto, fixo) {
    el.aviso.textContent = texto;
    el.aviso.hidden = false;
    clearTimeout(timerAviso);
    if (!fixo) timerAviso = setTimeout(esconderAviso, 6000);
  }

  function esconderAviso() {
    el.aviso.hidden = true;
  }

  function mostrarDigitando(sim) {
    var fim = pertoDoFim();
    el.digitando.hidden = !sim;
    if (sim && fim) rolarParaFim();
  }

  // ---------------------------------------------------------------------
  // Status da conversa (topo)
  // ---------------------------------------------------------------------
  function atualizarStatus(status) {
    if (!status) return;
    el.statusTexto.textContent = status.rotulo || "";
    el.statusPonto.className = "ponto ponto--" + (status.codigo || "bot");
    el.avatarTopo.textContent = status.codigo === "humano" ? "👤" : "🤖";
  }

  // ---------------------------------------------------------------------
  // Renderização das mensagens
  // ---------------------------------------------------------------------
  function criarBotoes(linhas) {
    var caixa = document.createElement("div");
    caixa.className = "botoes";
    linhas.forEach(function (linha) {
      var div = document.createElement("div");
      div.className = "botoes__linha";
      linha.forEach(function (b) {
        var item;
        if (b.url) {
          item = document.createElement("a");
          item.href = b.url;
          item.target = "_blank";
          item.rel = "noopener noreferrer";
          item.className = "botao-msg botao-msg--link";
          item.textContent = b.texto + " ↗";
        } else {
          item = document.createElement("button");
          item.type = "button";
          item.className = "botao-msg";
          item.textContent = b.texto;
          item.addEventListener("click", function () {
            if (item.disabled) return;
            enviar({ dado: b.dado }, b.texto);
          });
        }
        div.appendChild(item);
      });
      caixa.appendChild(div);
    });
    return caixa;
  }

  function criarBolha(m) {
    var li = document.createElement("li");
    li.className = "msg msg--" + m.remetente;
    if (m.id) li.setAttribute("data-id", m.id);

    if (m.remetente === "sistema") {
      var aviso = document.createElement("div");
      aviso.className = "msg__sistema";
      aviso.innerHTML = formatar(m.texto);
      li.appendChild(aviso);
      if (m.botoes && m.botoes.length) li.appendChild(criarBotoes(m.botoes));
      return li;
    }

    if (m.remetente !== "cliente") {
      var avatar = document.createElement("span");
      avatar.className = "bolha-avatar";
      avatar.setAttribute("aria-hidden", "true");
      avatar.textContent = m.remetente === "atendente" ? "👤" : "🤖";
      li.appendChild(avatar);
    }

    var corpo = document.createElement("div");
    corpo.className = "msg__corpo";

    var quem = document.createElement("span");
    quem.className = m.remetente === "atendente" ? "msg__autor" : "sr-only";
    if (m.remetente === "cliente") quem.textContent = "Você:";
    else if (m.remetente === "atendente") quem.textContent = (m.atendente || "Atendente") + " · atendente";
    else quem.textContent = "Assistente:";
    corpo.appendChild(quem);

    var bolha = document.createElement("div");
    bolha.className = "bolha";
    var texto = document.createElement("div");
    texto.className = "bolha__texto";
    texto.innerHTML = formatar(m.texto);
    bolha.appendChild(texto);
    var hora = document.createElement("span");
    hora.className = "bolha__hora";
    hora.textContent = m.hora || "";
    bolha.appendChild(hora);
    corpo.appendChild(bolha);

    if (m.botoes && m.botoes.length) corpo.appendChild(criarBotoes(m.botoes));
    li.appendChild(corpo);
    return li;
  }

  function inserirAntesDosPendentes(no) {
    var primeiro = estado.pendentes.length ? estado.pendentes[0] : null;
    if (primeiro && primeiro.parentNode === el.lista) el.lista.insertBefore(no, primeiro);
    else el.lista.appendChild(no);
  }

  function adicionarMensagens(mensagens) {
    var fim = pertoDoFim();
    var chegouCliente = false;
    mensagens.forEach(function (m) {
      if (estado.vistos[m.id]) return;
      estado.vistos[m.id] = true;
      if (m.id > estado.ultimoId) estado.ultimoId = m.id;

      if (estado.ultimaConversa !== null && m.conversa !== estado.ultimaConversa) {
        var sep = document.createElement("li");
        sep.className = "separador";
        sep.innerHTML = "<span>Nova conversa</span>";
        inserirAntesDosPendentes(sep);
      }
      estado.ultimaConversa = m.conversa;

      if (m.remetente === "cliente" && estado.pendentes.length) {
        // Reconciliação: a mensagem otimista foi confirmada pelo servidor.
        var pend = estado.pendentes.shift();
        if (pend.parentNode) pend.parentNode.removeChild(pend);
      }
      if (m.remetente === "cliente") chegouCliente = true;
      inserirAntesDosPendentes(criarBolha(m));
    });
    if (mensagens.length) {
      atualizarBotoesAtivos();
      if (fim || chegouCliente) rolarParaFim();
    }
  }

  // Só os botões da última mensagem com botões ficam ativos, e só se o
  // cliente ainda não respondeu depois dela.
  function atualizarBotoesAtivos() {
    var itens = el.lista.children;
    var ativo = null;
    for (var i = itens.length - 1; i >= 0; i--) {
      var li = itens[i];
      if (li.classList.contains("msg--cliente")) break;
      if (li.querySelector(".botoes")) { ativo = li; break; }
    }
    var botoes = el.lista.querySelectorAll("button.botao-msg");
    for (var j = 0; j < botoes.length; j++) {
      var desativar = !ativo || !ativo.contains(botoes[j]) || estado.enviando;
      botoes[j].disabled = desativar;
    }
  }

  function limparTela() {
    estado.geracao++;
    estado.ultimoId = 0;
    estado.vistos = {};
    estado.ultimaConversa = null;
    estado.pendentes = [];
    el.lista.innerHTML = "";
  }

  // ---------------------------------------------------------------------
  // Polling
  // ---------------------------------------------------------------------
  function agendar(ms) {
    clearTimeout(estado.timer);
    estado.timer = setTimeout(buscar, ms);
  }

  function buscar() {
    if (!estado.iniciado) return Promise.resolve();
    if (document.hidden) {
      clearTimeout(estado.timer);
      return Promise.resolve(); // retoma no visibilitychange
    }
    if (estado.buscando) return estado.buscando;
    var geracao = estado.geracao;
    var url = urls.mensagens + "?depois=" + encodeURIComponent(estado.ultimoId);
    estado.buscando = requisicao("GET", url)
      .then(function (dados) {
        if (geracao !== estado.geracao) return;
        adicionarMensagens(dados.mensagens || []);
        atualizarStatus(dados.status);
        agendar(INTERVALO_POLLING);
      })
      .catch(function () {
        agendar(INTERVALO_ERRO);
      })
      .then(function () {
        estado.buscando = false;
      });
    return estado.buscando;
  }

  // Busca agora (espera uma busca em andamento terminar e faz outra).
  function buscarAgora() {
    var emCurso = estado.buscando || Promise.resolve();
    return emCurso.then(function () { return buscar(); });
  }

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden && estado.iniciado) buscarAgora();
  });

  // ---------------------------------------------------------------------
  // Envio
  // ---------------------------------------------------------------------
  function criarPendente(texto) {
    var li = criarBolha({ remetente: "cliente", texto: texto, hora: "" });
    li.classList.add("msg--pendente");
    li.querySelector(".bolha__hora").textContent = "enviando…";
    el.lista.appendChild(li);
    estado.pendentes.push(li);
    rolarParaFim();
    return li;
  }

  function confirmarLocal(li) {
    // O servidor não gravou um eco desta mensagem: mantém a bolha como enviada.
    var idx = estado.pendentes.indexOf(li);
    if (idx >= 0) estado.pendentes.splice(idx, 1);
    li.classList.remove("msg--pendente");
    var agora = new Date();
    li.querySelector(".bolha__hora").textContent =
      ("0" + agora.getHours()).slice(-2) + ":" + ("0" + agora.getMinutes()).slice(-2);
  }

  function marcarFalha(li) {
    var idx = estado.pendentes.indexOf(li);
    if (idx >= 0) estado.pendentes.splice(idx, 1);
    li.classList.remove("msg--pendente");
    li.classList.add("msg--falhou");
    li.querySelector(".bolha__hora").textContent = "não enviada";
  }

  function definirEnviando(sim) {
    estado.enviando = sim;
    el.botaoEnviar.disabled = sim;
    mostrarDigitando(sim);
    atualizarBotoesAtivos();
  }

  function enviar(corpo, rotulo) {
    if (estado.enviando || !estado.iniciado) return;
    esconderAviso();
    var geracao = estado.geracao;
    var pendente = criarPendente(rotulo);
    definirEnviando(true);

    requisicao("POST", urls.enviar, corpo)
      .then(function (dados) {
        atualizarStatus(dados.status);
        return buscarAgora();
      })
      .then(function () {
        if (geracao === estado.geracao && pendente.parentNode && estado.pendentes.indexOf(pendente) >= 0) {
          confirmarLocal(pendente);
        }
      })
      .catch(function (erro) {
        if (pendente.parentNode) marcarFalha(pendente);
        mostrarAviso(erro.message || "Não foi possível enviar. Verifique sua conexão.");
        if (corpo.texto && !el.campo.value) {
          el.campo.value = corpo.texto;
          ajustarAltura();
        }
      })
      .then(function () {
        definirEnviando(false);
      });
  }

  function ajustarAltura() {
    el.campo.style.height = "auto";
    el.campo.style.height = Math.min(el.campo.scrollHeight, 140) + "px";
  }

  el.form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var texto = el.campo.value.trim();
    if (!texto || estado.enviando) return;
    if (texto.length > limite) {
      mostrarAviso("Mensagem muito longa (máximo " + limite + " caracteres).");
      return;
    }
    el.campo.value = "";
    ajustarAltura();
    enviar({ texto: texto }, texto);
    el.campo.focus();
  });

  el.campo.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) {
      ev.preventDefault();
      if (typeof el.form.requestSubmit === "function") el.form.requestSubmit();
      else el.form.dispatchEvent(new Event("submit", { cancelable: true }));
    }
  });
  el.campo.addEventListener("input", ajustarAltura);

  // ---------------------------------------------------------------------
  // Menu do topo
  // ---------------------------------------------------------------------
  function abrirMenu(abrir) {
    el.menuLista.hidden = !abrir;
    el.menuBotao.setAttribute("aria-expanded", abrir ? "true" : "false");
    if (abrir) {
      var primeiro = el.menuLista.querySelector("[role=menuitem]");
      if (primeiro) primeiro.focus();
    }
  }

  el.menuBotao.addEventListener("click", function (ev) {
    ev.stopPropagation();
    abrirMenu(el.menuLista.hidden);
  });
  document.addEventListener("click", function (ev) {
    if (!el.menuLista.hidden && !el.menuLista.contains(ev.target)) abrirMenu(false);
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && !el.menuLista.hidden) {
      abrirMenu(false);
      el.menuBotao.focus();
    }
  });

  el.acaoNova.addEventListener("click", function () {
    abrirMenu(false);
    if (estado.enviando || !estado.iniciado) return;
    if (!window.confirm("Começar uma nova conversa? A conversa atual será encerrada.")) return;
    definirEnviando(true);
    requisicao("POST", urls.nova, {})
      .then(function (dados) {
        limparTela();
        atualizarStatus(dados.status);
        return buscarAgora();
      })
      .catch(function (erro) {
        mostrarAviso(erro.message || "Não foi possível iniciar uma nova conversa.");
      })
      .then(function () {
        definirEnviando(false);
        el.campo.focus();
      });
  });

  // ---------------------------------------------------------------------
  // Início: nome do visitante e boas-vindas
  // ---------------------------------------------------------------------
  function iniciar(nome) {
    definirEnviando(true);
    return requisicao("POST", urls.iniciar, { nome: nome || "" })
      .then(function (dados) {
        atualizarStatus(dados.status);
      })
      .catch(function (erro) {
        mostrarAviso(erro.message || "Não foi possível falar com o assistente.", true);
      })
      .then(function () {
        estado.iniciado = true;
        return buscarAgora();
      })
      .then(function () {
        definirEnviando(false);
        rolarParaFim();
      });
  }

  function fecharModal(nome) {
    el.modal.hidden = true;
    iniciar(nome);
    el.campo.focus();
  }

  if (raiz.getAttribute("data-precisa-nome") === "1") {
    el.modal.hidden = false;
    el.campoNome.focus();
    el.formNome.addEventListener("submit", function (ev) {
      ev.preventDefault();
      fecharModal(el.campoNome.value.trim());
    });
    el.pularNome.addEventListener("click", function () { fecharModal(""); });
    el.modal.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") fecharModal("");
    });
  } else {
    iniciar("");
  }
})();
