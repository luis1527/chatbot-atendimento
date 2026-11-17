"""Regras do controle de chaves. Toda mudança de estado passa por aqui e gera Movimentacao."""
from django.db import transaction
from django.utils import timezone

from .models import Chave, Emprestimo, Movimentacao, Usuario


class ErroChave(Exception):
    """Operação não permitida (mensagem pronta para mostrar ao funcionário)."""


@transaction.atomic
def emprestar(*, chave: Chave, usuario: Usuario, operador, devolucao_prevista, observacao: str = "") -> Emprestimo:
    # Trava a linha da chave: dois funcionários não emprestam a mesma chave ao mesmo tempo.
    chave = Chave.objects.select_for_update().select_related("sala").get(pk=chave.pk)
    if chave.status != Chave.Status.DISPONIVEL:
        raise ErroChave(f"A chave {chave.codigo} não está disponível ({chave.get_status_display().lower()}).")
    if not chave.sala.ativa:
        raise ErroChave(f"A sala {chave.sala.codigo} está desativada.")
    if not usuario.ativo:
        raise ErroChave(f"{usuario.nome} está inativo e não pode retirar chaves.")
    agora = timezone.now()
    if devolucao_prevista <= agora:
        raise ErroChave("A devolução prevista precisa ser depois de agora.")

    emprestimo = Emprestimo.objects.create(
        chave=chave, usuario=usuario, registrado_por=operador,
        retirada_em=agora, devolucao_prevista=devolucao_prevista, observacao=observacao,
    )
    chave.status = Chave.Status.EMPRESTADA
    chave.save(update_fields=["status"])
    Movimentacao.objects.create(
        chave=chave, emprestimo=emprestimo, usuario=usuario, operador=operador,
        tipo=Movimentacao.Tipo.RETIRADA, data_hora=agora, observacao=observacao,
    )
    return emprestimo


@transaction.atomic
def devolver(*, emprestimo: Emprestimo, operador, observacao: str = "") -> Emprestimo:
    emprestimo = Emprestimo.objects.select_for_update().get(pk=emprestimo.pk)
    if emprestimo.devolvido_em is not None:
        raise ErroChave("Esse empréstimo já foi devolvido.")
    agora = timezone.now()
    emprestimo.devolvido_em = agora
    emprestimo.recebido_por = operador
    if observacao:
        emprestimo.observacao = (f"{emprestimo.observacao} | {observacao}" if emprestimo.observacao else observacao)[:255]
    emprestimo.save(update_fields=["devolvido_em", "recebido_por", "observacao"])

    chave = Chave.objects.select_for_update().get(pk=emprestimo.chave_id)
    chave.status = Chave.Status.DISPONIVEL
    chave.save(update_fields=["status"])
    atraso = " (com atraso)" if agora > emprestimo.devolucao_prevista else ""
    Movimentacao.objects.create(
        chave=chave, emprestimo=emprestimo, usuario=emprestimo.usuario, operador=operador,
        tipo=Movimentacao.Tipo.DEVOLUCAO, data_hora=agora, observacao=(observacao + atraso).strip(),
    )
    return emprestimo


_STATUS_POR_TIPO = {
    Movimentacao.Tipo.MANUTENCAO: Chave.Status.MANUTENCAO,
    Movimentacao.Tipo.PERDA: Chave.Status.PERDIDA,
    Movimentacao.Tipo.LIBERACAO: Chave.Status.DISPONIVEL,
}


@transaction.atomic
def alterar_situacao(*, chave: Chave, tipo: str, operador, observacao: str = "") -> Chave:
    """Manutenção, perda ou liberação de uma chave que não está emprestada."""
    if tipo not in _STATUS_POR_TIPO:
        raise ErroChave("Operação inválida.")
    chave = Chave.objects.select_for_update().get(pk=chave.pk)
    if chave.status == Chave.Status.EMPRESTADA:
        raise ErroChave(f"A chave {chave.codigo} está emprestada. Registre a devolução primeiro.")
    novo = _STATUS_POR_TIPO[tipo]
    if chave.status == novo:
        raise ErroChave(f"A chave {chave.codigo} já está {chave.get_status_display().lower()}.")
    chave.status = novo
    chave.save(update_fields=["status"])
    Movimentacao.objects.create(chave=chave, operador=operador, tipo=tipo, observacao=observacao)
    return chave


@transaction.atomic
def cadastrar_chave(*, operador, **campos) -> Chave:
    chave = Chave.objects.create(**campos)
    Movimentacao.objects.create(chave=chave, operador=operador, tipo=Movimentacao.Tipo.CADASTRO)
    return chave
