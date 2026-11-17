"""
Cérebro do bot: decide o que responder a cada entrada do cliente.

Um único motor para os dois canais (Telegram e chat do site). Fluxo:

    processar_entrada(contato, texto | dado)
      ├─ grava a mensagem do cliente (ignora reenvio duplicado do Telegram)
      ├─ /encerrar ou botão "Encerrar" → services.encerrar (pede avaliação)
      ├─ status "humano" → só grava (o atendente responde pelo painel)
      ├─ status "fila"   → no máximo UM aviso de "aguarde"
      └─ status "bot":
           ├─ clique em botão (dado)   → ação determinística, sem IA
           ├─ /start, /menu, "menu"    → boas-vindas + menu
           └─ texto livre              → Gemini interpreta e escolhe a AÇÃO
                                         (fallback: bot/nlp.py, sem IA)

Ações que o sistema realmente executa (a IA só escolhe e redige):
responder_faq, sem_resposta, nao_suportado, conversa_livre, abrir_ticket,
consultar_tickets, falar_com_atendente, mostrar_menu, encerrar.

Estado do fluxo de ticket: não há campo no banco para isso (e cache não serve
em serverless), então o estado viaja na PRÓPRIA última mensagem do bot: o botão
"Cancelar" de cada passo carrega `dado="ticket_cancelar:<passo>"` e uma chave
extra `estado` com o que já foi coletado. Telegram e site ignoram chaves extras.
"""
import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from core import services
from core.models import Canal, Conversa, Intencao, Mensagem, PerguntaFAQ, Ticket

from . import ia, nlp

log = logging.getLogger(__name__)

MAX_FALHAS_DUVIDA = 2   # depois de N "não sei" seguidos, oferece atendente
TAM_HISTORICO = 10      # mensagens recentes mandadas para a IA
MAX_FAQ_IA = 40         # limite de perguntas do FAQ no prompt

HORARIO_ATENDIMENTO = getattr(
    settings, "HORARIO_ATENDIMENTO", "segunda a sexta, das 8h às 18h, e sábado, das 8h às 12h",
)
AVISO_FILA = "⏳ Recebido! Você já está na fila e um atendente vai te responder em breve."
PALAVRAS_CANCELAR = {"cancelar", "cancela", "cancele", "sair", "parar", "desistir", "deixa pra la"}
PALAVRAS_MENU = {"menu", "inicio", "voltar", "opcoes", "menu principal"}

# ---------------------------------------------------------------------------
# Botões
# ---------------------------------------------------------------------------
B_MENU = {"texto": "🏠 Menu", "dado": "menu:inicio"}
B_HUMANO = {"texto": "👤 Falar com atendente", "dado": "menu:humano"}
B_TICKET = {"texto": "📝 Abrir ticket", "dado": "menu:ticket"}
B_MEUS_TICKETS = {"texto": "📋 Meus tickets", "dado": "menu:meus_tickets"}
B_OUTRA_DUVIDA = {"texto": "❓ Outra dúvida", "dado": "menu:duvida"}
B_ENCERRAR = {"texto": "🏁 Encerrar atendimento", "dado": "menu:encerrar"}
B_NOVO = {"texto": "🔄 Novo atendimento", "dado": "menu:inicio"}

ROTULOS_PADRAO = {
    "menu:duvida": "❓ Chat de dúvida", "menu:conversa": "💬 Chat de conversa", "menu:ticket": "📝 Abrir ticket",
    "menu:meus_tickets": "📋 Meus tickets", "menu:humano": "👤 Falar com atendente", "menu:inicio": "🏠 Menu",
    "menu:encerrar": "🏁 Encerrar atendimento",
}


def botoes_menu():
    return [
        [{"texto": "❓ Chat de dúvida", "dado": "menu:duvida"}, {"texto": "💬 Chat de conversa", "dado": "menu:conversa"}],
        [{"texto": "📝 Abrir ticket", "dado": "menu:ticket"}, {"texto": "📋 Meus tickets", "dado": "menu:meus_tickets"}],
        [{"texto": "👤 Falar com atendente", "dado": "menu:humano"}],
    ]


