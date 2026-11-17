from django.urls import path

from . import views

app_name = "webchat"
urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("chat/", views.chat, name="chat"),
    path("api/chat/iniciar/", views.api_iniciar, name="api_iniciar"),
    path("api/chat/enviar/", views.api_enviar, name="api_enviar"),
    path("api/chat/mensagens/", views.api_mensagens, name="api_mensagens"),
    path("api/chat/nova/", views.api_nova_conversa, name="api_nova"),
    path("saude/", views.saude, name="saude"),
]
