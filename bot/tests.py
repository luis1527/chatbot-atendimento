"""
Testes do bot. Telegram e Gemini são SEMPRE mockados (nenhuma chamada real).

    DATABASE_URL= .venv/bin/python manage.py test bot
"""
import json
from itertools import count
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings

from bot import engine, ia, nlp
from bot.views import tratar_update
from core import services
from core.models import Conversa, Mensagem, PerguntaFAQ, Ticket, Usuario

SEGREDO = "segredo-de-teste"
CHAT_ID = 555001


def _resposta_telegram(numeros=count(1000)):
    r = mock.Mock()
    r.json.return_value = {"ok": True, "result": {"message_id": next(numeros)}}
    return r


@override_settings(
    GEMINI_API_KEY="", TELEGRAM_BOT_TOKEN="123:teste", TELEGRAM_WEBHOOK_SECRET=SEGREDO, NOME_EMPRESA="Empresa Teste",
)
class BaseBot(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("popular_demo", stdout=mock.MagicMock())

    def setUp(self):
        patcher = mock.patch("bot.telegram_api.requests.post", side_effect=lambda *a, **k: _resposta_telegram())
        self.tg = patcher.start()
        self.addCleanup(patcher.stop)
        self.msg_id = count(1)

    # -- auxiliares ---------------------------------------------------------
    def update_texto(self, texto, message_id=None, chat_id=CHAT_ID):
        return {"update_id": 1, "message": {
            "message_id": message_id or next(self.msg_id), "chat": {"id": chat_id, "type": "private"},
            "from": {"id": chat_id, "first_name": "Maria", "last_name": "Teste"}, "text": texto,
        }}

    def enviar(self, texto, **kw):
        tratar_update(self.update_texto(texto, **kw))

    def clicar(self, dado, chat_id=CHAT_ID):
        tratar_update({"update_id": 2, "callback_query": {
            "id": "cb1", "data": dado, "from": {"id": chat_id, "first_name": "Maria"},
            "message": {"message_id": 99, "chat": {"id": chat_id, "type": "private"}},
        }})

    def conversa(self):
        return Conversa.objects.filter(contato__telegram_chat_id=CHAT_ID).order_by("-id").first()

    def respostas_bot(self, conversa=None):
        return list((conversa or self.conversa()).mensagens.exclude(remetente="cliente").order_by("id"))

    def ultima_resposta(self):
        return self.respostas_bot()[-1]

    def metodos_telegram(self):
        return [c.args[0].rsplit("/", 1)[-1] for c in self.tg.call_args_list]


class MenuTests(BaseBot):
    def test_start_mostra_boas_vindas_com_menu(self):
        self.enviar("/start")
        resp = self.ultima_resposta()
        self.assertIn("Empresa Teste", resp.texto)
        self.assertIn("Maria", resp.texto)
        self.assertEqual(resp.botoes, engine.botoes_menu())
        self.assertIn("sendMessage", self.metodos_telegram())
        corpo = self.tg.call_args_list[-1].kwargs["json"]
        self.assertEqual(corpo["chat_id"], CHAT_ID)
        self.assertIn("inline_keyboard", corpo["reply_markup"])

    def test_menu_por_texto_e_comando(self):
        self.enviar("menu")
        self.assertEqual(self.ultima_resposta().botoes, engine.botoes_menu())
        self.enviar("/menu@felipeprojeto_bot")
        self.assertEqual(len(self.respostas_bot()), 2)

    def test_saudacao_sem_ia_responde_e_mostra_menu(self):
        self.enviar("oii, tudo bem?")
        resp = self.ultima_resposta()
        self.assertIn("Olá", resp.texto)
        self.assertEqual(resp.botoes, engine.botoes_menu())
        self.assertEqual(self.conversa().mensagens.get(remetente="cliente").intencao.slug, "saudacao")

    def test_callback_responde_e_remove_teclado(self):
        self.clicar("menu:duvida")
        metodos = self.metodos_telegram()
        self.assertIn("answerCallbackQuery", metodos)
        self.assertIn("editMessageReplyMarkup", metodos)
        conv = self.conversa()
        self.assertEqual(conv.modo, Conversa.Modo.DUVIDA)
        # O clique fica no histórico com o rótulo do botão, não com o código.
        self.assertEqual(conv.mensagens.get(remetente="cliente").texto, "❓ Chat de dúvida")


class DuvidaTests(BaseBot):
    def test_duvida_respondida_pelo_faq_no_fallback(self):
        self.clicar("menu:duvida")
        self.enviar("esqueci minha senha, como faço?")
        resp = self.ultima_resposta()
        faq = PerguntaFAQ.objects.get(pergunta__startswith="Esqueci minha senha")
        self.assertEqual(resp.origem_resposta, Mensagem.Origem.FAQ)
        self.assertEqual(resp.faq, faq)
        self.assertEqual(resp.texto, faq.resposta)
        faq.refresh_from_db()
        self.assertEqual(faq.vezes_usada, 1)
        dados = [b["dado"] for linha in resp.botoes for b in linha]
        self.assertIn("menu:duvida", dados)
        self.assertIn("menu:humano", dados)

    def test_varias_perguntas_do_faq(self):
        casos = {
            "qual o horario de atendimento?": "Qual o horário de atendimento?",
            "como pago com pix": "Quais as formas de pagamento?",
            "preciso da segunda via do boleto": "Como emito a segunda via do boleto?",
            "quero reembolso": "Como peço reembolso?",
        }
        faqs = list(PerguntaFAQ.objects.all())
        for texto, pergunta in casos.items():
            faq, _ = nlp.melhor_faq(texto, faqs)
            self.assertIsNotNone(faq, texto)
            self.assertEqual(faq.pergunta, pergunta, texto)

    def test_sem_resposta_oferece_atendente_depois_de_duas_falhas(self):
        self.clicar("menu:duvida")
        self.enviar("vocês vendem bicicletas?")
        primeira = self.ultima_resposta()
        self.assertIn("não encontrei", primeira.texto.lower())
        self.assertIn("menu:ticket", [b["dado"] for linha in primeira.botoes for b in linha])
        self.enviar("e patinetes elétricos?")
        segunda = self.ultima_resposta()
        self.assertIn("chame um atendente", segunda.texto)
        self.assertEqual(segunda.botoes[0][0]["dado"], "menu:humano")
        self.assertEqual(self.conversa().status, Conversa.Status.BOT)  # só oferece, não escala sozinho


class FilaHumanoTests(BaseBot):
    def test_pedir_atendente_vai_para_fila_e_avisa_so_uma_vez(self):
        self.enviar("quero falar com um atendente")
        conv = self.conversa()
        self.assertEqual(conv.status, Conversa.Status.FILA)
        self.assertIn("posição 1", self.ultima_resposta().texto)
        self.assertIn("8h", self.ultima_resposta().texto)
        total = len(self.respostas_bot())
        for t in ("alô?", "tem alguém aí?", "oi??"):
            self.enviar(t)
        self.assertEqual(len(self.respostas_bot()), total + 1)
        self.assertEqual(self.ultima_resposta().texto, engine.AVISO_FILA)
        self.assertEqual(conv.mensagens.filter(remetente="cliente").count(), 4)

    def test_botao_falar_com_atendente(self):
        self.clicar("menu:humano")
        self.assertEqual(self.conversa().status, Conversa.Status.FILA)

    def test_em_atendimento_humano_bot_fica_quieto(self):
        self.enviar("quero falar com atendente")
        atendente = Usuario.objects.get(username="atendente1")
        services.assumir(self.conversa(), atendente)
        antes = len(self.respostas_bot())
        chamadas = self.tg.call_count
        self.enviar("oi, meu boleto veio errado")
        self.enviar("/menu")
        self.assertEqual(len(self.respostas_bot()), antes)
        self.assertEqual(self.tg.call_count, chamadas)
        self.assertEqual(self.conversa().mensagens.filter(remetente="cliente").count(), 3)

    def test_encerrar_pede_avaliacao(self):
        self.enviar("oi")
        self.enviar("/encerrar")
        conv = self.conversa()
        self.assertEqual(conv.status, Conversa.Status.ENCERRADA)
        self.assertTrue(self.ultima_resposta().botoes[0][0]["dado"].startswith(f"avaliar:{conv.pk}:"))


class TicketTests(BaseBot):
    def test_fluxo_completo_de_ticket(self):
        self.clicar("menu:ticket")
        self.assertIn("assunto", self.ultima_resposta().texto.lower())
        self.enviar("Boleto duplicado")
        self.assertIn("detalhes", self.ultima_resposta().texto)
        self.enviar("Recebi dois boletos iguais este mês")
        self.assertIn("categoria", self.ultima_resposta().texto)
        self.clicar("ticket_cat:financeiro")
        ticket = Ticket.objects.get()
        self.assertEqual(ticket.assunto, "Boleto duplicado")
        self.assertEqual(ticket.descricao, "Recebi dois boletos iguais este mês")
        self.assertEqual(ticket.categoria, "financeiro")
        self.assertEqual(ticket.conversa, self.conversa())
        self.assertRegex(ticket.protocolo, r"^TCK-\d{4}$")
        self.assertIn(ticket.protocolo, self.ultima_resposta().texto)
        self.assertEqual(self.conversa().modo, Conversa.Modo.MENU)
        # Estado do fluxo não vaza para o Telegram (só texto/callback_data).
        corpos = [c.kwargs["json"] for c in self.tg.call_args_list if "reply_markup" in c.kwargs.get("json", {})]
        for corpo in corpos:
            for linha in corpo["reply_markup"]["inline_keyboard"]:
                for b in linha:
                    self.assertLessEqual(set(b), {"text", "callback_data", "url"})

    def test_categoria_digitada_e_meus_tickets(self):
        self.enviar("quero abrir um chamado")
        self.assertEqual(self.conversa().modo, Conversa.Modo.TICKET)
        self.enviar("Sistema lento")
        self.enviar("Demora muito para carregar")
        self.enviar("suporte")
        ticket = Ticket.objects.get()
        self.assertEqual(ticket.categoria, "suporte")
        self.clicar("menu:meus_tickets")
        self.assertIn(ticket.protocolo, self.ultima_resposta().texto)
        self.assertIn("Aberto", self.ultima_resposta().texto)

    def test_cancelar_ticket(self):
        self.clicar("menu:ticket")
        self.enviar("Assunto qualquer")
        self.enviar("cancelar")
        self.assertEqual(Ticket.objects.count(), 0)
        self.assertEqual(self.conversa().modo, Conversa.Modo.MENU)
        self.assertIn("cancelei", self.ultima_resposta().texto)

    def test_meus_tickets_vazio(self):
        self.clicar("menu:meus_tickets")
        self.assertIn("ainda não tem tickets", self.ultima_resposta().texto)


class AvaliacaoTests(BaseBot):
    def test_avaliacao_nao_cria_conversa_nova(self):
        self.enviar("oi")
        self.enviar("/encerrar")
        conv = self.conversa()
        self.clicar(f"avaliar:{conv.pk}:5")
        conv.refresh_from_db()
        self.assertEqual(conv.avaliacao, 5)
        self.assertEqual(Conversa.objects.filter(contato=conv.contato).count(), 1)
        self.assertIn("5/5", self.respostas_bot(conv)[-1].texto)
        # Segundo clique não muda a nota.
        self.clicar(f"avaliar:{conv.pk}:1")
        conv.refresh_from_db()
        self.assertEqual(conv.avaliacao, 5)

    def test_nao_avalia_conversa_de_outro_contato(self):
        self.enviar("oi", chat_id=777)
        outra = Conversa.objects.get(contato__telegram_chat_id=777)
        services.encerrar(outra)
        self.enviar("oi")
        self.clicar(f"avaliar:{outra.pk}:1")
        outra.refresh_from_db()
        self.assertIsNone(outra.avaliacao)

    def test_novo_atendimento_depois_de_avaliar(self):
        self.enviar("/encerrar")
        conv = self.conversa()
        self.clicar(f"avaliar:{conv.pk}:4")
        self.clicar("menu:inicio")
        nova = self.conversa()
        self.assertNotEqual(nova.pk, conv.pk)
        self.assertEqual(nova.status, Conversa.Status.BOT)


class WebhookTests(BaseBot):
    def post(self, corpo, segredo=SEGREDO):
        extra = {"HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN": segredo} if segredo is not None else {}
        return self.client.post("/telegram/webhook/", data=json.dumps(corpo), content_type="application/json", **extra)

    def test_segredo_errado_ou_ausente_da_403(self):
        self.assertEqual(self.post(self.update_texto("oi"), segredo="errado").status_code, 403)
        self.assertEqual(self.post(self.update_texto("oi"), segredo=None).status_code, 403)
        self.assertEqual(Mensagem.objects.count(), 0)

    def test_webhook_ok(self):
        r = self.post(self.update_texto("/start"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.conversa().mensagens.count(), 2)

    def test_update_duplicado_nao_duplica(self):
        upd = self.update_texto("/start", message_id=42)
        self.post(upd)
        self.post(upd)
        conv = self.conversa()
        self.assertEqual(conv.mensagens.filter(remetente="cliente").count(), 1)
        self.assertEqual(conv.mensagens.filter(remetente="bot").count(), 1)

    def test_erro_interno_devolve_200(self):
        with mock.patch("bot.engine.processar_entrada", side_effect=RuntimeError("boom")):
            r = self.post(self.update_texto("oi"))
        self.assertEqual(r.status_code, 200)

    def test_json_invalido_devolve_200(self):
        r = self.client.post("/telegram/webhook/", data="{nao json", content_type="application/json",
                             HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=SEGREDO)
        self.assertEqual(r.status_code, 200)

    def test_foto_responde_que_so_entende_texto(self):
        upd = self.update_texto("x")
        del upd["message"]["text"]
        upd["message"]["photo"] = [{"file_id": "abc"}]
        self.post(upd)
        self.assertIn("só entendo mensagens de texto", self.ultima_resposta().texto)

    def test_grupo_e_ignorado(self):
        upd = self.update_texto("oi")
        upd["message"]["chat"]["type"] = "group"
        self.post(upd)
        self.assertEqual(Mensagem.objects.count(), 0)


class SiteTests(BaseBot):
    def test_contato_do_site_nao_chama_telegram(self):
        contato = services.contato_web("sessao-teste", "Visitante")
        conv = engine.processar_entrada(contato, texto="/start")
        engine.processar_entrada(contato, dado="menu:duvida")
        engine.processar_entrada(contato, texto="quais as formas de pagamento?")
        self.assertEqual(self.tg.call_count, 0)
        self.assertEqual(conv.mensagens.filter(remetente="bot").count(), 3)
        self.assertEqual(conv.mensagens.last().origem_resposta, Mensagem.Origem.FAQ)


@override_settings(GEMINI_API_KEY="chave-falsa")
class IAMockadaTests(BaseBot):
    def resultado(self, **campos):
        base = {"acao": "conversa_livre", "intencao": "outro", "confianca": 0.9, "faq_id": None, "resposta": "",
                "ticket": {"assunto": "", "descricao": "", "categoria": ""}}
        base.update(campos)
        return base

    def test_pedido_impossivel_responde_com_honestidade(self):
        res = self.resultado(acao="nao_suportado", resposta="Ainda não consigo fazer pedidos por aqui.")
        with mock.patch("bot.ia.interpretar", return_value=res) as m:
            self.enviar("quero pedir uma pizza")
        self.assertTrue(m.called)
        self.assertIn("sendChatAction", self.metodos_telegram())  # sendChatAction antes da IA
        resp = self.ultima_resposta()
        self.assertEqual(resp.texto, "Ainda não consigo fazer pedidos por aqui.")
        self.assertEqual(resp.origem_resposta, Mensagem.Origem.IA)
        self.assertIn("menu:ticket", [b["dado"] for linha in resp.botoes for b in linha])

    def test_ia_responde_faq(self):
        faq = PerguntaFAQ.objects.get(pergunta__startswith="Quais as formas")
        res = self.resultado(acao="responder_faq", intencao="financeiro", faq_id=faq.pk, resposta="Pode pagar com Pix!")
        with mock.patch("bot.ia.interpretar", return_value=res):
            self.enviar("da pra pagar no pix?")
        resp = self.ultima_resposta()
        self.assertEqual(resp.faq, faq)
        self.assertEqual(resp.origem_resposta, Mensagem.Origem.FAQ)
        self.assertEqual(self.conversa().mensagens.get(remetente="cliente").intencao.slug, "financeiro")

    def test_ia_abre_ticket_completo_numa_frase(self):
        res = self.resultado(acao="abrir_ticket", ticket={
            "assunto": "Boleto duplicado", "descricao": "Meu boleto veio duplicado", "categoria": "financeiro"})
        with mock.patch("bot.ia.interpretar", return_value=res):
            self.enviar("quero abrir um ticket porque meu boleto veio duplicado")
        ticket = Ticket.objects.get()
        self.assertEqual(ticket.categoria, "financeiro")
        self.assertIn(ticket.protocolo, self.ultima_resposta().texto)

    def test_ia_abre_ticket_incompleto_pergunta_o_que_falta(self):
        res = self.resultado(acao="abrir_ticket", ticket={"assunto": "Problema no login", "descricao": "", "categoria": ""})
        with mock.patch("bot.ia.interpretar", return_value=res):
            self.enviar("quero abrir um ticket sobre login")
        self.assertIn("Problema no login", self.ultima_resposta().texto)
        self.assertIn("detalhes", self.ultima_resposta().texto)

    def test_ia_pede_atendente(self):
        with mock.patch("bot.ia.interpretar", return_value=self.resultado(acao="falar_com_atendente")):
            self.enviar("kd o atendente??")
        self.assertEqual(self.conversa().status, Conversa.Status.FILA)

    def test_ia_falhou_usa_fallback(self):
        with mock.patch("bot.ia.interpretar", return_value=None):
            self.enviar("esqueci a senha")
        self.assertEqual(self.ultima_resposta().origem_resposta, Mensagem.Origem.FAQ)

    def test_faq_inventado_pela_ia_e_ignorado(self):
        res = self.resultado(acao="responder_faq", faq_id=99999, resposta="Inventei algo")
        with mock.patch("bot.ia.interpretar", return_value=res):
            self.enviar("pergunta estranha")
        self.assertNotEqual(self.ultima_resposta().texto, "Inventei algo")


@override_settings(GEMINI_API_KEY="chave-falsa", GEMINI_MODEL="gemini-teste")
class ClienteGeminiTests(TestCase):
    def chamar(self, resposta):
        with mock.patch("bot.ia.requests.post", return_value=resposta) as post:
            res = ia.interpretar("oi", faqs=[], intencoes=[("saudacao", "Oi")], categorias=[("outro", "Outro")])
        return res, post

    def test_429_retorna_none(self):
        res, _ = self.chamar(mock.Mock(status_code=429, text="quota"))
        self.assertIsNone(res)

    def test_timeout_retorna_none(self):
        import requests
        with mock.patch("bot.ia.requests.post", side_effect=requests.Timeout):
            self.assertIsNone(ia.interpretar("oi", faqs=[], intencoes=[], categorias=[]))

    @override_settings(GEMINI_API_KEY="")
    def test_sem_chave_nao_chama(self):
        res, post = self.chamar(mock.Mock())
        self.assertIsNone(res)
        post.assert_not_called()

    def test_resposta_valida_e_requisicao_correta(self):
        corpo = {"acao": "conversa_livre", "intencao": "saudacao", "confianca": 0.9, "faq_id": 0,
                 "resposta": "Olá!", "ticket_assunto": "", "ticket_descricao": "", "ticket_categoria": "nenhuma"}
        r = mock.Mock(status_code=200)
        r.json.return_value = {"candidates": [{"content": {"parts": [{"text": json.dumps(corpo)}]}}]}
        res, post = self.chamar(r)
        self.assertEqual(res["acao"], "conversa_livre")
        self.assertEqual(res["resposta"], "Olá!")
        self.assertIsNone(res["faq_id"])
        self.assertEqual(res["ticket"]["categoria"], "")
        args, kwargs = post.call_args
        self.assertIn("models/gemini-teste:generateContent", args[0])
        self.assertEqual(kwargs["headers"]["x-goog-api-key"], "chave-falsa")
        gc = kwargs["json"]["generationConfig"]
        self.assertEqual(gc["responseMimeType"], "application/json")
        self.assertIn("thinkingConfig", gc)

    def test_modelo_404_tenta_reserva(self):
        ia._modelo_indisponivel.clear()
        self.addCleanup(ia._modelo_indisponivel.clear)
        ok = mock.Mock(status_code=200)
        ok.json.return_value = {"candidates": [{"content": {"parts": [{"text": json.dumps(
            {"acao": "mostrar_menu", "intencao": "saudacao", "confianca": 1, "faq_id": 0, "resposta": "",
             "ticket_assunto": "", "ticket_descricao": "", "ticket_categoria": "nenhuma"})}]}}]}
        with mock.patch("bot.ia.requests.post", side_effect=[mock.Mock(status_code=404, text="gone"), ok]) as post:
            res = ia.interpretar("menu", faqs=[], intencoes=[], categorias=[])
        self.assertEqual(res["acao"], "mostrar_menu")
        self.assertIn(ia.MODELO_RESERVA, post.call_args_list[1].args[0])

    def test_sobrecarga_503_usa_modelo_alternativo(self):
        ok = mock.Mock(status_code=200)
        ok.json.return_value = {"candidates": [{"content": {"parts": [{"text": json.dumps(
            {"acao": "conversa_livre", "intencao": "saudacao", "confianca": 1, "faq_id": 0, "resposta": "Oi!",
             "ticket_assunto": "", "ticket_descricao": "", "ticket_categoria": "nenhuma"})}]}}]}
        sobrecarga = mock.Mock(status_code=503, text="high demand")
        with mock.patch("bot.ia.time.sleep"), \
                mock.patch("bot.ia.requests.post", side_effect=[sobrecarga, sobrecarga, ok]) as post:
            res = ia.interpretar("oi", faqs=[], intencoes=[], categorias=[])
        self.assertEqual(res["resposta"], "Oi!")
        self.assertIn(ia.MODELOS_ALTERNATIVOS[0], post.call_args_list[2].args[0])


class NlpTests(TestCase):
    def test_normalizar(self):
        self.assertEqual(nlp.normalizar("  Olá, AÇÃO!!  "), "ola acao")

    def test_intencoes(self):
        casos = {
            "quero falar com um atendente": "falar_humano",
            "atendente": "falar_humano",
            "me passa pra um humano pfv": "falar_humano",
            "oi": "saudacao",
            "bom dia, tudo bem?": "saudacao",
            "valeu, obrigado!": "despedida",
            "quero abrir um ticket": "abrir_ticket",
            "status do meu ticket": "status_ticket",
            "o boleto não chegou": "financeiro",
            "o sistema travou": "suporte",
            "atendimento péssimo": "reclamacao",
            "como funciona?": "duvida",
        }
        for texto, esperado in casos.items():
            self.assertEqual(nlp.detectar_intencao(texto)[0], esperado, texto)

    def test_atendente_sem_pedido_nao_escala(self):
        self.assertNotEqual(nlp.detectar_intencao("o atendente de ontem foi ótimo e resolveu meu caso")[0], "falar_humano")
