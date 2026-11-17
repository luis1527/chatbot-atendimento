"""
Admin do Django (/admin/) — visão "crua" do banco para o supervisor/equipe de dados.

O dia a dia dos atendentes é no painel (/painel/). Aqui é onde se confere
registros, corrige cadastro e audita o histórico.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.db.models import Count

from .models import (
    CategoriaFAQ, Contato, Conversa, EventoConversa, Intencao, Mensagem, PerguntaFAQ, Ticket, Usuario,
)


def _resumo(texto, n=60):
    texto = texto or ""
    return texto if len(texto) <= n else texto[: n - 1] + "…"


# ---------------------------------------------------------------------------
# Funcionários
# ---------------------------------------------------------------------------
@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ("username", "nome_exibicao", "cargo", "online", "is_active", "is_staff", "last_login")
    list_filter = ("cargo", "online", "is_active", "is_staff")
    search_fields = ("username", "apelido", "first_name", "last_name", "email")
    ordering = ("username",)
    readonly_fields = ("last_login", "date_joined", "ultimo_acesso_painel")
    fieldsets = UserAdmin.fieldsets + (
        ("Atendimento", {"fields": ("cargo", "apelido", "online", "ultimo_acesso_painel")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Atendimento", {"fields": ("cargo", "apelido")}),
    )

    @admin.display(description="nome de exibição")
    def nome_exibicao(self, obj):
        return obj.nome_exibicao


# ---------------------------------------------------------------------------
# Clientes
# ---------------------------------------------------------------------------
class ConversaDoContatoInline(admin.TabularInline):
    model = Conversa
    fields = ("id", "status", "canal", "atendente", "avaliacao", "iniciada_em", "encerrada_em")
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Contato)
class ContatoAdmin(admin.ModelAdmin):
    list_display = ("nome", "canal", "telegram_chat_id", "telegram_username", "web_sessao", "total_conversas",
                    "ultimo_contato_em")
    list_filter = ("canal",)
    search_fields = ("nome", "telegram_username", "telegram_chat_id", "web_sessao", "email", "telefone")
    readonly_fields = ("criado_em", "ultimo_contato_em")
    inlines = [ConversaDoContatoInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_total_conversas=Count("conversas"))

    @admin.display(description="conversas", ordering="_total_conversas")
    def total_conversas(self, obj):
        return obj._total_conversas


# ---------------------------------------------------------------------------
# Base de conhecimento
# ---------------------------------------------------------------------------
@admin.register(Intencao)
class IntencaoAdmin(admin.ModelAdmin):
    list_display = ("slug", "nome", "descricao", "total_mensagens")
    search_fields = ("slug", "nome", "descricao")
    prepopulated_fields = {"slug": ("nome",)}

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_total=Count("mensagens"))

    @admin.display(description="mensagens classificadas", ordering="_total")
    def total_mensagens(self, obj):
        return obj._total


class PerguntaFAQInline(admin.StackedInline):
    model = PerguntaFAQ
    fields = ("pergunta", "resposta", "palavras_chave", "ativa", "vezes_usada")
    readonly_fields = ("vezes_usada",)
    extra = 0


@admin.register(CategoriaFAQ)
class CategoriaFAQAdmin(admin.ModelAdmin):
    list_display = ("nome", "ordem", "total_perguntas")
    list_editable = ("ordem",)
    search_fields = ("nome",)
    inlines = [PerguntaFAQInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_total=Count("perguntas"))

    @admin.display(description="perguntas", ordering="_total")
    def total_perguntas(self, obj):
        return obj._total


@admin.register(PerguntaFAQ)
class PerguntaFAQAdmin(admin.ModelAdmin):
    list_display = ("pergunta", "categoria", "ativa", "vezes_usada", "atualizada_em")
    list_filter = ("ativa", "categoria")
    list_editable = ("ativa",)
    search_fields = ("pergunta", "resposta", "palavras_chave")
    readonly_fields = ("vezes_usada", "criada_em", "atualizada_em")
    list_select_related = ("categoria",)


# ---------------------------------------------------------------------------
# Conversas
# ---------------------------------------------------------------------------
class MensagemInline(admin.TabularInline):
    model = Mensagem
    fields = ("criada_em", "remetente", "atendente", "texto", "intencao", "confianca", "origem_resposta", "faq")
    readonly_fields = fields
    extra = 0
    can_delete = False
    ordering = ("criada_em", "id")

    def has_add_permission(self, request, obj=None):
        return False


class EventoConversaInline(admin.TabularInline):
    model = EventoConversa
    fields = ("criado_em", "tipo", "usuario", "para_usuario", "detalhe")
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class TicketDaConversaInline(admin.TabularInline):
    model = Ticket
    fields = ("protocolo", "assunto", "status", "prioridade", "responsavel")
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Conversa)
class ConversaAdmin(admin.ModelAdmin):
    list_display = ("id", "contato", "canal", "status", "modo", "atendente", "avaliacao", "total_mensagens",
                    "iniciada_em", "atualizada_em")
    list_display_links = ("id", "contato")
    list_filter = ("status", "canal", "atendente", "avaliacao", "iniciada_em")
    search_fields = ("contato__nome", "contato__telegram_username", "motivo_escalonamento", "mensagens__texto")
    date_hierarchy = "iniciada_em"
    list_select_related = ("contato", "atendente")
    autocomplete_fields = ("contato", "atendente")
    readonly_fields = ("iniciada_em", "atualizada_em", "escalada_em", "assumida_em", "encerrada_em",
                       "ultima_leitura_atendente_em")
    fieldsets = (
        (None, {"fields": ("contato", "canal", "status", "modo", "atendente", "motivo_escalonamento")}),
        ("Avaliação", {"fields": ("avaliacao", "comentario_avaliacao")}),
        ("Linha do tempo", {"fields": readonly_fields}),
    )
    inlines = [MensagemInline, EventoConversaInline, TicketDaConversaInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_total_msgs=Count("mensagens", distinct=True))

    def get_search_results(self, request, queryset, search_term):
        qs, _ = super().get_search_results(request, queryset, search_term)
        return qs, True  # busca em mensagens__texto pode duplicar linhas

    @admin.display(description="mensagens", ordering="_total_msgs")
    def total_mensagens(self, obj):
        return obj._total_msgs


@admin.register(Mensagem)
class MensagemAdmin(admin.ModelAdmin):
    list_display = ("id", "conversa", "remetente", "texto_curto", "intencao", "confianca", "origem_resposta",
                    "atendente", "criada_em")
    list_filter = ("remetente", "origem_resposta", "intencao", "conversa__canal")
    search_fields = ("texto", "conversa__contato__nome")
    date_hierarchy = "criada_em"
    list_select_related = ("conversa__contato", "intencao", "atendente")
    raw_id_fields = ("conversa", "faq")
    readonly_fields = ("criada_em", "telegram_message_id")

    @admin.display(description="texto")
    def texto_curto(self, obj):
        return _resumo(obj.texto)


@admin.register(EventoConversa)
class EventoConversaAdmin(admin.ModelAdmin):
    """Trilha de auditoria: só leitura."""

    list_display = ("criado_em", "conversa", "tipo", "usuario", "para_usuario", "detalhe")
    list_filter = ("tipo", "usuario")
    search_fields = ("detalhe", "conversa__contato__nome")
    date_hierarchy = "criado_em"
    list_select_related = ("conversa__contato", "usuario", "para_usuario")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------
@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("protocolo", "assunto", "contato", "categoria", "prioridade", "status", "responsavel",
                    "criado_em", "resolvido_em")
    list_display_links = ("protocolo", "assunto")
    list_filter = ("status", "prioridade", "categoria", "responsavel")
    search_fields = ("protocolo", "assunto", "descricao", "contato__nome")
    date_hierarchy = "criado_em"
    list_select_related = ("contato", "responsavel")
    autocomplete_fields = ("contato", "responsavel")
    raw_id_fields = ("conversa",)
    readonly_fields = ("protocolo", "criado_em", "atualizado_em", "resolvido_em")
    fieldsets = (
        (None, {"fields": ("protocolo", "contato", "conversa", "assunto", "descricao")}),
        ("Classificação", {"fields": ("categoria", "prioridade", "status", "responsavel")}),
        ("Solução", {"fields": ("resposta",)}),
        ("Datas", {"fields": ("criado_em", "atualizado_em", "resolvido_em")}),
    )
