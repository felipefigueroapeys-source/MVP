from rich.console import Console
from rich.table import Table
from rich.panel import Panel


SECTOR_ABBREVIATIONS = {
    "Decentralized Finance (DeFi)": "DeFi",
    "Artificial Intelligence (AI)": "AI",
    "Real World Assets (RWA)": "RWA",
    "Layer 1 (L1)": "L1",
    "Layer 2 (L2)": "L2",
    "Optimism Superchain Ecosystem": "Optimism",
    "Cross-chain Communication": "Cross-chain",
    "Privacy Blockchain": "Privacy",
    "Chain Abstraction": "Chain Abs.",
    "BNB Chain Ecosystem": "BNB Chain",
    "Solana Ecosystem": "Solana",
    "Ethereum Ecosystem": "Ethereum",
    "Avalanche Ecosystem": "Avalanche",
    "Polygon Ecosystem": "Polygon",
    "Gaming": "Gaming",
    "DePIN": "DePIN",
    "RWA Protocol": "RWA Prot.",
}


def abbreviate_sector_name(name: str | None, max_len: int = 14) -> str:
    if not name:
        return "-"

    if name in SECTOR_ABBREVIATIONS:
        return SECTOR_ABBREVIATIONS[name]

    cleaned = (
        name.replace("Ecosystem", "Eco.")
            .replace("Protocol", "Prot.")
            .replace("Communication", "Comm.")
            .replace("Decentralized", "DeFi")
            .replace("Artificial Intelligence", "AI")
            .replace("Real World Assets", "RWA")
    )

    if len(cleaned) <= max_len:
        return cleaned

    return cleaned[: max_len - 1].rstrip() + "…"


def token_color_from_category(category: str | None) -> str:
    category = category or ""

    if category.startswith("A+"):
        return "🟩"
    if category.startswith("A "):
        return "🟢"
    if category.startswith("B "):
        return "🟡"
    if category.startswith("C "):
        return "🔴"

    return "⚪"


def action_from_token(token) -> str:
    category = token.category or ""
    ch24 = token.change_24h_pct
    ch7 = token.change_7d_pct
    ch30 = token.change_30d_pct

    if category.startswith("C "):
        return "⛔ Descartar"

    if ch24 is not None and ch24 > 20:
        return "🔴 No perseguir"

    if ch24 is not None and ch24 > 15:
        return "🟠 Extendido"

    if ch30 is not None and ch30 > 150:
        return "⚠️ Exceso 30D"

    if category.startswith("A+") and ch24 is not None and 2 <= ch24 <= 15 and (ch7 or 0) > 5 and (ch30 or 0) > 10:
        return "🚀 Prioridad operativa"

    if category.startswith("A") and ch24 is not None and ch24 >= 0:
        if (ch7 or 0) < 0:
            return "🟡 Rebote táctico"
        return "🟢 Candidato activo"

    if category.startswith("A") and ch24 is not None and -10 <= ch24 < 0:
        return "🟡 Esperar retroceso"

    if category.startswith("B "):
        return "🟡 Vigilar"

    return "⚪ Revisar"


def operational_reason_from_token(token) -> str:
    category = token.category or ""
    notes = token.notes or []
    joined_notes = " | ".join(notes)

    ch24 = token.change_24h_pct
    ch7 = token.change_7d_pct
    ch30 = token.change_30d_pct
    volume = token.volume_24h_usd or 0
    market_cap = token.market_cap_usd or 0

    if category.startswith("C "):
        if "Gate: market cap bajo" in joined_notes:
            return "Market cap bajo"
        if "Gate: volumen bajo" in joined_notes:
            return "Volumen bajo"
        if "Gate: 24h <" in joined_notes:
            return "Caída 24h fuerte"
        if not token.spot_pair:
            return "Sin spot validado"
        return "No cumple gates"

    if ch24 is not None and ch24 > 20:
        return "24h extendido >20%"

    if ch24 is not None and ch24 > 15:
        return "24h extendido >15%"

    if ch30 is not None and ch30 > 150:
        return "30D >150%"

    if category.startswith("A+") and ch24 is not None and 2 <= ch24 <= 15:
        return "Momentum operativo"

    if category.startswith("A") and ch24 is not None and ch24 >= 0:
        if (ch7 or 0) < 0 and (ch30 or 0) > 10:
            return "Rebote con 7D negativo"
        if (ch7 or 0) > 5 and (ch30 or 0) > 10:
            return "24h/7D/30D alineados"
        if (ch30 or 0) > 20:
            return "30D fuerte"
        return "Momentum positivo"

    if category.startswith("A") and ch24 is not None and -10 <= ch24 < 0:
        if (ch7 or 0) > 5 and (ch30 or 0) > 10:
            return "Fuerza previa, retroceso actual"
        if (ch30 or 0) > 20:
            return "30D fuerte, esperar retroceso"
        return "Fuerte en retroceso"

    if category.startswith("B "):
        if market_cap >= 500_000_000 and volume >= 50_000_000:
            return "Líquida, sin momentum claro"
        if (ch30 or 0) > 20:
            return "30D fuerte, vigilar"
        return "Vigilar confirmación operativa"

    return "Revisar manualmente"



