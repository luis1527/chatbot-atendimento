"""Cérebro do bot (STUB — será implementado)."""


def botoes_menu():
    return [
        [{"texto": "❓ Chat de dúvida", "dado": "menu:duvida"}, {"texto": "💬 Chat de conversa", "dado": "menu:conversa"}],
        [{"texto": "📝 Abrir ticket", "dado": "menu:ticket"}, {"texto": "📋 Meus tickets", "dado": "menu:meus_tickets"}],
        [{"texto": "👤 Falar com atendente", "dado": "menu:humano"}],
    ]


def processar_entrada(contato, texto=None, dado=None, telegram_message_id=None):
    raise NotImplementedError
