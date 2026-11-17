"""
Carrega dados de teste: funcionários, intenções, FAQ.

    python manage.py popular_demo            # cria o que faltar (pode rodar várias vezes)
    python manage.py popular_demo --conversas # também cria conversas/tickets fictícios
"""
import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import (
    CategoriaFAQ, Canal, Contato, Conversa, EventoConversa, Intencao, Mensagem, PerguntaFAQ, Ticket, Usuario,
)

SENHA_PADRAO = "teste123"

FUNCIONARIOS = [
    ("supervisor", "Supervisor Teste", Usuario.Cargo.SUPERVISOR),
    ("atendente1", "Atendente Teste 1", Usuario.Cargo.ATENDENTE),
    ("atendente2", "Atendente Teste 2", Usuario.Cargo.ATENDENTE),
]

INTENCOES = [
    ("saudacao", "Saudação", "Oi, olá, bom dia"),
    ("duvida", "Dúvida", "Pergunta sobre o serviço ou produto"),
    ("suporte", "Suporte técnico", "Algo não está funcionando"),
    ("financeiro", "Financeiro", "Pagamento, boleto, cobrança, reembolso"),
    ("reclamacao", "Reclamação", "Insatisfação com o serviço"),
    ("abrir_ticket", "Abrir ticket", "Quer registrar uma solicitação"),
    ("status_ticket", "Consultar ticket", "Quer saber o andamento de um ticket"),
    ("falar_humano", "Falar com atendente", "Pede atendimento humano"),
    ("despedida", "Despedida/agradecimento", "Tchau, obrigado"),
    ("outro", "Outro", "Não se encaixa nas demais"),
]

FAQ = {
    "Geral": [
        ("Qual o horário de atendimento?",
         "Nosso atendimento humano funciona de segunda a sexta, das 8h às 18h, e aos sábados das 8h às 12h. "
         "O assistente virtual responde 24 horas.",
         "horário, horario, funciona, abre, fecha, expediente"),
        ("Como falo com um atendente?",
         "É só pedir \"falar com atendente\" ou tocar no botão 👤 Falar com atendente. "
         "Um funcionário assume a conversa assim que estiver disponível.",
         "atendente, humano, pessoa, falar com alguém"),
        ("Onde vocês ficam?",
         "Somos a Empresa Teste, na Rua Teste, 123 - Centro. Também atendemos 100% online por aqui e pelo Telegram.",
         "endereço, endereco, onde fica, localização, local"),
    ],
    "Conta e acesso": [
        ("Esqueci minha senha, o que faço?",
         "Na tela de login, clique em \"Esqueci minha senha\" e informe seu e-mail. "
         "Você receberá um link para criar uma nova senha em até 5 minutos (confira o spam).",
         "senha, esqueci, recuperar, redefinir, login, acesso"),
        ("Como altero meus dados cadastrais?",
         "Acesse Minha Conta > Dados pessoais e clique em Editar. Para alterar CPF, abra um ticket.",
         "alterar dados, cadastro, atualizar, email, telefone"),
    ],
    "Pagamentos": [
        ("Quais as formas de pagamento?",
         "Aceitamos Pix, cartão de crédito (até 12x) e boleto bancário.",
         "pagamento, pagar, pix, cartão, cartao, boleto, parcelar"),
        ("Como emito a segunda via do boleto?",
         "Em Minha Conta > Financeiro, clique em \"2ª via\" ao lado da fatura. O boleto atualizado é gerado na hora.",
         "segunda via, 2 via, boleto, fatura, vencido"),
        ("Como peço reembolso?",
         "Reembolsos podem ser pedidos em até 7 dias após a compra. Abra um ticket na categoria Financeiro "
         "informando o número do pedido; o prazo de análise é de até 5 dias úteis.",
         "reembolso, estorno, devolver dinheiro, cancelar compra"),
    ],
    "Suporte técnico": [
        ("O sistema está fora do ar, o que faço?",
         "Primeiro, tente atualizar a página e limpar o cache do navegador. Se continuar, abra um ticket na "
         "categoria Suporte técnico com um print do erro.",
         "fora do ar, erro, não carrega, nao funciona, travou, bug"),
        ("Qual o prazo de resposta de um ticket?",
         "Tickets de prioridade alta são respondidos em até 4 horas úteis; média em até 1 dia útil; baixa em até 3 dias úteis.",
         "prazo, ticket, demora, quanto tempo, resposta"),
    ],
}

CLIENTES = ["Cliente Teste 1", "Cliente Teste 2", "Cliente Teste 3", "Maria Teste", "João Teste", "Visitante Teste"]
PERGUNTAS_EXEMPLO = [
    ("Qual o horário de atendimento?", "duvida"),
    ("esqueci minha senha", "suporte"),
    ("como pago com pix?", "financeiro"),
    ("quero falar com um atendente", "falar_humano"),
    ("o sistema não carrega", "suporte"),
    ("quero meu dinheiro de volta", "financeiro"),
    ("oi, bom dia!", "saudacao"),
    ("o atendimento foi péssimo", "reclamacao"),
]