def alerts_from_token(token) -> str:
    alerts = []

    ch24 = token.change_24h_pct
    ch7 = token.change_7d_pct
    ch30 = token.change_30d_pct

    if ch24 is not None:
        if ch24 > 20:
            alerts.append("🔴 24h extremo")
        elif ch24 > 15:
            alerts.append("🟠 24h extendido")
        elif ch24 > 12:
            alerts.append("🟡 24h cerca de extensión")
        elif ch24 < -10:
            alerts.append("🔴 caída 24h fuerte")

    if ch7 is not None and ch7 > 50:
        alerts.append("⚠️ 7D muy alto")

    if ch30 is not None:
        if ch30 > 300:
            alerts.append("⚠️ 30D extremo")
        elif ch30 > 150:
            alerts.append("⚠️ 30D alto")

    return " | ".join(alerts) if alerts else "-"


def priority_tier_from_token(token) -> str:
    action = action_from_token(token)
    category = token.category or ""
    alerts = alerts_from_token(token)

    high_risk_alerts = (
        "🔴 24h extremo",
        "🟠 24h extendido",
        "⚠️ 30D extremo",
        "🔴 caída 24h fuerte",
    )

    if category.startswith("C ") or action.startswith("⛔"):
        return "T4 riesgo alto"

    if any(alert in alerts for alert in high_risk_alerts) or action.startswith("🔴") or action.startswith("🟠"):
        return "T4 riesgo alto"

    if category.startswith("B ") or action.startswith("🟡 Vigilar"):
        return "T3 vigilancia"

    if alerts and alerts != "-":
        return "T2 válido con alerta"

    if category.startswith("A+") or category.startswith("A "):
        return "T1 limpio"

    return "T3 vigilancia"


def category_group(category: str | None) -> str:
    category = category or ""
    if category.startswith("A+"):
        return "A+"
    if category.startswith("A "):
        return "A"
    if category.startswith("B "):
        return "B"
    if category.startswith("C "):
        return "C"
    return "OTHER"


def is_reference_asset(token, reference_symbols: set[str]) -> bool:
    symbol = (getattr(token, "symbol", "") or "").upper()
    return symbol in reference_symbols


def compact_category_label(category: str | None) -> str:
    category = category or ""
    if category.startswith("A+"):
        return "🟩 A+"
    if category.startswith("A "):
        return "🟢 A"
    if category.startswith("B "):
        return "🟡 B"
    if category.startswith("C "):
        return "🔴 C"
    return "⚪ -"


def compact_action_label(action: str | None) -> str:
    action = action or ""
    mapping = {
        "🚀 Prioridad operativa": "🚀 Prioridad",
        "🟢 Candidato activo": "🟢 Activo",
        "🟡 Esperar retroceso": "🟡 Retroceso",
        "🟡 Rebote táctico": "🟡 Rebote",
        "🟡 Vigilar": "🟡 Vigilar",
        "🟠 Extendido": "🟠 Extendido",
        "🔴 No perseguir": "🔴 No perseguir",
        "⚠️ Exceso 30D": "⚠️ Exceso 30D",
        "⛔ Descartar": "⛔ Descartar",
    }
    return mapping.get(action, action)


