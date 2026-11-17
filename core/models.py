"""
Modelo de dados do Chatbot de Atendimento.

Visão geral (ver docs/diagrama-er.drawio):

    Usuario (funcionário)  1 ── N  Conversa (atendente responsável)
    Contato (cliente)      1 ── N  Conversa
    Conversa               1 ── N  Mensagem
    Conversa               1 ── N  EventoConversa (histórico/auditoria)
    Contato                1 ── N  Ticket
    Conversa               1 ── N  Ticket
    CategoriaFAQ           1 ── N  PerguntaFAQ
    Intencao               1 ── N  Mensagem (intenção detectada)
    PerguntaFAQ            1 ── N  Mensagem (resposta usada)

Regras de integridade ficam no banco (constraints), não só no código:
  - um cliente do Telegram é cadastrado uma única vez (telegram_chat_id único);
  - cada cliente tem no máximo UMA conversa aberta por vez;
  - protocolo de ticket é único;
  - avaliação só aceita 1 a 5;
  - mensagem de atendente sempre aponta o funcionário que enviou.
"""
from django.contrib.auth.models import AbstractUser
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


# ---------------------------------------------------------------------------
# Funcionários
# ---------------------------------------------------------------------------
class Usuario(AbstractUser):
    """Funcionário que acessa o painel (atendente ou supervisor)."""

    class Cargo(models.TextChoices):
        ATENDENTE = "atendente", "Atendente"
        SUPERVISOR = "supervisor", "Supervisor"

    cargo = models.CharField(max_length=20, choices=Cargo.choices, default=Cargo.ATENDENTE)
    apelido = models.CharField(
        "nome de exibição", max_length=60, blank=True,
        help_text="Nome que o cliente vê no Telegram. Ex.: Ana",
    )
    online = models.BooleanField(default=False, help_text="Disponível para receber conversas.")
    ultimo_acesso_painel = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "funcionário"
        verbose_name_plural = "funcionários"

    @property
    def nome_exibicao(self):
        return self.apelido or self.get_full_name() or self.username

    @property
    def is_supervisor(self):
        return self.cargo == self.Cargo.SUPERVISOR or self.is_superuser

    def __str__(self):
        return self.nome_exibicao


# ---------------------------------------------------------------------------
# Clientes
# ---------------------------------------------------------------------------
class Canal(models.TextChoices):
    TELEGRAM = "telegram", "Telegram"
    WEB = "web", "Site"