def _marcado_falha(botao: dict) -> dict:
    """Cópia do botão com marca interna de 'o bot não soube responder'."""
    return {**botao, "falha": True}


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------
def processar_entrada(contato, texto: str | None = None, dado: str | None = None,
                      telegram_message_id: int | None = None) -> Conversa:
    """Trata uma mensagem de texto OU um clique de botão (`dado`) do cliente."""
    texto = (texto or "").strip()
    dado = (dado or "").strip()

    # Avaliação refere-se a uma conversa JÁ encerrada: não abre conversa nova.
    if dado.startswith("avaliar:"):
        return _avaliar(contato, dado)

    conversa = services.conversa_aberta(contato)
    if not texto and not dado:
        return conversa

    rotulo = _rotulo_do_botao(contato, dado) if dado else texto
    msg = _gravar_cliente(conversa, rotulo, telegram_message_id)
    if msg is None:  # reenvio do Telegram: já processado
        return conversa

    comando = _comando(texto)
    if comando == "encerrar" or dado == "menu:encerrar":
        return services.encerrar(conversa)

    if conversa.status == Conversa.Status.HUMANO:
        return conversa  # o atendente vê no painel; bot fica quieto
    if conversa.status == Conversa.Status.FILA:
        _aviso_fila(conversa)
        return _recarregar(conversa)

    if dado:
        _tratar_botao(conversa, dado)
    elif comando in ("start", "menu") or nlp.normalizar(texto) in PALAVRAS_MENU:
        _boas_vindas(conversa)
    elif comando:
        _enviar(conversa, "Não conheço esse comando 🤔. Use /menu para ver as opções.", botoes_menu())
    else:
        _tratar_texto(conversa, msg, texto)
    return _recarregar(conversa)


def processar_midia(contato, tipo: str, telegram_message_id: int | None = None) -> Conversa:
    """Foto, áudio, figurinha etc.: o bot só entende texto, então avisa com educação."""
    conversa = services.conversa_aberta(contato)
    msg = _gravar_cliente(conversa, f"[{tipo} enviado - o bot só recebe texto]", telegram_message_id)
    if msg is None:
        return conversa
    if conversa.status == Conversa.Status.HUMANO:
        # Exceção ao "silêncio": sem isso o cliente acharia que o atendente recebeu o arquivo.
        _enviar(conversa, f"📎 Por aqui só consigo repassar mensagens de texto ao atendente. "
                          f"Pode descrever por escrito? 🙏", remetente=Mensagem.Remetente.SISTEMA)
    else:
        _enviar(conversa, "📎 Por enquanto eu só entendo mensagens de texto 🙂. Pode escrever o que você precisa?",
                botoes_menu() if conversa.status == Conversa.Status.BOT else None)
    return conversa


# ---------------------------------------------------------------------------
# Auxiliares gerais
# ---------------------------------------------------------------------------
def _recarregar(conversa):
    return Conversa.objects.select_related("contato").get(pk=conversa.pk)


def _comando(texto: str) -> str | None:
    """'/start@felipeprojeto_bot abc' -> 'start'."""
    if not texto.startswith("/"):
        return None
    return texto.split()[0][1:].split("@")[0].lower() or None


def _gravar_cliente(conversa, texto, telegram_message_id):
    try:
        with transaction.atomic():  # savepoint: o IntegrityError não estraga a transação externa
            return services.registrar_mensagem(
                conversa, Mensagem.Remetente.CLIENTE, texto, telegram_message_id=telegram_message_id,
            )
    except IntegrityError:
        if telegram_message_id:
            log.info("Mensagem %s do Telegram duplicada; ignorada.", telegram_message_id)
            return None
        raise


def _rotulo_do_botao(contato, dado):
    """Texto do botão clicado (para o histórico ficar legível)."""
    recentes = Mensagem.objects.filter(conversa__contato=contato, botoes__isnull=False).order_by("-id")[:15]
    for m in recentes:
        for linha in m.botoes or []:
            for b in linha if isinstance(linha, list) else []:
                if isinstance(b, dict) and b.get("dado") == dado:
                    return b.get("texto") or dado
    return ROTULOS_PADRAO.get(dado, dado)


