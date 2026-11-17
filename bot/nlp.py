"""
Entendimento de texto SEM IA (fallback).

Usado quando o Gemini está indisponível (sem chave, erro, timeout ou cota
estourada - HTTP 429). É simples de propósito: normaliza o texto, procura
padrões (regex) para descobrir a intenção e pontua as perguntas do FAQ por
palavras-chave + palavras em comum com a pergunta.
"""
import re
import unicodedata

# Palavras que não ajudam a diferenciar uma pergunta da outra.
STOPWORDS = {
    "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das", "em", "no", "na", "nos",
    "nas", "por", "pra", "para", "pro", "com", "sem", "e", "ou", "que", "se", "me", "meu", "minha", "meus",
    "minhas", "eu", "voce", "voces", "vc", "vcs", "ele", "ela", "isso", "esse", "essa", "este", "esta", "ao",
    "qual", "quais", "como", "quando", "onde", "quanto", "quem", "porque", "por que", "tem", "ter", "ja", "nao",
    "sim", "mais", "muito", "faco", "fazer", "ser", "ta", "esta", "estou", "e", "eh", "oi", "ola", "bom", "boa",
    "dia", "tarde", "noite", "favor", "pf", "pfv", "obrigado", "obrigada", "gostaria", "queria", "quero", "preciso",
    "saber", "posso", "pode", "consigo", "algum", "alguma", "aqui", "ai", "la", "lo", "seu", "sua", "vou",
}

