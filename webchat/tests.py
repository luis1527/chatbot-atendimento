"""
Testes do site público e do chat do site.

O motor do bot (bot.engine.processar_entrada) é substituído por um fake que
grava a mensagem do cliente e uma resposta do bot — assim estes testes não
dependem do motor real nem de IA.
"""
import json
from unittest import mock

from django.test import Client, TestCase
from django.urls import reverse

from core import services
from core.models import Contato, Conversa, Mensagem, Usuario

MENU = [[{"texto": "❓ Chat de dúvida", "dado": "menu:duvida"}], [{"texto": "Site", "url": "https://exemplo.com"}]]


def engine_fake(contato, texto=None, dado=None, telegram_message_id=None):
    conversa = services.conversa_aberta(contato)
    if texto == "/start":
        services.registrar_mensagem(conversa, Mensagem.Remetente.BOT, "Olá! *Bem-vindo*", botoes=MENU)
        return conversa
    services.registrar_mensagem(conversa, Mensagem.Remetente.CLIENTE, texto or f"[{dado}]")
    services.registrar_mensagem(conversa, Mensagem.Remetente.BOT, f"Você disse: {texto or dado}")
    return conversa


def post_json(cliente, url, dados):
    return cliente.post(url, data=json.dumps(dados), content_type="application/json")


