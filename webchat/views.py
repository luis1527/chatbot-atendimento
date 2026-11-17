"""
Site público: página inicial e "Chat teste" (conversar com o bot pelo navegador).

O chat do site usa o MESMO motor do Telegram (bot.engine.processar_entrada).
O motor grava a mensagem do cliente e as respostas no banco; o navegador
busca as mensagens novas por polling (GET /api/chat/mensagens/?depois=<id>).
Respostas de atendentes humanos (painel) chegam pelo mesmo caminho.

Identidade do visitante: um UUID guardado na sessão do Django. Todas as
consultas filtram pelo contato dessa sessão — um visitante nunca lê a
conversa de outro.
"""
import json
import logging
import time
import uuid
from datetime import timedelta

from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from bot import engine
from core import services
from core.models import Contato, Conversa, Mensagem

log = logging.getLogger(__name__)

CHAVE_SESSAO = "webchat_visitante"
CHAVE_ULTIMO_ENVIO = "webchat_ultimo_envio"
LIMITE_TEXTO = 1000
LIMITE_DADO = 200
INTERVALO_MINIMO = 0.5  # segundos entre mensagens do mesmo visitante
MAX_MENSAGENS = 200
# Conversa encerrada há pouco continua visível (pedido de avaliação).
JANELA_ENCERRADA = timedelta(hours=1)
NOME_PADRAO = "Visitante"


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------
def _sessao_uuid(request, criar=False):
    valor = request.session.get(CHAVE_SESSAO)
    if not valor and criar:
        valor = uuid.uuid4().hex
        request.session[CHAVE_SESSAO] = valor
    return valor


def _contato_da_sessao(request):
    sessao = _sessao_uuid(request)
    if not sessao:
        return None
    return Contato.objects.filter(web_sessao=sessao).first()


def _conversa_exibida(contato):
    """Conversa mostrada ao abrir o chat: a aberta ou a encerrada há pouco."""
    conversa = services.conversa_aberta(contato, criar=False)
    if conversa:
        return conversa
    ultima = contato.conversas.order_by("-iniciada_em", "-id").first()
    if ultima and ultima.encerrada_em and timezone.now() - ultima.encerrada_em <= JANELA_ENCERRADA:
        return ultima
    return None


def _status(contato):
    conversa = services.conversa_aberta(contato, criar=False)
    if not conversa:
        if contato.conversas.exists():
            return {"codigo": "encerrada", "rotulo": "Atendimento encerrado", "atendente": None}
        return {"codigo": "bot", "rotulo": "Assistente virtual", "atendente": None}
    if conversa.status == Conversa.Status.FILA:
        return {"codigo": "fila", "rotulo": "Aguardando atendente…", "atendente": None}
    if conversa.status == Conversa.Status.HUMANO:
        nome = conversa.atendente.nome_exibicao if conversa.atendente else "atendente"
        return {"codigo": "humano", "rotulo": f"Em atendimento com {nome}", "atendente": nome}
    return {"codigo": "bot", "rotulo": "Assistente virtual", "atendente": None}


def _serializar(msg):
    return {
        "id": msg.id,
        "conversa": msg.conversa_id,
        "remetente": msg.remetente,
        "texto": msg.texto,
        "atendente": msg.atendente.nome_exibicao if msg.atendente_id and msg.atendente else None,
        "botoes": _botoes_validos(msg.botoes),
        "hora": timezone.localtime(msg.criada_em).strftime("%H:%M"),
        "criada_em": msg.criada_em.isoformat(),
    }


def _botoes_validos(botoes):
    """Normaliza o JSON de botões (lista de linhas) e descarta lixo."""
    if not isinstance(botoes, list):
        return []
    linhas = []
    for linha in botoes:
        if isinstance(linha, dict):
            linha = [linha]
        if not isinstance(linha, list):
            continue
        itens = []
        for b in linha:
            if not isinstance(b, dict) or not b.get("texto"):
                continue
            item = {"texto": str(b["texto"])}
            if b.get("url"):
                url = str(b["url"])
                if not url.lower().startswith(("http://", "https://", "tg://")):
                    continue
                item["url"] = url
            elif b.get("dado") is not None:
                item["dado"] = str(b["dado"])
            else:
                continue
            itens.append(item)
        if itens:
            linhas.append(itens)
    return linhas


def _ler_corpo(request):
    if request.content_type == "application/json":
        try:
            dados = json.loads(request.body or b"{}")
        except (ValueError, UnicodeDecodeError):
            return None
        return dados if isinstance(dados, dict) else None
    return request.POST.dict()


def _erro(mensagem, status=400):
    return JsonResponse({"ok": False, "erro": mensagem}, status=status)


def _ultimo_id(contato):
    ultimo = Mensagem.objects.filter(conversa__contato=contato).order_by("-id").values_list("id", flat=True).first()
    return ultimo or 0


