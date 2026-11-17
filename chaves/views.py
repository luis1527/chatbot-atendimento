"""Páginas do controle de chaves (dentro do painel, mesmo login dos funcionários)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import services
from .forms import ChaveForm, EmprestimoForm, SalaForm, UsuarioForm
from .models import Chave, Emprestimo, Movimentacao, Sala, Usuario


def _ctx(**extra):
    return {"menu": "chaves", **extra}


def _voltar(request, padrao="chaves:inicio"):
    """Volta para a página de origem (só URLs do próprio site)."""
    destino = request.POST.get("proximo", "")
    if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
        return redirect(destino)
    return redirect(padrao)


def _pagina(request, qs, por_pagina=25):
    return Paginator(qs, por_pagina).get_page(request.GET.get("pagina"))


def _parametros(request):
    q = request.GET.copy()
    q.pop("pagina", None)
    return q.urlencode()


# ---------------------------------------------------------------------------
# Visão geral (chaves)
# ---------------------------------------------------------------------------
@login_required
def inicio(request):
    agora = timezone.now()
    abertos = Emprestimo.objects.filter(devolvido_em__isnull=True)
    contagem = dict(Chave.objects.values_list("status").annotate(n=Count("id")))
    kpis = {
        "total": sum(contagem.values()),
        "disponiveis": contagem.get(Chave.Status.DISPONIVEL, 0),
        "emprestadas": contagem.get(Chave.Status.EMPRESTADA, 0),
        "atrasadas": abertos.filter(devolucao_prevista__lt=agora).count(),
        "indisponiveis": contagem.get(Chave.Status.MANUTENCAO, 0) + contagem.get(Chave.Status.PERDIDA, 0),
        "salas": Sala.objects.filter(ativa=True).count(),
        "usuarios": Usuario.objects.filter(ativo=True).count(),
        "hoje": Emprestimo.objects.filter(retirada_em__date=timezone.localdate()).count(),
    }

    status = request.GET.get("status", "")
    busca = request.GET.get("q", "").strip()
    chaves = (
        Chave.objects.select_related("sala")
        .prefetch_related(Prefetch(
            "emprestimos", queryset=abertos.select_related("usuario"), to_attr="em_aberto",
        ))
    )
    if status in Chave.Status.values:
        chaves = chaves.filter(status=status)
    if busca:
        chaves = chaves.filter(
            Q(codigo__icontains=busca) | Q(sala__nome__icontains=busca) | Q(sala__codigo__icontains=busca)
            | Q(emprestimos__devolvido_em__isnull=True, emprestimos__usuario__nome__icontains=busca)
        ).distinct()
    pagina = _pagina(request, chaves.order_by("sala__codigo", "codigo"), 30)
    for c in pagina:
        c.aberto = c.em_aberto[0] if c.em_aberto else None

    return render(request, "painel/chaves/inicio.html", _ctx(
        kpis=kpis, pagina=pagina, filtros={"status": status, "q": busca},
        status_choices=Chave.Status.choices, parametros=_parametros(request),
        ultimas=Movimentacao.objects.select_related("chave", "usuario", "operador")[:8],
    ))


# ---------------------------------------------------------------------------
# Empréstimos
# ---------------------------------------------------------------------------
@login_required
def emprestimos(request):
    agora = timezone.now()
    situacao = request.GET.get("situacao", "abertos")
    busca = request.GET.get("q", "").strip()
    qs = Emprestimo.objects.select_related("chave__sala", "usuario", "registrado_por", "recebido_por")
    if situacao == "abertos":
        qs = qs.filter(devolvido_em__isnull=True)
    elif situacao == "atrasados":
        qs = qs.filter(devolvido_em__isnull=True, devolucao_prevista__lt=agora)
    elif situacao == "devolvidos":
        qs = qs.filter(devolvido_em__isnull=False)
    else:
        situacao = "todos"
    if busca:
        qs = qs.filter(
            Q(chave__codigo__icontains=busca) | Q(chave__sala__nome__icontains=busca)
            | Q(usuario__nome__icontains=busca) | Q(usuario__matricula__icontains=busca)
        )
    contagem = {
        "abertos": Emprestimo.objects.filter(devolvido_em__isnull=True).count(),
        "atrasados": Emprestimo.objects.filter(devolvido_em__isnull=True, devolucao_prevista__lt=agora).count(),
        "devolvidos": Emprestimo.objects.filter(devolvido_em__isnull=False).count(),
        "todos": Emprestimo.objects.count(),
    }
    return render(request, "painel/chaves/emprestimos.html", _ctx(
        pagina=_pagina(request, qs), filtros={"situacao": situacao, "q": busca},
        contagem=contagem, parametros=_parametros(request),
    ))


@login_required
def emprestimo_novo(request):
    form = EmprestimoForm(request.POST or None, initial={"chave": request.GET.get("chave")})
    if request.method == "POST" and form.is_valid():
        try:
            e = services.emprestar(
                chave=form.cleaned_data["chave"], usuario=form.cleaned_data["usuario"], operador=request.user,
                devolucao_prevista=form.cleaned_data["devolucao_prevista"],
                observacao=form.cleaned_data["observacao"],
            )
        except services.ErroChave as erro:
            form.add_error(None, str(erro))
        else:
            messages.success(request, f"Chave {e.chave.codigo} emprestada para {e.usuario.nome}.")
            return redirect("chaves:inicio")
    return render(request, "painel/form.html", _ctx(
        form=form, titulo="Registrar empréstimo", voltar=reverse("chaves:inicio"),
    ))


@login_required
@require_POST
def emprestimo_devolver(request, pk):
    emprestimo = get_object_or_404(Emprestimo.objects.select_related("chave", "usuario"), pk=pk)
    try:
        services.devolver(emprestimo=emprestimo, operador=request.user,
                          observacao=request.POST.get("observacao", "").strip()[:200])
    except services.ErroChave as erro:
        messages.error(request, str(erro))
    else:
        messages.success(request, f"Devolução da chave {emprestimo.chave.codigo} registrada.")
    return _voltar(request)


# ---------------------------------------------------------------------------
# Chaves (cadastro e situação)
# ---------------------------------------------------------------------------
@login_required
def chave_form(request, pk=None):
    chave = get_object_or_404(Chave, pk=pk) if pk else None
    form = ChaveForm(request.POST or None, instance=chave, initial={"sala": request.GET.get("sala")})
    if request.method == "POST" and form.is_valid():
        if chave:
            form.save()
            messages.success(request, f"Chave {chave.codigo} atualizada.")
        else:
            nova = services.cadastrar_chave(operador=request.user, **form.cleaned_data)
            messages.success(request, f"Chave {nova.codigo} cadastrada.")
        return redirect("chaves:inicio")
    return render(request, "painel/form.html", _ctx(
        form=form, titulo=f"Editar chave {chave.codigo}" if chave else "Nova chave", voltar=reverse("chaves:inicio"),
    ))


@login_required
@require_POST
def chave_situacao(request, pk, tipo):
    chave = get_object_or_404(Chave, pk=pk)
    try:
        services.alterar_situacao(chave=chave, tipo=tipo, operador=request.user,
                                  observacao=request.POST.get("observacao", "").strip()[:200])
    except services.ErroChave as erro:
        messages.error(request, str(erro))
    else:
        messages.success(request, f"Chave {chave.codigo}: {Movimentacao.Tipo(tipo).label.lower()}.")
    return _voltar(request)


@login_required
def chave_detalhe(request, pk):
    chave = get_object_or_404(Chave.objects.select_related("sala"), pk=pk)
    return render(request, "painel/chaves/chave_detalhe.html", _ctx(
        chave=chave,
        aberto=chave.emprestimos.filter(devolvido_em__isnull=True).select_related("usuario").first(),
        movimentacoes=chave.movimentacoes.select_related("usuario", "operador", "emprestimo")[:100],
    ))


# ---------------------------------------------------------------------------
# Salas
# ---------------------------------------------------------------------------
@login_required
def salas(request):
    lista = Sala.objects.annotate(
        n_chaves=Count("chaves", distinct=True),
        n_disponiveis=Count("chaves", filter=Q(chaves__status=Chave.Status.DISPONIVEL), distinct=True),
    ).order_by("codigo")
    return render(request, "painel/chaves/salas.html", _ctx(lista=lista))


@login_required
def sala_form(request, pk=None):
    sala = get_object_or_404(Sala, pk=pk) if pk else None
    form = SalaForm(request.POST or None, instance=sala)
    if request.method == "POST" and form.is_valid():
        s = form.save()
        messages.success(request, f"Sala {s.codigo} salva.")
        return redirect("chaves:salas")
    return render(request, "painel/form.html", _ctx(
        form=form, titulo=f"Editar sala {sala.codigo}" if sala else "Nova sala", voltar=reverse("chaves:salas"),
    ))


# ---------------------------------------------------------------------------
# Usuários (quem retira chaves)
# ---------------------------------------------------------------------------
@login_required
def usuarios(request):
    busca = request.GET.get("q", "").strip()
    lista = Usuario.objects.annotate(
        n_emprestimos=Count("emprestimos", distinct=True),
        n_abertos=Count("emprestimos", filter=Q(emprestimos__devolvido_em__isnull=True), distinct=True),
    ).order_by("-ativo", "nome")
    if busca:
        lista = lista.filter(Q(nome__icontains=busca) | Q(matricula__icontains=busca) | Q(email__icontains=busca))
    return render(request, "painel/chaves/usuarios.html", _ctx(
        pagina=_pagina(request, lista), filtros={"q": busca}, parametros=_parametros(request),
    ))


@login_required
def usuario_form(request, pk=None):
    usuario = get_object_or_404(Usuario, pk=pk) if pk else None
    form = UsuarioForm(request.POST or None, instance=usuario)
    if request.method == "POST" and form.is_valid():
        u = form.save()
        messages.success(request, f"Usuário {u.nome} salvo.")
        return redirect("chaves:usuarios")
    return render(request, "painel/form.html", _ctx(
        form=form, titulo=f"Editar {usuario.nome}" if usuario else "Novo usuário", voltar=reverse("chaves:usuarios"),
    ))


# ---------------------------------------------------------------------------
# Movimentações (histórico)
# ---------------------------------------------------------------------------
@login_required
def movimentacoes(request):
    tipo = request.GET.get("tipo", "")
    busca = request.GET.get("q", "").strip()
    qs = Movimentacao.objects.select_related("chave__sala", "usuario", "operador")
    if tipo in Movimentacao.Tipo.values:
        qs = qs.filter(tipo=tipo)
    if busca:
        qs = qs.filter(Q(chave__codigo__icontains=busca) | Q(usuario__nome__icontains=busca)
                       | Q(chave__sala__nome__icontains=busca))
    return render(request, "painel/chaves/movimentacoes.html", _ctx(
        pagina=_pagina(request, qs, 40), filtros={"tipo": tipo, "q": busca},
        tipo_choices=Movimentacao.Tipo.choices, parametros=_parametros(request),
    ))
