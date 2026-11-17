"""Páginas do painel dos funcionários."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core import services
from core.models import CategoriaFAQ, Conversa, PerguntaFAQ, Ticket, Usuario

from . import metricas
from .forms import (
    CategoriaFAQForm, FuncionarioForm, LoginForm, PerguntaFAQForm, RedefinirSenhaForm, TicketForm,
)
from .permissoes import supervisor_required

# Textos prontos na caixa de resposta. {nome} vira o primeiro nome do cliente.
RESPOSTAS_RAPIDAS = [
    ("👋 Saudação", "Olá, {nome}! Tudo bem? Sou {atendente} e vou te ajudar a partir de agora."),
    ("⏳ Um momento", "Só um momento, por favor, estou verificando para você."),
    ("🔎 Mais detalhes", "Pode me dar mais detalhes, por favor? Se tiver um número de pedido ou protocolo, ajuda bastante."),
    ("📋 Abrir ticket", "Vou registrar um ticket para a equipe responsável e você receberá o retorno por aqui."),
    ("🙏 Obrigado", "Obrigado pela paciência, {nome}!"),
    ("✅ Algo mais?", "Posso ajudar em mais alguma coisa?"),
    ("👋 Despedida", "Foi um prazer te atender, {nome}! Vou encerrar o atendimento, tenha um ótimo dia."),
]


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------
class Entrar(LoginView):
    template_name = "painel/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


class Sair(LogoutView):
    pass


# ---------------------------------------------------------------------------
# Atendimentos (fila + conversa)
# ---------------------------------------------------------------------------
@login_required
def fila(request, pk=None):
    """Tela principal. A lista e a conversa são carregadas pelo JS (polling)."""
    if pk is not None:
        get_object_or_404(Conversa, pk=pk)
    aba = request.GET.get("aba")
    if aba not in ("fila", "meus", "todos", "encerradas"):
        aba = ""
    funcionarios = [
        {"id": u.pk, "nome": u.nome_exibicao, "online": u.online, "cargo": u.get_cargo_display()}
        for u in Usuario.objects.filter(is_active=True).exclude(pk=request.user.pk).order_by("-online", "first_name", "username")
    ]
    config = {
        "conversaInicial": pk,
        "abaInicial": aba,
        "usuario": {"id": request.user.pk, "nome": request.user.nome_exibicao},
        "funcionarios": funcionarios,
        "respostasRapidas": [{"rotulo": r, "texto": t} for r, t in RESPOSTAS_RAPIDAS],
        "urls": {
            "lista": reverse("painel:api_conversas"),
            "conversa": reverse("painel:api_conversa", args=[0]),
            "mensagens": reverse("painel:api_mensagens", args=[0]),
            "enviar": reverse("painel:api_enviar", args=[0]),
            "acao": reverse("painel:api_acao", args=[0, "ACAO"]),
            "pagina": reverse("painel:conversa", args=[0]),
            "inicio": reverse("painel:fila"),
        },
    }
    return render(request, "painel/atendimentos.html", {"config": config, "menu": "atendimentos"})


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------
@login_required
def tickets(request):
    qs = Ticket.objects.select_related("contato", "responsavel", "conversa")
    f = {
        "status": request.GET.get("status", ""),
        "prioridade": request.GET.get("prioridade", ""),
        "categoria": request.GET.get("categoria", ""),
        "responsavel": request.GET.get("responsavel", ""),
        "q": request.GET.get("q", "").strip(),
    }
    if f["status"] == "abertos":
        qs = qs.filter(status__in=[Ticket.Status.ABERTO, Ticket.Status.EM_ANDAMENTO])
    elif f["status"]:
        qs = qs.filter(status=f["status"])
    if f["prioridade"]:
        qs = qs.filter(prioridade=f["prioridade"])
    if f["categoria"]:
        qs = qs.filter(categoria=f["categoria"])
    if f["responsavel"] == "eu":
        qs = qs.filter(responsavel=request.user)
    elif f["responsavel"] == "ninguem":
        qs = qs.filter(responsavel__isnull=True)
    if f["q"]:
        qs = qs.filter(Q(protocolo__icontains=f["q"]) | Q(assunto__icontains=f["q"]) | Q(contato__nome__icontains=f["q"]))

    pagina = Paginator(qs, 25).get_page(request.GET.get("pagina"))
    parametros = request.GET.copy()
    parametros.pop("pagina", None)
    contagem = dict(Ticket.objects.values_list("status").annotate(n=Count("id")))
    return render(request, "painel/tickets.html", {
        "menu": "tickets",
        "pagina": pagina,
        "filtros": f,
        "parametros": parametros.urlencode(),
        "status_choices": Ticket.Status.choices,
        "prioridade_choices": Ticket.Prioridade.choices,
        "categoria_choices": Ticket.Categoria.choices,
        "status_chips": [(v, r, contagem.get(v, 0)) for v, r in Ticket.Status.choices],
    })


@login_required
def ticket_detalhe(request, pk):
    ticket = get_object_or_404(Ticket.objects.select_related("contato", "responsavel", "conversa"), pk=pk)
    if request.method == "POST":
        form = TicketForm(request.POST)
        if form.is_valid():
            dados = form.cleaned_data
            if dados["responsavel"] != ticket.responsavel:
                ticket.responsavel = dados["responsavel"]
                ticket.save(update_fields=["responsavel", "atualizado_em"])
            novo_status = dados["status"] if dados["status"] != ticket.status else None
            resposta = dados["resposta"] if dados["resposta"] != ticket.resposta else None
            services.atualizar_ticket(
                ticket, request.user, status=novo_status, resposta=resposta, avisar_cliente=dados["avisar_cliente"],
            )
            aviso = "Ticket atualizado."
            if dados["avisar_cliente"] and novo_status in (Ticket.Status.RESOLVIDO, Ticket.Status.EM_ANDAMENTO):
                aviso += " O cliente foi avisado."
            messages.success(request, aviso)
            return redirect("painel:ticket_detalhe", pk=ticket.pk)
    else:
        form = TicketForm(initial={
            "status": ticket.status, "responsavel": ticket.responsavel, "resposta": ticket.resposta, "avisar_cliente": True,
        })
    return render(request, "painel/ticket_detalhe.html", {"menu": "tickets", "ticket": ticket, "form": form})


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@login_required
def dashboard(request):
    """Todos veem os números; a tabela por funcionário é só do supervisor."""
    try:
        dias = int(request.GET.get("dias", 30))
    except ValueError:
        dias = 30
    if dias not in (7, 30, 90, 365):
        dias = 30
    dados = metricas.calcular(dias=dias, incluir_funcionarios=request.user.is_supervisor)
    return render(request, "painel/dashboard.html", {
        "menu": "dashboard",
        "dados": dados,
        "graficos": dados["graficos"],
        "opcoes_dias": [(7, "7 dias"), (30, "30 dias"), (90, "90 dias"), (365, "1 ano")],
    })


# ---------------------------------------------------------------------------
# FAQ (todos veem; supervisor edita)
# ---------------------------------------------------------------------------
@login_required
def faq(request):
    categorias = CategoriaFAQ.objects.annotate(total=Count("perguntas")).order_by("ordem", "nome")
    perguntas = PerguntaFAQ.objects.select_related("categoria")
    cat = request.GET.get("categoria", "")
    busca = request.GET.get("q", "").strip()
    situacao = request.GET.get("situacao", "")
    if cat.isdigit():
        perguntas = perguntas.filter(categoria_id=int(cat))
    if busca:
        perguntas = perguntas.filter(
            Q(pergunta__icontains=busca) | Q(resposta__icontains=busca) | Q(palavras_chave__icontains=busca)
        )
    if situacao == "ativas":
        perguntas = perguntas.filter(ativa=True)
    elif situacao == "inativas":
        perguntas = perguntas.filter(ativa=False)
    return render(request, "painel/faq.html", {
        "menu": "faq", "categorias": categorias, "perguntas": perguntas,
        "filtros": {"categoria": cat, "q": busca, "situacao": situacao},
    })


def _form_pagina(request, form, titulo, voltar, menu, excluir_url=None):
    return render(request, "painel/form.html", {
        "form": form, "titulo": titulo, "voltar": voltar, "menu": menu, "excluir_url": excluir_url,
    })


@supervisor_required
def faq_pergunta(request, pk=None):
    pergunta = get_object_or_404(PerguntaFAQ, pk=pk) if pk else None
    form = PerguntaFAQForm(request.POST or None, instance=pergunta)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Pergunta salva.")
        return redirect("painel:faq")
    return _form_pagina(
        request, form, "Editar pergunta" if pergunta else "Nova pergunta", reverse("painel:faq"), "faq",
        reverse("painel:faq_pergunta_excluir", args=[pk]) if pergunta else None,
    )


@supervisor_required
@require_POST
def faq_pergunta_alternar(request, pk):
    pergunta = get_object_or_404(PerguntaFAQ, pk=pk)
    pergunta.ativa = not pergunta.ativa
    pergunta.save(update_fields=["ativa", "atualizada_em"])
    messages.success(request, f"Pergunta {'ativada' if pergunta.ativa else 'desativada'}.")
    voltar = request.POST.get("voltar", "")
    return redirect(voltar if voltar.startswith("/painel/") else "painel:faq")


@supervisor_required
@require_POST
def faq_pergunta_excluir(request, pk):
    get_object_or_404(PerguntaFAQ, pk=pk).delete()
    messages.success(request, "Pergunta excluída.")
    return redirect("painel:faq")


@supervisor_required
def faq_categoria(request, pk=None):
    categoria = get_object_or_404(CategoriaFAQ, pk=pk) if pk else None
    form = CategoriaFAQForm(request.POST or None, instance=categoria)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Categoria salva.")
        return redirect("painel:faq")
    return _form_pagina(
        request, form, "Editar categoria" if categoria else "Nova categoria", reverse("painel:faq"), "faq",
        reverse("painel:faq_categoria_excluir", args=[pk]) if categoria else None,
    )


@supervisor_required
@require_POST
def faq_categoria_excluir(request, pk):
    categoria = get_object_or_404(CategoriaFAQ, pk=pk)
    try:
        categoria.delete()
        messages.success(request, "Categoria excluída.")
    except ProtectedError:
        messages.error(request, "Essa categoria ainda tem perguntas. Mova ou exclua as perguntas antes.")
    return redirect("painel:faq")


# ---------------------------------------------------------------------------
# Funcionários (só supervisor)
# ---------------------------------------------------------------------------
@supervisor_required
def funcionarios(request):
    lista = Usuario.objects.annotate(
        abertas=Count("conversas", filter=Q(conversas__status=Conversa.Status.HUMANO)),
        total=Count("conversas"),
    ).order_by("-is_active", "cargo", "username")
    return render(request, "painel/funcionarios.html", {"menu": "funcionarios", "lista": lista})


@supervisor_required
def funcionario_form(request, pk=None):
    usuario = get_object_or_404(Usuario, pk=pk) if pk else None
    form = FuncionarioForm(request.POST or None, instance=usuario)
    if request.method == "POST" and form.is_valid():
        if usuario and usuario.pk == request.user.pk and form.cleaned_data["cargo"] != Usuario.Cargo.SUPERVISOR \
                and not request.user.is_superuser:
            form.add_error("cargo", "Você não pode tirar o seu próprio cargo de supervisor.")
        else:
            salvo = form.save()
            messages.success(request, f"Funcionário {salvo.username} salvo.")
            return redirect("painel:funcionarios")
    return _form_pagina(
        request, form, f"Editar {usuario.username}" if usuario else "Novo funcionário",
        reverse("painel:funcionarios"), "funcionarios",
    )


@supervisor_required
def funcionario_senha(request, pk):
    usuario = get_object_or_404(Usuario, pk=pk)
    form = RedefinirSenhaForm(usuario, request.POST or None)
    if request.method == "POST" and form.is_valid():
        usuario.set_password(form.cleaned_data["senha"])
        usuario.save(update_fields=["password"])
        if usuario.pk == request.user.pk:
            from django.contrib.auth import update_session_auth_hash
            update_session_auth_hash(request, usuario)
        messages.success(request, f"Senha de {usuario.username} redefinida.")
        return redirect("painel:funcionarios")
    return _form_pagina(request, form, f"Redefinir senha de {usuario.username}", reverse("painel:funcionarios"), "funcionarios")


@supervisor_required
@require_POST
def funcionario_alternar(request, pk):
    usuario = get_object_or_404(Usuario, pk=pk)
    if usuario.pk == request.user.pk:
        messages.error(request, "Você não pode desativar a si mesmo.")
        return redirect("painel:funcionarios")
    usuario.is_active = not usuario.is_active
    campos = ["is_active"]
    if not usuario.is_active:
        usuario.online = False
        campos.append("online")
    usuario.save(update_fields=campos)
    aviso = f"{usuario.username} {'ativado' if usuario.is_active else 'desativado'}."
    if not usuario.is_active:
        abertas = Conversa.objects.filter(atendente=usuario, status=Conversa.Status.HUMANO).count()
        if abertas:
            aviso += f" Atenção: ele ainda tem {abertas} conversa(s) em atendimento — transfira-as."
    messages.success(request, aviso)
    return redirect("painel:funcionarios")
