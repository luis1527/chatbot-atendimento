"""
Endpoints JSON do painel (tempo real por polling).

A Vercel roda em serverless (sem websocket), então o navegador pergunta
"tem novidade?" a cada 2–3 segundos:

    GET  /painel/api/status/                              -> badge da fila, novas conversas
    GET  /painel/api/conversas/?aba=fila|meus|todos|encerradas&q=
    GET  /painel/api/conversas/<id>/                      -> dados + mensagens
    GET  /painel/api/conversas/<id>/mensagens/?depois=<id> -> só as novas
    POST /painel/api/conversas/<id>/enviar/               -> {texto}
    POST /painel/api/conversas/<id>/<acao>/               -> assumir|transferir|devolver|encerrar
    POST /painel/api/online/                              -> alterna Online/Ausente

Toda ação passa por core.services (as regras ficam num lugar só).
"""
import json

from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core import services
from core.models import Conversa, Mensagem, Usuario

from .permissoes import pode_assumir, pode_gerenciar, pode_responder, pode_transferir

ABAS = ("fila", "meus", "todos", "encerradas")
LIMITE_LISTA = 100
LIMITE_MENSAGENS = 300


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------
def _erro(texto, status=400):
    return JsonResponse({"ok": False, "erro": texto}, status=status)


def _dados_post(request):
    """Aceita JSON (fetch) ou formulário comum."""
    if request.content_type == "application/json":
        try:
            return json.loads(request.body or b"{}")
        except ValueError:
            return {}
    return request.POST


def _iso(dt):
    return timezone.localtime(dt).isoformat() if dt else None


def _horario_curto(dt):
    if not dt:
        return ""
    local = timezone.localtime(dt)
    if local.date() == timezone.localdate():
        return local.strftime("%H:%M")
    return local.strftime("%d/%m")


def _queryset_lista():
    """Conversas com prévia da última mensagem e contador de não lidas."""
    ultima = Mensagem.objects.filter(conversa=OuterRef("pk")).order_by("-criada_em", "-id")
    return (
        Conversa.objects.select_related("contato", "atendente")
        .annotate(
            previa_texto=Subquery(ultima.values("texto")[:1]),
            previa_remetente=Subquery(ultima.values("remetente")[:1]),
            previa_em=Subquery(ultima.values("criada_em")[:1]),
            # Não lidas = mensagens do cliente depois da última leitura do atendente
            # (ou, se ninguém leu ainda, depois de entrar na fila).
            nao_lidas=Count(
                "mensagens",
                filter=Q(
                    mensagens__remetente=Mensagem.Remetente.CLIENTE,
                    mensagens__criada_em__gt=Coalesce(F("ultima_leitura_atendente_em"), F("escalada_em")),
                ),
            ),
        )
    )


def _filtrar_aba(qs, aba, usuario):
    if aba == "fila":
        return qs.filter(status=Conversa.Status.FILA).order_by(F("escalada_em").asc(nulls_last=True), "id")
    if aba == "meus":
        return qs.filter(status=Conversa.Status.HUMANO, atendente=usuario).order_by("-atualizada_em")
    if aba == "encerradas":
        return qs.filter(status=Conversa.Status.ENCERRADA).order_by(F("encerrada_em").desc(nulls_last=True), "-id")
    return qs.exclude(status=Conversa.Status.ENCERRADA).order_by("-atualizada_em")


def _conversa_resumo(c, usuario):
    agora = timezone.now()
    espera = None
    if c.status == Conversa.Status.FILA and c.escalada_em:
        espera = int((agora - c.escalada_em).total_seconds())
    previa = getattr(c, "previa_texto", "") or ""
    remetente = getattr(c, "previa_remetente", "") or ""
    em = getattr(c, "previa_em", None) or c.atualizada_em
    return {
        "id": c.pk,
        "nome": c.contato.nome,
        "canal": c.canal,
        "canal_label": c.get_canal_display(),
        "status": c.status,
        "status_label": c.get_status_display(),
        "atendente": c.atendente.nome_exibicao if c.atendente else None,
        "eh_minha": c.atendente_id == usuario.pk and c.status == Conversa.Status.HUMANO,
        "previa": previa[:90],
        "previa_remetente": remetente,
        "horario": _horario_curto(em),
        "atualizada_em": _iso(c.atualizada_em),
        "espera_seg": espera,
        "nao_lidas": getattr(c, "nao_lidas", 0) if c.status != Conversa.Status.ENCERRADA else 0,
        "avaliacao": c.avaliacao,
        "motivo": c.motivo_escalonamento,
    }


