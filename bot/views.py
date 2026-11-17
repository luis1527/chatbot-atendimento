"""
Webhook do Telegram: POST /telegram/webhook/

O Telegram chama esta URL a cada mensagem/clique. Regras:
  - só aceita se o header X-Telegram-Bot-Api-Secret-Token bater com
    settings.TELEGRAM_WEBHOOK_SECRET (senão 403);
  - processa de forma síncrona (Vercel serverless não tem fila/worker);
  - SEMPRE devolve 200, mesmo com erro interno (fica no log), para o
    Telegram não ficar reenviando a mesma atualização.

`tratar_update` também é usado pelo comando `telegram_polling` (modo local).
"""
import hmac
import json
import logging

from django.conf import settings
from django.http import HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core import services

from . import engine, telegram_api

log = logging.getLogger(__name__)

# Tipos de mensagem que não são texto -> nome amigável.
TIPOS_MIDIA = {
    "photo": "foto", "voice": "áudio", "audio": "áudio", "video": "vídeo", "video_note": "vídeo",
    "sticker": "figurinha", "animation": "GIF", "document": "arquivo", "location": "localização",
    "contact": "contato", "poll": "enquete", "dice": "dado",
}


@csrf_exempt
@require_POST
def webhook(request):
    segredo = settings.TELEGRAM_WEBHOOK_SECRET or ""
    recebido = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not segredo or not hmac.compare_digest(recebido.encode(), segredo.encode()):
        return HttpResponseForbidden("segredo inválido")
    try:
        update = json.loads(request.body or b"{}")
        tratar_update(update)
    except Exception:
        log.exception("Erro tratando update do Telegram")
    return JsonResponse({"ok": True})


def tratar_update(update: dict):
    """Despacha uma atualização do Telegram (mensagem ou clique em botão)."""
    if not isinstance(update, dict):
        return
    if update.get("callback_query"):
        _tratar_callback(update["callback_query"])
    elif update.get("message"):
        _tratar_mensagem(update["message"])


def _contato(usuario: dict, chat_id: int):
    nome = " ".join(p for p in (usuario.get("first_name"), usuario.get("last_name")) if p).strip()
    return services.contato_telegram(chat_id, nome, usuario.get("username") or "")


def _tratar_mensagem(msg: dict):
    chat = msg.get("chat") or {}
    if chat.get("type") != "private":  # o bot só atende em conversa privada
        return
    contato = _contato(msg.get("from") or {}, chat["id"])
    if msg.get("text"):
        engine.processar_entrada(contato, texto=msg["text"], telegram_message_id=msg.get("message_id"))
        return
    tipo = next((nome for chave, nome in TIPOS_MIDIA.items() if chave in msg), None)
    if tipo:
        engine.processar_midia(contato, tipo, telegram_message_id=msg.get("message_id"))
    # Mensagens de serviço (fixar, etc.) são ignoradas.


def _tratar_callback(cq: dict):
    # Responde logo para o botão parar de "carregar" no app do cliente.
    telegram_api.responder_callback(cq.get("id", ""))
    mensagem = cq.get("message") or {}
    chat_id = (mensagem.get("chat") or {}).get("id") or (cq.get("from") or {}).get("id")
    if not chat_id:
        return
    if mensagem.get("message_id"):
        # Tira os botões da mensagem clicada (evita clique duplo / botão velho).
        telegram_api.remover_teclado(chat_id, mensagem["message_id"])
    contato = _contato(cq.get("from") or {}, chat_id)
    engine.processar_entrada(contato, dado=cq.get("data") or "")
