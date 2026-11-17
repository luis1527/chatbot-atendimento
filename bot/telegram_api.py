"""Cliente mínimo da API de Bots do Telegram (HTTP puro, funciona em serverless)."""
import logging
import re

import requests
from django.conf import settings

log = logging.getLogger(__name__)
TIMEOUT = 15


def _url(metodo: str) -> str:
    return f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/{metodo}"


def chamar(metodo: str, **dados):
    """Chama um método da API. Retorna o 'result' ou None em caso de erro."""
    if not settings.TELEGRAM_BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN não configurado; ignorando %s", metodo)
        return None
    timeout = dados.pop("_timeout", TIMEOUT)
    try:
        r = requests.post(_url(metodo), json=dados, timeout=timeout)
        corpo = r.json()
    except Exception:
        log.exception("Erro chamando Telegram %s", metodo)
        return None
    if not corpo.get("ok"):
        log.error("Telegram %s falhou: %s", metodo, corpo.get("description"))
        return None
    return corpo.get("result")


def escapar(texto: str) -> str:
    """Escapa texto para MarkdownV2."""
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!\\])", r"\\\1", texto or "")


def teclado(botoes):
    """Converte [[{"texto","dado"}]] para inline_keyboard do Telegram."""
    if not botoes:
        return None
    linhas = []
    for linha in botoes:
        linhas.append([
            {"text": b["texto"], "url": b["url"]} if b.get("url") else {"text": b["texto"], "callback_data": b["dado"][:64]}
            for b in linha
        ])
    return {"inline_keyboard": linhas}


def enviar_mensagem(chat_id: int, texto: str, botoes=None, markdown: bool = False):
    dados = {"chat_id": chat_id, "text": texto[:4096]}
    if markdown:
        dados["parse_mode"] = "MarkdownV2"
    kb = teclado(botoes)
    if kb:
        dados["reply_markup"] = kb
    resultado = chamar("sendMessage", **dados)
    if resultado is None and markdown:
        # Se o Markdown der erro, tenta de novo em texto puro.
        dados.pop("parse_mode", None)
        dados["text"] = re.sub(r"\\(.)", r"\1", texto).replace("*", "")[:4096]
        resultado = chamar("sendMessage", **dados)
    return resultado


def digitando(chat_id: int):
    chamar("sendChatAction", chat_id=chat_id, action="typing", _timeout=5)


def responder_callback(callback_id: str, texto: str = ""):
    chamar("answerCallbackQuery", callback_query_id=callback_id, text=texto[:200], _timeout=5)


def remover_teclado(chat_id: int, message_id: int):
    chamar("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id, reply_markup={"inline_keyboard": []}, _timeout=5)