class Command(BaseCommand):
    help = "Popula o banco com dados de teste (funcionários, intenções e FAQ)."

    def add_arguments(self, parser):
        parser.add_argument("--conversas", action="store_true", help="Cria também conversas e tickets fictícios.")

    @transaction.atomic
    def handle(self, *args, **opts):
        for username, nome, cargo in FUNCIONARIOS:
            u, criado = Usuario.objects.get_or_create(
                username=username,
                defaults={"apelido": nome, "first_name": nome, "cargo": cargo, "is_staff": cargo == Usuario.Cargo.SUPERVISOR,
                          "is_superuser": cargo == Usuario.Cargo.SUPERVISOR},
            )
            if criado:
                u.set_password(SENHA_PADRAO)
                u.save()
                self.stdout.write(f"  funcionário {username} / {SENHA_PADRAO}")

        for slug, nome, desc in INTENCOES:
            Intencao.objects.update_or_create(slug=slug, defaults={"nome": nome, "descricao": desc})

        for ordem, (cat_nome, itens) in enumerate(FAQ.items()):
            cat, _ = CategoriaFAQ.objects.update_or_create(nome=cat_nome, defaults={"ordem": ordem})
            for pergunta, resposta, chaves in itens:
                PerguntaFAQ.objects.update_or_create(
                    categoria=cat, pergunta=pergunta, defaults={"resposta": resposta, "palavras_chave": chaves},
                )

        if opts["conversas"]:
            self._conversas()
        self.stdout.write(self.style.SUCCESS("Dados de teste prontos."))

    def _conversas(self):
        """Histórico fictício dos últimos 14 dias, para o dashboard ter o que mostrar."""
        random.seed(42)
        atendentes = list(Usuario.objects.filter(cargo=Usuario.Cargo.ATENDENTE))
        intencoes = {i.slug: i for i in Intencao.objects.all()}
        faqs = list(PerguntaFAQ.objects.all())
        agora = timezone.now()
        for n in range(40):
            canal = random.choice([Canal.TELEGRAM, Canal.TELEGRAM, Canal.WEB])
            nome = random.choice(CLIENTES)
            ident = 900000000 + n
            contato = Contato.objects.create(
                canal=canal, nome=nome,
                telegram_chat_id=ident if canal == Canal.TELEGRAM else None,
                web_sessao=f"demo-{ident}" if canal == Canal.WEB else None,
            )
            inicio = agora - timedelta(days=random.randint(0, 13), hours=random.randint(0, 10), minutes=random.randint(0, 59))
            conv = Conversa.objects.create(contato=contato, canal=canal, status=Conversa.Status.ENCERRADA)
            pergunta, slug = random.choice(PERGUNTAS_EXEMPLO)
            msgs = [Mensagem(conversa=conv, remetente="cliente", texto=pergunta, intencao=intencoes[slug],
                             confianca=round(random.uniform(0.7, 0.99), 2))]
            humano = slug in ("falar_humano", "reclamacao") or random.random() < 0.25
            if humano and atendentes:
                at = random.choice(atendentes)
                conv.atendente = at
                conv.escalada_em = inicio + timedelta(minutes=1)
                conv.assumida_em = conv.escalada_em + timedelta(minutes=random.randint(1, 15))
                msgs.append(Mensagem(conversa=conv, remetente="atendente", atendente=at, origem_resposta="humano",
                                     texto="Olá! Já estou verificando para você."))
            else:
                faq = random.choice(faqs)
                msgs.append(Mensagem(conversa=conv, remetente="bot", origem_resposta=random.choice(["faq", "ia"]),
                                     faq=faq, texto=faq.resposta))
            conv.avaliacao = random.choice([None, 3, 4, 4, 5, 5, 5])
            conv.encerrada_em = inicio + timedelta(minutes=random.randint(3, 40))
            conv.save()
            Mensagem.objects.bulk_create(msgs)
            Conversa.objects.filter(pk=conv.pk).update(iniciada_em=inicio, atualizada_em=conv.encerrada_em)
            Mensagem.objects.filter(conversa=conv).update(criada_em=inicio)
            EventoConversa.objects.create(conversa=conv, tipo="criada")
            if random.random() < 0.3:
                t = Ticket.objects.create(
                    contato=contato, conversa=conv, assunto=f"Solicitação de teste {n}", descricao=pergunta,
                    categoria=random.choice(Ticket.Categoria.values),
                    prioridade=random.choice(Ticket.Prioridade.values),
                    status=random.choice([Ticket.Status.ABERTO, Ticket.Status.EM_ANDAMENTO, Ticket.Status.RESOLVIDO]),
                )
                Ticket.objects.filter(pk=t.pk).update(criado_em=inicio)
        self.stdout.write("  40 conversas fictícias criadas")