def _mensagem_json(m):
    return {
        "id": m.pk,
        "remetente": m.remetente,
        "texto": m.texto,
        "atendente": m.atendente.nome_exibicao if m.atendente else None,
        "origem": m.origem_resposta,
        "origem_label": m.get_origem_resposta_display() if m.origem_resposta else "",
        "intencao": m.intencao.nome if m.intencao else None,
        "confianca": round(m.confianca, 2) if m.confianca is not None else None,
        "botoes": m.botoes or [],
        "criada_em": _iso(m.criada_em),
        "hora": timezone.localtime(m.criada_em).strftime("%d/%m %H:%M"),
    }


def _mensagens_qs(conversa):
    return conversa.mensagens.select_related("atendente", "intencao")


def _conversa_detalhe(conversa, usuario):
    contato = conversa.contato
    resumo = _conversa_resumo(conversa, usuario)
    resumo.update({
        "contato": {
            "nome": contato.nome,
            "canal": contato.get_canal_display(),
            "telegram_username": contato.telegram_username,
            "email": contato.email,
            "telefone": contato.telefone,
            "cliente_desde": timezone.localtime(contato.criado_em).strftime("%d/%m/%Y"),
            "total_conversas": contato.conversas.count(),
        },
        "iniciada_em": timezone.localtime(conversa.iniciada_em).strftime("%d/%m/%Y %H:%M"),
        "escalada_em": _iso(conversa.escalada_em),
        "atendente_id": conversa.atendente_id,
        "comentario_avaliacao": conversa.comentario_avaliacao,
        "tickets": [
            {
                "protocolo": t.protocolo, "assunto": t.assunto, "status": t.get_status_display(),
                "url": reverse("painel:ticket_detalhe", args=[t.pk]),
            }
            for t in contato.tickets.order_by("-criado_em")[:5]
        ],
        "permissoes": {
            "responder": pode_responder(usuario, conversa),
            "assumir": pode_assumir(usuario, conversa),
            "transferir": pode_transferir(usuario, conversa),
            "devolver": pode_gerenciar(usuario, conversa) and conversa.status != Conversa.Status.BOT,
            "encerrar": pode_gerenciar(usuario, conversa),
        },
    })
    return resumo


def _marcar_lida(conversa, usuario):
    """Zera as não lidas quando o responsável (ou ninguém ainda, na fila) abre a conversa."""
    if conversa.atendente_id == usuario.pk or conversa.status == Conversa.Status.FILA:
        agora = timezone.now()
        # update() não mexe em atualizada_em (a conversa não "sobe" na lista só por ser lida).
        Conversa.objects.filter(pk=conversa.pk).update(ultima_leitura_atendente_em=agora)
        conversa.ultima_leitura_atendente_em = agora


def _buscar_conversa(pk):
    return get_object_or_404(Conversa.objects.select_related("contato", "atendente"), pk=pk)


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------
@login_required
@require_GET
def status(request):
    """Chamado em todas as páginas: badge da fila e alerta de conversa nova."""
    fila = Conversa.objects.filter(status=Conversa.Status.FILA)
    meus_nao_lidas = (
        Mensagem.objects.filter(
            conversa__status=Conversa.Status.HUMANO,
            conversa__atendente=request.user,
            remetente=Mensagem.Remetente.CLIENTE,
        )
        .filter(Q(conversa__ultima_leitura_atendente_em__isnull=True)
                | Q(criada_em__gt=F("conversa__ultima_leitura_atendente_em")))
        .count()
    )
    return JsonResponse({
        "ok": True,
        "fila": fila.count(),
        "fila_ids": list(fila.order_by("-id").values_list("id", flat=True)[:50]),
        "meus": Conversa.objects.filter(status=Conversa.Status.HUMANO, atendente=request.user).count(),
        "meus_nao_lidas": meus_nao_lidas,
        "online": request.user.online,
    })


@login_required
@require_GET
def conversas(request):
    aba = request.GET.get("aba", "fila")
    if aba not in ABAS:
        aba = "fila"
    qs = _filtrar_aba(_queryset_lista(), aba, request.user)
    busca = request.GET.get("q", "").strip()
    if busca:
        filtro = Q(contato__nome__icontains=busca) | Q(contato__telegram_username__icontains=busca)
        if busca.isdigit():
            filtro |= Q(pk=int(busca))
        qs = qs.filter(filtro)
    lista = [_conversa_resumo(c, request.user) for c in qs[:LIMITE_LISTA]]
    contagem = {
        "fila": Conversa.objects.filter(status=Conversa.Status.FILA).count(),
        "meus": Conversa.objects.filter(status=Conversa.Status.HUMANO, atendente=request.user).count(),
        "todos": Conversa.objects.exclude(status=Conversa.Status.ENCERRADA).count(),
    }
    return JsonResponse({"ok": True, "aba": aba, "conversas": lista, "contagem": contagem})


