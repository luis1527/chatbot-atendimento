"""
Roda o bot localmente por long polling (getUpdates), sem precisar de URL pública.

    python manage.py telegram_polling

ATENÇÃO: o Telegram não entrega por polling enquanto houver webhook, então
este comando APAGA o webhook. Para voltar a usar a Vercel depois:
    python manage.py telegram_webhook --url https://SEU-APP.vercel.app/telegram/webhook/
"""
import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from bot import telegram_api
from bot.views import tratar_update

log = logging.getLogger(__name__)
ESPERA_LONG_POLL = 50  # segundos que o Telegram segura a requisição esperando mensagens


class Command(BaseCommand):
    help = "Roda o bot do Telegram localmente via long polling (Ctrl+C para sair)."

    def handle(self, *args, **opts):
        if not settings.TELEGRAM_BOT_TOKEN:
            raise CommandError("TELEGRAM_BOT_TOKEN não configurado no .env")
        eu = telegram_api.chamar("getMe")
        if not eu:
            raise CommandError("Não consegui falar com o Telegram (token inválido ou sem internet).")

        self.stdout.write(self.style.WARNING(
            "⚠ Apagando o webhook: enquanto o polling roda, a URL da Vercel NÃO recebe mensagens.\n"
            "  Para voltar ao webhook depois: python manage.py telegram_webhook --url https://.../telegram/webhook/"
        ))
        telegram_api.chamar("deleteWebhook", drop_pending_updates=False)
        self.stdout.write(self.style.SUCCESS(f"Bot @{eu.get('username')} rodando por polling. Ctrl+C para sair."))

        offset = None
        try:
            while True:
                updates = telegram_api.chamar(
                    "getUpdates", offset=offset, timeout=ESPERA_LONG_POLL,
                    allowed_updates=["message", "callback_query"], _timeout=ESPERA_LONG_POLL + 10,
                )
                if updates is None:  # erro de rede/API: espera um pouco e tenta de novo
                    time.sleep(3)
                    continue
                for update in updates:
                    offset = update["update_id"] + 1
                    close_old_connections()
                    try:
                        tratar_update(update)
                    except Exception:
                        log.exception("Erro tratando update %s", update.get("update_id"))
                    resumo = (update.get("message") or {}).get("text") or (update.get("callback_query") or {}).get("data")
                    self.stdout.write(f"  update {update['update_id']}: {str(resumo)[:60]}")
        except KeyboardInterrupt:
            self.stdout.write("\nPolling encerrado.")
