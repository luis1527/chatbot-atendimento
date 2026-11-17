"""
Regras de negócio compartilhadas.

TODO o resto do sistema (bot do Telegram, chat do site, painel) passa por
aqui para criar contatos, conversas, mensagens e mudar o status de um
atendimento. Assim as regras ficam num lugar só.
"""
import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Canal, Contato, Conversa, EventoConversa, Mensagem, Ticket, Usuario

log = logging.getLogger(__name__)


class ErroAtendimento(Exception):
    """Ação inválida no estado atual (ex.: assumir conversa já assumida)."""


# ---------------------------------------------------------------------------
# Contatos
# ---------------------------------------------------------------------------
def contato_telegram(chat_id: int, nome: str, username: str = "") -> Contato:
    contato, criado = Contato.objects.get_or_create(
        telegram_chat_id=chat_id,
        defaults={"canal": Canal.TELEGRAM, "nome": nome or "Cliente Telegram", "telegram_username": username or ""},
    )
    if not criado and ((nome and contato.nome != nome) or (username or "") != contato.telegram_username):
        contato.nome = nome or contato.nome
        contato.telegram_username = username or ""
        contato.save(update_fields=["nome", "telegram_username", "ultimo_contato_em"])
    return contato


def contato_web(sessao: str, nome: str | None = None) -> Contato:
    contato, criado = Contato.objects.get_or_create(
        web_sessao=sessao, defaults={"canal": Canal.WEB, "nome": nome or "Visitante do site"},
    )
    if nome and not criado and contato.nome != nome:
        contato.nome = nome
        contato.save(update_fields=["nome", "ultimo_contato_em"])
    return contato


# ---------------------------------------------------------------------------
# Conversas
# ---------------------------------------------------------------------------
def conversa_aberta(contato: Contato, criar: bool = True) -> Conversa | None:
    """Retorna a conversa aberta do contato (cria uma se não houver)."""
    conversa = contato.conversas.exclude(status=Conversa.Status.ENCERRADA).first()
    if conversa or not criar:
        return conversa
    try:
        with transaction.atomic():
            conversa = Conversa.objects.create(contato=contato, canal=contato.canal)
            EventoConversa.objects.create(conversa=conversa, tipo=EventoConversa.Tipo.CRIADA)
            return conversa
    except IntegrityError:
        # Duas mensagens chegaram juntas e a outra criou a conversa primeiro.
        return contato.conversas.exclude(status=Conversa.Status.ENCERRADA).get()


def registrar_mensagem(conversa: Conversa, remetente: str, texto: str, **campos) -> Mensagem:
    """Grava a mensagem e 'toca' a conversa (atualizada_em) para ela subir na lista."""
    msg = Mensagem.objects.create(conversa=conversa, remetente=remetente, texto=texto, **campos)
    Conversa.objects.filter(pk=conversa.pk).update(atualizada_em=timezone.now())
    Contato.objects.filter(pk=conversa.contato_id).update(ultimo_contato_em=timezone.now())
    return msg


def enviar_ao_cliente(
    conversa: Conversa,
    texto: str,
    *,
    remetente: str = Mensagem.Remetente.BOT,
    atendente: Usuario | None = None,
    botoes: list | None = None,
    **campos,
) -> Mensagem:
    """
    Grava a mensagem e entrega ao cliente pelo canal da conversa.

    - Telegram: envia pelo bot (mensagens de atendente saem com o nome dele).
    - Site: só grava; o chat do site busca as mensagens novas sozinho.

    `botoes`: lista de linhas, cada linha uma lista de {"texto", "dado"}.
    """
    msg = registrar_mensagem(
        conversa, remetente, texto, atendente=atendente, botoes=botoes or None, **campos,
    )
    if conversa.canal == Canal.TELEGRAM:
        from bot import telegram_api

        texto_envio = texto
        if remetente == Mensagem.Remetente.ATENDENTE and atendente:
            texto_envio = f"👤 *{telegram_api.escapar(atendente.nome_exibicao)}* \\(atendente\\):\n{telegram_api.escapar(texto)}"
            enviado = telegram_api.enviar_mensagem(conversa.contato.telegram_chat_id, texto_envio, botoes, markdown=True)
        else:
            enviado = telegram_api.enviar_mensagem(conversa.contato.telegram_chat_id, texto_envio, botoes)
        if enviado and enviado.get("message_id"):
            Mensagem.objects.filter(pk=msg.pk).update(telegram_message_id=enviado["message_id"])
    return msg


