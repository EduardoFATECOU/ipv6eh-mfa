"""Runner dos cenarios C1-C4 (Fase 0.6 do CHECKLIST_EXPERIMENTOS.md).

Executa uma repeticao (ou a campanha) e grava um CSV com as metricas do
Cap. 8: TPR, FPR, AUC, EER, precisao/recall/F1, latencia (P50/P95/P99),
CPU/RSS, bloqueios e escaladas.

Duas fontes de dados:

``simulado`` (padrao)
    Reexecuta o pipeline de ``eval/simulador.py`` sobre o dataset IPv6-EH
    (Anexo B): fluxo temporal deterministico, aquecimento e aprendizado
    incremental (prever -> medir -> aprender). Serve de referencia para o
    smoke test e para os valores esperados nos experimentos reais.

``coleta`` (alias ``vm``)
    Analisa os logs reais do Agente Auditoria (``eventos.jsonl``) contra um
    CSV de rotulos (0 = legitimo, 1..4 = C1..C4). O score de risco e
    ``1 - confianca`` (a confianca do AD e a probabilidade de legitimidade);
    se o log nao trouxer ``confianca``, usa a acao como fallback. Campos
    opcionais por evento: ``latencia_ms``, ``cpu_pct``, ``rss_mb``, ``rep``.

Uso:

    # Smoke test (1 repeticao) - mesmo comando da Fase 6 do checklist
    python -m eval.experimentos_vms --cenario C1 --reps 1 --seed 42 \\
           --saida eval/results/smoke_vm

    # Campanha completa simulada (4 cenarios)
    python -m eval.experimentos_vms --cenario ALL --reps 30 --seed 42 \\
           --saida eval/results/vm_2026-XX-XX/simulado

    # Coleta de uma execucao real nas VMs
    python -m eval.experimentos_vms --cenario C1 --fonte coleta \\
           --audit-log /var/lib/mfa/logs/eventos.jsonl --rotulos rotulos.csv \\
           --saida eval/results/vm_2026-XX-XX/C1
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from attacks.scenarios import CENARIOS  # noqa: E402
from eval.metrics import operating_point, resumo  # noqa: E402
from eval.simulador import (  # noqa: E402
    DESTINO,
    _estatisticas,
    _padronizar,
    avaliar_detector,
    avaliar_dqn,
    carregar_classes,
    montar_stream,
)

#: Colunas do CSV (uma linha por repeticao x modelo).
COLUNAS = [
    "cenario", "rep", "seed", "fonte", "modelo", "eventos",
    "tpr", "fpr", "auc", "eer", "tpr_fpr3",
    "precisao", "recall", "f1",
    "lat_p50_ms", "lat_p95_ms", "lat_p99_ms",
    "cpu_pct", "rss_mb", "bloqueios", "escaladas", "duracao_s",
]

#: Acoes do Agente Decisor (AD) mapeadas para inteiros.
ACOES = {"aceitar": 0, "solicitar_mfa": 1, "bloquear": 2}

#: Risco atribuido a cada acao quando o log nao traz ``confianca``.
RISCO_POR_ACAO = {0: 0.1, 1: 0.5, 2: 0.9}

MODELOS_VALIDOS = ("ftrl", "arf", "ensemble", "dqn")


# ---------------------------------------------------------------------------
# Recursos do processo (opcional: psutil)
# ---------------------------------------------------------------------------
def _cpu_amostra():
    """Marca o inicio da medicao de CPU (None se psutil nao estiver instalado)."""
    try:
        import psutil

        t = psutil.Process().cpu_times()
        return (t.user + t.system, time.perf_counter())
    except Exception:  # pragma: no cover - ambiente sem psutil
        return None


def _recursos(inicio) -> tuple:
    """Percentual de CPU (relativo a um nucleo) e RSS em MB desde ``inicio``."""
    try:
        import psutil

        proc = psutil.Process()
        rss = proc.memory_info().rss / (1024.0 * 1024.0)
        if inicio is None:
            return float("nan"), round(rss, 2)
        t = proc.cpu_times()
        cpu_s = (t.user + t.system) - inicio[0]
        parede = time.perf_counter() - inicio[1]
        cpu = 100.0 * cpu_s / parede if parede > 0 else float("nan")
        return round(cpu, 2), round(rss, 2)
    except Exception:  # pragma: no cover - ambiente sem psutil
        return float("nan"), float("nan")


# ---------------------------------------------------------------------------
# Metricas por cenario (mesma semantica de eval.simulador._metricas_por_cenario)
# ---------------------------------------------------------------------------
def metricas_cenario(scores, ybin, cen, codigo: int) -> dict:
    """Metricas do cenario ``codigo`` contra os eventos legitimos.

    Reaproveita ``eval.metrics.resumo`` e ``operating_point`` (ponto de
    operacao com FPR <= 3%, critico do QP4), mas calcula apenas o cenario
    pedido - evita recomputar os quatro cenarios a cada repeticao.
    """
    scores = np.asarray(scores, dtype=np.float64)
    ybin = np.asarray(ybin, dtype=np.int64)
    cen = np.asarray(cen, dtype=np.int64)
    ata = cen == codigo
    leg = cen == 0
    if ata.sum() == 0 or leg.sum() == 0:
        raise ValueError(
            f"sem eventos suficientes para C{codigo} "
            f"(ataques={int(ata.sum())}, legitimos={int(leg.sum())}); "
            "aumente --eventos"
        )
    sc = np.concatenate([scores[ata], scores[leg]])
    lb = np.concatenate([np.ones(ata.sum(), dtype=np.int64),
                         np.zeros(leg.sum(), dtype=np.int64)])
    return {**resumo(sc, lb), **operating_point(sc, lb)}


def _percentis_ms(valores) -> tuple:
    if not valores:
        return (float("nan"), float("nan"), float("nan"))
    v = np.asarray(valores, dtype=np.float64)
    return tuple(float(np.percentile(v, p)) for p in (50, 95, 99))


# ---------------------------------------------------------------------------
# Fonte simulada
# ---------------------------------------------------------------------------
def executar_simulado(cenarios, reps: int, seed_base: int, eventos: int, warm: int,
                      modelos, destino=DESTINO, verboso: bool = True) -> list:
    """Reexecuta o pipeline do simulador e devolve uma linha por rep x modelo."""
    classes = carregar_classes(Path(destino))
    linhas = []

    for cenario in cenarios:
        codigo = CENARIOS[cenario].codigo
        for rep in range(reps):
            seed = seed_base + rep
            X, y = montar_stream(classes, eventos, warm, seed)
            med, des = _estatisticas(X, warm)
            X = _padronizar(X, med, des)

            for modelo in modelos:
                t0 = time.perf_counter()
                inicio_cpu = _cpu_amostra()

                if modelo == "dqn":
                    pol = avaliar_dqn(X, y, warm, seed)
                    m = metricas_cenario(pol["scores"], pol["ybin"], pol["cenario"], codigo)
                    ata = pol["cenario"] == codigo
                    bloqueios = int((pol["acoes"][ata] == 2).sum())
                    escaladas = int((pol["acoes"][ata] == 1).sum())
                    lat = tuple(v / 1000.0 for v in (pol["lat_p50_us"],
                                                     pol["lat_p95_us"],
                                                     pol["lat_p99_us"]))
                else:
                    det = avaliar_detector(X, y, modelo, warm, seed)
                    m = metricas_cenario(det["scores"], det["ybin"], det["cenario"], codigo)
                    bloqueios = escaladas = ""
                    lat = tuple(v / 1000.0 for v in (det["lat_p50_us"],
                                                     det["lat_p95_us"],
                                                     det["lat_p99_us"]))

                duracao = time.perf_counter() - t0
                cpu, rss = _recursos(inicio_cpu)
                linhas.append(_montar_linha(
                    cenario=cenario, rep=rep, seed=seed, fonte="simulado",
                    modelo=modelo, eventos=int(m["n_pos"] + m["n_neg"]), m=m,
                    lat=lat, cpu=cpu, rss=rss, bloqueios=bloqueios,
                    escaladas=escaladas, duracao=duracao,
                ))
                if verboso:
                    print(f"  {cenario} rep={rep} {modelo}: "
                          f"TPR={m['tpr']:.4f} FPR={m['fpr']:.4f} "
                          f"AUC={m['auc']:.4f} ({duracao:.1f}s)")
    return linhas


# ---------------------------------------------------------------------------
# Fonte de coleta (logs reais do AA)
# ---------------------------------------------------------------------------
def ler_auditoria(caminho) -> list:
    """Le o JSONL do Agente Auditoria (um objeto por linha)."""
    eventos = []
    caminho = Path(caminho)
    with open(caminho, encoding="utf-8") as fh:
        for numero, linha in enumerate(fh, 1):
            linha = linha.strip()
            if not linha:
                continue
            try:
                evento = json.loads(linha)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{caminho}:{numero}: JSON invalido ({exc})") from exc
            if "acao" not in evento:
                raise ValueError(f"{caminho}:{numero}: campo 'acao' ausente")
            eventos.append(evento)
    return eventos


def _coluna(campos, nomes) -> str | None:
    for campo in campos or ():
        if campo.strip().lower() in nomes:
            return campo
    return None


def normalizar_rotulo(valor) -> int:
    """Converte 'legitimo', 'C1'..'C4' ou '0'..'4' para o codigo numerico."""
    texto = str(valor).strip().lower()
    if texto in {"", "0", "legitimo", "legítimo", "legit", "normal"}:
        return 0
    for cenario in CENARIOS.values():
        if texto in {cenario.id.lower(), str(cenario.codigo), cenario.nome.lower()}:
            return cenario.codigo
    return int(texto)


def ler_rotulos(caminho) -> list:
    """Le o CSV de rotulos (coluna ``rotulo``, ``label`` ou ``cenario``)."""
    caminho = Path(caminho)
    with open(caminho, newline="", encoding="utf-8") as fh:
        leitor = csv.DictReader(fh)
        campo = _coluna(leitor.fieldnames, {"rotulo", "rótulo", "label",
                                            "cenario", "cenário", "classe"})
        if campo is None:
            raise ValueError(
                f"{caminho}: coluna de rotulo ausente "
                "(use 'rotulo', 'label' ou 'cenario')"
            )
        return [normalizar_rotulo(linha[campo]) for linha in leitor]


def _agrupar_por_rep(eventos) -> dict:
    grupos = {}
    for indice, evento in enumerate(eventos):
        try:
            rep = int(evento.get("rep", 0))
        except (TypeError, ValueError):
            rep = 0
        grupos.setdefault(rep, []).append(indice)
    return dict(sorted(grupos.items()))


def _media_campo(eventos, indices, campo) -> float:
    valores = []
    for i in indices:
        valor = eventos[i].get(campo)
        if valor is None:
            continue
        try:
            valores.append(float(valor))
        except (TypeError, ValueError):
            continue
    return float(np.mean(valores)) if valores else float("nan")


def executar_coleta(cenario: str, eventos, rotulos, verboso: bool = True) -> list:
    """Analisa logs reais do AA contra os rotulos e devolve uma linha por rep."""
    if len(eventos) != len(rotulos):
        raise ValueError(
            f"{len(eventos)} eventos no log e {len(rotulos)} rotulos: "
            "as listas precisam ter o mesmo tamanho"
        )
    codigo = CENARIOS[cenario].codigo
    linhas = []

    for rep, indices in _agrupar_por_rep(eventos).items():
        acoes = []
        riscos = []
        for i in indices:
            nome = str(eventos[i]["acao"]).strip().lower()
            if nome not in ACOES:
                raise ValueError(
                    f"acao desconhecida '{eventos[i]['acao']}' "
                    f"(esperado: {', '.join(ACOES)})"
                )
            acao = ACOES[nome]
            acoes.append(acao)
            confianca = eventos[i].get("confianca")
            if confianca is None:
                riscos.append(RISCO_POR_ACAO[acao])
            else:
                riscos.append(1.0 - float(confianca))

        acoes = np.asarray(acoes, dtype=np.int64)
        riscos = np.asarray(riscos, dtype=np.float64)
        ybin = np.asarray([rotulos[i] != 0 for i in indices], dtype=np.int64)
        cen = np.asarray([rotulos[i] for i in indices], dtype=np.int64)

        m = metricas_cenario(riscos, ybin, cen, codigo)
        ata = cen == codigo
        lat = _percentis_ms([
            float(eventos[i]["latencia_ms"]) for i in indices
            if eventos[i].get("latencia_ms") is not None
        ])
        duracao = _media_campo(eventos, indices, "duracao_s")
        linhas.append(_montar_linha(
            cenario=cenario, rep=rep, seed=0, fonte="coleta", modelo="sistema",
            eventos=int(m["n_pos"] + m["n_neg"]), m=m,
            lat=lat,
            cpu=_media_campo(eventos, indices, "cpu_pct"),
            rss=_media_campo(eventos, indices, "rss_mb"),
            bloqueios=int((acoes[ata] == 2).sum()),
            escaladas=int((acoes[ata] == 1).sum()),
            duracao=duracao,
        ))
        if verboso:
            print(f"  {cenario} rep={rep}: TPR={m['tpr']:.4f} "
                  f"FPR={m['fpr']:.4f} AUC={m['auc']:.4f}")
    return linhas


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------
def _montar_linha(*, cenario, rep, seed, fonte, modelo, eventos, m, lat,
                  cpu, rss, bloqueios, escaladas, duracao) -> dict:
    return {
        "cenario": cenario,
        "rep": int(rep),
        "seed": int(seed),
        "fonte": fonte,
        "modelo": modelo,
        "eventos": int(eventos),
        "tpr": round(float(m["tpr"]), 4),
        "fpr": round(float(m["fpr"]), 4),
        "auc": round(float(m["auc"]), 4),
        "eer": round(float(m["eer"]), 4),
        "tpr_fpr3": round(float(m["tpr_fpr3"]), 4),
        "precisao": round(float(m["precisao"]), 4),
        "recall": round(float(m["recall"]), 4),
        "f1": round(float(m["f1"]), 4),
        "lat_p50_ms": round(float(lat[0]), 6),
        "lat_p95_ms": round(float(lat[1]), 6),
        "lat_p99_ms": round(float(lat[2]), 6),
        "cpu_pct": cpu,
        "rss_mb": rss,
        "bloqueios": bloqueios,
        "escaladas": escaladas,
        "duracao_s": round(float(duracao), 2) if duracao is not None else "",
    }


def _limpar(valor):
    if isinstance(valor, float) and math.isnan(valor):
        return ""
    return valor


def escrever_csv(caminho, linhas) -> Path:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", newline="", encoding="utf-8") as fh:
        escritor = csv.DictWriter(fh, fieldnames=COLUNAS, extrasaction="ignore")
        escritor.writeheader()
        for linha in linhas:
            escritor.writerow({k: _limpar(v) for k, v in linha.items()})
    return caminho


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python -m eval.experimentos_vms",
        description="Runner dos cenarios C1-C4 (simulado ou coleta de logs reais).",
    )
    ap.add_argument("--cenario", default="C1", help="C1|C2|C3|C4|ALL (padrao: C1)")
    ap.add_argument("--reps", type=int, default=1, help="repeticoes (tese: 30)")
    ap.add_argument("--seed", type=int, default=42, help="semente base")
    ap.add_argument("--saida", default=str(Path(__file__).resolve().parent
                                           / "results" / "experimentos"),
                    help="diretorio de saida do CSV")
    ap.add_argument("--fonte", default="simulado",
                    choices=["simulado", "coleta", "vm"],
                    help="simulado (pipeline local) ou coleta/vm (logs reais)")
    ap.add_argument("--eventos", type=int, default=20000,
                    help="eventos por repeticao (fonte simulado)")
    ap.add_argument("--warm", type=int, default=2000,
                    help="eventos de aquecimento (fonte simulado)")
    ap.add_argument("--modelos", default="ensemble,dqn",
                    help="modelos separados por virgula (ftrl,arf,ensemble,dqn)")
    ap.add_argument("--destino", default=str(DESTINO),
                    help="diretorio do dataset IPv6-EH (fonte simulado)")
    ap.add_argument("--audit-log", default=None,
                    help="JSONL do AA (fonte coleta)")
    ap.add_argument("--rotulos", default=None,
                    help="CSV de rotulos 0..4 na ordem do log (fonte coleta)")
    ap.add_argument("--arquivo", default="experimentos.csv",
                    help="nome do CSV de saida")
    ap.add_argument("--silencioso", action="store_true", help="nao imprime por repeticao")
    return ap


def _validar(args) -> list:
    cenario = args.cenario.strip().upper()
    if cenario != "ALL" and cenario not in CENARIOS:
        raise ValueError(f"cenario invalido '{args.cenario}' (use C1..C4 ou ALL)")
    if args.reps < 1:
        raise ValueError("--reps deve ser >= 1")

    modelos = [m.strip().lower() for m in args.modelos.split(",") if m.strip()]
    desconhecidos = [m for m in modelos if m not in MODELOS_VALIDOS]
    if desconhecidos:
        raise ValueError(f"modelo(s) invalido(s): {', '.join(desconhecidos)}")
    if not modelos:
        raise ValueError("informe ao menos um modelo")

    fonte = "coleta" if args.fonte == "vm" else args.fonte
    if fonte == "simulado":
        if args.eventos <= args.warm:
            raise ValueError("--eventos deve ser maior que --warm")
    else:
        if not args.audit_log or not args.rotulos:
            raise ValueError("--fonte coleta exige --audit-log e --rotulos")

    cenarios = list(CENARIOS) if cenario == "ALL" else [cenario]
    return cenarios, modelos, fonte


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        cenarios, modelos, fonte = _validar(args)
    except ValueError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2

    if not args.silencioso:
        print(f"Runner C1-C4: fonte={fonte} cenarios={','.join(cenarios)} "
              f"reps={args.reps} seed={args.seed}")

    t0 = time.perf_counter()
    try:
        if fonte == "simulado":
            linhas = executar_simulado(
                cenarios, args.reps, args.seed, args.eventos, args.warm,
                modelos, destino=args.destino, verboso=not args.silencioso,
            )
        else:
            eventos = ler_auditoria(args.audit_log)
            rotulos = ler_rotulos(args.rotulos)
            linhas = []
            for cenario in cenarios:
                linhas += executar_coleta(cenario, eventos, rotulos,
                                          verboso=not args.silencioso)
    except (ValueError, FileNotFoundError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2

    caminho = escrever_csv(Path(args.saida) / args.arquivo, linhas)
    print(f"\n{len(linhas)} linha(s) em {caminho} "
          f"({time.perf_counter() - t0:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