def _chamar_engine(contato, **kwargs):
    """Chama o motor do bot; devolve None se deu certo ou uma resposta de erro."""
    try:
        engine.processar_entrada(contato, **kwargs)
    except Exception:
        log.exception("Falha no motor do bot (webchat, contato %s)", contato.pk)
        return _erro("O assistente está indisponível no momento. Tente novamente em instantes.", 503)
    return None


# ---------------------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------------------
def inicio(request):
    return render(request, "webchat/inicio.html")


@ensure_csrf_cookie
def chat(request):
    _sessao_uuid(request, criar=True)
    contato = _contato_da_sessao(request)
    return render(request, "webchat/chat.html", {
        "precisa_nome": contato is None,
        "nome_visitante": contato.nome if contato else "",
        "limite_texto": LIMITE_TEXTO,
    })


# ---------------------------------------------------------------------------
# API JSON
# ---------------------------------------------------------------------------
@require_POST
def api_iniciar(request):
    """
    Cria/recupera o contato do visitante e, se não houver conversa para
    mostrar, pede ao bot as boas-vindas (/start).
    """
    dados = _ler_corpo(request)
    if dados is None:
        return _erro("Requisição inválida.")
    nome = str(dados.get("nome") or "").strip()[:60]
    sessao = _sessao_uuid(request, criar=True)
    existente = Contato.objects.filter(web_sessao=sessao).first()
    if existente:
        contato = services.contato_web(sessao, nome or None)
    else:
        contato = services.contato_web(sessao, nome or NOME_PADRAO)

    conversa = _conversa_exibida(contato)
    if conversa is None or not conversa.mensagens.exists():
        erro = _chamar_engine(contato, texto="/start")
        if erro:
            return erro
    return JsonResponse({
        "ok": True, "nome": contato.nome, "status": _status(contato), "ultimo_id": _ultimo_id(contato),
    })


@require_POST
def api_enviar(request):
    contato = _contato_da_sessao(request)
    if not contato:
        return _erro("Sessão do chat não iniciada. Recarregue a página.", 403)
    dados = _ler_corpo(request)
    if dados is None:
        return _erro("Requisição inválida.")

    texto = str(dados.get("texto") or "").strip()
    dado = str(dados.get("dado") or "").strip()
    if not texto and not dado:
        return _erro("Mensagem vazia.")
    if len(texto) > LIMITE_TEXTO:
        return _erro(f"Mensagem muito longa (máximo {LIMITE_TEXTO} caracteres).")
    if len(dado) > LIMITE_DADO:
        return _erro("Botão inválido.")

    agora = time.time()
    ultimo = request.session.get(CHAVE_ULTIMO_ENVIO) or 0
    if agora - ultimo < INTERVALO_MINIMO:
        return _erro("Calma! Espere um instante antes de enviar outra mensagem.", 429)
    request.session[CHAVE_ULTIMO_ENVIO] = agora

    if dado:
        erro = _chamar_engine(contato, dado=dado)
    else:
        erro = _chamar_engine(contato, texto=texto)
    if erro:
        return erro
    return JsonResponse({"ok": True, "ultimo_id": _ultimo_id(contato), "status": _status(contato)})


@require_POST
def api_nova_conversa(request):
    """Encerra a conversa atual (sem pedir avaliação) e começa outra."""
    contato = _contato_da_sessao(request)
    if not contato:
        return _erro("Sessão do chat não iniciada. Recarregue a página.", 403)
    conversa = services.conversa_aberta(contato, criar=False)
    if conversa:
        services.encerrar(conversa, pedir_avaliacao=False)
    erro = _chamar_engine(contato, texto="/start")
    if erro:
        return erro
    return JsonResponse({"ok": True, "ultimo_id": _ultimo_id(contato), "status": _status(contato)})


@require_GET
def api_mensagens(request):
    """
    depois=0 (ou ausente): mensagens da conversa exibida (aberta ou recém-encerrada).
    depois=<id>: todas as mensagens novas do visitante (de qualquer conversa dele),
    o que inclui o pedido de avaliação de uma conversa que acabou de ser encerrada.
    """
    contato = _contato_da_sessao(request)
    if not contato:
        return _erro("Sessão do chat não iniciada. Recarregue a página.", 403)
    try:
        depois = max(int(request.GET.get("depois") or 0), 0)
    except ValueError:
        return _erro("Parâmetro 'depois' inválido.")

    qs = Mensagem.objects.select_related("atendente").order_by("id")
    if depois:
        qs = qs.filter(conversa__contato=contato, id__gt=depois)
        mensagens = list(qs[:MAX_MENSAGENS])
    else:
        conversa = _conversa_exibida(contato)
        if conversa:
            # As mais recentes, em ordem cronológica.
            mensagens = list(qs.filter(conversa=conversa).order_by("-id")[:MAX_MENSAGENS])[::-1]
        else:
            mensagens = []

    return JsonResponse({
        "ok": True,
        "mensagens": [_serializar(m) for m in mensagens],
        "status": _status(contato),
        "nome": contato.nome,
    })


@require_GET
def saude(request):
    banco = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        log.exception("Health check: banco indisponível")
        banco = False
    return JsonResponse({"ok": True, "banco": banco})
