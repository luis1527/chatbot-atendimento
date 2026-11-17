"""Gera docs/diagrama-er.drawio e docs/diagrama-er.svg a partir do mesmo layout.

Uso (na raiz do projeto):  python docs/gerar_diagrama.py docs
Se mudar core/models.py, atualize TABELAS/RELACOES aqui e rode de novo.
"""
import sys
from xml.sax.saxutils import escape

DOCS = sys.argv[1]

W, HDR, ROW = 380, 34, 24
CK, CN, CT, CNN = 66, 168, 112, 34  # larguras: chave, nome, tipo, NN

CORES = {  # (cabeçalho, borda)
    "func": ("#F8CECC", "#B85450"),
    "cli": ("#D5E8D4", "#82B366"),
    "atend": ("#DAE8FC", "#6C8EBF"),
    "kb": ("#E1D5E7", "#9673A6"),
}

TZ = "timestamptz"
TABELAS = {
    "core_usuario": ("func", 540, 520, "Funcionário (login do painel)", [
        ("PK", "id", "bigint", 1), ("UQ", "username", "varchar(150)", 1), ("", "password", "varchar(128)", 1),
        ("", "first_name", "varchar(150)", 1), ("", "last_name", "varchar(150)", 1), ("", "email", "varchar(254)", 1),
        ("", "cargo", "varchar(20)", 1), ("", "apelido", "varchar(60)", 1), ("", "online", "boolean", 1),
        ("", "ultimo_acesso_painel", TZ, 0), ("", "is_active", "boolean", 1), ("", "is_staff", "boolean", 1),
        ("", "is_superuser", "boolean", 1), ("", "last_login", TZ, 0), ("", "date_joined", TZ, 1)]),
    "core_contato": ("cli", 40, 40, "Cliente (Telegram ou site)", [
        ("PK", "id", "bigint", 1), ("", "canal", "varchar(20)", 1), ("", "nome", "varchar(120)", 1),
        ("UQ", "telegram_chat_id", "bigint", 0), ("", "telegram_username", "varchar(64)", 1),
        ("UQ", "web_sessao", "varchar(64)", 0), ("", "email", "varchar(254)", 1), ("", "telefone", "varchar(30)", 1),
        ("", "criado_em", TZ, 1), ("", "ultimo_contato_em", TZ, 1)]),
    "core_ticket": ("cli", 40, 400, "Solicitação com protocolo", [
        ("PK", "id", "bigint", 1), ("UQ", "protocolo", "varchar(20)", 1), ("FK", "contato_id", "bigint", 1),
        ("FK", "conversa_id", "bigint", 0), ("FK", "responsavel_id", "bigint", 0), ("", "assunto", "varchar(150)", 1),
        ("", "descricao", "text", 1), ("", "categoria", "varchar(20)", 1), ("", "prioridade", "varchar(10)", 1),
        ("", "status", "varchar(20)", 1), ("", "resposta", "text", 1), ("", "criado_em", TZ, 1),
        ("", "atualizado_em", TZ, 1), ("", "resolvido_em", TZ, 0)]),
    "core_conversa": ("atend", 540, 64, "Um atendimento do início ao fim", [
        ("PK", "id", "bigint", 1), ("FK UQ*", "contato_id", "bigint", 1), ("FK", "atendente_id", "bigint", 0),
        ("", "canal", "varchar(20)", 1), ("", "status", "varchar(20)", 1), ("", "modo", "varchar(20)", 1),
        ("", "motivo_escalonamento", "varchar(255)", 1), ("CK", "avaliacao", "smallint", 0),
        ("", "comentario_avaliacao", "varchar(500)", 1), ("", "iniciada_em", TZ, 1), ("", "atualizada_em", TZ, 1),
        ("", "escalada_em", TZ, 0), ("", "assumida_em", TZ, 0), ("", "encerrada_em", TZ, 0),
        ("", "ultima_leitura_atendente_em", TZ, 0)]),
    "core_mensagem": ("atend", 1040, 40, "Cada mensagem trocada", [
        ("PK", "id", "bigint", 1), ("FK", "conversa_id", "bigint", 1), ("FK", "atendente_id", "bigint", 0),
        ("FK", "intencao_id", "bigint", 0), ("FK", "faq_id", "bigint", 0), ("CK", "remetente", "varchar(20)", 1),
        ("", "texto", "text", 1), ("", "confianca", "double precision", 0), ("", "origem_resposta", "varchar(20)", 1),
        ("", "botoes", "jsonb", 0), ("UQ*", "telegram_message_id", "bigint", 0), ("", "criada_em", TZ, 1)]),
    "core_eventoconversa": ("atend", 1040, 440, "Histórico / auditoria", [
        ("PK", "id", "bigint", 1), ("FK", "conversa_id", "bigint", 1), ("FK", "usuario_id", "bigint", 0),
        ("FK", "para_usuario_id", "bigint", 0), ("", "tipo", "varchar(20)", 1), ("", "detalhe", "varchar(255)", 1),
        ("", "criado_em", TZ, 1)]),
    "core_intencao": ("kb", 1540, 40, "Intenções que o bot reconhece", [
        ("PK", "id", "bigint", 1), ("UQ", "slug", "varchar(40)", 1), ("", "nome", "varchar(80)", 1),
        ("", "descricao", "varchar(255)", 1)]),
    "core_perguntafaq": ("kb", 1540, 240, "Pergunta e resposta do FAQ", [
        ("PK", "id", "bigint", 1), ("FK UQ²", "categoria_id", "bigint", 1), ("UQ²", "pergunta", "varchar(255)", 1),
        ("", "resposta", "text", 1), ("", "palavras_chave", "varchar(255)", 1), ("", "ativa", "boolean", 1),
        ("", "vezes_usada", "integer", 1), ("", "criada_em", TZ, 1), ("", "atualizada_em", TZ, 1)]),
    "core_categoriafaq": ("kb", 1540, 580, "Agrupa perguntas do FAQ", [
        ("PK", "id", "bigint", 1), ("UQ", "nome", "varchar(80)", 1), ("", "ordem", "smallint", 1)]),
}