class Contato(models.Model):
    """Cliente que conversa com o bot (pelo Telegram ou pelo chat do site)."""

    canal = models.CharField(max_length=20, choices=Canal.choices)
    nome = models.CharField(max_length=120)
    telegram_chat_id = models.BigIntegerField(null=True, blank=True, unique=True)
    telegram_username = models.CharField(max_length=64, blank=True)
    web_sessao = models.CharField(
        max_length=64, null=True, blank=True, unique=True,
        help_text="Identificador anônimo do visitante do chat do site.",
    )
    email = models.EmailField(blank=True)
    telefone = models.CharField(max_length=30, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    ultimo_contato_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-ultimo_contato_em"]
        constraints = [
            # Contato do Telegram precisa do chat_id; contato do site precisa da sessão.
            models.CheckConstraint(
                name="contato_identificador_por_canal",
                condition=(
                    Q(canal="telegram", telegram_chat_id__isnull=False)
                    | Q(canal="web", web_sessao__isnull=False)
                ),
            ),
        ]

    def __str__(self):
        return f"{self.nome} ({self.get_canal_display()})"


# ---------------------------------------------------------------------------
# Base de conhecimento
# ---------------------------------------------------------------------------
class Intencao(models.Model):
    """Intenção que o bot reconhece numa mensagem (ex.: duvida, falar_humano)."""

    slug = models.SlugField(max_length=40, unique=True)
    nome = models.CharField(max_length=80)
    descricao = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "intenção"
        verbose_name_plural = "intenções"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class CategoriaFAQ(models.Model):
    nome = models.CharField(max_length=80, unique=True)
    ordem = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "categoria do FAQ"
        verbose_name_plural = "categorias do FAQ"
        ordering = ["ordem", "nome"]

    def __str__(self):
        return self.nome


class PerguntaFAQ(models.Model):
    categoria = models.ForeignKey(CategoriaFAQ, on_delete=models.PROTECT, related_name="perguntas")
    pergunta = models.CharField(max_length=255)
    resposta = models.TextField()
    palavras_chave = models.CharField(
        max_length=255, blank=True,
        help_text="Separadas por vírgula. Usadas quando a IA está indisponível.",
    )
    ativa = models.BooleanField(default=True)
    vezes_usada = models.PositiveIntegerField(default=0)
    criada_em = models.DateTimeField(auto_now_add=True)
    atualizada_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "pergunta do FAQ"
        verbose_name_plural = "perguntas do FAQ"
        ordering = ["categoria__ordem", "pergunta"]
        constraints = [
            models.UniqueConstraint(fields=["categoria", "pergunta"], name="faq_pergunta_unica_por_categoria"),
        ]

    def lista_palavras_chave(self):
        return [p.strip().lower() for p in self.palavras_chave.split(",") if p.strip()]

    def __str__(self):
        return self.pergunta


# ---------------------------------------------------------------------------
# Conversas
# ---------------------------------------------------------------------------
class Conversa(models.Model):
    """
    Um atendimento do início ao fim.

    Ciclo de vida (status):
        bot  ──(cliente pede humano / bot não sabe)──►  fila
        fila ──(funcionário clica "Assumir")─────────►  humano
        humano ──(transferir)──► humano (outro funcionário)
        bot / fila / humano ──(encerrar)────────────►  encerrada
    """

    class Status(models.TextChoices):
        BOT = "bot", "Com o bot"
        FILA = "fila", "Aguardando atendente"
        HUMANO = "humano", "Em atendimento humano"
        ENCERRADA = "encerrada", "Encerrada"

    class Modo(models.TextChoices):
        MENU = "menu", "Menu"
        DUVIDA = "duvida", "Chat de dúvida"
        CONVERSA = "conversa", "Chat de conversa"
        TICKET = "ticket", "Abrindo ticket"

    STATUS_ABERTOS = (Status.BOT, Status.FILA, Status.HUMANO)

    contato = models.ForeignKey(Contato, on_delete=models.CASCADE, related_name="conversas")
    canal = models.CharField(max_length=20, choices=Canal.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.BOT, db_index=True)
    modo = models.CharField(
        max_length=20, choices=Modo.choices, default=Modo.MENU,
        help_text="Em qual 'chat' do menu o cliente está (só vale enquanto status=bot).",
    )
    atendente = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, blank=True, related_name="conversas",
    )
    motivo_escalonamento = models.CharField(max_length=255, blank=True)
    avaliacao = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    comentario_avaliacao = models.CharField(max_length=500, blank=True)
    iniciada_em = models.DateTimeField(auto_now_add=True)
    atualizada_em = models.DateTimeField(auto_now=True, db_index=True)
    escalada_em = models.DateTimeField(null=True, blank=True)
    assumida_em = models.DateTimeField(null=True, blank=True)
    encerrada_em = models.DateTimeField(null=True, blank=True)
    ultima_leitura_atendente_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-atualizada_em"]
        constraints = [
            # Cada cliente tem no máximo uma conversa aberta por vez.
            models.UniqueConstraint(
                fields=["contato"], condition=~Q(status="encerrada"),
                name="uma_conversa_aberta_por_contato",
            ),
            # Em atendimento humano sempre tem um responsável.
            models.CheckConstraint(
                name="conversa_humano_tem_atendente",
                condition=~Q(status="humano") | Q(atendente__isnull=False),
            ),
            models.CheckConstraint(
                name="conversa_avaliacao_1_a_5",
                condition=Q(avaliacao__isnull=True) | Q(avaliacao__gte=1, avaliacao__lte=5),
            ),
        ]

    @property
    def aberta(self):
        return self.status in self.STATUS_ABERTOS

    def __str__(self):
        return f"Conversa #{self.pk} - {self.contato.nome}"


class Mensagem(models.Model):
    class Remetente(models.TextChoices):
        CLIENTE = "cliente", "Cliente"
        BOT = "bot", "Bot"
        ATENDENTE = "atendente", "Atendente"
        SISTEMA = "sistema", "Sistema"

    class Origem(models.TextChoices):
        FAQ = "faq", "FAQ"
        IA = "ia", "IA (Gemini)"
        REGRA = "regra", "Regra fixa"
        HUMANO = "humano", "Humano"

    conversa = models.ForeignKey(Conversa, on_delete=models.CASCADE, related_name="mensagens")
    remetente = models.CharField(max_length=20, choices=Remetente.choices)
    atendente = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, blank=True, related_name="mensagens_enviadas",
    )
    texto = models.TextField()
    intencao = models.ForeignKey(Intencao, on_delete=models.SET_NULL, null=True, blank=True, related_name="mensagens")
    confianca = models.FloatField(null=True, blank=True, help_text="0 a 1, confiança da classificação.")
    origem_resposta = models.CharField(max_length=20, choices=Origem.choices, blank=True)
    faq = models.ForeignKey(PerguntaFAQ, on_delete=models.SET_NULL, null=True, blank=True, related_name="mensagens")
    botoes = models.JSONField(
        null=True, blank=True,
        help_text='Botões enviados junto: lista de linhas [[{"texto": "...", "dado": "..."}]].',
    )
    telegram_message_id = models.BigIntegerField(null=True, blank=True)
    criada_em = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["criada_em", "id"]
        indexes = [models.Index(fields=["conversa", "criada_em"], name="msg_conversa_data_idx")]
        constraints = [
            models.CheckConstraint(
                name="mensagem_atendente_identificado",
                condition=~Q(remetente="atendente") | Q(atendente__isnull=False),
            ),
            # Evita gravar duas vezes a mesma mensagem do Telegram (reenvio de webhook).
            models.UniqueConstraint(
                fields=["conversa", "telegram_message_id"],
                condition=Q(telegram_message_id__isnull=False, remetente="cliente"),
                name="mensagem_telegram_sem_duplicidade",
            ),
        ]

    def __str__(self):
        return f"[{self.remetente}] {self.texto[:40]}"


