from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Chatbot de Atendimento — Administração"
admin.site.site_title = "Chatbot Admin"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("telegram/", include("bot.urls")),
    path("painel/", include("painel.urls")),
    path("", include("webchat.urls")),
]