def _evento(conversa, tipo, usuario=None, para_usuario=None, detalhe=""):
    return EventoConversa.objects.create(
        conversa=conversa, tipo=tipo, usuario=usuario, para_usuario=para_usuario, detalhe=detalhe[:255],
    )


@transaction.atomic
def escalar(conversa: Conversa, motivo: str = "Cliente pediu atendente") -> Conversa:
    """Manda a conversa para a fila dos atendentes."""
    conversa = Conversa.objects.select_for_update().get(pk=conversa.pk)
    if conversa.status in (Conversa.Status.FILA, Conversa.Status.HUMANO):
        return conversa
    if conversa.status == Conversa.Status.ENCERRADA:
        raise ErroAtendimento("Conversa já encerrada.")
    conversa.status = Conversa.Status.FILA
    conversa.motivo_escalonamento = motivo[:255]
    conversa.escalada_em = timezone.now()
    conversa.save(update_fields=["status", "motivo_escalonamento", "escalada_em", "atualizada_em"])
    _evento(conversa, EventoConversa.Tipo.ESCALADA, detalhe=motivo)
    return conversa


def assumir(conversa: Conversa, atendente: Usuario) -> Conversa:
    """Funcionário pega a conversa. Só um consegue (trava no banco)."""
    with transaction.atomic():
        conversa = Conversa.objects.select_for_update().get(pk=conversa.pk)
        if conversa.status == Conversa.Status.ENCERRADA:
            raise ErroAtendimento("Conversa já encerrada.")
        if conversa.status == Conversa.Status.HUMANO:
            if conversa.atendente_id == atendente.pk:
                return conversa
            raise ErroAtendimento(f"Conversa já está com {conversa.atendente.nome_exibicao}.")
        conversa.status = Conversa.Status.HUMANO
        conversa.atendente = atendente
        conversa.assumida_em = timezone.now()
        if not conversa.escalada_em:
            conversa.escalada_em = conversa.assumida_em
        conversa.save(update_fields=["status", "atendente", "assumida_em", "escalada_em", "atualizada_em"])
        _evento(conversa, EventoConversa.Tipo.ASSUMIDA, usuario=atendente)
    enviar_ao_cliente(
        conversa, f"✅ {atendente.nome_exibicao} entrou na conversa e vai te atender agora.",
        remetente=Mensagem.Remetente.SISTEMA,
    )
    return conversa


def transferir(conversa: Conversa, de: Usuario, para: Usuario) -> Conversa:
    if para.pk == de.pk:
        raise ErroAtendimento("Escolha outro funcionário.")
    with transaction.atomic():
        conversa = Conversa.objects.select_for_update().get(pk=conversa.pk)
        if conversa.status != Conversa.Status.HUMANO:
            raise ErroAtendimento("Só é possível transferir conversas em atendimento.")
        conversa.atendente = para
        conversa.save(update_fields=["atendente", "atualizada_em"])
        _evento(conversa, EventoConversa.Tipo.TRANSFERIDA, usuario=de, para_usuario=para)
    enviar_ao_cliente(
        conversa, f"🔄 Você foi transferido para {para.nome_exibicao}.", remetente=Mensagem.Remetente.SISTEMA,
    )
    return conversa


def devolver_ao_bot(conversa: Conversa, usuario: Usuario) -> Conversa:
    with transaction.atomic():
        conversa = Conversa.objects.select_for_update().get(pk=conversa.pk)
        if conversa.status == Conversa.Status.ENCERRADA:
            raise ErroAtendimento("Conversa já encerrada.")
        conversa.status = Conversa.Status.BOT
        conversa.modo = Conversa.Modo.MENU
        conversa.atendente = None
        conversa.save(update_fields=["status", "modo", "atendente", "atualizada_em"])
        _evento(conversa, EventoConversa.Tipo.DEVOLVIDA_BOT, usuario=usuario)
    from bot.engine import botoes_menu

    enviar_ao_cliente(
        conversa, "🤖 O assistente virtual voltou. Posso ajudar em mais alguma coisa?",
        remetente=Mensagem.Remetente.SISTEMA, botoes=botoes_menu(),
    )
    return conversa


