from django.urls import path

from . import api, views

app_name = "painel"

urlpatterns = [
    # Login
    path("entrar/", views.Entrar.as_view(), name="login"),
    path("sair/", views.Sair.as_view(), name="logout"),

    # Atendimentos
    path("", views.fila, name="fila"),
    path("conversas/<int:pk>/", views.fila, name="conversa"),

    # Tickets
    path("tickets/", views.tickets, name="tickets"),
    path("tickets/<int:pk>/", views.ticket_detalhe, name="ticket_detalhe"),

    # Dashboard
    path("dashboard/", views.dashboard, name="dashboard"),

    # FAQ
    path("faq/", views.faq, name="faq"),
    path("faq/perguntas/nova/", views.faq_pergunta, name="faq_pergunta_nova"),
    path("faq/perguntas/<int:pk>/", views.faq_pergunta, name="faq_pergunta"),
    path("faq/perguntas/<int:pk>/alternar/", views.faq_pergunta_alternar, name="faq_pergunta_alternar"),
    path("faq/perguntas/<int:pk>/excluir/", views.faq_pergunta_excluir, name="faq_pergunta_excluir"),
    path("faq/categorias/nova/", views.faq_categoria, name="faq_categoria_nova"),
    path("faq/categorias/<int:pk>/", views.faq_categoria, name="faq_categoria"),
    path("faq/categorias/<int:pk>/excluir/", views.faq_categoria_excluir, name="faq_categoria_excluir"),

    # Funcionários (supervisor)
    path("funcionarios/", views.funcionarios, name="funcionarios"),
    path("funcionarios/novo/", views.funcionario_form, name="funcionario_novo"),
    path("funcionarios/<int:pk>/", views.funcionario_form, name="funcionario_editar"),
    path("funcionarios/<int:pk>/senha/", views.funcionario_senha, name="funcionario_senha"),
    path("funcionarios/<int:pk>/alternar/", views.funcionario_alternar, name="funcionario_alternar"),

    # API JSON (polling)
    path("api/status/", api.status, name="api_status"),
    path("api/online/", api.alternar_online, name="api_online"),
    path("api/conversas/", api.conversas, name="api_conversas"),
    path("api/conversas/<int:pk>/", api.conversa_detalhe, name="api_conversa"),
    path("api/conversas/<int:pk>/mensagens/", api.conversa_mensagens, name="api_mensagens"),
    path("api/conversas/<int:pk>/enviar/", api.enviar, name="api_enviar"),
    path("api/conversas/<int:pk>/<str:nome>/", api.acao, name="api_acao"),
]