def _enviar(conversa, texto, botoes=None, *, origem=Mensagem.Origem.REGRA, faq=None,
            remetente=Mensagem.Remetente.BOT):
    return services.enviar_ao_cliente(
        conversa, texto, remetente=remetente, botoes=botoes, origem_resposta=origem, faq=faq,
    )


def _mudar_modo(conversa, modo):
    if conversa.modo != modo:
        Conversa.objects.filter(pk=conversa.pk).update(modo=modo)
        conversa.modo = modo


def _digitando(conversa):
    if conversa.canal == Canal.TELEGRAM and conversa.contato.telegram_chat_id:
        from . import telegram_api
        try:
            telegram_api.digitando(conversa.contato.telegram_chat_id)
        except Exception:  # só cosmético
            log.debug("Falha no 'digitando'", exc_info=True)


def _primeiro_nome(conversa):
    nome = (conversa.contato.nome or "").split()
    return nome[0] if nome and nome[0].lower() not in ("visitante", "cliente") else ""


def dentro_do_horario(agora=None) -> bool:
    """Horário do atendimento humano (o mesmo descrito no FAQ)."""
    agora = timezone.localtime(agora or timezone.now())
    d, h = agora.weekday(), agora.hour
    return (d < 5 and 8 <= h < 18) or (d == 5 and 8 <= h < 12)


# ---------------------------------------------------------------------------
# Botões (determinísticos, sem IA)
# ---------------------------------------------------------------------------
def _tratar_botao(conversa, dado):
    if dado == "menu:inicio":
        _boas_vindas(conversa)
    elif dado == "menu:duvida":
        _mudar_modo(conversa, Conversa.Modo.DUVIDA)
        _enviar(conversa, "❓ Pode mandar sua dúvida! Vou procurar a resposta na nossa base de ajuda.", [[B_MENU]])
    elif dado == "menu:conversa":
        _mudar_modo(conversa, Conversa.Modo.CONVERSA)
        _enviar(conversa, "💬 Vamos conversar! Pode escrever à vontade. Se precisar, eu chamo um atendente.",
                [[B_MENU, B_HUMANO]])
    elif dado == "menu:ticket":
        _mudar_modo(conversa, Conversa.Modo.TICKET)
        _continuar_ticket(conversa, {})
    elif dado == "menu:meus_tickets":
        _meus_tickets(conversa)
    elif dado == "menu:humano":
        _escalar(conversa)
    elif dado.startswith("ticket_cancelar:"):
        _cancelar_ticket(conversa)
    elif dado.startswith("ticket_cat:"):
        passo, estado = _estado_ticket(conversa)
        categoria = dado.split(":", 1)[1]
        if conversa.modo != Conversa.Modo.TICKET or passo != "categoria" or categoria not in Ticket.Categoria.values:
            _enviar(conversa, "Esse botão não vale mais 🙂. Escolha uma opção:", botoes_menu())
            return
        _continuar_ticket(conversa, {**estado, "categoria": categoria})
    else:
        _enviar(conversa, "Essa opção não está mais disponível. Veja o que posso fazer:", botoes_menu())


def _boas_vindas(conversa, texto=None):
    _mudar_modo(conversa, Conversa.Modo.MENU)
    nome = _primeiro_nome(conversa)
    texto = texto or (
        f"👋 Olá{', ' + nome if nome else ''}! Bem-vindo(a) ao atendimento da {settings.NOME_EMPRESA}.\n"
        "Sou o assistente virtual: tiro dúvidas, converso, abro tickets ou te passo para um atendente. "
        "Escolha uma opção abaixo ou escreva sua mensagem. 😊"
    )
    _enviar(conversa, texto, botoes_menu())


# ---------------------------------------------------------------------------
# Texto livre: IA (ou fallback) escolhe a ação
# ---------------------------------------------------------------------------
def _faqs_ativas():
    return list(PerguntaFAQ.objects.filter(ativa=True).select_related("categoria"))