def compact_reason_label(reason: str | None) -> str:
    reason = reason or "-"
    mapping = {
        "Momentum operativo": "Momentum",
        "Momentum positivo": "Momentum +",
        "24h/7D/30D alineados": "24/7/30 ok",
        "30D fuerte": "30D fuerte",
        "30D > 150%": "30D >150%",
        "Fuerza previa, retroceso actual": "Fza previa",
        "30D fuerte, esperar retroceso": "30D fuerte",
        "Fuerte en retroceso": "Retroceso",
        "24h extendido >15%": "24h >15%",
        "24h extendido >20%": "24h >20%",
        "Líquida, sin momentum claro": "Líquida",
        "Vigilar confirmación operativa": "Confirmar",
        "No cumple gates": "No cumple",
        "Market cap bajo": "MC bajo",
        "Volumen bajo": "Vol bajo",
        "Caída 24h fuerte": "Caída 24h",
        "Sin spot validado": "Sin spot",
    }
    return mapping.get(reason, reason)


def compact_alerts_label(alerts: str | None) -> str:
    alerts = alerts or "-"
    if alerts == "-":
        return "-"

    replacements = {
        "🔴 24h extremo": "🔴24h",
        "🟠 24h extendido": "🟠24h",
        "🟡 24h cerca de extensión": "🟡24h",
        "⚠️ 30D extremo": "⚠️30D",
        "⚠️ 30D alto": "⚠️30D",
        "⚠️ 7D muy alto": "⚠️7D",
        "🔴 caída 24h fuerte": "🔴Caída",
    }

    parts = [p.strip() for p in alerts.split("|")]
    compacted = [replacements.get(p, p) for p in parts if p]
    return " ".join(compacted) if compacted else "-"


def compact_tier_label(tier: str | None) -> str:
    tier = tier or "-"
    if tier.startswith("T1"):
        return "T1"
    if tier.startswith("T2"):
        return "T2"
    if tier.startswith("T3"):
        return "T3"
    if tier.startswith("T4"):
        return "T4"
    return tier


def abbreviate_trend_signal(signal: str | None) -> str:
    if not signal or signal == "-":
        return "-"

    s = str(signal)
    s = s.replace("CoinGecko Trending", "CG")
    s = s.replace(" | ", "/")
    return s


def sector_group_from_name(sector_name: str | None) -> str:
    if not sector_name:
        return "other"

    name = str(sector_name).lower()

    noisy_keywords = ["meme", "memes", "meme coins", "telegram apps", "socialfi"]
    optional_keywords = ["gaming", "gamefi", "socialfi", "telegram apps"]
    core_keywords = [
        "decentralized finance", "defi", "real world assets", "rwa", "layer 1", "layer 2",
        "artificial intelligence", "ai", "privacy", "chain abstraction", "cross-chain",
        "optimism", "tokenized", "depin", "restaking", "liquid restaking", "payments",
        "settlement", "data availability", "modular", "oracle", "middleware"
    ]

    for keyword in noisy_keywords:
        if keyword in name:
            return "noisy"

    for keyword in optional_keywords:
        if keyword in name:
            return "optional"

    for keyword in core_keywords:
        if keyword in name:
            return "core"

    return "other"



def sort_tokens_desc(tokens):
    """
    Orden operativo real: mejor primero.
    Se usa como base para ranking interno.
    """
    def category_rank(token):
        group = category_group(token.category)
        if group == "A+":
            return 4
        if group == "A":
            return 3
        if group == "B":
            return 2
        if group == "C":
            return 1
        return 0

    def tier_rank(token):
        tier = priority_tier_from_token(token)
        if tier.startswith("T1"):
            return 4
        if tier.startswith("T2"):
            return 3
        if tier.startswith("T3"):
            return 2
        if tier.startswith("T4"):
            return 1
        return 0

    return sorted(
        tokens,
        key=lambda t: (
            t.score or 0,
            category_rank(t),
            tier_rank(t),
            t.change_24h_pct if t.change_24h_pct is not None else -999,
            t.volume_24h_usd or 0,
        ),
        reverse=True,
    )


def sort_tokens_for_screen(tokens):
    """
    Orden visual solicitado:
    - El mejor candidato queda en la última línea del bloque.
    - La columna # marca ranking real: 1 = mejor.
    Ejemplo con A de 16 tokens:
    arriba aparece #16 y abajo queda #1.
    """
    return list(reversed(sort_tokens_desc(tokens)))


