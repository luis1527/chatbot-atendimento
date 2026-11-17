"""
Testes do painel.

    DATABASE_URL= .venv/bin/python manage.py test painel
"""
import json
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core import services
from core.models import (
    CategoriaFAQ, Conversa, Intencao, Mensagem, PerguntaFAQ, Ticket, Usuario,
)


class BasePainel(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.sup = Usuario.objects.create_user("supervisor", password="teste123", cargo=Usuario.Cargo.SUPERVISOR, apelido="Sup")
        cls.at1 = Usuario.objects.create_user("atendente1", password="teste123", apelido="Ana")
        cls.at2 = Usuario.objects.create_user("atendente2", password="teste123", apelido="Bruno")

    def nova_conversa_na_fila(self, sessao="s1", nome="Cliente Web"):
        contato = services.contato_web(sessao, nome)
        conversa = services.conversa_aberta(contato)
        services.registrar_mensagem(conversa, Mensagem.Remetente.CLIENTE, "Quero falar com atendente")
        return services.escalar(conversa)

    def entrar(self, usuario):
        self.client.force_login(usuario)

    def post_json(self, url, dados=None):
        return self.client.post(url, data=json.dumps(dados or {}), content_type="application/json")


class LoginTests(BasePainel):
    def test_paginas_exigem_login(self):
        for nome in ["painel:fila", "painel:tickets", "painel:dashboard", "painel:faq", "painel:funcionarios",
                     "painel:api_status", "painel:api_conversas"]:
            r = self.client.get(reverse(nome))
            self.assertEqual(r.status_code, 302, nome)
            self.assertIn(reverse("painel:login"), r["Location"])

    def test_login_mostra_usuarios_de_teste_e_entra(self):
        r = self.client.get(reverse("painel:login"))
        self.assertContains(r, "teste123")
        r = self.client.post(reverse("painel:login"), {"username": "atendente1", "password": "teste123"})
        self.assertRedirects(r, reverse("painel:fila"))
        self.at1.refresh_from_db()
        self.assertTrue(self.at1.online)

    def test_login_errado(self):
        r = self.client.post(reverse("painel:login"), {"username": "atendente1", "password": "x"})
        self.assertContains(r, "incorretos")

    def test_logout_por_post(self):
        self.client.post(reverse("painel:login"), {"username": "atendente1", "password": "teste123"})
        r = self.client.post(reverse("painel:logout"))
        self.assertEqual(r.status_code, 302)
        self.at1.refresh_from_db()
        self.assertFalse(self.at1.online)

    def test_atendente_nao_entra_em_funcionarios(self):
        self.entrar(self.at1)
        self.assertEqual(self.client.get(reverse("painel:funcionarios")).status_code, 302)
        self.assertEqual(self.client.get(reverse("painel:faq_pergunta_nova")).status_code, 302)


class AtendimentoTests(BasePainel):
    def test_assumir_concorrente_segundo_recebe_erro(self):
        conversa = self.nova_conversa_na_fila()
        url = reverse("painel:api_acao", args=[conversa.pk, "assumir"])

        self.entrar(self.at1)
        r1 = self.post_json(url)
        self.assertEqual(r1.status_code, 200)
        self.assertTrue(r1.json()["ok"])

        self.entrar(self.at2)
        r2 = self.post_json(url)
        self.assertEqual(r2.status_code, 409)
        self.assertIn("Ana", r2.json()["erro"])

        conversa.refresh_from_db()
        self.assertEqual(conversa.status, Conversa.Status.HUMANO)
        self.assertEqual(conversa.atendente, self.at1)

    def test_responder_so_quem_assumiu(self):
        conversa = self.nova_conversa_na_fila()
        url = reverse("painel:api_enviar", args=[conversa.pk])

        self.entrar(self.at1)
        r = self.post_json(url, {"texto": "oi"})
        self.assertEqual(r.status_code, 403)
        self.assertIn("Assuma", r.json()["erro"])

        services.assumir(conversa, self.at1)
        r = self.post_json(url, {"texto": "Olá, sou a Ana!"})
        self.assertEqual(r.status_code, 200)
        msg = r.json()["mensagem"]
        self.assertEqual(msg["remetente"], "atendente")
        self.assertEqual(msg["atendente"], "Ana")
        self.assertTrue(Mensagem.objects.filter(conversa=conversa, atendente=self.at1, texto="Olá, sou a Ana!").exists())

        # Conversa alheia: bloqueado, inclusive para supervisor.
        for outro in (self.at2, self.sup):
            self.entrar(outro)
            r = self.post_json(url, {"texto": "intrometido"})
            self.assertEqual(r.status_code, 403)
        self.assertFalse(Mensagem.objects.filter(texto="intrometido").exists())

    def test_acoes_exigem_post(self):
        conversa = self.nova_conversa_na_fila()
        self.entrar(self.at1)
        self.assertEqual(self.client.get(reverse("painel:api_acao", args=[conversa.pk, "assumir"])).status_code, 405)
        self.assertEqual(self.client.get(reverse("painel:api_enviar", args=[conversa.pk])).status_code, 405)

    def test_csrf_obrigatorio(self):
        from django.test import Client
        conversa = self.nova_conversa_na_fila()
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.at1)
        r = c.post(reverse("painel:api_acao", args=[conversa.pk, "assumir"]), content_type="application/json", data="{}")
        self.assertEqual(r.status_code, 403)

    def test_transferir_devolver_encerrar(self):
        conversa = self.nova_conversa_na_fila()
        services.assumir(conversa, self.at1)

        # Atendente 2 não pode mexer na conversa da Ana.
        self.entrar(self.at2)
        self.assertEqual(self.post_json(reverse("painel:api_acao", args=[conversa.pk, "encerrar"])).status_code, 403)
        self.assertEqual(self.post_json(reverse("painel:api_acao", args=[conversa.pk, "transferir"]), {"para": self.at2.pk}).status_code, 403)

        self.entrar(self.at1)
        r = self.post_json(reverse("painel:api_acao", args=[conversa.pk, "transferir"]), {"para": self.at2.pk})
        self.assertEqual(r.status_code, 200, r.content)
        conversa.refresh_from_db()
        self.assertEqual(conversa.atendente, self.at2)

        self.entrar(self.at2)
        r = self.post_json(reverse("painel:api_acao", args=[conversa.pk, "devolver"]))
        self.assertEqual(r.status_code, 200, r.content)
        conversa.refresh_from_db()
        self.assertEqual(conversa.status, Conversa.Status.BOT)

        r = self.post_json(reverse("painel:api_acao", args=[conversa.pk, "encerrar"]))
        self.assertEqual(r.status_code, 200)
        conversa.refresh_from_db()
        self.assertEqual(conversa.status, Conversa.Status.ENCERRADA)
        self.assertTrue(conversa.mensagens.filter(remetente="sistema", botoes__isnull=False).exists())

    def test_alternar_online(self):
        self.entrar(self.at1)
        r = self.post_json(reverse("painel:api_online"), {"online": True})
        self.assertTrue(r.json()["online"])
        r = self.post_json(reverse("painel:api_online"), {"online": False})
        self.assertFalse(r.json()["online"])
        self.at1.refresh_from_db()
        self.assertFalse(self.at1.online)