def altura(t):
    return HDR + ROW * len(TABELAS[t][4])


def linha_y(t, col):
    _, _, y, _, cols = TABELAS[t]
    i = [c[1] for c in cols].index(col)
    return y + HDR + ROW * i + ROW / 2


def lado_x(t, lado):
    x = TABELAS[t][1]
    return x if lado == "L" else x + W


# (pai, lado, filho, coluna FK, lado, [x das "pistas" verticais], rótulo)
# Pista: o traço sai do pai, anda até x=pista, sobe/desce até a linha da FK e entra no filho.
RELACOES = [
    ("core_contato", "R", "core_conversa", "contato_id", "L", 470, "tem"),
    ("core_contato", "L", "core_ticket", "contato_id", "L", 16, "abre"),
    ("core_conversa", "L", "core_ticket", "conversa_id", "R", 500, "origina"),
    ("core_usuario", "L", "core_ticket", "responsavel_id", "R", 440, "responsável"),
    ("core_usuario", "R", "core_conversa", "atendente_id", "R", 940, "atende"),
    ("core_conversa", "R", "core_mensagem", "conversa_id", "L", None, "contém"),
    ("core_conversa", "R", "core_eventoconversa", "conversa_id", "L", 962, "registra"),
    ("core_usuario", "R", "core_mensagem", "atendente_id", "L", 984, "envia"),
    ("core_usuario", "R", "core_eventoconversa", "usuario_id", "L", 1004, ""),
    ("core_usuario", "R", "core_eventoconversa", "para_usuario_id", "L", 1022, ""),
    ("core_intencao", "L", "core_mensagem", "intencao_id", "R", 1470, "classifica"),
    ("core_perguntafaq", "L", "core_mensagem", "faq_id", "R", 1500, "responde"),
    ("core_categoriafaq", "R", "core_perguntafaq", "categoria_id", "R", 1950, "agrupa"),
]


def nn_da_fk(filho, col):
    return next(c[3] for c in TABELAS[filho][4] if c[1] == col)


def pontos(rel):
    pai, lp, filho, col, lf, pista, _ = rel
    p0 = (lado_x(pai, lp), linha_y(pai, "id"))
    p3 = (lado_x(filho, lf), linha_y(filho, col))
    if pista is None:
        return [p0, p3]
    return [p0, (pista, p0[1]), (pista, p3[1]), p3]


