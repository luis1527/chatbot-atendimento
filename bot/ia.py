"""
Integração com o Google Gemini (REST puro, via requests - funciona em serverless).

Uma ÚNICA chamada por mensagem do cliente: o Gemini recebe o histórico recente,
o FAQ ativo e a lista de AÇÕES que o sistema sabe executar, e devolve um JSON
(saída estruturada com responseSchema) dizendo qual ação executar, a intenção,
qual FAQ usar, a resposta em linguagem natural e os campos de ticket extraídos.

Quem executa a ação é o engine (bot/engine.py) - a IA só decide e redige.
Se a chave não existir, der erro, timeout ou 429 (cota), as funções
retornam None e o engine usa o fallback sem IA (bot/nlp.py).
"""
import json
import logging
import time

import requests
from django.conf import settings

log = logging.getLogger(__name__)

URL = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
TIMEOUT = 12  # segundos; acima disso o cliente espera demais -> fallback
# Modelo usado se o configurado (GEMINI_MODEL) não existir mais para a chave (HTTP 404).
MODELO_RESERVA = "gemini-flash-lite-latest"
# Tentados em ordem quando o modelo principal está sobrecarregado (503) mesmo após nova tentativa.
MODELOS_ALTERNATIVOS = ["gemini-3.1-flash-lite", "gemini-flash-latest"]
_modelo_indisponivel: set[str] = set()  # lembra (por processo) modelos que deram 404

ACOES = [
    "responder_faq", "sem_resposta", "nao_suportado", "conversa_livre", "abrir_ticket",
    "consultar_tickets", "falar_com_atendente", "mostrar_menu", "encerrar",
]

PROMPT_SISTEMA = """Você é o assistente virtual de atendimento da {empresa}, num chat (Telegram ou site).
Interprete a mensagem do cliente (entenda gírias e erros de digitação) e escolha UMA ação que o sistema vai executar.

Ações:
- responder_faq: a mensagem é respondida por um item do FAQ (inclusive quando o FAQ ensina o cliente a fazer algo sozinho). Informe faq_id e, em "resposta", reescreva a resposta do FAQ de forma natural e curta usando SOMENTE o que o FAQ diz.
- sem_resposta: pergunta sobre a empresa/serviço que o FAQ não responde. Diga com honestidade que não tem essa informação e sugira abrir um ticket ou falar com um atendente.
- nao_suportado: pedido de algo que este chat não sabe fazer (ex.: cancelar conta, fazer pedido, emitir documento, alterar cadastro, qualquer coisa fora desta lista de ações). Diga claramente que isso ainda não é possível por aqui e ofereça abrir um ticket ou falar com um atendente.
- conversa_livre: saudação, agradecimento, despedida, papo casual ou mensagem ambígua (nesse caso peça esclarecimento). Responda de forma natural, de acordo com o contexto.
  No modo 'Chat de conversa', conversa_livre também vale para QUALQUER assunto geral (tecnologia, carreira, estudos, curiosidades etc.): responda de verdade, com conteúdo útil, como um assistente simpático. Só não invente dados da empresa.
- abrir_ticket: o cliente quer registrar uma solicitação, problema ou reclamação para a equipe. Preencha ticket_assunto (resumo curto), ticket_descricao (detalhes) e ticket_categoria APENAS com o que o cliente disse; deixe "" / "nenhuma" o que ele não informou.
- consultar_tickets: quer ver seus tickets/protocolos.
- falar_com_atendente: quer falar com uma pessoa/atendente humano.
- mostrar_menu: quer ver as opções ou não sabe o que pode fazer aqui.
- encerrar: pede explicitamente para encerrar/finalizar o atendimento (agradecer ou dizer tchau NÃO é encerrar).

Regras:
- NUNCA diga que fez algo que o sistema não faz (ex.: "enviei seu boleto", "cancelei sua conta"). NUNCA invente informações (preços, prazos, endereços, políticas) que não estejam no FAQ.
- "resposta": português do Brasil, cordial, no máximo 3 frases curtas, texto puro sem Markdown, no máximo 1 emoji. Nas ações abrir_ticket, consultar_tickets, falar_com_atendente e encerrar deixe a resposta vazia (o sistema completa).
- Antes de escolher sem_resposta ou nao_suportado, confira se algum item do FAQ ajuda (mesmo que só explique como o cliente faz sozinho); se ajudar, use responder_faq.
- faq_id = 0 quando a ação não for responder_faq."""