def encerrar(conversa: Conversa, usuario: Usuario | None = None, pedir_avaliacao: bool = True) -> Conversa:
    with transaction.atomic():
        conversa = Conversa.objects.select_for_update().get(pk=conversa.pk)
        if conversa.status == Conversa.Status.ENCERRADA:
            return conversa
        conversa.status = Conversa.Status.ENCERRADA
        conversa.encerrada_em = timezone.now()
        conversa.save(update_fields=["status", "encerrada_em", "atualizada_em"])
        _evento(conversa, EventoConversa.Tipo.ENCERRADA, usuario=usuario)
    if pedir_avaliacao:
        enviar_ao_cliente(
            conversa,
            "🏁 Atendimento encerrado. Como você avalia este atendimento?",
            remetente=Mensagem.Remetente.SISTEMA,
            botoes=[[{"texto": "⭐" * n, "dado": f"avaliar:{conversa.pk}:{n}"} for n in range(1, 6)]],
        )
    return conversa


def registrar_avaliacao(conversa: Conversa, nota: int, comentario: str = "") -> Conversa:
    if not 1 <= int(nota) <= 5:
        raise ErroAtendimento("Nota deve ser de 1 a 5.")
    conversa.avaliacao = int(nota)
    if comentario:
        conversa.comentario_avaliacao = comentario[:500]
    conversa.save(update_fields=["avaliacao", "comentario_avaliacao", "atualizada_em"])
    _evento(conversa, EventoConversa.Tipo.AVALIADA, detalhe=f"Nota {nota}")
    return conversa


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------
def abrir_ticket(
    contato: Contato,
    assunto: str,
    descricao: str,
    *,
    conversa: Conversa | None = None,
    categoria: str = Ticket.Categoria.OUTRO,
    prioridade: str = Ticket.Prioridade.MEDIA,
) -> Ticket:
    ticket = Ticket.objects.create(
        contato=contato, conversa=conversa, assunto=assunto[:150], descricao=descricao,
        categoria=categoria, prioridade=prioridade,
    )
    if conversa:
        _evento(conversa, EventoConversa.Tipo.TICKET, detalhe=ticket.protocolo)
    return ticket


def atualizar_ticket(ticket: Ticket, usuario: Usuario, *, status=None, resposta=None, avisar_cliente=True) -> Ticket:
    """Muda status/resposta e, se resolvido, avisa o cliente pelo canal dele."""
    campos = ["atualizado_em"]
    if status and status != ticket.status:
        ticket.status = status
        campos.append("status")
        if status == Ticket.Status.RESOLVIDO:
            ticket.resolvido_em = timezone.now()
            campos.append("resolvido_em")
    if resposta is not None:
        ticket.resposta = resposta
        campos.append("resposta")
    if not ticket.responsavel_id:
        ticket.responsavel = usuario
        campos.append("responsavel")
    ticket.save(update_fields=campos)

    if avisar_cliente and status in (Ticket.Status.RESOLVIDO, Ticket.Status.EM_ANDAMENTO):
        conversa = conversa_aberta(ticket.contato)
        if status == Ticket.Status.RESOLVIDO:
            texto = f"📋 Seu ticket {ticket.protocolo} ({ticket.assunto}) foi resolvido."
            if ticket.resposta:
                texto += f"\n\nResposta: {ticket.resposta}"
        else:
            texto = f"📋 Seu ticket {ticket.protocolo} está em andamento com {usuario.nome_exibicao}."
        try:
            enviar_ao_cliente(conversa, texto, remetente=Mensagem.Remetente.SISTEMA)
        except Exception:  # aviso é bônus; não pode quebrar a atualização
            log.exception("Falha ao avisar cliente sobre ticket %s", ticket.protocolo)
    return ticket