class ConsoleUI:
    def __init__(self):
        self.console = Console()

    def header(self, title: str, subtitle: str = ""):
        self.console.print(Panel.fit(f"[bold]{title}[/bold]\n{subtitle}", border_style="cyan"))

    def print_source_plan(self, config: dict):
        cmc_cfg = config.get("coinmarketcap", {})
        cmc_enabled = cmc_cfg.get("enabled", False)
        exchanges = config.get("exchanges", {}).get("preferred", [])

        self.console.print("[bold]📡 Fuentes objetivo del scanner[/bold]")
        trend_cfg = config.get("trend_signals", {})
        cg_suffix = " + Trending" if trend_cfg.get("enabled", False) and trend_cfg.get("coingecko_trending", False) else ""
        self.console.print(f"   🦎 CoinGecko: categorías + tokens{cg_suffix}")

        sector_expansion = config.get("sector_expansion", {})
        if sector_expansion.get("enabled", False):
            self.console.print("   🧭 Sectores recomendados/opcionales: activado")

        self.console.print(f"   🪙 CoinMarketCap: {'activado' if cmc_enabled else 'desactivado'}")
        self.console.print(f"   🏦 Exchanges: {' → '.join(exchanges) if exchanges else 'sin configurar'}")
        self.console.print("")

    def print_sources_status(self, context: dict):
        cmc_configured = context.get("coinmarketcap_api_configured")
        cmc_loaded = context.get("coinmarketcap_categories_loaded", 0)
        cmc_status = context.get("coinmarketcap_status", "desconocido")

        self.console.print("[bold]📡 Fuentes consultadas[/bold]")
        self.console.print("   🦎 CoinGecko: activo")

        if cmc_status == "ok":
            self.console.print(f"   🪙 CoinMarketCap: OK ({cmc_loaded} categorías cargadas)")
        elif cmc_configured:
            self.console.print(f"   🟠 CoinMarketCap: configurado, pero sin datos útiles ({cmc_status})")
        else:
            self.console.print("   ⚪ CoinMarketCap: no configurado / no usado")

        trend_info = context.get("trend_signals", {})
        if trend_info.get("enabled"):
            self.console.print(f"   🔥 CoinGecko Trending: OK ({trend_info.get('tokens_loaded', 0)} señales cargadas)")

        sector_expansion = context.get("sector_expansion", {})
        if sector_expansion.get("enabled"):
            rec = ", ".join(sector_expansion.get("recommended", []))
            opt = ", ".join(sector_expansion.get("optional", []))
            self.console.print(f"   🧭 Sector expansion: recomendados [{rec}]")
            self.console.print(f"   🧭 Sector expansion: opcionales [{opt}]")

        self.console.print("   🏦 Exchanges implementados: Binance → Bybit → LBank")

        exclusions = context.get("token_exclusions", {})
        if exclusions.get("enabled"):
            self.console.print(
                f"   🧹 Exclusiones token-level: {exclusions.get('total_excluded_occurrences', 0)} ocurrencias"
            )

        pair_stats = context.get("pair_validation", {})
        if pair_stats:
            self.console.print(
                f"   🪪 Pares validados: {pair_stats.get('validated', 0)} | "
                f"mismatch rechazados: {pair_stats.get('rejected_price_mismatch', 0)}"
            )
        self.console.print("")

    def print_market_context(self, context: dict):
        self.console.print(f"[bold]🧭 Modo mercado:[/bold] {context.get('mode')} {context.get('color', '')}")
        self.console.print("")
        for note in context.get("notes", []):
            self.console.print(f"   - {note}")
        self.console.print("")

    def print_token_summary(self, tokens, show_discarded_in_console: bool = False):
        summary = {
            "a_plus": 0,
            "a": 0,
            "b": 0,
            "c": 0,
            "other": 0,
            "total": len(tokens),
        }

        for token in tokens:
            group = category_group(token.category)
            if group == "A+":
                summary["a_plus"] += 1
            elif group == "A":
                summary["a"] += 1
            elif group == "B":
                summary["b"] += 1
            elif group == "C":
                summary["c"] += 1
            else:
                summary["other"] += 1

        c_suffix = "" if show_discarded_in_console else " ocultos en consola"

        self.console.print("[bold]📊 Resumen tokens[/bold]")
        self.console.print(f"   🟩 A+: {summary['a_plus']}")
        self.console.print(f"   🟢 A: {summary['a']}")
        self.console.print(f"   🟡 B: {summary['b']}")
        self.console.print(f"   🔴 C: {summary['c']}{c_suffix}")
        self.console.print(f"   Total exportado: {summary['total']}")
        self.console.print("")

    def print_top_operational(self, tokens, display_config: dict | None = None):
        display_config = display_config or {}
        max_per_group = int(display_config.get("top_operational_max_per_group", 8))

        groups = {
            "🚀 Prioridad": [],
            "🟢 Activos": [],
            "🟡 Rebote táctico": [],
            "🟡 Retroceso": [],
            "🟠 Extendidos": [],
            "⚠️ Exceso 30D": [],
            "🔴 No perseguir": [],
        }

        for token in tokens:
            action = action_from_token(token)
            symbol = token.symbol

            if action.startswith("🚀") and len(groups["🚀 Prioridad"]) < max_per_group:
                groups["🚀 Prioridad"].append(symbol)
            elif action.startswith("🟢") and len(groups["🟢 Activos"]) < max_per_group:
                groups["🟢 Activos"].append(symbol)
            elif "Rebote táctico" in action and len(groups["🟡 Rebote táctico"]) < max_per_group:
                groups["🟡 Rebote táctico"].append(symbol)
            elif "Esperar retroceso" in action and len(groups["🟡 Retroceso"]) < max_per_group:
                groups["🟡 Retroceso"].append(symbol)
            elif "Extendido" in action and len(groups["🟠 Extendidos"]) < max_per_group:
                groups["🟠 Extendidos"].append(symbol)
            elif "Exceso 30D" in action and len(groups["⚠️ Exceso 30D"]) < max_per_group:
                groups["⚠️ Exceso 30D"].append(symbol)
            elif "No perseguir" in action and len(groups["🔴 No perseguir"]) < max_per_group:
                groups["🔴 No perseguir"].append(symbol)

        self.console.print("[bold]🎯 Top operativo[/bold]")
        any_group = False
        for label, symbols in groups.items():
            if not symbols:
                continue
            any_group = True
            self.console.print(f"   {label}: {', '.join(symbols)}")

        if not any_group:
            self.console.print("   Sin candidatos operativos destacados.")

        self.console.print("")

    def print_alert_summary(self, tokens):
        alert_counts = {}

        for token in tokens:
            alerts_text = alerts_from_token(token)
            if not alerts_text or alerts_text == "-":
                continue

            for alert in alerts_text.split(" | "):
                alert_counts[alert] = alert_counts.get(alert, 0) + 1

        if not alert_counts:
            return

        self.console.print("[bold]⚠️ Resumen alertas[/bold]")
        for alert, count in sorted(alert_counts.items(), key=lambda item: item[1], reverse=True):
            self.console.print(f"   {alert}: {count}")
        self.console.print("")

    def print_priority_tier_summary(self, tokens):
        summary = {}

        for token in tokens:
            tier = priority_tier_from_token(token)
            summary[tier] = summary.get(tier, 0) + 1

        order = ["T1 limpio", "T2 válido con alerta", "T3 vigilancia", "T4 riesgo alto"]

        self.console.print("[bold]🏷️ Priority tiers[/bold]")
        for tier in order:
            if tier in summary:
                self.console.print(f"   {tier}: {summary[tier]}")
        self.console.print("")

    def print_sectors(self, sectors):
        if not sectors:
            self.console.print("[bold]✅ Sectores considerados en el análisis:[/bold] -")
            self.console.print("")
            return

        sector_names = [abbreviate_sector_name(s.name, max_len=18) for s in sectors]
        self.console.print("[bold]✅ Sectores considerados en el análisis:[/bold]")
        self.console.print("   " + " | ".join(sector_names))
        self.console.print("")

        table = Table(title="Sectores")
        table.add_column("#", justify="right", no_wrap=True)
        table.add_column("Sector")
        table.add_column("Fuente")
        table.add_column("24h", justify="right", no_wrap=True)
        table.add_column("7D", justify="right", no_wrap=True)
        table.add_column("Market Cap", justify="right")
        table.add_column("Vol", justify="right", no_wrap=True)
        table.add_column("Sc", justify="right", no_wrap=True)
        table.add_column("Uso")

        for i, s in enumerate(sectors, 1):
            table.add_row(
                str(i),
                s.name,
                s.source or "-",
                f"{s.change_24h_pct:.2f}%" if s.change_24h_pct is not None else "-",
                f"{s.change_7d_pct:.2f}%" if s.change_7d_pct is not None else "-",
                f"{s.market_cap_usd/1e9:.2f}B" if s.market_cap_usd else "-",
                f"{s.volume_24h_usd/1e6:.1f}M" if s.volume_24h_usd else "-",
                str(s.score),
                "✅ Considerado",
            )
        self.console.print(table)
        self.console.print("")

    def _build_tokens_table(self, title: str, tokens, show_operational_reason: bool = True):
        table = Table(title=title, expand=False, show_lines=False)
        table.add_column("#", justify="right", no_wrap=True, width=3)
        table.add_column("Token", no_wrap=True, width=8)
        table.add_column("Sector", no_wrap=True, width=10)
        table.add_column("Par", no_wrap=True, width=12)
        table.add_column("Ex", no_wrap=True, width=8)
        table.add_column("24h", justify="right", no_wrap=True, width=8)
        table.add_column("7D", justify="right", no_wrap=True, width=8)
        table.add_column("30D", justify="right", no_wrap=True, width=8)
        table.add_column("Vol", justify="right", no_wrap=True, width=8)
        table.add_column("Sc", justify="right", no_wrap=True, width=4)
        table.add_column("Cat", no_wrap=True, width=5)
        table.add_column("Acción", no_wrap=True, width=14)

        if show_operational_reason:
            table.add_column("Motivo", no_wrap=True, width=14)

        table.add_column("Alertas", no_wrap=True, width=14)
        table.add_column("Tier", no_wrap=True, width=4)
        table.add_column("Trend", no_wrap=True, width=6)

        for i, t in enumerate(tokens, 1):
            color = token_color_from_category(t.category)
            row = [
                str(len(tokens) - i + 1),
                t.symbol,
                abbreviate_sector_name(t.sector_name),
                t.spot_pair or "-",
                t.exchange or "-",
                f"{t.change_24h_pct:.2f}%" if t.change_24h_pct is not None else "-",
                f"{t.change_7d_pct:.2f}%" if t.change_7d_pct is not None else "-",
                f"{t.change_30d_pct:.2f}%" if t.change_30d_pct is not None else "-",
                f"{t.volume_24h_usd/1e6:.1f}M" if t.volume_24h_usd else "-",
                str(t.score),
                compact_category_label(t.category),
                compact_action_label(action_from_token(t)),
            ]

            if show_operational_reason:
                row.append(compact_reason_label(operational_reason_from_token(t)))

            row.append(compact_alerts_label(alerts_from_token(t)))
            row.append(compact_tier_label(priority_tier_from_token(t)))
            row.append(abbreviate_trend_signal(t.trend_signal))

            table.add_row(*row)

        return table


    def print_prose_watchlist(self, tokens):
        """
        Lista final en prosa: priorizados -> fuertes -> vigilados.
        Se muestra al final para lectura rápida operacional.
        """
        def symbols(items, limit=None):
            ordered = sort_tokens_desc(items)
            if limit is not None:
                ordered = ordered[:limit]
            return ", ".join(t.symbol for t in ordered) if ordered else "-"

        priority = [
            t for t in tokens
            if category_group(t.category) == "A+"
            or action_from_token(t).startswith("🚀")
            or (getattr(t, "operational_bucket", "") == "prioridad_operativa")
        ]

        strong = [
            t for t in tokens
            if category_group(t.category) == "A"
            and priority_tier_from_token(t) in ("T1 limpio", "T2 válido con alerta")
            and not action_from_token(t).startswith("⚠️")
            and not action_from_token(t).startswith("🔴")
            and not action_from_token(t).startswith("🟠")
        ]

        watched = [
            t for t in tokens
            if (
                category_group(t.category) == "B"
                or priority_tier_from_token(t) in ("T3 vigilancia", "T4 riesgo alto")
                or action_from_token(t).startswith("⚠️")
                or action_from_token(t).startswith("🔴")
                or action_from_token(t).startswith("🟠")
            )
            and t not in priority
            and t not in strong
        ]

        self.console.print("[bold]🎯 Lista final operativa[/bold]")
        self.console.print(f"   🟩 Prioritarios: {symbols(priority)}.")
        self.console.print(f"   🟢 Fuertes: {symbols(strong)}.")
        self.console.print(f"   🟡 Vigilados: {symbols(watched, limit=18)}.")
        self.console.print(
            "   Lectura: verde oscuro = prioridad; verde claro = candidatos fuertes; amarillo = vigilar/no perseguir si hay exceso o alerta."
        )
        self.console.print("")

    def print_column_legend(self):
        self.console.print("[bold]🧾 Lectura rápida[/bold]")
        self.console.print(
            "   # = ranking real dentro del bloque: 1 es el mejor; por diseño, los mejores quedan al final de cada tabla."
        )
        self.console.print(
            "   Sc = score bruto por liquidez, momentum, sector y exchange; mayor Sc suele indicar mejor candidato."
        )
        self.console.print(
            "   Cat = categoría resumida: A+ prioridad, A fuerte, B vigilancia, C descartada."
        )
        self.console.print(
            "   Acción/Motivo = conducta sugerida y razón principal resumida; Alertas/Tier = riesgos y calidad final."
        )
        self.console.print(
            "   Trend = interés externo actual; CG #N significa CoinGecko Trending en posición N."
        )
        self.console.print(
            "   Grupo sector queda solo en exports para no ensuciar la consola."
        )
        self.console.print(
            "   El bloque A+ aparece al final de la consola para dejar visible la prioridad operativa."
        )
        self.console.print(
            "   Regla práctica: Trend aumenta interés, pero no reduce riesgo."
        )
        self.console.print("")

    def print_tokens(self, tokens, display_config: dict | None = None):
        display_config = display_config or {}

        show_discarded = display_config.get("show_discarded_in_console", False)
        max_tokens_console = int(display_config.get("max_tokens_console", 80))
        group_tokens = display_config.get("group_tokens_by_category", True)
        show_reason = display_config.get("show_operational_reason", True)

        # Desde MVP 2.6.5 los activos base NO se separan.
        # BTC, ETH, SOL, BNB, etc. entran en B/A/A+ según su categoría real.
        visible_tokens = [
            t for t in tokens
            if show_discarded or not (t.category or "").startswith("C ")
        ]

        reference_tokens = []
        tokens_for_console = sort_tokens_for_screen(visible_tokens)

        # No recortar aquí cuando se trabaja por bloques.
        # Si recortamos antes de agrupar, el orden visual invertido puede eliminar A/A+.
        if not group_tokens:
            tokens_for_console = tokens_for_console[:max_tokens_console]

        if not tokens_for_console and not reference_tokens:
            self.console.print("[yellow]No hay tokens A+/A/B para mostrar en consola.[/yellow]")
            self.console.print("Los descartados siguen guardados en los archivos exportados.")
            self.print_column_legend()
            return

        if not group_tokens:
            if reference_tokens:
                self.console.print(self._build_tokens_table("Activos base incluidos en su categoría", reference_tokens, show_reason))
                self.console.print("")
            self.console.print(self._build_tokens_table("Tokens candidatos", tokens_for_console, show_reason))
            self.print_column_legend()
            return

        # Orden inverso intencional:
        # primero activos base, luego B, luego A y al final A+ para que lo más recomendado
        # quede visible al final de la pantalla.
        ordered_sections = []

        source_for_sections = visible_tokens

        b_tokens = sort_tokens_for_screen([t for t in source_for_sections if category_group(t.category) == "B"])
        a_tokens = sort_tokens_for_screen([t for t in source_for_sections if category_group(t.category) == "A"])
        a_plus_tokens = sort_tokens_for_screen([t for t in source_for_sections if category_group(t.category) == "A+"])

        # Límite solo para bloques muy grandes. A y A+ nunca deberían quedar fuera.
        b_tokens = b_tokens[:max_tokens_console]

        ordered_sections.extend([
            ("🟡 B VIGILAR", b_tokens),
            ("🟢 A CANDIDATOS / REBOTES", a_tokens),
            ("🟩 A+ PRIORIDAD OPERATIVA", a_plus_tokens),
        ])

        if show_discarded:
            c_tokens = sort_tokens_for_screen([t for t in source_for_sections if category_group(t.category) == "C"])
            ordered_sections.insert(0, ("🔴 C DESCARTADOS", c_tokens[:max_tokens_console]))

        for title, group_tokens_list in ordered_sections:
            if not group_tokens_list:
                continue
            self.console.print(self._build_tokens_table(title, group_tokens_list, show_reason))
            self.console.print("")

        self.print_column_legend()
        self.print_prose_watchlist(source_for_sections)
