from django.conf import settings


def site(request):
    return {
        "NOME_EMPRESA": settings.NOME_EMPRESA,
        "TELEGRAM_BOT_USERNAME": settings.TELEGRAM_BOT_USERNAME,
        "TELEGRAM_LINK": f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}",
    }
