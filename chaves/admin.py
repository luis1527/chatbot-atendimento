from django.contrib import admin

from .models import Chave, Emprestimo, Movimentacao, Sala, Usuario


class ChaveInline(admin.TabularInline):
    model = Chave
    extra = 0
    fields = ("codigo", "descricao", "status")


@admin.register(Sala)
class SalaAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nome", "tipo", "bloco", "andar", "capacidade", "ativa")
    list_filter = ("tipo", "bloco", "ativa")
    search_fields = ("codigo", "nome")
    inlines = [ChaveInline]


@admin.register(Chave)
class ChaveAdmin(admin.ModelAdmin):
    list_display = ("codigo", "sala", "status", "descricao")
    list_filter = ("status", "sala__bloco")
    search_fields = ("codigo", "sala__nome", "sala__codigo")
    list_select_related = ("sala",)


@admin.register(Usuario)
class UsuarioAdmin(admin.ModelAdmin):
    list_display = ("nome", "matricula", "tipo", "email", "telefone", "ativo")
    list_filter = ("tipo", "ativo")
    search_fields = ("nome", "matricula", "email")


@admin.register(Emprestimo)
class EmprestimoAdmin(admin.ModelAdmin):
    list_display = ("chave", "usuario", "retirada_em", "devolucao_prevista", "devolvido_em", "registrado_por")
    list_filter = ("devolvido_em",)
    search_fields = ("chave__codigo", "usuario__nome", "usuario__matricula")
    list_select_related = ("chave", "usuario", "registrado_por")
    date_hierarchy = "retirada_em"


@admin.register(Movimentacao)
class MovimentacaoAdmin(admin.ModelAdmin):
    """Somente leitura: o histórico não é editado à mão."""
    list_display = ("data_hora", "tipo", "chave", "usuario", "operador", "observacao")
    list_filter = ("tipo",)
    search_fields = ("chave__codigo", "usuario__nome")
    list_select_related = ("chave", "usuario", "operador")
    date_hierarchy = "data_hora"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
