"""Regras de acesso do painel (quem pode fazer o quê)."""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect

from core.models import Conversa


def supervisor_required(view):
    """Só supervisor (ou superusuário) entra. Atendente volta para a fila com aviso."""

    @login_required
    @wraps(view)
    def _view(request, *args, **kwargs):
        if not request.user.is_supervisor:
            if request.headers.get("x-requested-with") == "fetch" or request.path.startswith("/painel/api/"):
                return JsonResponse({"ok": False, "erro": "Apenas supervisores podem fazer isso."}, status=403)
            messages.error(request, "Apenas supervisores podem acessar essa página.")
            return redirect("painel:fila")
        return view(request, *args, **kwargs)

    return _view


def pode_responder(usuario, conversa: Conversa) -> bool:
    """Só quem está com a conversa responde."""
    return conversa.status == Conversa.Status.HUMANO and conversa.atendente_id == usuario.pk


def pode_assumir(usuario, conversa: Conversa) -> bool:
    return conversa.status in (Conversa.Status.FILA, Conversa.Status.BOT)


def pode_gerenciar(usuario, conversa: Conversa) -> bool:
    """Transferir / devolver ao bot / encerrar."""
    if conversa.status == Conversa.Status.ENCERRADA:
        return False
    if usuario.is_supervisor:
        return True
    if conversa.status == Conversa.Status.HUMANO:
        return conversa.atendente_id == usuario.pk
    # Na fila ou com o bot: qualquer funcionário pode encerrar/devolver.
    return True


def pode_transferir(usuario, conversa: Conversa) -> bool:
    return conversa.status == Conversa.Status.HUMANO and (
        conversa.atendente_id == usuario.pk or usuario.is_supervisor
    )
