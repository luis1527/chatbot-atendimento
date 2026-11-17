"""
Números do dashboard.

Só agregações simples do ORM (Count, Avg, TruncDate) para funcionar igual
no PostgreSQL (produção) e no SQLite (testes). Diferenças de tempo
(espera na fila) são calculadas em Python, porque média de intervalo de
datas não é portável entre bancos.
"""
from datetime import timedelta

from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from core.models import Canal, Conversa, Mensagem, PerguntaFAQ, Usuario


def _media_segundos(pares):
    difs = [(fim - inicio).total_seconds() for inicio, fim in pares if inicio and fim and fim >= inicio]
    return sum(difs) / len(difs) if difs else None


def formatar_duracao(segundos):
    if segundos is None:
        return "—"
    segundos = int(round(segundos))
    if segundos < 60:
        return f"{segundos}s"
    minutos, seg = divmod(segundos, 60)
    if minutos < 60:
        return f"{minutos}min {seg:02d}s"
    horas, minutos = divmod(minutos, 60)
    return f"{horas}h {minutos:02d}min"


def calcular(dias: int = 30, incluir_funcionarios: bool = True) -> dict:
    agora = timezone.now()
    hoje = timezone.localdate()
    inicio_periodo = agora - timedelta(days=dias)

    conversas_periodo = Conversa.objects.filter(iniciada_em__gte=inicio_periodo)
    encerradas = conversas_periodo.filter(status=Conversa.Status.ENCERRADA)
    total_encerradas = encerradas.count()
    so_bot = encerradas.filter(escalada_em__isnull=True).count()

    espera = _media_segundos(
        conversas_periodo.filter(escalada_em__isnull=False, assumida_em__isnull=False)
        .values_list("escalada_em", "assumida_em")
    )
    nota = conversas_periodo.aggregate(m=Avg("avaliacao"), n=Count("avaliacao"))

    cards = {
        "conversas_hoje": Conversa.objects.filter(iniciada_em__date=hoje).count(),
        "mensagens_hoje": Mensagem.objects.filter(criada_em__date=hoje).count(),
        "na_fila": Conversa.objects.filter(status=Conversa.Status.FILA).count(),
        "em_atendimento": Conversa.objects.filter(status=Conversa.Status.HUMANO).count(),
        "espera_media": formatar_duracao(espera),
        "pct_bot": round(100 * so_bot / total_encerradas) if total_encerradas else None,
        "total_encerradas": total_encerradas,
        "nota_media": round(nota["m"], 1) if nota["m"] is not None else None,
        "total_avaliacoes": nota["n"],
        "online": Usuario.objects.filter(is_active=True, online=True).count(),
    }

    # Mensagens por dia (últimos 14 dias, preenchendo dias sem movimento com zero).
    inicio_14 = hoje - timedelta(days=13)
    por_dia_qs = (
        Mensagem.objects.filter(criada_em__date__gte=inicio_14)
        .annotate(dia=TruncDate("criada_em"))
        .values("dia")
        .annotate(
            total=Count("id"),
            clientes=Count("id", filter=Q(remetente=Mensagem.Remetente.CLIENTE)),
        )
    )
    mapa = {r["dia"]: r for r in por_dia_qs}
    dias_lista = [inicio_14 + timedelta(days=i) for i in range(14)]
    mensagens_por_dia = {
        "labels": [d.strftime("%d/%m") for d in dias_lista],
        "total": [mapa.get(d, {}).get("total", 0) for d in dias_lista],
        "clientes": [mapa.get(d, {}).get("clientes", 0) for d in dias_lista],
    }

    msgs_periodo = Mensagem.objects.filter(criada_em__gte=inicio_periodo)
    intencoes = list(
        msgs_periodo.filter(intencao__isnull=False)
        .values("intencao__nome").annotate(total=Count("id")).order_by("-total")[:8]
    )
    canais_raw = dict(conversas_periodo.values_list("canal").annotate(total=Count("id")))
    canais = {
        "labels": [Canal(c).label for c in (Canal.TELEGRAM, Canal.WEB)],
        "dados": [canais_raw.get(Canal.TELEGRAM, 0), canais_raw.get(Canal.WEB, 0)],
    }
    origens_raw = dict(
        msgs_periodo.filter(origem_resposta__in=["faq", "ia", "humano"])
        .values_list("origem_resposta").annotate(total=Count("id"))
    )
    origens = {
        "labels": ["FAQ", "IA (Gemini)", "Humano"],
        "dados": [origens_raw.get("faq", 0), origens_raw.get("ia", 0), origens_raw.get("humano", 0)],
    }
    notas_raw = dict(
        conversas_periodo.filter(avaliacao__isnull=False).values_list("avaliacao").annotate(total=Count("id"))
    )
    notas = {"labels": [f"{n} ★" for n in range(1, 6)], "dados": [notas_raw.get(n, 0) for n in range(1, 6)]}

    faq_top = list(
        PerguntaFAQ.objects.filter(vezes_usada__gt=0).select_related("categoria").order_by("-vezes_usada")[:8]
    )

    graficos = {
        "mensagens_por_dia": mensagens_por_dia,
        "intencoes": {"labels": [i["intencao__nome"] for i in intencoes], "dados": [i["total"] for i in intencoes]},
        "canais": canais,
        "origens": origens,
        "notas": notas,
        "faq": {"labels": [f.pergunta for f in faq_top], "dados": [f.vezes_usada for f in faq_top]},
    }

    funcionarios = []
    if incluir_funcionarios:
        for u in Usuario.objects.filter(is_active=True).order_by("cargo", "username"):
            minhas = conversas_periodo.filter(atendente=u)
            agg = minhas.aggregate(n=Count("id"), nota=Avg("avaliacao"))
            funcionarios.append({
                "usuario": u,
                "atendimentos": agg["n"],
                "em_andamento": Conversa.objects.filter(atendente=u, status=Conversa.Status.HUMANO).count(),
                "tempo_assumir": formatar_duracao(_media_segundos(
                    minhas.filter(escalada_em__isnull=False, assumida_em__isnull=False)
                    .values_list("escalada_em", "assumida_em")
                )),
                "nota": round(agg["nota"], 1) if agg["nota"] is not None else None,
            })
        funcionarios.sort(key=lambda f: -f["atendimentos"])

    return {"cards": cards, "graficos": graficos, "funcionarios": funcionarios, "dias": dias}
