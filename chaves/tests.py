from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Usuario as Funcionario

from . import services
from .models import Chave, Emprestimo, Movimentacao, Sala, Usuario


class Base(TestCase):
    def setUp(self):
        self.op = Funcionario.objects.create_user("op", password="senha-forte-123", cargo="supervisor")
        self.sala = Sala.objects.create(codigo="B-204", nome="Lab 1", tipo="laboratorio")
        self.chave = Chave.objects.create(sala=self.sala, codigo="B-204-01")
        self.user = Usuario.objects.create(nome="Aluno Teste", matricula="2026001")
        self.prazo = timezone.now() + timedelta(hours=2)


class RegrasTests(Base):
    def test_emprestar_e_devolver_gera_movimentacoes(self):
        e = services.emprestar(chave=self.chave, usuario=self.user, operador=self.op, devolucao_prevista=self.prazo)
        self.chave.refresh_from_db()
        self.assertEqual(self.chave.status, Chave.Status.EMPRESTADA)
        services.devolver(emprestimo=e, operador=self.op)
        self.chave.refresh_from_db()
        e.refresh_from_db()
        self.assertEqual(self.chave.status, Chave.Status.DISPONIVEL)
        self.assertEqual(e.recebido_por, self.op)
        self.assertEqual(list(Movimentacao.objects.order_by("id").values_list("tipo", flat=True)),
                         ["retirada", "devolucao"])

    def test_nao_empresta_chave_ja_emprestada(self):
        services.emprestar(chave=self.chave, usuario=self.user, operador=self.op, devolucao_prevista=self.prazo)
        with self.assertRaises(services.ErroChave):
            services.emprestar(chave=self.chave, usuario=self.user, operador=self.op, devolucao_prevista=self.prazo)

    def test_nao_empresta_para_usuario_inativo_nem_chave_em_manutencao(self):
        self.user.ativo = False
        self.user.save()
        with self.assertRaises(services.ErroChave):
            services.emprestar(chave=self.chave, usuario=self.user, operador=self.op, devolucao_prevista=self.prazo)
        self.user.ativo = True
        self.user.save()
        services.alterar_situacao(chave=self.chave, tipo="manutencao", operador=self.op)
        with self.assertRaises(services.ErroChave):
            services.emprestar(chave=self.chave, usuario=self.user, operador=self.op, devolucao_prevista=self.prazo)

    def test_prazo_no_passado_e_devolucao_dupla(self):
        with self.assertRaises(services.ErroChave):
            services.emprestar(chave=self.chave, usuario=self.user, operador=self.op,
                               devolucao_prevista=timezone.now() - timedelta(minutes=1))
        e = services.emprestar(chave=self.chave, usuario=self.user, operador=self.op, devolucao_prevista=self.prazo)
        services.devolver(emprestimo=e, operador=self.op)
        with self.assertRaises(services.ErroChave):
            services.devolver(emprestimo=e, operador=self.op)

    def test_nao_muda_situacao_de_chave_emprestada(self):
        services.emprestar(chave=self.chave, usuario=self.user, operador=self.op, devolucao_prevista=self.prazo)
        with self.assertRaises(services.ErroChave):
            services.alterar_situacao(chave=self.chave, tipo="perda", operador=self.op)

    def test_atrasado(self):
        agora = timezone.now()
        e = Emprestimo(chave=self.chave, usuario=self.user, registrado_por=self.op,
                       retirada_em=agora - timedelta(hours=3), devolucao_prevista=agora - timedelta(hours=1))
        self.assertTrue(e.atrasado)
        self.assertEqual(e.situacao, "Atrasado")


