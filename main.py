import os
import sys
import yaml

from app.controller import AppController
from app.performance_tracker import PerformanceTracker
from app.ohlc_validator import OHLCValidator
from app.timing import TimingDiagnostics
from app.ui_console import ConsoleUI
from services.market_data_client import MarketDataClient


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    performance_report = {"enabled": False, "tracked_new": 0, "updated_entries": 0}
    ohlc_report = {"enabled": False}
    paths = {}

    config = load_config()
    diagnostics = TimingDiagnostics(config.get("diagnostics", {}))
    diagnostics.add_metadata("app_version", config.get("app", {}).get("version", "unknown"))
    diagnostics.add_metadata("github_run_context", {
        "event_name": os.getenv("GITHUB_EVENT_NAME", "local"),
        "run_id": os.getenv("GITHUB_RUN_ID", ""),
        "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT", ""),
        "sha": os.getenv("GITHUB_SHA", ""),
        "ref": os.getenv("GITHUB_REF", ""),
        "expected_schedule_utc": os.getenv("SCANNER_EXPECTED_SCHEDULE_UTC", "13:00"),
    })

    with diagnostics.step("init_ui_controller"):
        ui = ConsoleUI()
        ui.header(config["app"]["name"], f"Versión {config['app']['version']}")
        controller = AppController(config)

    ui.print_source_plan(config)
    ui.console.print("[cyan]🔎 Ejecutando scan inicial...[/cyan]")

    try:
        scan_cfg = config.get("scan", {})
        with diagnostics.step("run_scan_total"):
            with ui.console.status("[bold cyan]Buscando datos en CoinGecko / CoinMarketCap / exchanges...[/bold cyan]", spinner="dots"):
                result = controller.run_scan(
                    max_sectors=scan_cfg.get("max_sectors", 5),
                    tokens_per_sector=scan_cfg.get("tokens_per_sector", 20),
                )
    except Exception as exc:
        ui.console.print(f"[red]Error durante el scan:[/red] {exc}")
        ui.console.print("Revisa conexión a internet o límites de API.")
        diagnostics.add_metadata("fatal_error", f"{type(exc).__name__}: {exc}")
        diagnostics.write()
        sys.exit(1)

    with diagnostics.step("render_console"):
        ui.print_sources_status(result.market_context)
        ui.print_market_context(result.market_context)
        ui.print_sectors(result.sectors)

        display_cfg = config.get("display", {})
        display_cfg["reference_assets"] = config.get("reference_assets", {})
        display_cfg["top_operational_max_per_group"] = config.get("operational_rules", {}).get("top_operational_max_per_group", 8)

        if display_cfg.get("show_token_summary", True):
            ui.print_token_summary(
                result.tokens,
                show_discarded_in_console=display_cfg.get("show_discarded_in_console", False),
            )

        ui.print_top_operational(result.tokens, display_config=display_cfg)
        ui.print_alert_summary(result.tokens)
        ui.print_priority_tier_summary(result.tokens)
        ui.print_tokens(result.tokens, display_config=display_cfg)

    with diagnostics.step("export_outputs"):
        paths = controller.export(result)

    try:
        with diagnostics.step("performance_tracker"):
            performance_report = PerformanceTracker(
                config,
                controller.cg,
            ).run(result)
    except Exception as exc:
        ui.console.print(f"[yellow]⚠️ Performance tracker no pudo ejecutarse:[/yellow] {exc}")
        performance_report = {"enabled": False, "tracked_new": 0, "updated_entries": 0, "error": str(exc)}



    try:
        with diagnostics.step("ohlc_validator"):
            ohlc_report = OHLCValidator(
                config,
                MarketDataClient(config.get("ohlc_validator", {})),
            ).run(result)
    except Exception as exc:
        ui.console.print(f"[yellow]⚠️ OHLC validator no pudo ejecutarse:[/yellow] {exc}")
        ohlc_report = {"enabled": False, "error": str(exc)}

    diagnostics.add_metadata("performance_report", performance_report)
    diagnostics.add_metadata("ohlc_report", ohlc_report)
    diagnostics.add_metadata("tokens_total", len(getattr(result, "tokens", [])))
    diagnostics.add_metadata("market_mode", getattr(result, "market_mode", ""))
    diagnostics.add_metadata("export_paths", paths)

    with diagnostics.step("write_diagnostics"):
        diag_paths = diagnostics.write()

    ui.console.print("[green]Exportación completada:[/green]")
    for key, value in paths.items():
        ui.console.print(f"  {key}: {value}")

    if performance_report and performance_report.get("enabled"):
        ui.console.print("[bold]📈 Performance tracker[/bold]")
        ui.console.print(f"   Nuevos registros: {performance_report.get('tracked_new', 0)}")
        ui.console.print(f"   Versión / esquema: {performance_report.get('app_version', 'unknown')} / {performance_report.get('schema_version', 'unknown')}")
        ui.console.print(f"   Registros actualizados en ventana exacta: {performance_report.get('updated_entries', 0)}")
        ui.console.print(f"   Observaciones de precio actualizadas: {performance_report.get('observed_updates', 0)}")
        ui.console.print("   Archivos: tracked_entries.csv | performance_summary.csv | audit_report.json | output_manifest.json")
        target_summary = performance_report.get("target_summary", {})
        if isinstance(target_summary, dict) and target_summary.get("text"):
            ui.console.print(f"   {target_summary.get('text')}")
        target_hit_summary = performance_report.get("target_hit_summary", {})
        if isinstance(target_hit_summary, dict) and target_hit_summary.get("text"):
            ui.console.print(f"   {target_hit_summary.get('text')}")
        target_summary_net = performance_report.get("target_summary_net", {})
        if isinstance(target_summary_net, dict) and target_summary_net.get("text"):
            ui.console.print(f"   {target_summary_net.get('text')}")
        quality = performance_report.get("data_quality", {})
        if isinstance(quality, dict):
            ui.console.print(
                f"   🧪 Auditoría: {quality.get('status', '-')} | grado {quality.get('grade', '-')} | "
                f"legacy excluidos: {quality.get('legacy_entries_excluded', 0)} | "
                f"entradas limpias: {quality.get('clean_trade_episode_entries', 0)}"
            )
        ui.console.print("")

    if ohlc_report and ohlc_report.get("enabled"):
        ui.console.print("[bold]📊 OHLC intradía token + BTC[/bold]")
        ui.console.print(f"   Top actuales: {ohlc_report.get('current_candidates', 0)} | históricos: {ohlc_report.get('historical_candidates', 0)}")
        ui.console.print(f"   Validaciones completas: {ohlc_report.get('validations_completed', 0)}")
        if ohlc_report.get("text"):
            ui.console.print(f"   {ohlc_report.get('text')}")
        ui.console.print("   Archivos: ohlc_validation.csv | latest_ohlc_report.json | ohlc_candidates_current.csv")
        ui.console.print("")

    if diag_paths:
        ui.console.print("[bold]⏱ Diagnóstico guardado[/bold]")
        for key, value in diag_paths.items():
            ui.console.print(f"   {key}: {value}")
        ui.console.print("")

    for line in diagnostics.format_summary_lines():
        ui.console.print(line)


if __name__ == "__main__":
    main()