LIMIAR_FAQ = 2.0  # pontuação mínima para considerar que o FAQ responde


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento, sem pontuação e com espaços simples."""
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def tokens(texto: str) -> list[str]:
    return [p for p in normalizar(texto).split() if p not in STOPWORDS and len(p) > 1]


def _raiz(palavra: str) -> str:
    """'Stemming' pobre: corta em 5 letras (senhas -> senha, boletos -> bolet)."""
    return palavra[:5]


# ---------------------------------------------------------------------------
# Intenções
# ---------------------------------------------------------------------------
_RE_HUMANO = re.compile(
    r"\b(atendentes?|humanos?|operador(es)?|pessoa real|pessoa de verdade|ser humano|funcionarios?|"
    r"alguem de verdade|falar com alguem|falar com uma pessoa|suporte humano)\b"
)
_RE_PEDIDO = re.compile(
    r"\b(quero|queria|gostaria|preciso|prefiro|posso|pode|poderia|passa|chama|chamar|chame|falar|fala|falo|"
    r"conversar|transfere|transferir|cade|tem|me coloca|manda)\b"
)
_RE_ABRIR_TICKET = re.compile(
    r"\b(abrir|abre|abra|abro|registrar|registra|criar|cria|novo|nova|fazer|faco)\b.{0,20}"
    r"\b(ticket|chamado|protocolo|solicitacao)\b"
)
_RE_STATUS_TICKET = re.compile(
    r"\b(meus? (tickets?|chamados?|protocolos?)|status do|andamento do|acompanhar)\b|\btck ?\d+"
)
_RE_RECLAMACAO = re.compile(r"\b(pessim|horrivel|absurd|ridicul|reclama|insatisf|descaso|vergonha|palhacada|lixo)")
_RE_FINANCEIRO = re.compile(
    r"\b(boleto|pagamento|pagar|paguei|pix|cartao|reembolso|estorno|cobranca|cobrad|fatura|dinheiro|parcel|"
    r"segunda via|2 via)"
)
_RE_SUPORTE = re.compile(r"\b(erro|nao funciona|nao carrega|nao abre|travou|trava|bug|fora do ar|senha|login|acess|caiu)")

_INICIO_PERGUNTA = {
    "como", "qual", "quais", "quando", "onde", "quanto", "quantos", "quem", "porque", "por", "posso", "pode",
    "tem", "existe", "voces", "vcs", "gostaria", "queria", "preciso",
}
_VOCAB_SAUDACAO = {
    "oi", "oii", "oiii", "oie", "ola", "opa", "eai", "e", "ai", "eae", "hey", "hello", "hi", "salve", "bom", "boa",
    "dia", "tarde", "noite", "tudo", "bem", "td", "bom", "como", "vai", "voce", "vc", "beleza", "blz", "pessoal",
    "amigo", "bot", "tranquilo", "joia",
}
_INICIO_SAUDACAO = {"oi", "oii", "oiii", "oie", "ola", "opa", "eai", "eae", "e", "hey", "hello", "hi", "salve", "bom", "boa", "tudo"}
_VOCAB_DESPEDIDA = {
    "tchau", "ate", "mais", "logo", "obrigado", "obrigada", "obg", "brigado", "brigada", "valeu", "vlw", "muito",
    "mto", "agradeco", "falou", "flw", "isso", "so", "era", "ok", "certo", "beleza", "blz", "entendi", "perfeito",
    "otimo", "resolvido", "resolveu", "ajudou", "bom", "boa", "dia", "tarde", "noite", "tenha", "um", "uma", "pela",
    "ajuda", "me", "por", "tudo", "show",
}
_FORTES_DESPEDIDA = {"tchau", "obrigado", "obrigada", "obg", "brigado", "brigada", "valeu", "vlw", "agradeco", "falou", "flw", "ate"}


def pede_humano(texto: str) -> bool:
    norm = normalizar(texto)
    if not _RE_HUMANO.search(norm):
        return False
    return bool(_RE_PEDIDO.search(norm)) or len(norm.split()) <= 3


def detectar_intencao(texto: str) -> tuple[str, float]:
    """Retorna (slug da intenção, confiança 0-1). Slugs iguais aos da tabela Intencao."""
    norm = normalizar(texto)
    palavras = norm.split()
    if not palavras:
        return "outro", 0.0
    if pede_humano(texto):
        return "falar_humano", 0.9
    if _RE_ABRIR_TICKET.search(norm):
        return "abrir_ticket", 0.85
    if _RE_STATUS_TICKET.search(norm):
        return "status_ticket", 0.8
    # Saudação/despedida só quando a mensagem é basicamente isso ("oi, tudo bem?").
    if palavras[0] in _INICIO_SAUDACAO and all(p in _VOCAB_SAUDACAO for p in palavras):
        return "saudacao", 0.95
    if all(p in _VOCAB_DESPEDIDA for p in palavras) and any(p in _FORTES_DESPEDIDA for p in palavras):
        return "despedida", 0.9
    if _RE_RECLAMACAO.search(norm):
        return "reclamacao", 0.7
    if _RE_FINANCEIRO.search(norm):
        return "financeiro", 0.7
    if _RE_SUPORTE.search(norm):
        return "suporte", 0.7
    if "?" in (texto or "") or palavras[0] in _INICIO_PERGUNTA:
        return "duvida", 0.6
    return "outro", 0.3


# ---------------------------------------------------------------------------
# FAQ
# ---------------------------------------------------------------------------
def pontuar_faq(texto: str, faq) -> float:
    """Quanto a pergunta do FAQ parece responder ao texto (0 = nada)."""
    norm = f" {normalizar(texto)} "
    raizes = {_raiz(t) for t in tokens(texto)}
    if not raizes:
        return 0.0
    pontos = 0.0
    chaves = {normalizar(c) for c in faq.lista_palavras_chave()} - {""}
    for chave in chaves:
        n_palavras = len(chave.split())
        if f" {chave} " in norm:
            pontos += 2 + 0.5 * (n_palavras - 1)
        elif n_palavras == 1 and len(chave) >= 4 and _raiz(chave) in raizes:
            pontos += 1  # "boletos" bate com "boleto"
    da_pergunta = {_raiz(t) for t in tokens(faq.pergunta)}
    if da_pergunta:
        comuns = len(raizes & da_pergunta)
        pontos += 2 * comuns / len(da_pergunta)
    return round(pontos, 2)


def ranquear_faq(texto: str, faqs) -> list[tuple]:
    """Lista [(faq, pontos)] com pontos > 0, do melhor para o pior."""
    pontuadas = [(f, pontuar_faq(texto, f)) for f in faqs]
    return sorted([p for p in pontuadas if p[1] > 0], key=lambda p: p[1], reverse=True)


def melhor_faq(texto: str, faqs):
    """(faq, pontos) se passar do limiar, senão (None, 0)."""
    ranking = ranquear_faq(texto, faqs)
    if ranking and ranking[0][1] >= LIMIAR_FAQ:
        return ranking[0]
    return None, 0.0