class EventoConversa(models.Model):
    """Histórico do que aconteceu na conversa (auditoria e métricas)."""

    class Tipo(models.TextChoices):
        CRIADA = "criada", "Conversa iniciada"
        ESCALADA = "escalada", "Enviada para a fila"
        ASSUMIDA = "assumida", "Assumida por atendente"
        TRANSFERIDA = "transferida", "Transferida"
        DEVOLVIDA_BOT = "devolvida_bot", "Devolvida ao bot"
        ENCERRADA = "encerrada", "Encerrada"
        AVALIADA = "avaliada", "Avaliada pelo cliente"
        TICKET = "ticket", "Ticket aberto"

    conversa = models.ForeignKey(Conversa, on_delete=models.CASCADE, related_name="eventos")
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    usuario = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, blank=True, related_name="eventos",
        help_text="Funcionário que fez a ação (vazio = cliente/bot).",
    )
    para_usuario = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, blank=True, related_name="eventos_recebidos",
        help_text="Destino, no caso de transferência.",
    )
    detalhe = models.CharField(max_length=255, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["criado_em", "id"]
        verbose_name = "evento da conversa"
        verbose_name_plural = "eventos das conversas"

    def __str__(self):
        return f"{self.get_tipo_display()} ({self.conversa_id})"


# ---------------------------------------------------------------------------
# Tickets (solicitações pendentes)
# ---------------------------------------------------------------------------
class Ticket(models.Model):
    class Status(models.TextChoices):
        ABERTO = "aberto", "Aberto"
        EM_ANDAMENTO = "em_andamento", "Em andamento"
        RESOLVIDO = "resolvido", "Resolvido"
        CANCELADO = "cancelado", "Cancelado"

    class Prioridade(models.TextChoices):
        BAIXA = "baixa", "Baixa"
        MEDIA = "media", "Média"
        ALTA = "alta", "Alta"

    class Categoria(models.TextChoices):
        DUVIDA = "duvida", "Dúvida"
        SUPORTE = "suporte", "Suporte técnico"
        FINANCEIRO = "financeiro", "Financeiro"
        RECLAMACAO = "reclamacao", "Reclamação"
        OUTRO = "outro", "Outro"

    protocolo = models.CharField(max_length=20, unique=True, editable=False)
    contato = models.ForeignKey(Contato, on_delete=models.CASCADE, related_name="tickets")
    conversa = models.ForeignKey(Conversa, on_delete=models.SET_NULL, null=True, blank=True, related_name="tickets")
    assunto = models.CharField(max_length=150)
    descricao = models.TextField()
    categoria = models.CharField(max_length=20, choices=Categoria.choices, default=Categoria.OUTRO)
    prioridade = models.CharField(max_length=10, choices=Prioridade.choices, default=Prioridade.MEDIA)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ABERTO, db_index=True)
    responsavel = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, blank=True, related_name="tickets",
    )
    resposta = models.TextField(blank=True, help_text="Solução informada ao cliente.")
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    resolvido_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-criado_em"]

    def save(self, *args, **kwargs):
        criando = self.pk is None and not self.protocolo
        if criando:
            # Protocolo provisório único; trocado pelo definitivo (baseado no id) logo abaixo.
            import uuid
            self.protocolo = f"TMP-{uuid.uuid4().hex[:12]}"
        super().save(*args, **kwargs)
        if criando:
            self.protocolo = f"TCK-{self.pk:04d}"
            super().save(update_fields=["protocolo"])

    def __str__(self):
        return f"{self.protocolo} - {self.assunto}"