def _config_raciocinio(modelo: str) -> dict:
    """Gemini 2.x desliga com thinkingBudget=0; Gemini 3+ usa thinkingLevel."""
    if modelo.startswith("gemini-2"):
        return {"thinkingBudget": 0}
    return {"thinkingLevel": "minimal" if "lite" in modelo else "low"}


def _modelo() -> str:
    modelo = settings.GEMINI_MODEL or MODELO_RESERVA
    return MODELO_RESERVA if modelo in _modelo_indisponivel else modelo


def _post(corpo: dict, modelo: str):
    return requests.post(
        URL.format(modelo=modelo),
        headers={"x-goog-api-key": settings.GEMINI_API_KEY, "Content-Type": "application/json"},
        json=corpo,
        timeout=TIMEOUT,
    )


def disponivel() -> bool:
    return bool(getattr(settings, "GEMINI_API_KEY", ""))


def _chamar(sistema: str, prompt: str, *, schema: dict | None = None, max_tokens: int = 700, temperatura: float = 0.3):
    """Faz a chamada ao Gemini. Retorna o texto gerado ou None em qualquer falha."""
    if not disponivel():
        return None
    config = {
        "temperature": temperatura,
        "maxOutputTokens": max_tokens,
        # Raciocínio interno no mínimo: bem mais rápido e suficiente para atendimento.
    }
    if schema:
        config["responseMimeType"] = "application/json"
        config["responseSchema"] = schema
    corpo = {
        "systemInstruction": {"parts": [{"text": sistema}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": config,
    }
    modelo = _modelo()
    config["thinkingConfig"] = _config_raciocinio(modelo)
    try:
        r = _post(corpo, modelo)
        if r.status_code == 404 and modelo != MODELO_RESERVA:
            log.error("Modelo %s indisponível para esta chave (404); usando %s. Atualize GEMINI_MODEL.",
                      modelo, MODELO_RESERVA)
            _modelo_indisponivel.add(modelo)
            modelo = MODELO_RESERVA
            config["thinkingConfig"] = _config_raciocinio(modelo)
            r = _post(corpo, modelo)
        if r.status_code == 400 and "hinking" in r.text:
            # Modelo não aceita essa configuração de raciocínio: tenta sem ela.
            log.warning("Gemini (%s) recusou thinkingConfig; repetindo sem ela.", modelo)
            config.pop("thinkingConfig", None)
            r = _post(corpo, modelo)
        if r.status_code in (404, 500, 502, 503, 504):
            # A API do Gemini às vezes devolve 404/503 de forma intermitente: tenta mais uma vez.
            log.warning("Gemini HTTP %s (%s); tentando de novo.", r.status_code, modelo)
            time.sleep(0.5)
            r = _post(corpo, modelo)
        for alternativo in MODELOS_ALTERNATIVOS:
            # Modelo principal sobrecarregado (503 "high demand"): tenta outro modelo do Gemini.
            if r.status_code not in (404, 500, 502, 503, 504) or alternativo == modelo:
                continue
            log.warning("Gemini HTTP %s (%s); tentando modelo alternativo %s.", r.status_code, modelo, alternativo)
            modelo = alternativo
            config["thinkingConfig"] = _config_raciocinio(modelo)
            r = _post(corpo, modelo)
    except requests.RequestException as e:
        log.warning("Gemini indisponível (%s); usando fallback.", e.__class__.__name__)
        return None
    if r.status_code == 429:
        log.warning("Gemini: cota estourada (429); usando fallback.")
        return None
    if r.status_code != 200:
        log.error("Gemini HTTP %s: %s", r.status_code, r.text[:300])
        return None
    try:
        partes = r.json()["candidates"][0]["content"]["parts"]
        texto = "".join(p.get("text", "") for p in partes if not p.get("thought"))
    except (ValueError, KeyError, IndexError, TypeError):
        log.error("Gemini: resposta em formato inesperado: %s", r.text[:300])
        return None
    return texto.strip() or None


def _schema(intencoes: list[str], categorias: list[str]) -> dict:
    intencao = {"type": "STRING"}
    if intencoes:
        intencao["enum"] = intencoes
    campos = {
        "acao": {"type": "STRING", "enum": ACOES},
        "intencao": intencao,
        "confianca": {"type": "NUMBER"},
        "faq_id": {"type": "INTEGER"},
        "resposta": {"type": "STRING"},
        "ticket_assunto": {"type": "STRING"},
        "ticket_descricao": {"type": "STRING"},
        "ticket_categoria": {"type": "STRING", "enum": list(categorias) + ["nenhuma"]},
    }
    ordem = list(campos)
    return {"type": "OBJECT", "properties": campos, "required": ordem, "propertyOrdering": ordem}


def interpretar(
    texto: str,
    *,
    faqs: list,
    intencoes: list[tuple[str, str]],
    categorias: list[tuple[str, str]],
    historico: list[tuple[str, str]] | None = None,
    situacao: str = "",
    empresa: str = "",
    nome_cliente: str = "",
) -> dict | None:
    """
    Interpreta a mensagem do cliente.

    faqs: objetos PerguntaFAQ; intencoes/categorias: [(valor, descrição)];
    historico: [(quem, texto)] em ordem cronológica.
    Retorna dict com acao, intencao, confianca, faq_id (ou None), resposta,
    ticket {assunto, descricao, categoria} - ou None se a IA falhar.
    """
    linhas = ["Intenções possíveis:"]
    linhas += [f"- {slug}: {desc}" for slug, desc in intencoes]
    linhas.append("\nCategorias de ticket: " + ", ".join(f"{v} ({d})" for v, d in categorias))
    linhas.append("\nFAQ (id | pergunta | resposta):")
    linhas += [f"[{f.pk}] {f.pergunta} | {f.resposta}" for f in faqs] or ["(vazio)"]
    if historico:
        linhas.append("\nHistórico recente:")
        linhas += [f"{quem}: {t[:400]}" for quem, t in historico]
    if nome_cliente:
        linhas.append(f"\nNome do cliente: {nome_cliente}")
    if situacao:
        linhas.append(f"Situação atual: {situacao}")
    linhas.append(f"\nMensagem do cliente: {texto[:1500]}")

    bruto = _chamar(
        PROMPT_SISTEMA.format(empresa=empresa or "empresa"),
        "\n".join(linhas),
        schema=_schema([s for s, _ in intencoes], [v for v, _ in categorias]),
    )
    if not bruto:
        return None
    try:
        dados = json.loads(bruto)
    except ValueError:
        log.error("Gemini devolveu JSON inválido: %s", bruto[:300])
        return None
    if not isinstance(dados, dict) or dados.get("acao") not in ACOES:
        return None

    # Validação: nada que venha da IA é usado sem conferir.
    ids_faq = {f.pk for f in faqs}
    try:
        faq_id = int(dados.get("faq_id") or 0)
    except (TypeError, ValueError):
        faq_id = 0
    try:
        confianca = max(0.0, min(1.0, float(dados.get("confianca") or 0)))
    except (TypeError, ValueError):
        confianca = None
    slugs = {s for s, _ in intencoes}
    intencao = dados.get("intencao") if dados.get("intencao") in slugs else None
    cats = {v for v, _ in categorias}
    categoria = dados.get("ticket_categoria") if dados.get("ticket_categoria") in cats else ""
    return {
        "acao": dados["acao"],
        "intencao": intencao,
        "confianca": confianca,
        "faq_id": faq_id if faq_id in ids_faq else None,
        "resposta": str(dados.get("resposta") or "").strip(),
        "ticket": {
            "assunto": str(dados.get("ticket_assunto") or "").strip()[:150],
            "descricao": str(dados.get("ticket_descricao") or "").strip(),
            "categoria": categoria,
        },
    }
