"""
Modelo de dados do Controle de Chaves (ver docs/diagrama-er-chaves.drawio).

    Sala         1 ── N  Chave          (uma sala pode ter várias cópias de chave)
    Chave        1 ── N  Emprestimo
    Usuario      1 ── N  Emprestimo     (quem retira a chave)
    Chave        1 ── N  Movimentacao   (histórico completo da chave)
    Emprestimo   1 ── N  Movimentacao   (retirada e devolução daquele empréstimo)
    Usuario      1 ── N  Movimentacao   (quem retirou/devolveu)
    Funcionário  1 ── N  Emprestimo / Movimentacao (operador que registrou no sistema)

"Funcionário" é o login do painel (core.Usuario). "Usuario" aqui é a pessoa
que pega a chave (aluno, professor, servidor ou visitante) e não precisa de login.

Regras garantidas pelo banco (constraints), não só pelo código:
  - código da sala, código da chave e matrícula do usuário são únicos;
  - uma chave tem no máximo UM empréstimo em aberto ao mesmo tempo;
  - devolução prevista e devolução real não podem ser antes da retirada;
  - quem devolveu está preenchido se, e somente se, houve devolução;
  - capacidade da sala, quando informada, é maior que zero;
  - nada é apagado em cascata: sala com chave, chave com empréstimo e
    usuário com empréstimo ficam protegidos (PROTECT) para não perder histórico.
"""
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone


class Usuario(models.Model):
    """Pessoa que retira chaves (não acessa o sistema)."""

    class Tipo(models.TextChoices):
        ALUNO = "aluno", "Aluno"
        PROFESSOR = "professor", "Professor"
        SERVIDOR = "servidor", "Servidor"
        VISITANTE = "visitante", "Visitante"

    nome = models.CharField(max_length=120)
    matricula = models.CharField("matrícula", max_length=30, unique=True)
    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.ALUNO)
    email = models.EmailField("e-mail", blank=True)
    telefone = models.CharField(max_length=30, blank=True)
    ativo = models.BooleanField(default=True, help_text="Usuário inativo não pode retirar chaves.")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "usuário"
        verbose_name_plural = "usuários"
        constraints = [
            models.CheckConstraint(
                condition=Q(tipo__in=["aluno", "professor", "servidor", "visitante"]),
                name="chaves_usuario_tipo_valido",
            ),
        ]

    def __str__(self):
        return f"{self.nome} ({self.matricula})"


class Sala(models.Model):
    class Tipo(models.TextChoices):
        AULA = "aula", "Sala de aula"
        LABORATORIO = "laboratorio", "Laboratório"
        AUDITORIO = "auditorio", "Auditório"
        ADMINISTRATIVA = "administrativa", "Administrativa"

    codigo = models.CharField("código", max_length=20, unique=True, help_text="Ex.: B-204")
    nome = models.CharField(max_length=100)
    bloco = models.CharField(max_length=20, blank=True)
    andar = models.SmallIntegerField(null=True, blank=True)
    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.AULA)
    capacidade = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
    ativa = models.BooleanField(default=True)

    class Meta:
        ordering = ["codigo"]
        verbose_name = "sala"
        verbose_name_plural = "salas"
        constraints = [
            models.CheckConstraint(
                condition=Q(capacidade__isnull=True) | Q(capacidade__gt=0),
                name="chaves_sala_capacidade_positiva",
            ),
        ]

    def __str__(self):
        return f"{self.codigo} · {self.nome}"


class Chave(models.Model):
    class Status(models.TextChoices):
        DISPONIVEL = "disponivel", "Disponível"
        EMPRESTADA = "emprestada", "Emprestada"
        MANUTENCAO = "manutencao", "Em manutenção"
        PERDIDA = "perdida", "Perdida"

    sala = models.ForeignKey(Sala, on_delete=models.PROTECT, related_name="chaves")
    codigo = models.CharField("código", max_length=30, unique=True, help_text="Ex.: B-204-01")
    descricao = models.CharField("descrição", max_length=150, blank=True, help_text="Ex.: cópia reserva, chaveiro azul")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DISPONIVEL)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["codigo"]
        verbose_name = "chave"
        verbose_name_plural = "chaves"
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=["disponivel", "emprestada", "manutencao", "perdida"]),
                name="chaves_chave_status_valido",
            ),
        ]

    def __str__(self):
        return self.codigo