class ConstraintsTests(Base):
    """Regras que o BANCO garante, mesmo se alguém pular o código."""

    def _emp(self, **kw):
        agora = timezone.now()
        dados = dict(chave=self.chave, usuario=self.user, registrado_por=self.op,
                     retirada_em=agora, devolucao_prevista=agora + timedelta(hours=1))
        dados.update(kw)
        return Emprestimo.objects.create(**dados)

    def test_um_emprestimo_aberto_por_chave(self):
        self._emp()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._emp()

    def test_prevista_antes_da_retirada(self):
        agora = timezone.now()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._emp(retirada_em=agora, devolucao_prevista=agora - timedelta(hours=1))

    def test_devolucao_sem_quem_recebeu(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._emp(devolvido_em=timezone.now() + timedelta(minutes=5))

    def test_matricula_e_codigos_unicos(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Usuario.objects.create(nome="Outro", matricula="2026001")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Chave.objects.create(sala=self.sala, codigo="B-204-01")

    def test_retirada_exige_emprestimo(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Movimentacao.objects.create(chave=self.chave, operador=self.op, tipo="retirada")

    def test_nao_apaga_sala_com_chave(self):
        from django.db.models.deletion import ProtectedError
        with self.assertRaises(ProtectedError):
            self.sala.delete()


class PaginasTests(Base):
    def setUp(self):
        super().setUp()
        self.client.login(username="op", password="senha-forte-123")

    def test_exige_login(self):
        self.client.logout()
        r = self.client.get(reverse("chaves:inicio"))
        self.assertEqual(r.status_code, 302)

    def test_todas_as_paginas_abrem(self):
        e = services.emprestar(chave=self.chave, usuario=self.user, operador=self.op, devolucao_prevista=self.prazo)
        for nome, args in [("inicio", []), ("emprestimos", []), ("emprestimo_novo", []), ("salas", []),
                           ("sala_nova", []), ("sala_editar", [self.sala.pk]), ("usuarios", []),
                           ("usuario_novo", []), ("usuario_editar", [self.user.pk]), ("movimentacoes", []),
                           ("chave", [self.chave.pk]), ("chave_nova", []), ("chave_editar", [self.chave.pk])]:
            r = self.client.get(reverse(f"chaves:{nome}", args=args))
            self.assertEqual(r.status_code, 200, nome)
        for q in ["?situacao=atrasados", "?situacao=devolvidos", "?situacao=todos&q=aluno"]:
            self.assertEqual(self.client.get(reverse("chaves:emprestimos") + q).status_code, 200)
        self.assertContains(self.client.get(reverse("chaves:inicio") + "?q=Aluno"), "B-204-01")
        self.assertContains(self.client.get(reverse("painel:fila")), "Controle de chaves")
        self.assertIsNotNone(e)

    def test_fluxo_pelo_site(self):
        prazo = timezone.localtime(self.prazo).strftime("%Y-%m-%dT%H:%M")
        r = self.client.post(reverse("chaves:emprestimo_novo"),
                             {"chave": self.chave.pk, "usuario": self.user.pk, "devolucao_prevista": prazo})
        self.assertRedirects(r, reverse("chaves:inicio"))
        e = Emprestimo.objects.get()
        r = self.client.post(reverse("chaves:emprestimo_devolver", args=[e.pk]), {"proximo": "https://malicioso.com/"})
        self.assertRedirects(r, reverse("chaves:inicio"))
        e.refresh_from_db()
        self.assertIsNotNone(e.devolvido_em)
        r = self.client.post(reverse("chaves:chave_situacao", args=[self.chave.pk, "perda"]))
        self.chave.refresh_from_db()
        self.assertEqual(self.chave.status, Chave.Status.PERDIDA)

    def test_cadastros_pelo_site(self):
        self.client.post(reverse("chaves:sala_nova"), {"codigo": "A-101", "nome": "Sala 101", "tipo": "aula", "ativa": "on"})
        sala = Sala.objects.get(codigo="A-101")
        self.client.post(reverse("chaves:chave_nova"), {"sala": sala.pk, "codigo": "A-101-01"})
        self.assertTrue(Movimentacao.objects.filter(chave__codigo="A-101-01", tipo="cadastro").exists())
        self.client.post(reverse("chaves:usuario_novo"), {"nome": "Prof", "matricula": "P1", "tipo": "professor", "ativo": "on"})
        self.assertTrue(Usuario.objects.filter(matricula="P1").exists())

    def test_popular_chaves(self):
        from django.core.management import call_command
        call_command("popular_chaves", "--historico", stdout=open("/dev/null", "w"))
        self.assertGreater(Emprestimo.objects.filter(devolvido_em__isnull=True).count(), 0)
        self.assertTrue(Chave.objects.filter(status="manutencao").exists())
        for nome in ["inicio", "emprestimos", "movimentacoes", "salas", "usuarios"]:
            self.assertEqual(self.client.get(reverse(f"chaves:{nome}")).status_code, 200)