@login_required
@require_GET
def conversa_detalhe(request, pk):
    conversa = _buscar_conversa(pk)
    _marcar_lida(conversa, request.user)
    total = conversa.mensagens.count()
    msgs = list(_mensagens_qs(conversa).order_by("-criada_em", "-id")[:LIMITE_MENSAGENS])[::-1]
    return JsonResponse({
        "ok": True,
        "conversa": _conversa_detalhe(conversa, request.user),
        "mensagens": [_mensagem_json(m) for m in msgs],
        "mensagens_ocultas": max(0, total - len(msgs)),
    })


@login_required
@require_GET
def conversa_mensagens(request, pk):
    """Polling da conversa aberta: só as mensagens com id > depois."""
    conversa = _buscar_conversa(pk)
    try:
        depois = int(request.GET.get("depois", 0))
    except ValueError:
        depois = 0
    novas = list(_mensagens_qs(conversa).filter(id__gt=depois).order_by("criada_em", "id")[:LIMITE_MENSAGENS])
    if novas:
        _marcar_lida(conversa, request.user)
    return JsonResponse({
        "ok": True,
        "conversa": _conversa_detalhe(conversa, request.user),
        "mensagens": [_mensagem_json(m) for m in novas],
    })


# ---------------------------------------------------------------------------
# Ações (POST + CSRF)
# ---------------------------------------------------------------------------
def _responder_acao(conversa, usuario, aviso=""):
    conversa = _buscar_conversa(conversa.pk)
    return JsonResponse({"ok": True, "aviso": aviso, "conversa": _conversa_detalhe(conversa, usuario)})


@login_required
@require_POST
def enviar(request, pk):
    conversa = _buscar_conversa(pk)
    texto = (_dados_post(request).get("texto") or "").strip()
    if not texto:
        return _erro("Escreva uma mensagem.")
    if len(texto) > 4000:
        return _erro("Mensagem muito longa (máximo 4000 caracteres).")
    if not pode_responder(request.user, conversa):
        if conversa.status == Conversa.Status.FILA:
            return _erro("Assuma a conversa para responder.", 403)
        if conversa.status == Conversa.Status.HUMANO:
            return _erro(f"Esta conversa está com {conversa.atendente.nome_exibicao}.", 403)
        return _erro("Esta conversa não está em atendimento humano.", 403)
    try:
        msg = services.enviar_ao_cliente(
            conversa, texto, remetente=Mensagem.Remetente.ATENDENTE, atendente=request.user,
            origem_resposta=Mensagem.Origem.HUMANO,
        )
    except services.ErroAtendimento as e:
        return _erro(str(e))
    _marcar_lida(conversa, request.user)
    msg = Mensagem.objects.select_related("atendente", "intencao").get(pk=msg.pk)
    return JsonResponse({"ok": True, "mensagem": _mensagem_json(msg)})


@login_required
@require_POST
def acao(request, pk, nome):
    conversa = _buscar_conversa(pk)
    usuario = request.user
    try:
        if nome == "assumir":
            # O serviço trava a linha no banco: se dois clicarem juntos, só um consegue
            # e o outro recebe "Conversa já está com Fulano".
            services.assumir(conversa, usuario)
            _marcar_lida(conversa, usuario)
            return _responder_acao(conversa, usuario, "Conversa assumida. Pode responder!")

        if nome == "transferir":
            if not pode_transferir(usuario, conversa):
                return _erro("Só quem está com a conversa (ou um supervisor) pode transferir.", 403)
            para_id = _dados_post(request).get("para")
            para = Usuario.objects.filter(pk=para_id, is_active=True).first() if para_id else None
            if not para:
                return _erro("Escolha para quem transferir.")
            services.transferir(conversa, usuario, para)
            # O novo responsável ainda não leu.
            Conversa.objects.filter(pk=conversa.pk).update(ultima_leitura_atendente_em=None)
            return _responder_acao(conversa, usuario, f"Conversa transferida para {para.nome_exibicao}.")

        if nome == "devolver":
            if not pode_gerenciar(usuario, conversa):
                return _erro("Você não pode devolver uma conversa que está com outro atendente.", 403)
            services.devolver_ao_bot(conversa, usuario)
            return _responder_acao(conversa, usuario, "Conversa devolvida ao bot.")

        if nome == "encerrar":
            if not pode_gerenciar(usuario, conversa):
                return _erro("Você não pode encerrar uma conversa que está com outro atendente.", 403)
            services.encerrar(conversa, usuario)
            return _responder_acao(conversa, usuario, "Atendimento encerrado. O cliente vai receber o pedido de avaliação.")
    except services.ErroAtendimento as e:
        return _erro(str(e), 409)
    return _erro("Ação desconhecida.", 404)


@login_required
@require_POST
def alternar_online(request):
    dados = _dados_post(request)
    valor = dados.get("online")
    if valor is None:
        novo = not request.user.online
    else:
        novo = str(valor).lower() in ("1", "true", "sim", "on")
    Usuario.objects.filter(pk=request.user.pk).update(online=novo)
    return JsonResponse({"ok": True, "online": novo})