def _historico(conversa, antes_de_id):
    quem = {"cliente": "Cliente", "bot": "Assistente", "atendente": "Atendente", "sistema": "Sistema"}
    msgs = conversa.mensagens.filter(id__lt=antes_de_id).order_by("-id")[:TAM_HISTORICO]
    return [(quem.get(m.remetente, m.remetente), m.texto) for m in reversed(list(msgs))]


def _situacao(conversa, passo=None, estado=None):
    if conversa.modo == Conversa.Modo.TICKET:
        pedido = {"assunto": "o ASSUNTO do ticket", "descricao": "a DESCRIÇÃO/detalhes do problema",
                  "categoria": "a CATEGORIA do ticket"}.get(passo, "o assunto do ticket")
        ja = "; ".join(f"{k}={v}" for k, v in (estado or {}).items() if v) or "nada ainda"
        return (f"O cliente está abrindo um ticket e o bot acabou de pedir {pedido} (já informado: {ja}). "
                "Se a mensagem for a resposta, use abrir_ticket preenchendo esse campo.")
    return {
        Conversa.Modo.DUVIDA: "O cliente escolheu 'Chat de dúvida': priorize responder pelo FAQ.",
        Conversa.Modo.CONVERSA: "O cliente escolheu 'Chat de conversa': converse livremente, sem inventar dados da empresa.",
    }.get(conversa.modo, "O cliente está no menu principal.")


def _interpretar(conversa, msg, texto, faqs, passo=None, estado=None):
    """Chama a IA; se ela falhar, usa o fallback por regras. Grava a intenção na mensagem."""
    res = None
    if ia.disponivel():
        _digitando(conversa)
        if len(faqs) > MAX_FAQ_IA:
            ranking = [f for f, _ in nlp.ranquear_faq(texto, faqs)]
            faqs = (ranking + [f for f in faqs if f not in ranking])[:MAX_FAQ_IA]
        res = ia.interpretar(
            texto,
            faqs=faqs,
            intencoes=list(Intencao.objects.values_list("slug", "descricao")),
            categorias=[(c.value, c.label) for c in Ticket.Categoria],
            historico=_historico(conversa, msg.pk),
            situacao=_situacao(conversa, passo, estado),
            empresa=settings.NOME_EMPRESA,
            nome_cliente=conversa.contato.nome,
        )
    if res is not None:
        res["via_ia"] = True
    else:
        res = _interpretar_sem_ia(texto, faqs)
    intencao = Intencao.objects.filter(slug=res.get("intencao")).first() if res.get("intencao") else None
    Mensagem.objects.filter(pk=msg.pk).update(intencao=intencao, confianca=res.get("confianca"))
    return res


def _interpretar_sem_ia(texto, faqs):
    """Mesmo formato da resposta da IA, montado com regex + palavras-chave."""
    slug, confianca = nlp.detectar_intencao(texto)
    res = {"intencao": slug, "confianca": confianca, "faq_id": None, "resposta": "", "via_ia": False,
           "ticket": {"assunto": "", "descricao": "", "categoria": ""}}
    acao_por_intencao = {
        "falar_humano": "falar_com_atendente", "abrir_ticket": "abrir_ticket",
        "status_ticket": "consultar_tickets", "saudacao": "conversa_livre", "despedida": "conversa_livre",
    }
    if slug in acao_por_intencao:
        res["acao"] = acao_por_intencao[slug]
        return res
    faq, pontos = nlp.melhor_faq(texto, faqs)
    if faq:
        res.update(acao="responder_faq", faq_id=faq.pk, confianca=min(1.0, round(pontos / 4, 2)))
    else:
        res["acao"] = "sem_resposta"
    return res


def _tratar_texto(conversa, msg, texto):
    if conversa.modo == Conversa.Modo.TICKET:
        _texto_no_ticket(conversa, msg, texto)
        return
    faqs = _faqs_ativas()
    res = _interpretar(conversa, msg, texto, faqs)
    _executar(conversa, res, faqs)