@mock.patch("bot.engine.processar_entrada", side_effect=engine_fake)
class ChatWebTests(TestCase):
    def setUp(self):
        self.c = Client()

    def iniciar(self, cliente=None, nome="Maria"):
        cliente = cliente or self.c
        cliente.get(reverse("webchat:chat"))
        return post_json(cliente, reverse("webchat:api_iniciar"), {"nome": nome})

    def mensagens(self, cliente=None, depois=0):
        cliente = cliente or self.c
        return (cliente or self.c).get(reverse("webchat:api_mensagens"), {"depois": depois}).json()

    def test_paginas_publicas(self, _engine):
        r = self.c.get(reverse("webchat:inicio"))
        self.assertContains(r, "Abrir no Telegram")
        self.assertContains(r, "https://t.me/")
        self.assertContains(r, "qrcode.min.js")
        self.assertContains(r, "/painel/")
        r = self.c.get(reverse("webchat:chat"))
        self.assertContains(r, 'data-precisa-nome="1"')
        self.assertIn("csrftoken", r.cookies)

    def test_sessao_cria_contato_unico(self, engine):
        r = self.iniciar()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["nome"], "Maria")
        self.iniciar()
        self.c.get(reverse("webchat:chat"))
        self.assertEqual(Contato.objects.filter(canal="web").count(), 1)
        # /start só é chamado uma vez (a conversa já tem mensagens)
        self.assertEqual(engine.call_count, 1)
        r = self.c.get(reverse("webchat:chat"))
        self.assertContains(r, 'data-precisa-nome="0"')

    def test_nome_opcional(self, _engine):
        r = self.iniciar(nome="")
        self.assertEqual(r.json()["nome"], "Visitante")

    def test_boas_vindas_e_botoes_serializados(self, _engine):
        self.iniciar()
        dados = self.mensagens()
        self.assertEqual(len(dados["mensagens"]), 1)
        m = dados["mensagens"][0]
        self.assertEqual(m["remetente"], "bot")
        self.assertEqual(m["botoes"], MENU)
        self.assertRegex(m["hora"], r"^\d\d:\d\d$")
        self.assertEqual(dados["status"]["codigo"], "bot")
        self.assertEqual(dados["status"]["rotulo"], "Assistente virtual")

    def test_enviar_e_receber_por_polling(self, engine):
        self.iniciar()
        ultimo = self.mensagens()["mensagens"][-1]["id"]
        r = post_json(self.c, reverse("webchat:api_enviar"), {"texto": "Oi, tudo bem?"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        engine.assert_called_with(mock.ANY, texto="Oi, tudo bem?")
        novas = self.mensagens(depois=ultimo)["mensagens"]
        self.assertEqual([m["remetente"] for m in novas], ["cliente", "bot"])
        self.assertEqual(novas[0]["texto"], "Oi, tudo bem?")
        self.assertEqual(r.json()["ultimo_id"], novas[-1]["id"])

    def test_enviar_dado(self, engine):
        self.iniciar()
        post_json(self.c, reverse("webchat:api_enviar"), {"dado": "menu:duvida"})
        engine.assert_called_with(mock.ANY, dado="menu:duvida")

    def test_validacoes_envio(self, _engine):
        url = reverse("webchat:api_enviar")
        # sem sessão iniciada
        self.assertEqual(post_json(self.c, url, {"texto": "oi"}).status_code, 403)
        self.iniciar()
        self.assertEqual(post_json(self.c, url, {"texto": "   "}).status_code, 400)
        self.assertEqual(post_json(self.c, url, {"texto": "x" * 1001}).status_code, 400)
        self.assertEqual(self.c.get(url).status_code, 405)

    def test_rate_limit(self, _engine):
        self.iniciar()
        url = reverse("webchat:api_enviar")
        self.assertEqual(post_json(self.c, url, {"texto": "um"}).status_code, 200)
        self.assertEqual(post_json(self.c, url, {"texto": "dois"}).status_code, 429)

    def test_visitante_nao_ve_mensagens_de_outro(self, _engine):
        a, b = Client(), Client()
        self.iniciar(a, "Ana")
        self.iniciar(b, "Bruno")
        post_json(a, reverse("webchat:api_enviar"), {"texto": "segredo da Ana"})
        textos_b = [m["texto"] for m in self.mensagens(b)["mensagens"]]
        textos_b += [m["texto"] for m in self.mensagens(b, depois=1)["mensagens"]]
        self.assertNotIn("segredo da Ana", textos_b)
        self.assertNotIn("Você disse: segredo da Ana", textos_b)
        self.assertEqual(Contato.objects.filter(canal="web").count(), 2)
        # sem sessão: proibido
        self.assertEqual(Client().get(reverse("webchat:api_mensagens")).status_code, 403)

    def test_status_atendente_e_encerramento(self, _engine):
        self.iniciar()
        contato = Contato.objects.get(canal="web")
        conversa = services.conversa_aberta(contato)
        ana = Usuario.objects.create_user("ana", password="x", apelido="Ana")
        ultimo = self.mensagens()["mensagens"][-1]["id"]

        services.escalar(conversa)
        self.assertEqual(self.mensagens(depois=ultimo)["status"]["rotulo"], "Aguardando atendente…")

        services.assumir(conversa, ana)
        services.enviar_ao_cliente(conversa, "Oi, sou a Ana", remetente=Mensagem.Remetente.ATENDENTE, atendente=ana)
        dados = self.mensagens(depois=ultimo)
        self.assertEqual(dados["status"]["rotulo"], "Em atendimento com Ana")
        self.assertEqual(dados["mensagens"][-1]["atendente"], "Ana")
        self.assertEqual(dados["mensagens"][-1]["remetente"], "atendente")
        ultimo = dados["mensagens"][-1]["id"]

        services.encerrar(conversa, ana)
        dados = self.mensagens(depois=ultimo)
        self.assertEqual(dados["status"]["codigo"], "encerrada")
        avaliacao = dados["mensagens"][-1]
        self.assertEqual(avaliacao["remetente"], "sistema")
        self.assertEqual(len(avaliacao["botoes"][0]), 5)
        # Recarregando a página, a conversa recém-encerrada continua visível.
        self.assertEqual(self.mensagens()["mensagens"][-1]["id"], avaliacao["id"])

    def test_nova_conversa(self, _engine):
        self.iniciar()
        contato = Contato.objects.get(canal="web")
        antiga = services.conversa_aberta(contato)
        r = post_json(self.c, reverse("webchat:api_nova"), {})
        self.assertEqual(r.status_code, 200)
        antiga.refresh_from_db()
        self.assertEqual(antiga.status, Conversa.Status.ENCERRADA)
        nova = services.conversa_aberta(contato, criar=False)
        self.assertNotEqual(nova.pk, antiga.pk)
        ids_conversa = {m["conversa"] for m in self.mensagens()["mensagens"]}
        self.assertEqual(ids_conversa, {nova.pk})

    def test_botoes_invalidos_sao_filtrados(self, _engine):
        self.iniciar()
        conversa = services.conversa_aberta(Contato.objects.get(canal="web"))
        services.registrar_mensagem(conversa, "bot", "x", botoes=[
            [{"texto": "ok", "dado": "a"}, {"texto": "mau", "url": "javascript:alert(1)"}, {"sem": "texto"}],
        ])
        ultima = self.mensagens()["mensagens"][-1]
        self.assertEqual(ultima["botoes"], [[{"texto": "ok", "dado": "a"}]])

    def test_engine_com_erro_responde_503(self, engine):
        self.iniciar()
        engine.side_effect = RuntimeError("quebrou")
        r = post_json(self.c, reverse("webchat:api_enviar"), {"texto": "oi"})
        self.assertEqual(r.status_code, 503)
        self.assertFalse(r.json()["ok"])

    def test_csrf_obrigatorio(self, _engine):
        c = Client(enforce_csrf_checks=True)
        c.get(reverse("webchat:chat"))
        r = post_json(c, reverse("webchat:api_iniciar"), {"nome": "X"})
        self.assertEqual(r.status_code, 403)
        token = c.cookies["csrftoken"].value
        r = c.post(reverse("webchat:api_iniciar"), data=json.dumps({"nome": "X"}),
                   content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(r.status_code, 200)


class SaudeTests(TestCase):
    def test_saude(self):
        r = self.client.get(reverse("webchat:saude"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"ok": True, "banco": True})