LEGENDA_Y = 960
NOTAS = [
    "PK chave primária · FK chave estrangeira · UQ valor único · NN obrigatório (NOT NULL) · CK regra CHECK",
    "UQ* = unicidade parcial:  uma conversa NÃO encerrada por contato  ·  telegram_message_id único por conversa (só mensagens do cliente)",
    "UQ² = único em conjunto: (categoria_id, pergunta)",
    "CHECK: contato tem telegram_chat_id (canal telegram) ou web_sessao (canal web) · conversa 'humano' exige atendente_id ·"
    " avaliacao entre 1 e 5 · mensagem de 'atendente' exige atendente_id",
    "Pé-de-galinha: ||  exatamente um   o|  zero ou um (FK opcional)   o<  zero ou muitos.  Linha cheia = FK obrigatória.",
]


# ---------------------------------------------------------------------------
# draw.io
# ---------------------------------------------------------------------------
def gerar_drawio():
    cel = []
    add = cel.append
    for nome, (grupo, x, y, desc, cols) in TABELAS.items():
        fill, stroke = CORES[grupo]
        add(f'<mxCell id="{nome}" value="{escape(nome)}" style="shape=table;startSize={HDR};container=1;'
            f'collapsible=0;childLayout=tableLayout;fixedRows=1;rowLines=1;fontStyle=1;align=center;resizeLast=1;'
            f'html=1;fillColor={fill};strokeColor={stroke};fontSize=13;swimlaneFillColor=#FFFFFF;" vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{y}" width="{W}" height="{altura(nome)}" as="geometry"/></mxCell>')
        for i, (k, c, tp, nn) in enumerate(cols):
            rid = f"{nome}.{c}"
            add(f'<mxCell id="{rid}" value="" style="shape=tableRow;horizontal=0;startSize=0;swimlaneHead=0;'
                f'swimlaneBody=0;fillColor=none;collapsible=0;dropTarget=0;points=[[0,0.5],[1,0.5]];'
                f'portConstraint=eastwest;top=0;left=0;right=0;bottom={1 if i == len(cols) - 1 else 0};'
                f'strokeColor={stroke};" vertex="1" parent="{nome}">'
                f'<mxGeometry y="{HDR + ROW * i}" width="{W}" height="{ROW}" as="geometry"/></mxCell>')
            bold = ";fontStyle=1" if "PK" in k else (";fontStyle=4" if "FK" in k else "")
            xs = 0
            for j, (txt, larg) in enumerate([(k, CK), (c, CN), (tp, CT), ("NN" if nn else "", CNN)]):
                cor = ";fontColor=#666666" if j in (2, 3) else ""
                al = "align=center" if j in (0, 3) else "align=left;spacingLeft=6"
                add(f'<mxCell id="{rid}#{j}" value="{escape(txt)}" style="shape=partialRectangle;connectable=0;'
                    f'fillColor=none;top=0;left=0;bottom=0;right=0;{al};overflow=hidden;whiteSpace=wrap;html=1;'
                    f'fontSize=11{bold if j in (0, 1) else ""}{cor};" vertex="1" parent="{rid}">'
                    f'<mxGeometry x="{xs}" width="{larg}" height="{ROW}" as="geometry">'
                    f'<mxRectangle width="{larg}" height="{ROW}" as="alternateBounds"/></mxGeometry></mxCell>')
                xs += larg
        add(f'<mxCell id="{nome}#desc" value="{escape(desc)}" style="text;html=1;fontSize=11;fontStyle=2;'
            f'fontColor=#666666;align=left;verticalAlign=bottom;" vertex="1" parent="1">'
            f'<mxGeometry x="{x}" y="{y - 22}" width="{W}" height="20" as="geometry"/></mxCell>')

    for n, rel in enumerate(RELACOES):
        pai, lp, filho, col, lf, pista, rot = rel
        obrig = nn_da_fk(filho, col)
        start = "ERmandOne" if obrig else "ERzeroToOne"
        pts = pontos(rel)
        meio = "".join(f'<mxPoint x="{px}" y="{py}"/>' for px, py in pts[1:-1])
        dash = "" if obrig else "dashed=1;"
        add(f'<mxCell id="rel{n}" value="{escape(rot)}" style="edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;'
            f'{dash}startArrow={start};endArrow=ERzeroToMany;startFill=0;endFill=0;startSize=10;endSize=10;'
            f'jumpStyle=arc;jumpSize=10;fontSize=10;fontColor=#444444;labelBackgroundColor=#FFFFFF;'
            f'exitX={0 if lp == "L" else 1};exitY=0.5;exitDx=0;exitDy=0;'
            f'entryX={0 if lf == "L" else 1};entryY=0.5;entryDx=0;entryDy=0;" edge="1" parent="1" '
            f'source="{pai}.id" target="{filho}.{col}"><mxGeometry relative="1" as="geometry">'
            f'<Array as="points">{meio}</Array></mxGeometry></mxCell>')

    legenda = "<br>".join(escape(t) for t in NOTAS)
    add(f'<mxCell id="legenda" value="&lt;b&gt;Legenda&lt;/b&gt;&lt;br&gt;{escape(legenda)}" style="rounded=1;'
        f'whiteSpace=wrap;html=1;align=left;verticalAlign=top;spacing=10;fontSize=11;fillColor=#FFF2CC;'
        f'strokeColor=#D6B656;arcSize=4;" vertex="1" parent="1">'
        f'<mxGeometry x="40" y="{LEGENDA_Y}" width="1880" height="120" as="geometry"/></mxCell>')
    add('<mxCell id="titulo" value="Chatbot de Atendimento — Modelo Entidade-Relacionamento (PostgreSQL)" '
        'style="text;html=1;fontSize=18;fontStyle=1;align=left;" vertex="1" parent="1">'
        '<mxGeometry x="40" y="-30" width="900" height="30" as="geometry"/></mxCell>')

    corpo = "".join(cel)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<mxfile host="app.diagrams.net" agent="gerado por script" version="24.7.17">\n'
        '  <diagram id="modelo-er" name="Modelo ER">\n'
        '    <mxGraphModel dx="1600" dy="1000" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" '
        'fold="1" page="0" pageScale="1" pageWidth="2000" pageHeight="1200" math="0" shadow="0">\n'
        f'      <root><mxCell id="0"/><mxCell id="1" parent="0"/>{corpo}</root>\n'
        '    </mxGraphModel>\n  </diagram>\n</mxfile>\n'
    )


