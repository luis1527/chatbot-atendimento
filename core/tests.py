"""
Testes do banco de dados e das regras de atendimento (app core).

Rodar:
    python manage.py test core                    # usa o banco do .env (PostgreSQL)
    DATABASE_URL= python manage.py test core      # força SQLite

Cada teste de "regra de integridade" tenta gravar um dado inválido e espera
que o PRÓPRIO BANCO recuse (IntegrityError). Isso prova que a regra vale
mesmo se algum código esquecer de validar.

Nada é enviado ao Telegram: bot.telegram_api.enviar_mensagem é substituído
por um mock em todos os testes.
"""
import re
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from . import services
from .models import (
    CategoriaFAQ, Canal, Contato, Conversa, EventoConversa, Intencao, Mensagem, PerguntaFAQ, Ticket, Usuario,
)


class BaseTeste(TestCase):
    """Cria dados fictícios mínimos e desliga o envio ao Telegram."""

    @classmethod
    def setUpTestData(cls):
        cls.ana = Usuario.objects.create_user("ana_teste", password="x", apelido="Ana", cargo=Usuario.Cargo.ATENDENTE)
        cls.beto = Usuario.objects.create_user("beto_teste", password="x", apelido="Beto")
        cls.cliente = Contato.objects.create(canal=Canal.TELEGRAM, nome="Cliente Teste", telegram_chat_id=111)
        cls.visitante = Contato.objects.create(canal=Canal.WEB, nome="Visitante Teste", web_sessao="sessao-teste-1")

    def setUp(self):
        envio = mock.patch("bot.telegram_api.enviar_mensagem", return_value={"message_id": 999})
        menu = mock.patch("bot.engine.botoes_menu", return_value=[[{"texto": "Menu", "dado": "menu"}]])
        self.envio = envio.start()
        menu.start()
        self.addCleanup(mock.patch.stopall)

    def assertBancoRecusa(self, func):
        """Executa func e exige IntegrityError vindo do banco."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                func()


# ---------------------------------------------------------------------------
# 1. Regras de integridade (constraints no banco)
# ---------------------------------------------------------------------------
class ContatoTests(BaseTeste):
    def test_contato_telegram_duplicado_e_barrado(self):
        self.assertBancoRecusa(
            lambda: Contato.objects.create(canal=Canal.TELEGRAM, nome="Outro", telegram_chat_id=111)
        )

    def test_sessao_web_duplicada_e_barrada(self):
        self.assertBancoRecusa(
            lambda: Contato.objects.create(canal=Canal.WEB, nome="Outro", web_sessao="sessao-teste-1")
        )

    def test_contato_sem_identificador_do_canal_e_barrado(self):
        self.assertBancoRecusa(lambda: Contato.objects.create(canal=Canal.TELEGRAM, nome="Sem chat_id"))
        self.assertBancoRecusa(lambda: Contato.objects.create(canal=Canal.WEB, nome="Sem sessão"))

    def test_service_contato_telegram_reaproveita_cadastro(self):
        c1 = services.contato_telegram(111, "Cliente Teste Renomeado", "cliente_t")
        c2 = services.contato_telegram(111, "Cliente Teste Renomeado", "cliente_t")
        self.assertEqual(c1.pk, self.cliente.pk)
        self.assertEqual(c2.pk, self.cliente.pk)
        self.assertEqual(Contato.objects.filter(telegram_chat_id=111).count(), 1)
        self.assertEqual(c2.nome, "Cliente Teste Renomeado")


class ConversaTests(BaseTeste):
    def test_so_uma_conversa_aberta_por_contato(self):
        Conversa.objects.create(contato=self.cliente, canal=Canal.TELEGRAM)
        self.assertBancoRecusa(
            lambda: Conversa.objects.create(contato=self.cliente, canal=Canal.TELEGRAM, status=Conversa.Status.FILA)
        )

    def test_conversas_encerradas_nao_contam_para_o_limite(self):
        for _ in range(3):
            Conversa.objects.create(contato=self.cliente, canal=Canal.TELEGRAM, status=Conversa.Status.ENCERRADA)
        Conversa.objects.create(contato=self.cliente, canal=Canal.TELEGRAM)  # a aberta
        self.assertEqual(self.cliente.conversas.count(), 4)

    def test_service_conversa_aberta_nao_duplica(self):
        c1 = services.conversa_aberta(self.cliente)
        c2 = services.conversa_aberta(self.cliente)
        self.assertEqual(c1.pk, c2.pk)
        self.assertEqual(EventoConversa.objects.filter(conversa=c1, tipo=EventoConversa.Tipo.CRIADA).count(), 1)

    def test_conversa_humano_sem_atendente_e_barrada(self):
        self.assertBancoRecusa(
            lambda: Conversa.objects.create(contato=self.cliente, canal=Canal.TELEGRAM, status=Conversa.Status.HUMANO)
        )

    def test_avaliacao_fora_de_1_a_5_e_barrada(self):
        conversa = Conversa.objects.create(contato=self.cliente, canal=Canal.TELEGRAM)
        for nota in (0, 6):
            conversa.avaliacao = nota
            self.assertBancoRecusa(lambda: conversa.save(update_fields=["avaliacao"]))
        for nota in (1, 5):
            conversa.avaliacao = nota
            conversa.save(update_fields=["avaliacao"])

    def test_service_registrar_avaliacao_valida_nota(self):
        conversa = Conversa.objects.create(contato=self.cliente, canal=Canal.TELEGRAM)
        with self.assertRaises(services.ErroAtendimento):
            services.registrar_avaliacao(conversa, 9)
        services.registrar_avaliacao(conversa, 4, "Bom")
        conversa.refresh_from_db()
        self.assertEqual(conversa.avaliacao, 4)
        self.assertTrue(conversa.eventos.filter(tipo=EventoConversa.Tipo.AVALIADA).exists())


class MensagemTests(BaseTeste):
    def setUp(self):
        super().setUp()
        self.conversa = Conversa.objects.create(contato=self.cliente, canal=Canal.TELEGRAM)

    def test_mensagem_de_atendente_sem_atendente_e_barrada(self):
        self.assertBancoRecusa(
            lambda: Mensagem.objects.create(conversa=self.conversa, remetente=Mensagem.Remetente.ATENDENTE, texto="Oi")
        )
        Mensagem.objects.create(conversa=self.conversa, remetente=Mensagem.Remetente.ATENDENTE, texto="Oi",
                                atendente=self.ana)

    def test_telegram_message_id_duplicado_e_barrado(self):
        Mensagem.objects.create(conversa=self.conversa, remetente="cliente", texto="oi", telegram_message_id=42)
        self.assertBancoRecusa(
            lambda: Mensagem.objects.create(conversa=self.conversa, remetente="cliente", texto="oi",
                                            telegram_message_id=42)
        )

    def test_regra_de_duplicidade_vale_so_para_mensagens_do_cliente(self):
        # Respostas do bot e mensagens sem id do Telegram não entram no índice parcial.
        Mensagem.objects.create(conversa=self.conversa, remetente="cliente", texto="a", telegram_message_id=7)
        Mensagem.objects.create(conversa=self.conversa, remetente="bot", texto="b", telegram_message_id=7)
        Mensagem.objects.create(conversa=self.conversa, remetente="cliente", texto="c")
        Mensagem.objects.create(conversa=self.conversa, remetente="cliente", texto="d")
        self.assertEqual(self.conversa.mensagens.count(), 4)

    def test_relacionamento_mensagem_intencao_faq(self):
        intencao = Intencao.objects.create(slug="duvida_teste", nome="Dúvida teste")
        cat = CategoriaFAQ.objects.create(nome="Categoria Teste")
        faq = PerguntaFAQ.objects.create(categoria=cat, pergunta="Pergunta teste?", resposta="Resposta teste.")
        Mensagem.objects.create(conversa=self.conversa, remetente="cliente", texto="?", intencao=intencao,
                                confianca=0.9)
        Mensagem.objects.create(conversa=self.conversa, remetente="bot", texto=faq.resposta, faq=faq,
                                origem_resposta=Mensagem.Origem.FAQ)
        self.assertEqual(intencao.mensagens.count(), 1)
        self.assertEqual(faq.mensagens.get().conversa.contato, self.cliente)
        # Consulta com JOIN: mensagens de clientes do Telegram com intenção "duvida_teste".
        self.assertEqual(
            Mensagem.objects.filter(intencao__slug="duvida_teste", conversa__contato__canal=Canal.TELEGRAM).count(), 1
        )


class FAQTests(BaseTeste):
    def test_pergunta_repetida_na_mesma_categoria_e_barrada(self):
        cat = CategoriaFAQ.objects.create(nome="Pagamentos Teste")
        PerguntaFAQ.objects.create(categoria=cat, pergunta="Como pago?", resposta="Pix.")
        self.assertBancoRecusa(lambda: PerguntaFAQ.objects.create(categoria=cat, pergunta="Como pago?", resposta="x"))

    def test_categoria_com_perguntas_nao_pode_ser_apagada(self):
        from django.db.models import ProtectedError

        cat = CategoriaFAQ.objects.create(nome="Protegida Teste")
        PerguntaFAQ.objects.create(categoria=cat, pergunta="P?", resposta="R.")
        with self.assertRaises(ProtectedError):
            cat.delete()


class TicketTests(BaseTeste):
    def test_protocolo_sequencial_e_unico(self):
        t1 = services.abrir_ticket(self.cliente, "Assunto 1", "Descrição 1")
        t2 = services.abrir_ticket(self.visitante, "Assunto 2", "Descrição 2")
        self.assertRegex(t1.protocolo, r"^TCK-\d{4,}$")
        self.assertEqual(t1.protocolo, f"TCK-{t1.pk:04d}")
        self.assertEqual(t2.protocolo, f"TCK-{t2.pk:04d}")
        n1, n2 = (int(re.search(r"\d+", t.protocolo).group()) for t in (t1, t2))
        self.assertEqual(n2, n1 + 1)
        # Recarregado do banco continua com o definitivo (não ficou o provisório TMP-...).
        self.assertEqual(Ticket.objects.get(pk=t1.pk).protocolo, t1.protocolo)
        self.assertBancoRecusa(lambda: Ticket.objects.filter(pk=t2.pk).update(protocolo=t1.protocolo))

    def test_ticket_ligado_a_conversa_gera_evento(self):
        conversa = services.conversa_aberta(self.cliente)
        t = services.abrir_ticket(self.cliente, "Boleto", "Não chegou", conversa=conversa,
                                  categoria=Ticket.Categoria.FINANCEIRO)
        ev = conversa.eventos.get(tipo=EventoConversa.Tipo.TICKET)
        self.assertEqual(ev.detalhe, t.protocolo)
        self.assertEqual(list(self.cliente.tickets.all()), [t])

    def test_resolver_ticket_marca_data_e_responsavel(self):
        t = services.abrir_ticket(self.cliente, "Senha", "Esqueci")
        services.atualizar_ticket(t, self.ana, status=Ticket.Status.RESOLVIDO, resposta="Feito")
        t.refresh_from_db()
        self.assertEqual(t.status, Ticket.Status.RESOLVIDO)
        self.assertIsNotNone(t.resolvido_em)
        self.assertEqual(t.responsavel, self.ana)
        self.envio.assert_called()  # avisou o cliente (mockado)


# ---------------------------------------------------------------------------
# 2. Ciclo de vida do atendimento (services)
# ---------------------------------------------------------------------------
class CicloAtendimentoTests(BaseTeste):
    def setUp(self):
        super().setUp()
        self.conversa = services.conversa_aberta(self.cliente)

    def _tipos(self):
        return list(self.conversa.eventos.values_list("tipo", flat=True))

    def test_escalar_coloca_na_fila(self):
        services.escalar(self.conversa, "Cliente pediu atendente")
        self.conversa.refresh_from_db()
        self.assertEqual(self.conversa.status, Conversa.Status.FILA)
        self.assertIsNotNone(self.conversa.escalada_em)
        self.assertIn(EventoConversa.Tipo.ESCALADA, self._tipos())

    def test_segundo_atendente_nao_consegue_assumir(self):
        services.escalar(self.conversa)
        services.assumir(self.conversa, self.ana)
        with self.assertRaises(services.ErroAtendimento):
            services.assumir(self.conversa, self.beto)
        self.conversa.refresh_from_db()
        self.assertEqual(self.conversa.atendente, self.ana)
        self.assertEqual(self.conversa.status, Conversa.Status.HUMANO)
        # Assumir de novo pelo mesmo atendente não é erro nem gera evento duplicado.
        services.assumir(self.conversa, self.ana)
        self.assertEqual(self._tipos().count(EventoConversa.Tipo.ASSUMIDA), 1)

    def test_assumir_avisa_cliente_pelo_telegram(self):
        services.escalar(self.conversa)
        services.assumir(self.conversa, self.ana)
        chat_id, texto = self.envio.call_args.args[:2]
        self.assertEqual(chat_id, 111)
        self.assertIn("Ana", texto)
        msg = self.conversa.mensagens.last()
        self.assertEqual(msg.remetente, Mensagem.Remetente.SISTEMA)
        self.assertEqual(msg.telegram_message_id, 999)

    def test_transferir_gera_evento_com_origem_e_destino(self):
        services.escalar(self.conversa)
        services.assumir(self.conversa, self.ana)
        services.transferir(self.conversa, self.ana, self.beto)
        self.conversa.refresh_from_db()
        self.assertEqual(self.conversa.atendente, self.beto)
        ev = self.conversa.eventos.get(tipo=EventoConversa.Tipo.TRANSFERIDA)
        self.assertEqual((ev.usuario, ev.para_usuario), (self.ana, self.beto))

    def test_transferir_para_si_mesmo_ou_fora_do_atendimento_e_erro(self):
        with self.assertRaises(services.ErroAtendimento):
            services.transferir(self.conversa, self.ana, self.beto)  # ainda está com o bot
        services.escalar(self.conversa)
        services.assumir(self.conversa, self.ana)
        with self.assertRaises(services.ErroAtendimento):
            services.transferir(self.conversa, self.ana, self.ana)

    def test_devolver_ao_bot_gera_evento_e_limpa_atendente(self):
        services.escalar(self.conversa)
        services.assumir(self.conversa, self.ana)
        services.devolver_ao_bot(self.conversa, self.ana)
        self.conversa.refresh_from_db()
        self.assertEqual(self.conversa.status, Conversa.Status.BOT)
        self.assertIsNone(self.conversa.atendente)
        self.assertIn(EventoConversa.Tipo.DEVOLVIDA_BOT, self._tipos())

    def test_encerrar_gera_evento_e_libera_nova_conversa(self):
        services.escalar(self.conversa)
        services.assumir(self.conversa, self.ana)
        services.encerrar(self.conversa, self.ana)
        self.conversa.refresh_from_db()
        self.assertEqual(self.conversa.status, Conversa.Status.ENCERRADA)
        self.assertIsNotNone(self.conversa.encerrada_em)
        self.assertEqual(
            self._tipos(),
            [EventoConversa.Tipo.CRIADA, EventoConversa.Tipo.ESCALADA, EventoConversa.Tipo.ASSUMIDA,
             EventoConversa.Tipo.ENCERRADA],
        )
        # Encerrar de novo é inofensivo; e agora o cliente pode abrir outra conversa.
        services.encerrar(self.conversa, self.ana)
        self.assertEqual(self._tipos().count(EventoConversa.Tipo.ENCERRADA), 1)
        nova = services.conversa_aberta(self.cliente)
        self.assertNotEqual(nova.pk, self.conversa.pk)
        with self.assertRaises(services.ErroAtendimento):
            services.assumir(self.conversa, self.beto)

    def test_conversa_do_site_nao_chama_telegram(self):
        conversa = services.conversa_aberta(self.visitante)
        self.envio.reset_mock()
        services.escalar(conversa)
        services.assumir(conversa, self.ana)
        services.enviar_ao_cliente(conversa, "Olá!", remetente=Mensagem.Remetente.ATENDENTE, atendente=self.ana)
        self.envio.assert_not_called()
        self.assertEqual(conversa.mensagens.filter(remetente="atendente").count(), 1)


# ---------------------------------------------------------------------------
# 3. Dados de teste e admin
# ---------------------------------------------------------------------------
class PopularDemoTests(TestCase):
    def _contagens(self):
        modelos = (Usuario, Intencao, CategoriaFAQ, PerguntaFAQ, Contato, Conversa, Mensagem, Ticket)
        return {m.__name__: m.objects.count() for m in modelos}

    def test_popular_demo_e_idempotente(self):
        call_command("popular_demo", "--conversas", stdout=StringIO())
        primeira = self._contagens()
        call_command("popular_demo", "--conversas", stdout=StringIO())
        self.assertEqual(self._contagens(), primeira)
        self.assertEqual(primeira["Usuario"], 3)
        self.assertEqual(primeira["Conversa"], 40)
        self.assertTrue(Usuario.objects.get(username="atendente1").check_password("teste123"))


class AdminTests(BaseTeste):
    def test_paginas_do_admin_abrem(self):
        sup = Usuario.objects.create_superuser("admin_teste", password="x")
        self.client.force_login(sup)
        conversa = services.conversa_aberta(self.cliente)
        services.abrir_ticket(self.cliente, "Assunto", "Desc", conversa=conversa)
        for modelo in ("usuario", "contato", "conversa", "mensagem", "eventoconversa", "intencao",
                       "categoriafaq", "perguntafaq", "ticket"):
            r = self.client.get(f"/admin/core/{modelo}/")
            self.assertEqual(r.status_code, 200, modelo)
        self.assertEqual(self.client.get(f"/admin/core/conversa/{conversa.pk}/change/").status_code, 200)
        self.assertEqual(self.client.get("/admin/core/ticket/?q=TCK").status_code, 200)