def _executar(conversa, res, faqs):
    acao = res["acao"]
    resposta = res.get("resposta") or ""
    origem_ia = Mensagem.Origem.IA if res.get("via_ia") else Mensagem.Origem.REGRA

    if acao == "falar_com_atendente":
        _escalar(conversa)
    elif acao == "consultar_tickets":
        _meus_tickets(conversa)
    elif acao == "abrir_ticket":
        _mudar_modo(conversa, Conversa.Modo.TICKET)
        _continuar_ticket(conversa, res.get("ticket") or {})
    elif acao == "mostrar_menu":
        _boas_vindas(conversa, resposta or None)
    elif acao == "encerrar":
        services.encerrar(conversa)
    elif acao == "responder_faq":
        faq = next((f for f in faqs if f.pk == res.get("faq_id")), None)
        if not faq:
            _sem_resposta(conversa, "", origem_ia)
            return
        PerguntaFAQ.objects.filter(pk=faq.pk).update(vezes_usada=F("vezes_usada") + 1)
        linha1 = [B_OUTRA_DUVIDA, B_MENU] if conversa.modo == Conversa.Modo.DUVIDA else [B_MENU]
        _enviar(conversa, resposta or faq.resposta, [linha1, [B_HUMANO]], origem=Mensagem.Origem.FAQ, faq=faq)
    elif acao == "nao_suportado":
        _enviar(conversa, resposta or "Isso eu ainda não consigo fazer por aqui 😕. Posso abrir um ticket para a "
                                      "equipe ou te passar para um atendente.",
                [[B_TICKET, B_HUMANO], [B_MENU]], origem=origem_ia)
    elif acao == "conversa_livre":
        _conversa_livre(conversa, res, origem_ia)
    else:  # sem_resposta
        _sem_resposta(conversa, resposta, origem_ia)


def _conversa_livre(conversa, res, origem):
    resposta = res.get("resposta") or ""
    intencao = res.get("intencao")
    if not resposta:  # fallback sem IA
        if intencao == "despedida":
            resposta = "Por nada! 😊 Se precisar de mais alguma coisa, é só chamar."
        elif intencao == "saudacao":
            nome = _primeiro_nome(conversa)
            resposta = f"Olá{', ' + nome if nome else ''}! 👋 Como posso te ajudar?"
        else:
            resposta = "Entendi! Como posso te ajudar? 🙂"
    if intencao == "despedida":
        botoes = [[B_MENU, B_ENCERRAR]]
    elif conversa.modo == Conversa.Modo.CONVERSA:
        botoes = [[B_MENU, B_HUMANO]]
    elif conversa.modo == Conversa.Modo.MENU:
        botoes = botoes_menu()
    else:
        botoes = [[B_MENU]]
    _enviar(conversa, resposta, botoes, origem=origem)


def _falhas_seguidas(conversa):
    """Quantas das últimas respostas do bot foram 'não sei' (botões marcados com falha)."""
    n = 0
    for m in conversa.mensagens.filter(remetente=Mensagem.Remetente.BOT).order_by("-id")[:MAX_FALHAS_DUVIDA + 2]:
        if any(isinstance(b, dict) and b.get("falha") for linha in (m.botoes or []) for b in linha):
            n += 1
        else:
            break
    return n


def _sem_resposta(conversa, resposta, origem):
    falhas = _falhas_seguidas(conversa) + 1
    if falhas >= MAX_FALHAS_DUVIDA:
        texto = (resposta + "\n\n" if resposta else "Não encontrei essa informação na nossa base 😕.\n\n") + \
            "Parece que não estou conseguindo te ajudar. Quer que eu chame um atendente?"
        botoes = [[_marcado_falha({**B_HUMANO, "texto": "👤 Sim, chamar atendente"})], [B_TICKET, B_MENU]]
    else:
        if conversa.modo == Conversa.Modo.CONVERSA and origem == Mensagem.Origem.REGRA:
            texto = ("Meu modo de conversa está indisponível agora 😅 e não achei isso na nossa base de ajuda. "
                     "Posso abrir um ticket ou te passar para um atendente.")
        else:
            texto = resposta or ("Hmm, não encontrei resposta para isso na nossa base de ajuda 😕. "
                                 "Tente perguntar de outro jeito, ou posso abrir um ticket ou chamar um atendente.")
        botoes = [[_marcado_falha(B_TICKET), B_HUMANO], [B_MENU]]
    _enviar(conversa, texto, botoes, origem=origem)