# ---------------------------------------------------------------------------
# SVG equivalente
# ---------------------------------------------------------------------------
def gerar_svg():
    ox, oy = 30, 60  # deslocamento para caber o título
    largura, alt = 2040, LEGENDA_Y + 120 + 20 + oy
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{largura}" height="{alt}" viewBox="0 0 {largura} {alt}" '
         f'font-family="Helvetica, Arial, sans-serif">',
         f'<rect width="{largura}" height="{alt}" fill="#FFFFFF"/>',
         f'<text x="{40+ox}" y="{oy - 30}" font-size="20" font-weight="bold" fill="#222">'
         'Chatbot de Atendimento — Modelo Entidade-Relacionamento (PostgreSQL)</text>']

    def T(x, y):
        return x + ox, y + oy

    # relações primeiro (ficam por baixo)
    for rel in RELACOES:
        pai, lp, filho, col, lf, pista, rot = rel
        obrig = nn_da_fk(filho, col)
        pts = [T(*p) for p in pontos(rel)]
        d = " ".join(f"{x},{y}" for x, y in pts)
        dash = '' if obrig else ' stroke-dasharray="6,4"'
        s.append(f'<polyline points="{d}" fill="none" stroke="#555" stroke-width="1.4"{dash}/>')
        # marcadores
        def marca(p, viz, tipo):
            (x, y), (vx, _) = p, viz
            sx = 1 if vx > x else -1  # direção para dentro da linha
            g = []
            if tipo == "um":
                for dx in (8, 13):
                    g.append(f'<line x1="{x+sx*dx}" y1="{y-7}" x2="{x+sx*dx}" y2="{y+7}" stroke="#333" stroke-width="1.6"/>')
            elif tipo == "zero_um":
                g.append(f'<line x1="{x+sx*8}" y1="{y-7}" x2="{x+sx*8}" y2="{y+7}" stroke="#333" stroke-width="1.6"/>')
                g.append(f'<circle cx="{x+sx*19}" cy="{y}" r="5" fill="#fff" stroke="#333" stroke-width="1.4"/>')
            else:  # zero ou muitos
                g.append(f'<polyline points="{x},{y-8} {x+sx*12},{y} {x},{y+8}" fill="none" stroke="#333" stroke-width="1.6"/>')
                g.append(f'<circle cx="{x+sx*19}" cy="{y}" r="5" fill="#fff" stroke="#333" stroke-width="1.4"/>')
            return g
        s += marca(pts[0], pts[1], "um" if obrig else "zero_um")
        s += marca(pts[-1], pts[-2], "muitos")
        # rótulo no segmento mais longo
        segs = list(zip(pts, pts[1:]))
        (ax, ay), (bx, by) = max(segs, key=lambda sg: abs(sg[0][0]-sg[1][0]) + abs(sg[0][1]-sg[1][1]))
        mx, my = (ax + bx) / 2, (ay + by) / 2
        halo = 'stroke="#fff" stroke-width="4" paint-order="stroke"'
        fixo = {"tem": (445, 79, "middle"), "abre": (11, 300, "end"), "responde": (1495, 236, "end"),
                "agrupa": (1956, 450, "start")}
        if rot in fixo:
            fx, fy, anc = fixo[rot]
            fx, fy = T(fx, fy)
            s.append(f'<text x="{fx}" y="{fy}" font-size="11" fill="#444" text-anchor="{anc}" {halo}>{escape(rot)}</text>')
            continue
        if not rot:
            continue
        if ax == bx:  # segmento vertical: texto ao lado da linha
            s.append(f'<text x="{mx+5}" y="{my+4}" font-size="11" fill="#444" {halo}>{escape(rot)}</text>')
        else:  # horizontal: texto acima da linha
            s.append(f'<text x="{mx}" y="{my-5}" font-size="11" fill="#444" text-anchor="middle" {halo}>{escape(rot)}</text>')

    for nome, (grupo, x, y, desc, cols) in TABELAS.items():
        fill, stroke = CORES[grupo]
        x, y = T(x, y)
        h = altura(nome)
        s.append(f'<text x="{x}" y="{y-6}" font-size="11" font-style="italic" fill="#666">{escape(desc)}</text>')
        s.append(f'<rect x="{x}" y="{y}" width="{W}" height="{h}" fill="#fff" stroke="{stroke}" stroke-width="1.5"/>')
        s.append(f'<rect x="{x}" y="{y}" width="{W}" height="{HDR}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
        s.append(f'<text x="{x+W/2}" y="{y+22}" font-size="14" font-weight="bold" text-anchor="middle" fill="#222">{nome}</text>')
        for i, (k, c, tp, nn) in enumerate(cols):
            ry = y + HDR + ROW * i
            if i:
                s.append(f'<line x1="{x}" y1="{ry}" x2="{x+W}" y2="{ry}" stroke="#E5E5E5"/>')
            ty = ry + 16
            peso = ' font-weight="bold"' if "PK" in k else ""
            sub = ' text-decoration="underline"' if "FK" in k else ""
            s.append(f'<text x="{x+CK/2}" y="{ty}" font-size="11" text-anchor="middle" fill="#222"{peso}>{escape(k)}</text>')
            s.append(f'<text x="{x+CK+6}" y="{ty}" font-size="12" fill="#222"{peso}{sub}>{escape(c)}</text>')
            s.append(f'<text x="{x+CK+CN+6}" y="{ty}" font-size="11" fill="#666">{escape(tp)}</text>')
            if nn:
                s.append(f'<text x="{x+CK+CN+CT+CNN/2}" y="{ty}" font-size="10" text-anchor="middle" fill="#666">NN</text>')
        s.append(f'<line x1="{x+CK}" y1="{y+HDR}" x2="{x+CK}" y2="{y+h}" stroke="#E5E5E5"/>')

    lx, ly = T(40, LEGENDA_Y)
    s.append(f'<rect x="{lx}" y="{ly}" width="1880" height="120" rx="6" fill="#FFF2CC" stroke="#D6B656"/>')
    s.append(f'<text x="{lx+12}" y="{ly+20}" font-size="12" font-weight="bold" fill="#222">Legenda</text>')
    for i, t in enumerate(NOTAS):
        s.append(f'<text x="{lx+12}" y="{ly+40+18*i}" font-size="12" fill="#333">{escape(t)}</text>')
    s.append("</svg>")
    return "\n".join(s)


open(f"{DOCS}/diagrama-er.drawio", "w", encoding="utf-8").write(gerar_drawio())
open(f"{DOCS}/diagrama-er.svg", "w", encoding="utf-8").write(gerar_svg())
print("ok")
