"""
Configura o webhook do Telegram (produção na Vercel).

    python manage.py telegram_webhook --url https://SEU-APP.vercel.app/telegram/webhook/
    python manage.py telegram_webhook --info       # mostra a situação atual
    python manage.py telegram_webhook --apagar     # remove o webhook
    python manage.py telegram_webhook --comandos   # só atualiza comandos/descrição do bot

Com --url também configura os comandos (/start, /menu, /encerrar) e a descrição.
"""
import json
import re

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from bot import telegram_api

COMANDOS = [
    {"command": "start", "description": "Começar / boas-vindas"},
    {"command": "menu", "description": "Mostrar o menu de opções"},
    {"command": "encerrar", "description": "Encerrar o atendimento"},
]


class Command(BaseCommand):
    help = "Configura, consulta ou apaga o webhook do bot do Telegram."

    def add_arguments(self, parser):
        grupo = parser.add_mutually_exclusive_group(required=True)
        grupo.add_argument("--url", help="URL pública completa, terminando em /telegram/webhook/")
        grupo.add_argument("--info", action="store_true", help="Mostra getWebhookInfo")
        grupo.add_argument("--apagar", action="store_true", help="Apaga o webhook (deleteWebhook)")
        grupo.add_argument("--comandos", action="store_true", help="Só configura comandos e descrição")

    def handle(self, *args, **opts):
        if not settings.TELEGRAM_BOT_TOKEN:
            raise CommandError("TELEGRAM_BOT_TOKEN não configurado no .env")

        if opts["info"]:
            info = telegram_api.chamar("getWebhookInfo")
            self.stdout.write(json.dumps(info, indent=2, ensure_ascii=False) if info else "Falha ao consultar.")
            return
        if opts["apagar"]:
            ok = telegram_api.chamar("deleteWebhook", drop_pending_updates=False)
            self._resultado(ok, "Webhook apagado.")
            return
        if opts["url"]:
            self._configurar_webhook(opts["url"])
        self._configurar_perfil()

    def _configurar_webhook(self, url):
        if not url.startswith("https://"):
            raise CommandError("O Telegram exige HTTPS na URL do webhook.")
        if not url.rstrip("/").endswith("/telegram/webhook"):
            self.stdout.write(self.style.WARNING("Atenção: a URL normalmente termina em /telegram/webhook/"))
        segredo = settings.TELEGRAM_WEBHOOK_SECRET
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", segredo or ""):
            raise CommandError("TELEGRAM_WEBHOOK_SECRET deve ter 1-256 caracteres: letras, números, _ ou -")
        if segredo == "troque-este-segredo":
            self.stdout.write(self.style.WARNING("Atenção: você está usando o segredo padrão; troque no .env/Vercel."))
        ok = telegram_api.chamar(
            "setWebhook", url=url, secret_token=segredo,
            allowed_updates=["message", "callback_query"], drop_pending_updates=True,
        )
        self._resultado(ok, f"Webhook configurado: {url}")

    def _configurar_perfil(self):
        empresa = settings.NOME_EMPRESA
        ok = telegram_api.chamar("setMyCommands", commands=COMANDOS)
        self._resultado(ok, "Comandos /start, /menu e /encerrar configurados.")
        telegram_api.chamar(
            "setMyDescription",
            description=(f"Olá! Sou o assistente virtual da {empresa}. Tiro dúvidas, abro tickets e, "
                         "se precisar, te passo para um atendente. Toque em Iniciar para começar."),
        )
        ok = telegram_api.chamar("setMyShortDescription", short_description=f"Atendimento da {empresa} 24h 🤖")
        self._resultado(ok, "Descrição do bot atualizada.")

    def _resultado(self, ok, mensagem):
        if ok is None:
            self.stdout.write(self.style.ERROR("Falhou (veja o log acima)."))
        else:
            self.stdout.write(self.style.SUCCESS(mensagem))