class ApiJsonTests(BasePainel):
    def test_lista_por_aba(self):
        c1 = self.nova_conversa_na_fila("a", "Primeiro")
        c2 = self.nova_conversa_na_fila("b", "Segundo")
        Conversa.objects.filter(pk=c1.pk).update(escalada_em=timezone.now() - timedelta(minutes=10))
        self.entrar(self.at1)

        dados = self.client.get(reverse("painel:api_conversas"), {"aba": "fila"}).json()
        self.assertEqual([c["id"] for c in dados["conversas"]], [c1.pk, c2.pk])  # mais antiga primeiro
        self.assertGreaterEqual(dados["conversas"][0]["espera_seg"], 600)
        self.assertEqual(dados["conversas"][1]["nao_lidas"], 0)  # mensagem é de antes de entrar na fila
        self.assertEqual(dados["contagem"]["fila"], 2)

        services.assumir(c2, self.at1)
        services.registrar_mensagem(c2, Mensagem.Remetente.CLIENTE, "Oi Ana")
        meus = self.client.get(reverse("painel:api_conversas"), {"aba": "meus"}).json()
        self.assertEqual([c["id"] for c in meus["conversas"]], [c2.pk])
        self.assertEqual(meus["conversas"][0]["previa"], "Oi Ana")
        self.assertGreaterEqual(meus["conversas"][0]["nao_lidas"], 1)

        todos = self.client.get(reverse("painel:api_conversas"), {"aba": "todos"}).json()
        self.assertEqual({c["id"] for c in todos["conversas"]}, {c1.pk, c2.pk})
        self.assertEqual(self.client.get(reverse("painel:api_conversas"), {"aba": "encerradas"}).json()["conversas"], [])

        status = self.client.get(reverse("painel:api_status")).json()
        self.assertEqual(status["fila"], 1)
        self.assertEqual(status["fila_ids"], [c1.pk])

    def test_detalhe_marca_lida_e_polling_de_mensagens(self):
        conversa = self.nova_conversa_na_fila()
        services.assumir(conversa, self.at1)
        services.registrar_mensagem(conversa, Mensagem.Remetente.CLIENTE, "mensagem nova")
        self.entrar(self.at1)

        r = self.client.get(reverse("painel:api_conversa", args=[conversa.pk])).json()
        self.assertTrue(r["conversa"]["permissoes"]["responder"])
        ultimo = r["mensagens"][-1]["id"]
        meus = self.client.get(reverse("painel:api_conversas"), {"aba": "meus"}).json()
        self.assertEqual(meus["conversas"][0]["nao_lidas"], 0)

        intencao = Intencao.objects.create(slug="duvida", nome="Dúvida")
        services.registrar_mensagem(conversa, Mensagem.Remetente.CLIENTE, "e agora?", intencao=intencao, confianca=0.9)
        r = self.client.get(reverse("painel:api_mensagens", args=[conversa.pk]), {"depois": ultimo}).json()
        self.assertEqual(len(r["mensagens"]), 1)
        self.assertEqual(r["mensagens"][0]["texto"], "e agora?")
        self.assertEqual(r["mensagens"][0]["intencao"], "Dúvida")
        r = self.client.get(reverse("painel:api_mensagens", args=[conversa.pk]), {"depois": r["mensagens"][0]["id"]}).json()
        self.assertEqual(r["mensagens"], [])

        # Para outro atendente, não pode responder.
        self.entrar(self.at2)
        r = self.client.get(reverse("painel:api_conversa", args=[conversa.pk])).json()
        self.assertFalse(r["conversa"]["permissoes"]["responder"])
        self.assertFalse(r["conversa"]["permissoes"]["encerrar"])

    def test_paginas_renderizam(self):
        conversa = self.nova_conversa_na_fila()
        self.entrar(self.at1)
        self.assertContains(self.client.get(reverse("painel:fila")), "config-atendimentos")
        self.assertEqual(self.client.get(reverse("painel:conversa", args=[conversa.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("painel:conversa", args=[9999])).status_code, 404)


class DashboardTests(BasePainel):
    def test_dashboard_com_dados(self):
        cat = CategoriaFAQ.objects.create(nome="Geral")
        faq = PerguntaFAQ.objects.create(categoria=cat, pergunta="Horário?", resposta="8h às 18h", vezes_usada=5)
        intencao = Intencao.objects.create(slug="duvida", nome="Dúvida")
        conversa = self.nova_conversa_na_fila()
        services.registrar_mensagem(conversa, Mensagem.Remetente.CLIENTE, "horário?", intencao=intencao)
        services.registrar_mensagem(conversa, Mensagem.Remetente.BOT, "8h às 18h", origem_resposta="faq", faq=faq)
        services.assumir(conversa, self.at1)
        services.encerrar(conversa, self.at1)
        services.registrar_avaliacao(conversa, 4)
        # Conversa resolvida só pelo bot
        outra = services.conversa_aberta(services.contato_web("s2", "Outro"))
        services.encerrar(outra, pedir_avaliacao=False)

        self.entrar(self.sup)
        r = self.client.get(reverse("painel:dashboard"))
        self.assertEqual(r.status_code, 200)
        cards = r.context["dados"]["cards"]
        self.assertEqual(cards["conversas_hoje"], 2)
        self.assertEqual(cards["pct_bot"], 50)
        self.assertEqual(cards["nota_media"], 4)
        self.assertContains(r, "Desempenho por funcionário")
        graficos = r.context["dados"]["graficos"]
        self.assertEqual(graficos["intencoes"]["labels"], ["Dúvida"])
        self.assertEqual(graficos["faq"]["dados"], [5])
        self.assertEqual(sum(graficos["mensagens_por_dia"]["total"]), conversa.mensagens.count())

        self.entrar(self.at1)
        r = self.client.get(reverse("painel:dashboard"), {"dias": 7})
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Desempenho por funcionário")

    def test_dashboard_vazio(self):
        self.entrar(self.sup)
        self.assertEqual(self.client.get(reverse("painel:dashboard")).status_code, 200)


class TicketTests(BasePainel):
    def test_lista_filtros_e_resolver(self):
        conversa = self.nova_conversa_na_fila()
        t = services.abrir_ticket(conversa.contato, "Boleto não chegou", "Não recebi", conversa=conversa,
                                  categoria=Ticket.Categoria.FINANCEIRO, prioridade=Ticket.Prioridade.ALTA)
        self.entrar(self.at1)
        r = self.client.get(reverse("painel:tickets"), {"q": t.protocolo, "status": "abertos", "prioridade": "alta"})
        self.assertContains(r, "Boleto não chegou")
        r = self.client.get(reverse("painel:tickets"), {"categoria": "suporte"})
        self.assertNotContains(r, "Boleto não chegou")

        r = self.client.post(reverse("painel:ticket_detalhe", args=[t.pk]), {
            "status": "resolvido", "responsavel": "", "resposta": "Reenviamos o boleto.", "avisar_cliente": "on",
        })
        self.assertEqual(r.status_code, 302)
        t.refresh_from_db()
        self.assertEqual(t.status, Ticket.Status.RESOLVIDO)
        self.assertEqual(t.responsavel, self.at1)
        self.assertTrue(conversa.mensagens.filter(texto__contains="Reenviamos o boleto").exists())
        self.assertContains(self.client.get(reverse("painel:ticket_detalhe", args=[t.pk])), t.protocolo)


class SupervisorTests(BasePainel):
    def test_crud_funcionario_e_faq(self):
        self.entrar(self.sup)
        r = self.client.post(reverse("painel:funcionario_novo"), {
            "username": "novo", "first_name": "Novo", "last_name": "", "apelido": "Nina", "email": "",
            "cargo": "atendente", "senha": "SenhaForte!2026",
        })
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        novo = Usuario.objects.get(username="novo")
        self.assertTrue(novo.check_password("SenhaForte!2026"))

        self.client.post(reverse("painel:funcionario_senha", args=[novo.pk]), {"senha": "OutraSenha#99", "confirmar": "OutraSenha#99"})
        novo.refresh_from_db()
        self.assertTrue(novo.check_password("OutraSenha#99"))

        self.client.post(reverse("painel:funcionario_alternar", args=[novo.pk]))
        novo.refresh_from_db()
        self.assertFalse(novo.is_active)
        self.client.post(reverse("painel:funcionario_alternar", args=[self.sup.pk]))
        self.sup.refresh_from_db()
        self.assertTrue(self.sup.is_active)

        self.client.post(reverse("painel:faq_categoria_nova"), {"nome": "Pagamentos", "ordem": 1})
        cat = CategoriaFAQ.objects.get(nome="Pagamentos")
        self.client.post(reverse("painel:faq_pergunta_nova"), {
            "categoria": cat.pk, "pergunta": "Aceita Pix?", "resposta": "Sim!", "palavras_chave": "pix", "ativa": "on",
        })
        p = PerguntaFAQ.objects.get(pergunta="Aceita Pix?")
        self.client.post(reverse("painel:faq_pergunta_alternar", args=[p.pk]))
        p.refresh_from_db()
        self.assertFalse(p.ativa)
        # Categoria com pergunta não pode ser excluída.
        self.client.post(reverse("painel:faq_categoria_excluir", args=[cat.pk]))
        self.assertTrue(CategoriaFAQ.objects.filter(pk=cat.pk).exists())
        self.assertEqual(self.client.get(reverse("painel:faq")).status_code, 200)

    def test_atendente_nao_altera_faq(self):
        cat = CategoriaFAQ.objects.create(nome="Geral")
        p = PerguntaFAQ.objects.create(categoria=cat, pergunta="X", resposta="Y")
        self.entrar(self.at1)
        self.client.post(reverse("painel:faq_pergunta_alternar", args=[p.pk]))
        p.refresh_from_db()
        self.assertTrue(p.ativa)
