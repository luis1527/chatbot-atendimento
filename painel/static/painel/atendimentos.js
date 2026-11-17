/* Tela de Atendimentos (estilo WhatsApp Web).
 *
 * Tempo real por polling (serverless, sem websocket):
 *   - lista da aba atual:        a cada 3s
 *   - mensagens da conversa:     a cada 2s, pedindo só as com id > última recebida
 * Com a aba do navegador escondida, os intervalos ficam 3x maiores.
 */
(function () {
  "use strict";

  const P = window.Painel;
  const esc = P.escapar;
  const CFG = JSON.parse(document.getElementById("config-atendimentos").textContent);
  const INTERVALO_LISTA = 3000;
  const INTERVALO_MSGS = 2000;

  const $ = function (id) { return document.getElementById(id); };
  const raiz = $("atendimentos");
  const elLista = $("lista");
  const elMsgs = $("mensagens");
  const elCabeca = $("conversa-cabeca");
  const elDetalhes = $("detalhes-contato");
  const elCompositor = $("compositor");
  const elBloqueio = $("bloqueio");
  const elTexto = $("texto");

  const estado = {
    aba: "fila",
    busca: "",
    conversaId: null,
    conversa: null,
    ultimoId: 0,
    idsRenderizados: new Set(),
    ultimoDia: null,
    assinaturaCabeca: "",
    modoCompositor: "",
    enviando: false,
    carregandoLista: false,
    carregandoMsgs: false,
    detalhesAbertos: false,
  };

  function url(nome, id, acao) {
    let u = CFG.urls[nome].replace("/0/", "/" + id + "/");
    if (acao) u = u.replace("ACAO", acao);
    return u;
  }
  function guardar(chave, valor) { try { localStorage.setItem(chave, valor); } catch (e) { /* ok */ } }
  function ler(chave) { try { return localStorage.getItem(chave); } catch (e) { return null; } }

  function iniciais(nome) {
    const partes = String(nome || "?").trim().split(/\s+/);
    return ((partes[0] || "?")[0] + (partes.length > 1 ? partes[partes.length - 1][0] : "")).toUpperCase();
  }
  function primeiroNome(nome) { return String(nome || "").trim().split(/\s+/)[0] || ""; }

  function tempoEspera(seg) {
    if (seg == null) return "";
    if (seg < 60) return seg + "s";
    const min = Math.floor(seg / 60);
    if (min < 60) return min + " min";
    return Math.floor(min / 60) + "h" + String(min % 60).padStart(2, "0");
  }

  function badgeCanal(c) {
    return c.canal === "telegram"
      ? '<span class="badge telegram p">Telegram</span>'
      : '<span class="badge web p">Site</span>';
  }
  function badgeStatus(c) {
    const mapa = {
      bot: ["cinza", "🤖 Com o bot"],
      fila: ["alerta", "⏳ Na fila"],
      humano: [c.eh_minha ? "sucesso" : "info", "👤 " + (c.eh_minha ? "Com você" : (c.atendente || "Atendente"))],
      encerrada: ["cinza", "Encerrada"],
    };
    const m = mapa[c.status] || ["cinza", c.status_label];
    return '<span class="badge ' + m[0] + ' p">' + esc(m[1]) + "</span>";
  }

  /* ================================================================ LISTA */
  function selecionarAba(aba, recarregar) {
    estado.aba = aba;
    guardar("painel.aba", aba);
    document.querySelectorAll(".abas button").forEach(function (b) {
      b.classList.toggle("ativa", b.dataset.aba === aba);
      b.setAttribute("aria-selected", b.dataset.aba === aba ? "true" : "false");
    });
    if (recarregar) {
      elLista.innerHTML = '<div class="vazio-msg">Carregando…</div>';
      carregarLista();
    }
  }

  function itemHTML(c) {
    const prefixo = { bot: "🤖 ", atendente: "👤 ", sistema: "⚙️ ", cliente: "" }[c.previa_remetente] || "";
    let linha3 = badgeCanal(c);
    if (estado.aba !== "meus") linha3 += " " + badgeStatus(c);
    if (c.status === "fila" && c.espera_seg != null) {
      linha3 += ' <span class="espera ' + (c.espera_seg > 300 ? "longa" : "") + '" title="Tempo de espera na fila">⏱ ' +
        tempoEspera(c.espera_seg) + "</span>";
    }
    if (c.status === "encerrada" && c.avaliacao) {
      linha3 += ' <span class="pequeno" title="Avaliação do cliente">' + "★".repeat(c.avaliacao) + "</span>";
    }
    if (c.nao_lidas) linha3 += ' <span class="badge sucesso nao-lidas" title="Não lidas">' + c.nao_lidas + "</span>";
    return (
      '<a class="item-conversa' + (c.id === estado.conversaId ? " ativa" : "") + (c.nao_lidas ? " tem-nao-lidas" : "") +
      '" href="' + url("pagina", c.id) + '" data-id="' + c.id + '">' +
      '<span class="avatar ' + c.canal + '">' + esc(iniciais(c.nome)) + "</span>" +
      '<span class="corpo">' +
      '<span class="linha1"><span class="nome">' + esc(c.nome) + '</span><span class="hora">' + esc(c.horario) + "</span></span>" +
      '<span class="previa" style="display:block">' + esc(prefixo + (c.previa || "—")) + "</span>" +
      '<span class="linha3">' + linha3 + "</span>" +
      "</span></a>"
    );
  }

  function mensagemVazia() {
    if (estado.busca) return "Nenhuma conversa encontrada para “" + esc(estado.busca) + "”.";
    return {
      fila: "🎉 Fila vazia! Ninguém aguardando atendente.",
      meus: "Você não está atendendo nenhuma conversa agora.<br>Vá na aba <strong>Fila</strong> e clique em Assumir.",
      todos: "Nenhuma conversa aberta no momento.",
      encerradas: "Nenhuma conversa encerrada.",
    }[estado.aba];
  }

  async function carregarLista() {
    if (estado.carregandoLista) return;
    estado.carregandoLista = true;
    const aba = estado.aba;
    const params = new URLSearchParams({ aba: aba });
    if (estado.busca) params.set("q", estado.busca);
    try {
      const r = await P.api(CFG.urls.lista + "?" + params.toString());
      if (!r.ok || aba !== estado.aba) return;
      elLista.innerHTML = r.conversas.length
        ? r.conversas.map(itemHTML).join("")
        : '<div class="vazio-msg">' + mensagemVazia() + "</div>";
      Object.keys(r.contagem).forEach(function (k) {
        const b = document.querySelector('[data-contagem="' + k + '"]');
        if (b) { b.textContent = r.contagem[k]; b.classList.toggle("vazio", !r.contagem[k]); }
      });
    } finally {
      estado.carregandoLista = false;
    }
  }

  elLista.addEventListener("click", function (ev) {
    const a = ev.target.closest(".item-conversa");
    if (!a || ev.ctrlKey || ev.metaKey) return;
    ev.preventDefault();
    abrirConversa(Number(a.dataset.id), true);
  });

  document.querySelectorAll(".abas button").forEach(function (b) {
    b.addEventListener("click", function () { selecionarAba(b.dataset.aba, true); });
  });

  let tBusca = null;
  $("busca").addEventListener("input", function (ev) {
    clearTimeout(tBusca);
    tBusca = setTimeout(function () { estado.busca = ev.target.value.trim(); carregarLista(); }, 300);
  });

  /* ============================================================= CONVERSA */
  function cabecaHTML(c) {
    const p = c.permissoes;
    let acoes = "";
    if (p.assumir) {
      acoes += '<button class="btn sucesso p" data-acao="assumir">✋ <span class="txt">Assumir</span></button>';
    }
    if (p.transferir) {
      const opcoes = CFG.funcionarios.map(function (f) {
        return '<option value="' + f.id + '">' + esc(f.nome) + (f.online ? " 🟢" : "") + " (" + esc(f.cargo) + ")</option>";
      }).join("");
      acoes += '<select id="sel-transferir" title="Transferir para"><option value="">Transferir para…</option>' + opcoes + "</select>" +
        '<button class="btn p" data-acao="transferir">🔄 <span class="txt">Transferir</span></button>';
    }
    if (p.devolver) acoes += '<button class="btn p" data-acao="devolver" title="O bot volta a responder">🤖 <span class="txt">Devolver ao bot</span></button>';
    if (p.encerrar) acoes += '<button class="btn perigo p" data-acao="encerrar" title="Encerra e pede avaliação">🏁 <span class="txt">Encerrar</span></button>';
    acoes += '<button class="btn fantasma p" data-acao="detalhes" title="Dados do cliente">ℹ️</button>';

    const meta = ["#" + c.id, "início " + c.iniciada_em];
    if (c.contato.telegram_username) meta.unshift("@" + c.contato.telegram_username);
    if (c.status === "fila" && c.espera_seg != null) meta.push("⏱ esperando há " + tempoEspera(c.espera_seg));
    if (c.motivo && c.status !== "bot") meta.push("motivo: " + c.motivo);

    return (
      '<button class="btn fantasma p btn-voltar" data-acao="voltar" title="Voltar à lista">←</button>' +
      '<span class="avatar ' + c.canal + '">' + esc(iniciais(c.nome)) + "</span>" +
      '<div class="info"><div class="nome">' + esc(c.nome) + " " + badgeCanal(c) + " " + badgeStatus(c) + "</div>" +
      '<div class="meta">' + meta.map(function (m) { return "<span>" + esc(m) + "</span>"; }).join("") + "</div></div>" +
      '<div class="conversa-acoes">' + acoes + "</div>"
    );
  }

  function detalhesHTML(c) {
    const k = c.contato;
    const itens = [
      ["Cliente", k.nome], ["Canal", k.canal],
      ["Telegram", k.telegram_username ? "@" + k.telegram_username : "—"],
      ["E-mail", k.email || "—"], ["Telefone", k.telefone || "—"],
      ["Cliente desde", k.cliente_desde], ["Conversas", k.total_conversas],
      ["Responsável", c.atendente || "—"],
    ];
    if (c.avaliacao) itens.push(["Avaliação", "★".repeat(c.avaliacao) + (c.comentario_avaliacao ? " — " + c.comentario_avaliacao : "")]);
    let html = itens.map(function (i) { return "<div><dt>" + esc(i[0]) + "</dt><dd>" + esc(i[1]) + "</dd></div>"; }).join("");
    if (c.tickets.length) {
      html += "<div><dt>Tickets</dt><dd>" + c.tickets.map(function (t) {
        return '<a href="' + t.url + '">' + esc(t.protocolo) + "</a> " + esc(t.status);
      }).join("<br>") + "</dd></div>";
    }
    return html;
  }

  function assinatura(c) {
    return JSON.stringify([c.status, c.atendente, c.permissoes, c.avaliacao, c.status === "fila" ? Math.floor((c.espera_seg || 0) / 60) : 0]);
  }

  function pintarConversa(c, forcar) {
    estado.conversa = c;
    const ass = assinatura(c);
    if (forcar || ass !== estado.assinaturaCabeca) {
      const valorSel = $("sel-transferir") ? $("sel-transferir").value : "";
      elCabeca.innerHTML = cabecaHTML(c);
      if ($("sel-transferir")) $("sel-transferir").value = valorSel;
      elDetalhes.innerHTML = detalhesHTML(c);
      estado.assinaturaCabeca = ass;
    }
    elDetalhes.classList.toggle("oculto", !estado.detalhesAbertos);
    pintarCompositor(c);
  }

  function pintarCompositor(c) {
    let modo;
    if (c.permissoes.responder) modo = "responder";
    else modo = c.status + "|" + (c.atendente || "") + "|" + c.permissoes.assumir + "|" + (c.avaliacao || "");
    if (modo === estado.modoCompositor) return;
    estado.modoCompositor = modo;

    if (c.permissoes.responder) {
      elCompositor.classList.remove("oculto");
      elBloqueio.classList.add("oculto");
      setTimeout(function () { elTexto.focus(); }, 50);
      return;
    }
    elCompositor.classList.add("oculto");
    elBloqueio.classList.remove("oculto");
    let html;
    if (c.status === "fila") {
      html = "🔒 <span><strong>Assuma para responder.</strong> O cliente está aguardando um atendente.</span>" +
        '<button class="btn sucesso" data-acao="assumir">✋ Assumir conversa</button>';
    } else if (c.status === "bot") {
      html = "🤖 <span>O bot está atendendo este cliente. Assuma se quiser responder você mesmo.</span>" +
        (c.permissoes.assumir ? '<button class="btn" data-acao="assumir">✋ Assumir</button>' : "");
    } else if (c.status === "humano") {
      html = "👤 <span>Esta conversa está com <strong>" + esc(c.atendente) + "</strong>. Só o responsável pode responder.</span>";
    } else {
      html = "🏁 <span>Atendimento encerrado." +
        (c.avaliacao ? " Avaliação do cliente: <strong>" + "★".repeat(c.avaliacao) + "</strong>" : " Aguardando avaliação do cliente.") +
        "</span>";
    }
    elBloqueio.innerHTML = html;
  }

  function diaDe(iso) { return (iso || "").slice(0, 10); }
  function rotuloDia(iso) {
    const d = diaDe(iso);
    const hoje = new Date();
    const pad = function (n) { return String(n).padStart(2, "0"); };
    const hojeStr = hoje.getFullYear() + "-" + pad(hoje.getMonth() + 1) + "-" + pad(hoje.getDate());
    const ontem = new Date(hoje.getTime() - 86400000);
    const ontemStr = ontem.getFullYear() + "-" + pad(ontem.getMonth() + 1) + "-" + pad(ontem.getDate());
    if (d === hojeStr) return "Hoje";
    if (d === ontemStr) return "Ontem";
    const p = d.split("-");
    return p[2] + "/" + p[1] + "/" + p[0];
  }

  function mensagemHTML(m) {
    let rotulo;
    if (m.remetente === "cliente") rotulo = esc(estado.conversa ? estado.conversa.nome : "Cliente");
    else if (m.remetente === "bot") rotulo = "🤖 Bot";
    else if (m.remetente === "sistema") rotulo = "⚙️ Sistema";
    else rotulo = "👤 " + esc(m.atendente || "Atendente") + (m.atendente === CFG.usuario.nome ? " (você)" : "");

    let origem = "";
    if (m.origem && m.remetente !== "cliente") {
      const nomes = { faq: "FAQ", ia: "IA", humano: "Humano", regra: "Regra" };
      origem = '<span class="origem ' + esc(m.origem) + '" title="' + esc(m.origem_label) + '">' + esc(nomes[m.origem] || m.origem) + "</span>";
    } else if (m.remetente === "atendente") {
      origem = '<span class="origem humano">Humano</span>';
    }

    let botoes = "";
    if (m.botoes && m.botoes.length) {
      botoes = '<div class="botoes-msg">' + m.botoes.flat().map(function (b) {
        return "<span>" + esc(b.texto) + "</span>";
      }).join("") + "</div>";
    }
    const hora = (m.hora || "").split(" ").pop();
    let intencao = "";
    if (m.intencao) {
      intencao = '<div class="intencao">intenção: ' + esc(m.intencao) +
        (m.confianca != null ? " (" + Math.round(m.confianca * 100) + "%)" : "") + "</div>";
    }
    return (
      '<div class="msg ' + esc(m.remetente) + '" data-id="' + m.id + '">' +
      '<div class="rotulo">' + rotulo + " " + origem + "</div>" +
      '<div class="bolha">' + esc(m.texto) + botoes +
      '<div class="rodape-msg"><span title="' + esc(m.hora) + '">' + esc(hora) + "</span></div></div>" +
      intencao + "</div>"
    );
  }

  function anexarMensagens(lista, rolarSempre) {
    if (!lista.length) return;
    const pertoDoFim = elMsgs.scrollHeight - elMsgs.scrollTop - elMsgs.clientHeight < 120;
    let html = "";
    lista.forEach(function (m) {
      if (estado.idsRenderizados.has(m.id)) return;
      estado.idsRenderizados.add(m.id);
      const dia = diaDe(m.criada_em);
      if (dia !== estado.ultimoDia) {
        html += '<div class="separador-dia">' + esc(rotuloDia(m.criada_em)) + "</div>";
        estado.ultimoDia = dia;
      }
      html += mensagemHTML(m);
      if (m.id > estado.ultimoId) estado.ultimoId = m.id;
    });
    if (!html) return;
    elMsgs.insertAdjacentHTML("beforeend", html);
    if (rolarSempre || pertoDoFim) elMsgs.scrollTop = elMsgs.scrollHeight;
  }

  function fecharConversa(mexerHistorico) {
    estado.conversaId = null;
    estado.conversa = null;
    raiz.classList.remove("com-conversa");
    $("conversa-aberta").classList.add("oculto");
    $("conversa-vazia").classList.remove("oculto");
    document.querySelectorAll(".item-conversa.ativa").forEach(function (el) { el.classList.remove("ativa"); });
    if (mexerHistorico) history.pushState({}, "", CFG.urls.inicio);
  }

  async function abrirConversa(id, mexerHistorico) {
    estado.conversaId = id;
    estado.ultimoId = 0;
    estado.idsRenderizados = new Set();
    estado.ultimoDia = null;
    estado.assinaturaCabeca = "";
    estado.modoCompositor = "";
    elTexto.value = "";
    elMsgs.innerHTML = '<div class="aviso-ocultas">Carregando conversa…</div>';
    elCabeca.innerHTML = "";
    $("conversa-vazia").classList.add("oculto");
    $("conversa-aberta").classList.remove("oculto");
    raiz.classList.add("com-conversa");
    document.querySelectorAll(".item-conversa").forEach(function (el) {
      el.classList.toggle("ativa", Number(el.dataset.id) === id);
    });
    if (mexerHistorico) history.pushState({ conversa: id }, "", url("pagina", id));

    const r = await P.api(url("conversa", id));
    if (estado.conversaId !== id) return; // usuário já clicou em outra
    if (!r.ok) {
      elMsgs.innerHTML = '<div class="aviso-ocultas">' + esc(r.erro || "Conversa não encontrada.") + "</div>";
      return;
    }
    elMsgs.innerHTML = r.mensagens_ocultas
      ? '<div class="aviso-ocultas">… ' + r.mensagens_ocultas + " mensagens mais antigas não exibidas</div>"
      : "";
    pintarConversa(r.conversa, true);
    anexarMensagens(r.mensagens, true);
    if (!r.mensagens.length) elMsgs.insertAdjacentHTML("beforeend", '<div class="aviso-ocultas">Sem mensagens ainda.</div>');
    // A lista some com o "não lidas" desta conversa.
    const item = elLista.querySelector('.item-conversa[data-id="' + id + '"]');
    if (item) { item.classList.remove("tem-nao-lidas"); const b = item.querySelector(".nao-lidas"); if (b) b.remove(); }
  }

  async function buscarNovas() {
    const id = estado.conversaId;
    if (!id || estado.carregandoMsgs) return;
    estado.carregandoMsgs = true;
    try {
      const r = await P.api(url("mensagens", id) + "?depois=" + estado.ultimoId);
      if (!r.ok || estado.conversaId !== id) return;
      pintarConversa(r.conversa, false);
      anexarMensagens(r.mensagens, false);
    } finally {
      estado.carregandoMsgs = false;
    }
  }

  /* =============================================================== AÇÕES */
  async function executarAcao(acao, botao) {
    const c = estado.conversa;
    if (!c) return;
    const dados = {};
    if (acao === "transferir") {
      const sel = $("sel-transferir");
      if (!sel || !sel.value) { P.toast("Escolha para quem transferir.", "erro"); if (sel) sel.focus(); return; }
      dados.para = sel.value;
      const nome = sel.options[sel.selectedIndex].text;
      if (!confirm("Transferir esta conversa para " + nome + "?")) return;
    }
    if (acao === "encerrar" && !confirm("Encerrar o atendimento de " + c.nome + "? O cliente vai receber o pedido de avaliação.")) return;
    if (acao === "devolver" && !confirm("Devolver " + c.nome + " ao bot? O assistente virtual volta a responder.")) return;

    if (botao) botao.disabled = true;
    const r = await P.api(url("acao", c.id, acao), { method: "POST", dados: dados });
    if (botao) botao.disabled = false;
    if (!r.ok) {
      P.toast(r.erro || "Não foi possível concluir a ação.", "erro");
    } else {
      if (r.aviso) P.toast(r.aviso, "ok");
      pintarConversa(r.conversa, true);
      if (acao === "assumir") selecionarAba("meus", false);
    }
    await buscarNovas();
    carregarLista();
    P.atualizarStatus();
  }

  document.addEventListener("click", function (ev) {
    const b = ev.target.closest("[data-acao]");
    if (!b || !raiz.contains(b)) return;
    const acao = b.dataset.acao;
    if (acao === "voltar") { fecharConversa(true); return; }
    if (acao === "detalhes") {
      estado.detalhesAbertos = !estado.detalhesAbertos;
      elDetalhes.classList.toggle("oculto", !estado.detalhesAbertos);
      return;
    }
    executarAcao(acao, b);
  });

  /* ============================================================== ENVIAR */
  function ajustarAltura() {
    elTexto.style.height = "auto";
    elTexto.style.height = Math.min(elTexto.scrollHeight, 160) + "px";
  }
  elTexto.addEventListener("input", ajustarAltura);
  elTexto.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) {
      ev.preventDefault();
      enviar();
    }
  });
  $("form-envio").addEventListener("submit", function (ev) { ev.preventDefault(); enviar(); });

  async function enviar() {
    const texto = elTexto.value.trim();
    const c = estado.conversa;
    if (!texto || !c || estado.enviando) return;
    estado.enviando = true;
    $("btn-enviar").disabled = true;
    const r = await P.api(url("enviar", c.id), { method: "POST", dados: { texto: texto } });
    estado.enviando = false;
    $("btn-enviar").disabled = false;
    if (!r.ok) {
      P.toast(r.erro || "Mensagem não enviada.", "erro");
      buscarNovas();
      return;
    }
    elTexto.value = "";
    ajustarAltura();
    elTexto.focus();
    anexarMensagens([r.mensagem], true);
  }

  // Respostas rápidas
  $("respostas-rapidas").innerHTML = CFG.respostasRapidas.map(function (r, i) {
    return '<button type="button" data-i="' + i + '" title="' + esc(r.texto) + '">' + esc(r.rotulo) + "</button>";
  }).join("");
  $("respostas-rapidas").addEventListener("click", function (ev) {
    const b = ev.target.closest("button[data-i]");
    if (!b) return;
    const modelo = CFG.respostasRapidas[Number(b.dataset.i)].texto;
    const texto = modelo
      .replace(/\{nome\}/g, primeiroNome(estado.conversa && estado.conversa.nome))
      .replace(/\{atendente\}/g, CFG.usuario.nome);
    elTexto.value = elTexto.value ? elTexto.value.replace(/\s*$/, " ") + texto : texto;
    ajustarAltura();
    elTexto.focus();
  });

  /* ============================================================ POLLING */
  function laco(fn, intervalo) {
    function proximo() {
      setTimeout(function () {
        Promise.resolve(fn()).catch(function (e) { console.error(e); }).finally(proximo);
      }, document.hidden ? intervalo * 3 : intervalo);
    }
    proximo();
  }

  window.addEventListener("popstate", function () {
    const m = location.pathname.match(/\/conversas\/(\d+)\/?$/);
    if (m) abrirConversa(Number(m[1]), false);
    else fecharConversa(false);
  });

  /* =============================================================== INÍCIO */
  const abaSalva = ler("painel.aba");
  selecionarAba(CFG.abaInicial || abaSalva || "fila", false);
  carregarLista();
  if (CFG.conversaInicial) abrirConversa(CFG.conversaInicial, false);
  laco(carregarLista, INTERVALO_LISTA);
  laco(buscarNovas, INTERVALO_MSGS);
})();