# ---------------------------------------------------------------------------
# Fila / atendente humano
# ---------------------------------------------------------------------------
def _escalar(conversa, motivo="Cliente pediu atendente"):
    conversa = services.escalar(conversa, motivo)
    posicao = Conversa.objects.filter(
        status=Conversa.Status.FILA, escalada_em__lte=conversa.escalada_em,
    ).count() or 1
    texto = f"👤 Pronto! Você está na fila de atendimento (posição {posicao}). Um atendente vai assumir a conversa em breve."
    if dentro_do_horario():
        texto += f"\n🕒 Atendimento humano: {HORARIO_ATENDIMENTO}."
    else:
        texto += (f"\n🕒 Agora estamos fora do horário de atendimento humano ({HORARIO_ATENDIMENTO}). "
                  "Sua mensagem fica registrada e respondemos assim que possível.")
    texto += "\nEnquanto isso, pode ir contando o que precisa por aqui. 😉"
    _enviar(conversa, texto, [[B_ENCERRAR]])


def _aviso_fila(conversa):
    """Na fila, responde no máximo UM aviso de 'aguarde' (não fica repetindo)."""
    ja_avisou = conversa.mensagens.filter(
        remetente=Mensagem.Remetente.BOT, texto=AVISO_FILA, criada_em__gte=conversa.escalada_em or conversa.iniciada_em,
    ).exists()
    if not ja_avisou:
        _enviar(conversa, AVISO_FILA)


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------
def _estado_ticket(conversa):
    """(passo, estado) guardados no botão 'Cancelar' da última mensagem do bot."""
    ultima = conversa.mensagens.filter(remetente=Mensagem.Remetente.BOT).order_by("-id").first()
    for linha in (ultima.botoes or []) if ultima else []:
        for b in linha:
            if isinstance(b, dict) and str(b.get("dado", "")).startswith("ticket_cancelar:"):
                return b["dado"].split(":", 1)[1], dict(b.get("estado") or {})
    return None, {}


def _botao_cancelar(passo, estado):
    return {"texto": "❌ Cancelar", "dado": f"ticket_cancelar:{passo}", "estado": estado}


def _continuar_ticket(conversa, estado):
    """Pergunta o próximo dado que falta; com tudo em mãos, abre o ticket."""
    estado = {k: (estado.get(k) or "").strip() for k in ("assunto", "descricao", "categoria")}
    if estado["categoria"] not in Ticket.Categoria.values:
        estado["categoria"] = ""

    if not estado["assunto"]:
        _enviar(conversa, "📝 Vamos abrir um ticket! Qual é o assunto? Resuma em poucas palavras "
                          "(ex.: Boleto duplicado).\nPara desistir, digite cancelar.",
                [[_botao_cancelar("assunto", estado)]])
    elif not estado["descricao"]:
        _enviar(conversa, f"Assunto: {estado['assunto']} ✔️\nAgora me conte os detalhes: o que aconteceu? "
                          "Quanto mais informação, mais rápido a equipe resolve.",
                [[_botao_cancelar("descricao", estado)]])
    elif not estado["categoria"]:
        cats = [{"texto": c.label, "dado": f"ticket_cat:{c.value}"} for c in Ticket.Categoria]
        linhas = [cats[i:i + 2] for i in range(0, len(cats), 2)] + [[_botao_cancelar("categoria", estado)]]
        _enviar(conversa, "Quase lá! Em qual categoria o seu ticket se encaixa?", linhas)
    else:
        ticket = services.abrir_ticket(
            conversa.contato, estado["assunto"], estado["descricao"], conversa=conversa, categoria=estado["categoria"],
        )
        _mudar_modo(conversa, Conversa.Modo.MENU)
        _enviar(conversa,
                f"✅ Ticket aberto! Protocolo: {ticket.protocolo}\n"
                f"Assunto: {ticket.assunto}\nCategoria: {ticket.get_categoria_display()}\n"
                "Nossa equipe vai analisar e você recebe a resposta por aqui. Guarde o protocolo. 😉",
                [[B_MEUS_TICKETS, B_MENU], [B_ENCERRAR]])


