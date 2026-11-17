"""Dados de exemplo do controle de chaves (nomes genéricos de teste).

    python manage.py popular_chaves            # cria só o que ainda não existe
    python manage.py popular_chaves --historico  # também gera empréstimos dos últimos 30 dias
"""
import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from chaves.models import Chave, Emprestimo, Movimentacao, Sala, Usuario

SALAS = [
    ("A-101", "Sala de aula 101", "A", 1, "aula", 40),
    ("A-102", "Sala de aula 102", "A", 1, "aula", 40),
    ("A-201", "Sala de aula 201", "A", 2, "aula", 35),
    ("B-204", "Laboratório de Informática 1", "B", 2, "laboratorio", 30),
    ("B-205", "Laboratório de Informática 2", "B", 2, "laboratorio", 30),
    ("B-301", "Laboratório de Redes", "B", 3, "laboratorio", 24),
    ("C-001", "Auditório", "C", 0, "auditorio", 150),
    ("C-110", "Secretaria", "C", 1, "administrativa", None),
]
USUARIOS = [
    ("Aluno Teste 1", "2026001", "aluno"), ("Aluno Teste 2", "2026002", "aluno"),
    ("Aluno Teste 3", "2026003", "aluno"), ("Professor Teste 1", "P1001", "professor"),
    ("Professor Teste 2", "P1002", "professor"), ("Servidor Teste 1", "S5001", "servidor"),
    ("Visitante Teste 1", "V9001", "visitante"),
]


class Command(BaseCommand):
    help = "Cria salas, chaves e usuários de teste do controle de chaves."

    def add_arguments(self, parser):
        parser.add_argument("--historico", action="store_true", help="Gera empréstimos de exemplo (passados e em aberto).")

    @transaction.atomic
    def handle(self, *args, historico=False, **opts):
        operador = get_user_model().objects.filter(is_active=True).order_by("-is_superuser", "pk").first()
        if not operador:
            self.stderr.write("Crie um funcionário antes (python manage.py popular_demo).")
            return
        for cod, nome, bloco, andar, tipo, cap in SALAS:
            sala, _ = Sala.objects.get_or_create(codigo=cod, defaults=dict(
                nome=nome, bloco=bloco, andar=andar, tipo=tipo, capacidade=cap))
            copias = 2 if tipo == "laboratorio" else 1
            for n in range(1, copias + 1):
                codigo = f"{cod}-{n:02d}"
                if not Chave.objects.filter(codigo=codigo).exists():
                    chave = Chave.objects.create(sala=sala, codigo=codigo,
                                                 descricao="cópia reserva" if n > 1 else "chave principal")
                    Movimentacao.objects.create(chave=chave, operador=operador, tipo=Movimentacao.Tipo.CADASTRO)
        for nome, mat, tipo in USUARIOS:
            Usuario.objects.get_or_create(matricula=mat, defaults=dict(
                nome=nome, tipo=tipo, email=f"{mat.lower()}@exemplo.com"))
        self.stdout.write(f"Salas: {Sala.objects.count()} · chaves: {Chave.objects.count()} · usuários: {Usuario.objects.count()}")

        if historico and not Emprestimo.objects.exists():
            self._historico(operador)
        self.stdout.write(f"Empréstimos: {Emprestimo.objects.count()} · movimentações: {Movimentacao.objects.count()}")

    def _historico(self, operador):
        rnd = random.Random(42)
        agora = timezone.now()
        chaves = list(Chave.objects.all())
        usuarios = list(Usuario.objects.all())
        # Devolvidos nos últimos 30 dias.
        for _ in range(40):
            chave, usuario = rnd.choice(chaves), rnd.choice(usuarios)
            retirada = agora - timedelta(days=rnd.randint(1, 30), hours=rnd.randint(0, 8))
            prevista = retirada + timedelta(hours=rnd.choice([2, 4, 4, 8]))
            devolvido = prevista + timedelta(minutes=rnd.randint(-90, 60))
            devolvido = max(devolvido, retirada + timedelta(minutes=20))
            e = Emprestimo.objects.create(chave=chave, usuario=usuario, registrado_por=operador,
                                          retirada_em=retirada, devolucao_prevista=prevista,
                                          devolvido_em=devolvido, recebido_por=operador)
            Movimentacao.objects.create(chave=chave, emprestimo=e, usuario=usuario, operador=operador,
                                        tipo="retirada", data_hora=retirada)
            Movimentacao.objects.create(chave=chave, emprestimo=e, usuario=usuario, operador=operador,
                                        tipo="devolucao", data_hora=devolvido,
                                        observacao="(com atraso)" if devolvido > prevista else "")
        # Em aberto agora: 3 no prazo e 1 atrasado.
        livres = [c for c in chaves if c.status == Chave.Status.DISPONIVEL]
        for i, (horas_atras, horas_prazo) in enumerate([(1, 3), (2, 4), (0.5, 2), (6, 4)]):
            chave, usuario = livres[i * 2], usuarios[i]
            retirada = agora - timedelta(hours=horas_atras)
            e = Emprestimo.objects.create(chave=chave, usuario=usuario, registrado_por=operador,
                                          retirada_em=retirada, devolucao_prevista=retirada + timedelta(hours=horas_prazo))
            chave.status = Chave.Status.EMPRESTADA
            chave.save(update_fields=["status"])
            Movimentacao.objects.create(chave=chave, emprestimo=e, usuario=usuario, operador=operador,
                                        tipo="retirada", data_hora=retirada)
        # Uma chave em manutenção.
        c = livres[-1]
        c.status = Chave.Status.MANUTENCAO
        c.save(update_fields=["status"])
        Movimentacao.objects.create(chave=c, operador=operador, tipo="manutencao", observacao="fechadura emperrando")
