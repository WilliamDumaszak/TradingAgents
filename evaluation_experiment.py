"""
Script de execução do experimento de racionalidade limitada.

Executa 30 rodadas organizadas em:
  - 2 datas  × 3 cenários × 5 runs = 30 execuções

Cenários:
  C1 — Baseline        : market + fundamentals + news + social
  C2 — Análise convencional : market + fundamentals
  C3 — Análise quantitativa : market

Uso:
  python run_experiment.py                    # roda tudo
  python run_experiment.py --scenario C1      # só um cenário
  python run_experiment.py --date 2024-08-05  # só uma data
  python run_experiment.py --dry-run          # mostra o plano sem executar
"""

import argparse
import time
import traceback
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

# ── Configuração do experimento ──────────────────────────────────────────────

TICKER = "AAPL"

DATES = [
    "2025-01-30",   # Earnings Q1 2025 — contexto misto
    "2024-08-05",   # Sell-off global   — choque exógeno
]

SCENARIOS = {
    "C1": ["market", "fundamentals", "news", "social"],
    "C2": ["market", "fundamentals"],
    "C3": ["market"],
}

N_RUNS = 5

# Pausa entre execuções (segundos) — evita rate limit na API
PAUSE_BETWEEN_RUNS = 5

# Pausa extra entre cenários
PAUSE_BETWEEN_SCENARIOS = 10

# Diretório de resultados
RESULTS_DIR = "results/experiments"

# ── Configuração do modelo ────────────────────────────────────────────────────

def build_config():
    config = DEFAULT_CONFIG.copy()
    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1
    config["data_vendors"] = {
        "core_stock_apis": "yfinance",
        "technical_indicators": "yfinance",
        "fundamental_data": "alpha_vantage",
        "news_data": "alpha_vantage",
    }
    return config


# ── Helpers de log de progresso ───────────────────────────────────────────────

def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def json_path(date: str, scenario: str, run_id: int) -> Path:
    """Retorna o path esperado do JSON de uma execução."""
    filename = f"{TICKER}_{date}_{scenario}_run{run_id}.json"
    return Path(RESULTS_DIR) / filename


def already_done(date: str, scenario: str, run_id: int) -> bool:
    """Verifica se a execução já foi salva com sucesso."""
    p = json_path(date, scenario, run_id)
    if not p.exists():
        return False
    # Valida que o arquivo não está vazio/corrompido
    try:
        import json
        with open(p) as f:
            data = json.load(f)
        # Checa campos mínimos esperados
        return bool(data.get("signals") and data.get("metadata"))
    except Exception:
        return False


def print_plan(dates, scenarios):
    total = len(dates) * len(scenarios) * N_RUNS
    done = sum(
        1 for date in dates
        for scenario in scenarios
        for run_id in range(1, N_RUNS + 1)
        if already_done(date, scenario, run_id)
    )
    pending = total - done

    print("\n" + "─" * 60)
    print(f"  PLANO DO EXPERIMENTO — {TICKER}")
    print("─" * 60)
    for date in dates:
        for scenario, analysts in scenarios.items():
            runs_done = sum(1 for r in range(1, N_RUNS + 1) if already_done(date, scenario, r))
            status = f"{runs_done}/{N_RUNS} concluídos"
            print(f"  {date} | {scenario} | analistas: {', '.join(analysts)} | {status}")
    print("─" * 60)
    print(f"  Total: {total}  |  Já concluídos: {done}  |  Pendentes: {pending}")
    print(f"  Pausa entre runs: {PAUSE_BETWEEN_RUNS}s | entre cenários: {PAUSE_BETWEEN_SCENARIOS}s")
    print("─" * 60 + "\n")


# ── Execução principal ────────────────────────────────────────────────────────

def run_all(dates, scenarios, dry_run=False):
    print_plan(dates, scenarios)

    if dry_run:
        log("Modo dry-run: nenhuma execução realizada.")
        return

    config = build_config()
    total = len(dates) * len(scenarios) * N_RUNS
    completed = 0
    failed = []

    for date in dates:
        for scenario_idx, (scenario, analysts) in enumerate(scenarios.items()):

            log(f"Iniciando cenário {scenario} ({', '.join(analysts)}) para {date}")

            # Instância nova por cenário (garante selected_analysts correto)
            ta = TradingAgentsGraph(
                selected_analysts=analysts,
                debug=False,
                config=config,
                experiment_results_dir=RESULTS_DIR,
            )

            for run_id in range(1, N_RUNS + 1):
                completed += 1
                label = f"{date} | {scenario} | run {run_id}/{N_RUNS}  [{completed}/{total}]"

                log(f"Verificando: {label}")

                if already_done(date, scenario, run_id):
                    log(f"  ↷ Já concluído, pulando.")
                    continue

                log(f"  → Executando...")

                MAX_RETRIES = 3
                for attempt in range(1, MAX_RETRIES + 1):
                    try:
                        _, decision = ta.propagate(
                            TICKER,
                            date,
                            scenario=scenario,
                            run_id=run_id,
                        )
                        log(f"  ✓ Decisão: {decision}")
                        break
                    except Exception as e:
                        log(f"  ✗ Tentativa {attempt}/{MAX_RETRIES} falhou: {type(e).__name__}: {e}")
                        if attempt < MAX_RETRIES:
                            wait = 30 * attempt
                            log(f"    Aguardando {wait}s antes de tentar novamente...")
                            time.sleep(wait)
                        else:
                            traceback.print_exc()
                            failed.append({"date": date, "scenario": scenario, "run_id": run_id, "error": str(e)})

                # Pausa entre runs (exceto na última)
                is_last_run = run_id == N_RUNS
                is_last_scenario = scenario_idx == len(scenarios) - 1
                is_last_date = date == dates[-1]

                if not (is_last_run and is_last_scenario and is_last_date):
                    pause = PAUSE_BETWEEN_SCENARIOS if is_last_run else PAUSE_BETWEEN_RUNS
                    log(f"  Aguardando {pause}s...")
                    time.sleep(pause)

    # Relatório final
    print("\n" + "─" * 60)
    print(f"  EXPERIMENTO CONCLUÍDO")
    print(f"  Execuções realizadas : {completed}")
    print(f"  Falhas               : {len(failed)}")
    if failed:
        print("\n  Execuções com erro:")
        for f in failed:
            print(f"    {f['date']} | {f['scenario']} | run {f['run_id']} → {f['error']}")
    print(f"\n  Resultados em: {RESULTS_DIR}/")
    print("─" * 60 + "\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Executa o experimento de racionalidade limitada.")
    parser.add_argument("--scenario", choices=["C1", "C2", "C3"], help="Rodar apenas um cenário específico")
    parser.add_argument("--date", choices=DATES, help="Rodar apenas uma data específica")
    parser.add_argument("--dry-run", action="store_true", help="Exibe o plano sem executar")
    args = parser.parse_args()

    dates = [args.date] if args.date else DATES
    scenarios = {args.scenario: SCENARIOS[args.scenario]} if args.scenario else SCENARIOS

    run_all(dates, scenarios, dry_run=args.dry_run)