def _cancelar_ticket(conversa):
    _mudar_modo(conversa, Conversa.Modo.MENU)
    _enviar(conversa, "Tudo bem, cancelei a abertura do ticket. 👍 Posso ajudar em algo mais?", botoes_menu())


def _categoria_pelo_texto(texto):
    norm = nlp.normalizar(texto)
    for c in Ticket.Categoria:
        rotulo = nlp.normalizar(c.label)
        if norm in (c.value, rotulo) or (len(norm) >= 4 and (rotulo.startswith(norm) or norm in rotulo.split())):
            return c.value
    return ""


def _texto_no_ticket(conversa, msg, texto):
    """Cliente digitou algo no meio do fluxo de ticket."""
    if nlp.normalizar(texto) in PALAVRAS_CANCELAR:
        _cancelar_ticket(conversa)
        return
    passo, estado = _estado_ticket(conversa)
    if passo is None:  # perdeu o fio (ex.: outra mensagem no meio): recomeça
        _continuar_ticket(conversa, {})
        return

    faqs = _faqs_ativas()
    res = _interpretar(conversa, msg, texto, faqs, passo, estado)
    # Mudou de ideia: sai do fluxo e faz o que pediu. Sem IA, só o pedido de
    # atendente (regex confiável) tira do fluxo; o resto é resposta do passo.
    saidas = ("falar_com_atendente", "consultar_tickets", "mostrar_menu", "encerrar") if res.get("via_ia") \
        else ("falar_com_atendente",)
    if res["acao"] in saidas:
        if res["acao"] != "encerrar":
            _mudar_modo(conversa, Conversa.Modo.MENU)
        _executar(conversa, res, faqs)
        return

    novos = (res.get("ticket") or {}) if res["acao"] == "abrir_ticket" else {}
    for campo in ("assunto", "descricao", "categoria"):
        if not estado.get(campo) and novos.get(campo):
            estado[campo] = novos[campo]
    # O que o cliente digitou é a resposta do passo atual (se a IA não preencheu).
    if not estado.get(passo):
        if passo == "categoria":
            estado["categoria"] = _categoria_pelo_texto(texto)
        else:
            estado[passo] = texto[:150] if passo == "assunto" else texto
    _continuar_ticket(conversa, estado)


def _meus_tickets(conversa):
    tickets = list(conversa.contato.tickets.order_by("-criado_em")[:5])
    if not tickets:
        _enviar(conversa, "Você ainda não tem tickets abertos. Quer abrir um agora?", [[B_TICKET, B_MENU]])
        return
    linhas = [f"• {t.protocolo} - {t.assunto} ({t.get_status_display()})" for t in tickets]
    _enviar(conversa, "📋 Seus últimos tickets:\n" + "\n".join(linhas), [[B_TICKET, B_MENU]])


# ---------------------------------------------------------------------------
# Avaliação (conversa já encerrada)
# ---------------------------------------------------------------------------
def _avaliar(contato, dado):
    try:
        _, conversa_id, nota = dado.split(":")
        conversa_id, nota = int(conversa_id), int(nota)
    except ValueError:
        return contato.conversas.first()
    conversa = Conversa.objects.filter(pk=conversa_id, contato=contato).select_related("contato").first()
    if conversa is None or not 1 <= nota <= 5:
        log.warning("Avaliação inválida %r do contato %s", dado, contato.pk)
        return contato.conversas.first()
    services.registrar_mensagem(conversa, Mensagem.Remetente.CLIENTE, "⭐" * nota)
    if conversa.status != Conversa.Status.ENCERRADA:
        return conversa
    if conversa.avaliacao:
        _enviar(conversa, "Você já avaliou este atendimento. Obrigado! 💙", [[B_NOVO]])
        return conversa
    services.registrar_avaliacao(conversa, nota)
    agradecimento = "Que bom que gostou! 🤩" if nota >= 4 else "Obrigado pela sinceridade, vamos melhorar! 🙏"
    _enviar(conversa, f"{agradecimento} Sua avaliação ({nota}/5) foi registrada. Se precisar, é só chamar.", [[B_NOVO]])
    return conversa