class Emprestimo(models.Model):
    chave = models.ForeignKey(Chave, on_delete=models.PROTECT, related_name="emprestimos")
    usuario = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name="emprestimos")
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="emprestimos_registrados",
        verbose_name="registrado por",
    )
    retirada_em = models.DateTimeField(default=timezone.now)
    devolucao_prevista = models.DateTimeField("devolução prevista")
    devolvido_em = models.DateTimeField("devolvido em", null=True, blank=True)
    recebido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="devolucoes_recebidas", verbose_name="recebido por",
    )
    observacao = models.CharField("observação", max_length=255, blank=True)

    class Meta:
        ordering = ["-retirada_em"]
        verbose_name = "empréstimo"
        verbose_name_plural = "empréstimos"
        constraints = [
            # Uma chave não pode estar emprestada duas vezes ao mesmo tempo.
            models.UniqueConstraint(
                fields=["chave"], condition=Q(devolvido_em__isnull=True),
                name="chaves_um_emprestimo_aberto_por_chave",
            ),
            models.CheckConstraint(
                condition=Q(devolucao_prevista__gt=F("retirada_em")),
                name="chaves_emprestimo_prevista_apos_retirada",
            ),
            models.CheckConstraint(
                condition=Q(devolvido_em__isnull=True) | Q(devolvido_em__gte=F("retirada_em")),
                name="chaves_emprestimo_devolucao_apos_retirada",
            ),
            models.CheckConstraint(
                condition=(Q(devolvido_em__isnull=True) & Q(recebido_por__isnull=True))
                | (Q(devolvido_em__isnull=False) & Q(recebido_por__isnull=False)),
                name="chaves_emprestimo_devolucao_completa",
            ),
        ]
        indexes = [models.Index(fields=["devolvido_em", "devolucao_prevista"], name="chaves_emp_aberto_idx")]

    @property
    def aberto(self):
        return self.devolvido_em is None

    @property
    def atrasado(self):
        return self.aberto and self.devolucao_prevista < timezone.now()

    @property
    def situacao(self):
        if not self.aberto:
            return "Devolvido com atraso" if self.devolvido_em > self.devolucao_prevista else "Devolvido"
        return "Atrasado" if self.atrasado else "Em aberto"

    def __str__(self):
        return f"{self.chave} → {self.usuario.nome}"


class Movimentacao(models.Model):
    """Histórico (auditoria) de tudo que acontece com uma chave. Nunca é editado."""

    class Tipo(models.TextChoices):
        RETIRADA = "retirada", "Retirada"
        DEVOLUCAO = "devolucao", "Devolução"
        MANUTENCAO = "manutencao", "Enviada para manutenção"
        PERDA = "perda", "Registrada como perdida"
        LIBERACAO = "liberacao", "Liberada (disponível)"
        CADASTRO = "cadastro", "Cadastrada"

    chave = models.ForeignKey(Chave, on_delete=models.PROTECT, related_name="movimentacoes")
    emprestimo = models.ForeignKey(
        Emprestimo, on_delete=models.PROTECT, null=True, blank=True, related_name="movimentacoes",
        verbose_name="empréstimo",
    )
    usuario = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, null=True, blank=True, related_name="movimentacoes",
        help_text="Quem retirou/devolveu (só em retirada e devolução).",
    )
    operador = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="movimentacoes_chaves",
        help_text="Funcionário que registrou no sistema.",
    )
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    data_hora = models.DateTimeField(default=timezone.now)
    observacao = models.CharField("observação", max_length=255, blank=True)

    class Meta:
        ordering = ["-data_hora", "-id"]
        verbose_name = "movimentação"
        verbose_name_plural = "movimentações"
        constraints = [
            models.CheckConstraint(
                condition=Q(tipo__in=["retirada", "devolucao", "manutencao", "perda", "liberacao", "cadastro"]),
                name="chaves_movimentacao_tipo_valido",
            ),
            # Retirada e devolução sempre apontam o empréstimo e a pessoa.
            models.CheckConstraint(
                condition=~Q(tipo__in=["retirada", "devolucao"])
                | (Q(emprestimo__isnull=False) & Q(usuario__isnull=False)),
                name="chaves_movimentacao_emprestimo_obrigatorio",
            ),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} · {self.chave}"
