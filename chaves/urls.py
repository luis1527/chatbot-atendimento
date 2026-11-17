from django.urls import path

from . import views

app_name = "chaves"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("nova/", views.chave_form, name="chave_nova"),
    path("<int:pk>/", views.chave_detalhe, name="chave"),
    path("<int:pk>/editar/", views.chave_form, name="chave_editar"),
    path("<int:pk>/situacao/<str:tipo>/", views.chave_situacao, name="chave_situacao"),

    path("emprestimos/", views.emprestimos, name="emprestimos"),
    path("emprestimos/novo/", views.emprestimo_novo, name="emprestimo_novo"),
    path("emprestimos/<int:pk>/devolver/", views.emprestimo_devolver, name="emprestimo_devolver"),

    path("salas/", views.salas, name="salas"),
    path("salas/nova/", views.sala_form, name="sala_nova"),
    path("salas/<int:pk>/", views.sala_form, name="sala_editar"),

    path("usuarios/", views.usuarios, name="usuarios"),
    path("usuarios/novo/", views.usuario_form, name="usuario_novo"),
    path("usuarios/<int:pk>/", views.usuario_form, name="usuario_editar"),

    path("movimentacoes/", views.movimentacoes, name="movimentacoes"),
]
