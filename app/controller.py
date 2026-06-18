from datetime import datetime
from pathlib import Path
import json
import time
import pandas as pd

from models.sector import Sector
from models.token import TokenCandidate
from models.scan_result import ScanResult
from engines.market_context_engine import MarketContextEngine
from engines.sector_scoring_engine import SectorScoringEngine
from engines.token_scoring_engine import TokenScoringEngine
from services.coingecko_service import CoinGeckoService
from services.binance_service import BinanceService
from services.lbank_service import LBankService
from services.bybit_service import BybitService
from services.coinmarketcap_service import CoinMarketCapService
from engines.pair_validator import PairValidator


class AppController:
    def __init__(self, config: dict):
        self.config = config
        self.operational_rules = config.get("operational_rules", {})
        self.alert_rules = config.get("alert_rules", {})
        self.priority_tiers = config.get("priority_tiers", {})
        self.trend_cfg = config.get("trend_signals", {})
        self.sector_expansion = config.get("sector_expansion", {})
        self.token_exclusions = config.get("token_exclusions", {})
        cg_cfg = config.get("coingecko", {})
        self.cg = CoinGeckoService(
            retry_attempts=cg_cfg.get("retry_attempts", 3),
            retry_sleep_seconds=cg_cfg.get("retry_sleep_seconds", 3),
        )
        self.cmc = CoinMarketCapService.from_config(config)
        self.binance = BinanceService()
        self.lbank = LBankService()
        self.bybit = BybitService()
        preferred_quotes = config.get("token_filters", {}).get("preferred_quotes", ["USDT", "USDC"])
        pair_cfg = config.get("pair_validation", {})
        self.pair_validator = PairValidator(
            validators=[self.binance, self.bybit, self.lbank],
            preferred_quotes=preferred_quotes,
            max_price_deviation_pct=pair_cfg.get("max_price_deviation_pct", 50),
            reject_price_mismatch=pair_cfg.get("reject_price_mismatch", True),
        )
        self.market_engine = MarketContextEngine(config)
        self.sector_engine = SectorScoringEngine(config)
        self.token_engine = TokenScoringEngine(config)

    def run_scan(self, max_sectors: int = 5, tokens_per_sector: int = 20) -> ScanResult:
        market_tokens = self.cg.get_market_context_tokens()
        btc = market_tokens.get("bitcoin", {})
        eth = market_tokens.get("ethereum", {})

        btc_change = btc.get("price_change_percentage_24h_in_currency")
        if btc_change is None:
            btc_change = btc.get("price_change_percentage_24h")

        eth_change = eth.get("price_change_percentage_24h_in_currency")
        if eth_change is None:
            eth_change = eth.get("price_change_percentage_24h")

        context = self.market_engine.classify(btc_change, eth_change)
        context["coinmarketcap_api_configured"] = bool(self.cmc.enabled)
        context["coinmarketcap_categories_loaded"] = 0
        context["coinmarketcap_status"] = "no_configurada" if not self.cmc.enabled else "pendiente"

        trend_index = self._load_trend_signals()
        context["trend_signals"] = {
            "enabled": bool(self.trend_cfg.get("enabled", False)),
            "coingecko_trending": bool(self.trend_cfg.get("coingecko_trending", False)),
            "tokens_loaded": len({k for k in trend_index.keys()}),
        }
        context["sector_expansion"] = {
            "enabled": bool(self.sector_expansion.get("enabled", False)),
            "recommended": self.sector_expansion.get("recommended_sectors", []),
            "optional": self.sector_expansion.get("optional_sectors", []),
            "noisy": self.sector_expansion.get("noisy_sectors", []),
        }
        token_exclusion_counts = {}

        raw_categories = self.cg.get_categories()
        sectors = []

        for c in raw_categories:
            if not self._coingecko_category_allowed(c):
                continue

            sector = Sector(
                id=c.get("id"),
                name=c.get("name"),
                market_cap_usd=c.get("market_cap"),
                volume_24h_usd=c.get("volume_24h"),
                change_24h_pct=c.get("market_cap_change_24h"),
                # CoinGecko categories endpoint often lacks 7d category change.
                change_7d_pct=None,
                top_3_coins=c.get("top_3_coins", []),
                source="CoinGecko",
            )
            scored = self.sector_engine.score(sector)
            self._apply_preferred_sector_boost(scored)
            sectors.append(scored)

        # CoinMarketCap es opcional: si hay API key, agregamos categorías como fuente secundaria.
        cmc_sectors = self._load_coinmarketcap_sectors()
        context["coinmarketcap_categories_loaded"] = len(cmc_sectors)
        if not self.cmc.enabled:
            context["coinmarketcap_status"] = "no_configurada"
        elif cmc_sectors:
            context["coinmarketcap_status"] = "ok"
        else:
            context["coinmarketcap_status"] = "sin_datos_o_error"
        sectors.extend(cmc_sectors)

        sectors = sorted(sectors, key=lambda s: s.score, reverse=True)
        selected_sectors = [s for s in sectors if s.status in {"prioritario", "interesante", "observacion"}][:max_sectors]
        selected_sectors = self._apply_sector_fallback_if_needed(
            selected_sectors=selected_sectors,
            all_sectors=sectors,
            max_sectors=max_sectors,
        )

        tokens = []
        preferred_quotes = self.config.get("token_filters", {}).get("preferred_quotes", ["USDT", "USDC"])
        pause_seconds = float(self.config.get("scan", {}).get("coingecko_pause_seconds", 1.3))

        for sector in selected_sectors:
            if not sector.id:
                continue

            # MVP 1.3: CoinMarketCap aporta scoring sectorial opcional.
            # La extracción de tokens operables sigue usando CoinGecko para mantener el scanner estable.
            if sector.source != "CoinGecko":
                sector.notes.append("Sector CMC usado como referencia; extracción de tokens CMC queda para MVP 1.4.")
                continue

            try:
                time.sleep(pause_seconds)
                raw_tokens = self.cg.get_markets_by_category(sector.id, per_page=tokens_per_sector)
            except Exception as exc:
                sector.notes.append(f"Error al consultar tokens: {exc}")
                continue

            for item in raw_tokens:
                allowed, exclusion_reason = self._token_allowed(item)
                if not allowed:
                    token_exclusion_counts[exclusion_reason] = token_exclusion_counts.get(exclusion_reason, 0) + 1
                    continue

                symbol = (item.get("symbol") or "").upper()
                pair = None
                quote_asset = None
                exchange = None
                pair_volume = None
                pair_last_price = None
                pair_price_deviation = None
                pair_identity_status = ""

                try:
                    pair_data = self.pair_validator.validate(symbol, reference_price=item.get("current_price"))
                except Exception:
                    pair_data = None

                if pair_data:
                    pair = pair_data.get("symbol")
                    quote_asset = pair_data.get("quote_asset")
                    exchange = pair_data.get("exchange")
                    pair_volume = pair_data.get("quote_volume")
                    pair_last_price = pair_data.get("last_price")
                    pair_price_deviation = pair_data.get("pair_price_deviation_pct")
                    pair_identity_status = pair_data.get("pair_identity_status", "")

                token = TokenCandidate(
                    id=item.get("id"),
                    symbol=symbol,
                    name=item.get("name"),
                    sector_name=sector.name,
                    sector_score=sector.score,
                    market_cap_usd=item.get("market_cap"),
                    volume_24h_usd=item.get("total_volume"),
                    change_24h_pct=item.get("price_change_percentage_24h_in_currency"),
                    change_7d_pct=item.get("price_change_percentage_7d_in_currency"),
                    change_30d_pct=item.get("price_change_percentage_30d_in_currency"),
                    price_usd=item.get("current_price"),
                    spot_pair=pair,
                    quote_asset=quote_asset,
                    exchange=exchange,
                    pair_volume_24h_usd=pair_volume,
                    pair_last_price=pair_last_price,
                    pair_price_deviation_pct=pair_price_deviation,
                    pair_identity_status=pair_identity_status,
                )

                # Excluyente parcial: si no tiene par spot USDT/USDC en Binance, queda, pero con score menor.
                # Luego agregaremos Bybit/Gate/OKX para ampliar validación.
                token = self.token_engine.score(token, sector.status)
                token = self._apply_trend_signal(token, trend_index)
                token.action = self._action_from_token(token)
                token.operational_reason = self._operational_reason_from_token(token)
                token.operational_bucket = self._operational_bucket_from_token(token)
                token.alerts = self._alerts_from_token(token)
                token.priority_tier = self._priority_tier_from_token(token)
                tokens.append(token)

        tokens = self._sort_tokens_operationally(tokens)

        if self.config.get("scan", {}).get("deduplicate_tokens", True):
            tokens = self._deduplicate_tokens(tokens)

        tokens = self._sort_tokens_operationally(tokens)

        context["token_summary"] = self._build_token_summary(tokens)
        context["top_operational"] = self._build_top_operational(tokens)
        context["alert_summary"] = self._build_alert_summary(tokens)
        context["priority_tier_summary"] = self._build_priority_tier_summary(tokens)
        context["token_exclusions"] = {
            "enabled": bool(self.token_exclusions.get("enabled", True)),
            "total_excluded_occurrences": sum(token_exclusion_counts.values()),
            "by_reason": token_exclusion_counts,
        }
        context["pair_validation"] = dict(self.pair_validator.stats)

        return ScanResult(created_at=datetime.now(), market_mode=context["mode"], market_context=context, sectors=selected_sectors, tokens=tokens)




    def _token_allowed(self, item: dict) -> tuple[bool, str]:
        """Filtro token-level para evitar stablecoins, recibos, wrappers y activos no operables."""
        cfg = self.token_exclusions or {}
        if not cfg.get("enabled", True):
            return True, ""

        coin_id = str(item.get("id") or "").strip().lower()
        symbol = str(item.get("symbol") or "").strip().upper()
        name = str(item.get("name") or "").strip().lower()

        excluded_ids = {str(x).lower() for x in cfg.get("excluded_ids", [])}
        excluded_symbols = {str(x).upper() for x in cfg.get("excluded_symbols", [])}
        name_keywords = [str(x).lower() for x in cfg.get("excluded_name_keywords", [])]

        if coin_id in excluded_ids:
            return False, "excluded_coin_id"
        if symbol in excluded_symbols:
            return False, "excluded_symbol"
        if any(keyword and keyword in name for keyword in name_keywords):
            return False, "excluded_name_keyword"
        return True, ""


    def _sector_group_from_name(self, sector_name: str | None) -> str:
        """
        Clasifica sector como core / optional / noisy / other usando keywords configurables.
        No cambia la categoría del token; solo agrega metadata visual/export.
        """
        if not sector_name:
            return "other"

        name = str(sector_name).lower()
        cfg = getattr(self, "sector_expansion", {})
        keywords_cfg = cfg.get("sector_group_keywords", {})

        # Orden intencional: noisy primero para que Memes/Telegram no queden como optional limpio.
        for group in ("noisy", "optional", "core"):
            for keyword in keywords_cfg.get(group, []):
                if str(keyword).lower() in name:
                    return group

        return "other"

    def _sector_group_label(self, group: str) -> str:
        labels = {
            "core": "core",
            "optional": "optional",
            "noisy": "noisy",
            "other": "other",
        }
        return labels.get(group, "other")


    def _load_trend_signals(self) -> dict:
        """
        Carga señales de tendencia simples.
        MVP 2.5: CoinGecko Trending. No modifica ranking por defecto.
        """
        cfg = getattr(self, "trend_cfg", {})
        if not cfg.get("enabled", False):
            return {}

        trend_index = {}

        if cfg.get("coingecko_trending", True):
            try:
                data = self.cg.get_trending()
                coins = data.get("coins", []) if isinstance(data, dict) else []
            except Exception:
                coins = []

            max_tokens = int(cfg.get("max_trending_tokens", 15))
            points = int(cfg.get("points_coingecko_trending", 2))

            for idx, wrapper in enumerate(coins[:max_tokens], 1):
                item = wrapper.get("item", {}) if isinstance(wrapper, dict) else {}
                coin_id = str(item.get("id") or "").lower()
                symbol = str(item.get("symbol") or "").upper()

                entry = {
                    "source": "CoinGecko Trending",
                    "rank": idx,
                    "points": points,
                }

                if coin_id:
                    trend_index.setdefault(coin_id, []).append(entry)
                if symbol:
                    trend_index.setdefault(symbol, []).append(entry)

        return trend_index

    def _apply_trend_signal(self, token, trend_index: dict):
        """
        Agrega señal de tendencia al token.
        Por defecto NO modifica score/categoría; solo exporta señal.
        """
        if not trend_index:
            token.trend_signal = "-"
            token.trend_score = 0
            token.trend_sources = []
            return token

        matches = []
        if token.id:
            matches.extend(trend_index.get(str(token.id).lower(), []))
        elif token.symbol:
            # Solo fallback por ticker cuando no existe CoinGecko ID.
            matches.extend(trend_index.get(str(token.symbol).upper(), []))

        if not matches:
            token.trend_signal = "-"
            token.trend_score = 0
            token.trend_sources = []
            return token

        # Deduplicar por fuente.
        by_source = {}
        for m in matches:
            src = m.get("source", "Trend")
            if src not in by_source or m.get("rank", 999) < by_source[src].get("rank", 999):
                by_source[src] = m

        selected = list(by_source.values())
        token.trend_sources = [m["source"] for m in selected]
        token.trend_score = max(int(m.get("points", 0)) for m in selected)
        token.trend_signal = " | ".join(f"{m['source']} #{m.get('rank', '-')}" for m in selected)
        token.notes.append(f"Trend: {token.trend_signal}.")

        if self.trend_cfg.get("apply_to_score", False):
            token.score += token.trend_score
            token.notes.append(f"Trend score aplicado: +{token.trend_score}.")
            # En MVP 2.5 no reabre gates ni recalcula categorías para evitar falsos positivos.
            token.notes.append("Trend no recalcula categoría en esta versión.")

        return token


    def _apply_sector_fallback_if_needed(self, selected_sectors, all_sectors, max_sectors: int):
        """
        Si los filtros dejan muy pocos sectores, se agregan sectores preferidos
        desde CoinGecko aunque estén débiles, siempre que no estén excluidos.
        Esto evita que el scanner quede solo con stable/synthetic o con 1 sector.
        """
        cfg = self.config.get("sector_selection", {})
        if not cfg.get("fallback_to_preferred_if_too_few", True):
            return selected_sectors

        min_selected = int(cfg.get("min_selected_sectors", 5))
        if len(selected_sectors) >= min_selected:
            return selected_sectors

        preferred = [str(x).lower() for x in self.config.get("coingecko", {}).get("preferred_category_keywords", [])]
        current_ids = {s.id for s in selected_sectors}

        fallback = []
        for sector in all_sectors:
            if sector.id in current_ids:
                continue

            name = (sector.name or "").lower()
            sid = (sector.id or "").lower()

            if any(k in name or k in sid for k in preferred):
                sector.notes.append("Fallback: sector preferido agregado para ampliar búsqueda.")
                fallback.append(sector)
                current_ids.add(sector.id)

            if len(selected_sectors) + len(fallback) >= max_sectors:
                break

        return (selected_sectors + fallback)[:max_sectors]


    def _coingecko_category_allowed(self, category: dict) -> bool:
        cg_cfg = self.config.get("coingecko", {})
        excluded_ids = {str(x).lower() for x in cg_cfg.get("excluded_category_ids", [])}
        excluded_keywords = [str(x).lower() for x in cg_cfg.get("excluded_category_keywords", [])]

        category_id = str(category.get("id", "")).lower()
        name = str(category.get("name", "")).lower()

        if category_id in excluded_ids:
            return False

        if any(k in name or k in category_id for k in excluded_keywords):
            return False

        mcap = category.get("market_cap") or 0
        vol = category.get("volume_24h") or 0

        if mcap < cg_cfg.get("min_sector_market_cap_usd", 0):
            return False

        if vol < cg_cfg.get("min_sector_volume_24h_usd", 0):
            return False

        return True

    def _apply_preferred_sector_boost(self, sector: Sector) -> None:
        cg_cfg = self.config.get("coingecko", {})
        preferred = [str(x).lower() for x in cg_cfg.get("preferred_category_keywords", [])]
        name = sector.name.lower()
        sector_id = sector.id.lower() if sector.id else ""

        if any(k in name or k in sector_id for k in preferred):
            sector.score += 1
            sector.notes.append("Boost: sector preferido por configuración.")
            if sector.score >= 10:
                sector.status = "prioritario"
            elif sector.score >= 7:
                sector.status = "interesante"
            elif sector.score >= 4:
                sector.status = "observacion"

    def _load_coinmarketcap_sectors(self):
        cmc_cfg = self.config.get("coinmarketcap", {})
        if not cmc_cfg.get("enabled", False):
            return []

        if not self.cmc.enabled:
            return []

        sectors = []
        try:
            categories = self.cmc.get_categories()
        except Exception:
            return []

        max_categories = int(cmc_cfg.get("max_categories", 30))
        for c in categories[:max_categories]:
            sector = Sector(
                id=c.get("id") or c.get("slug") or c.get("name"),
                name=c.get("name") or c.get("title") or "CMC category",
                market_cap_usd=c.get("market_cap"),
                volume_24h_usd=c.get("volume"),
                change_24h_pct=c.get("avg_price_change"),
                change_7d_pct=None,
                top_3_coins=[],
                source="CoinMarketCap",
            )
            sector = self.sector_engine.score(sector)
            sector.notes.append("Fuente: CoinMarketCap.")
            sectors.append(sector)

        return sectors

    def _deduplicate_tokens(self, tokens):
        """
        Un mismo token puede aparecer en varias categorías CoinGecko.
        Conservamos la mejor versión por score y fusionamos sectores en notes.
        """
        best = {}
        sectors_by_token = {}

        for token in tokens:
            key = str(token.id or token.symbol).lower()
            sectors_by_token.setdefault(key, set()).add(token.sector_name)

            current = best.get(key)
            if current is None or token.score > current.score:
                best[key] = token

        deduped = []
        for key, token in best.items():
            sectors = sorted(sectors_by_token.get(key, []))
            if len(sectors) > 1:
                token.notes.append("También aparece en sectores: " + ", ".join(sectors))
            deduped.append(token)

        return self._sort_tokens_operationally(deduped)


    def _category_rank(self, category: str | None) -> int:
        category = category or ""
        if category.startswith("A+"):
            return 4
        if category.startswith("A "):
            return 3
        if category.startswith("B "):
            return 2
        if category.startswith("C "):
            return 1
        return 0

    def _sort_tokens_operationally(self, tokens):
        """
        Ordena por categoría final, no solo por score bruto.
        Esto evita que tokens C Descartada con score alto aparezcan arriba.
        """
        return sorted(
            tokens,
            key=lambda t: (
                self._category_rank(t.category),
                t.score or 0,
                t.change_24h_pct if t.change_24h_pct is not None else -999,
                t.volume_24h_usd or 0,
            ),
            reverse=True,
        )

    def _visual_color_from_category(self, category: str | None) -> str:
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

    def _action_from_token(self, token) -> str:
        category = token.category or ""
        ch24 = token.change_24h_pct
        ch7 = token.change_7d_pct
        ch30 = token.change_30d_pct

        warn_30d = getattr(self, "operational_rules", {}).get("warn_30d_above", 150)

        if category.startswith("C "):
            return "⛔ Descartar"

        if ch24 is not None and ch24 > 20:
            return "🔴 No perseguir"

        if ch24 is not None and ch24 > 15:
            return "🟠 Extendido"

        if ch30 is not None and ch30 > warn_30d:
            return "⚠️ Exceso 30D"

        if category.startswith("A+") and ch24 is not None and 2 <= ch24 <= 15 and (ch7 or 0) > 5 and (ch30 or 0) > 10:
            return "🚀 Prioridad operativa"

        if category.startswith("A") and ch24 is not None and ch24 >= 0:
            if getattr(self, "operational_rules", {}).get("active_requires_7d_positive", True) and (ch7 or 0) < 0:
                return "🟡 Rebote táctico"
            return "🟢 Candidato activo"

        if category.startswith("A") and ch24 is not None and -10 <= ch24 < 0:
            return "🟡 Esperar retroceso"

        if category.startswith("B "):
            return "🟡 Vigilar"

        return "⚪ Revisar"



    def _alerts_from_token(self, token) -> str:
        """
        Alertas múltiples de riesgo operativo. No reemplazan la acción principal.
        Sirven para marcar extensiones o excesos acumulados aunque el token siga siendo candidato.
        """
        alerts = []

        ch24 = token.change_24h_pct
        ch7 = token.change_7d_pct
        ch30 = token.change_30d_pct

        watch_24h = getattr(self, "alert_rules", {}).get("watch_24h_above", 12)
        warn_24h = getattr(self, "alert_rules", {}).get("warn_24h_above", 15)
        extreme_24h = getattr(self, "alert_rules", {}).get("extreme_24h_above", 20)
        warn_30d = getattr(self, "alert_rules", {}).get("warn_30d_above", 150)
        extreme_30d = getattr(self, "alert_rules", {}).get("extreme_30d_above", 300)
        warn_7d = getattr(self, "alert_rules", {}).get("warn_7d_above", 50)
        strong_negative_24h = getattr(self, "alert_rules", {}).get("strong_negative_24h_below", -10)

        if ch24 is not None:
            if ch24 > extreme_24h:
                alerts.append("🔴 24h extremo")
            elif ch24 > warn_24h:
                alerts.append("🟠 24h extendido")
            elif ch24 > watch_24h:
                alerts.append("🟡 24h cerca de extensión")
            elif ch24 < strong_negative_24h:
                alerts.append("🔴 caída 24h fuerte")

        if ch7 is not None and ch7 > warn_7d:
            alerts.append("⚠️ 7D muy alto")

        if ch30 is not None:
            if ch30 > extreme_30d:
                alerts.append("⚠️ 30D extremo")
            elif ch30 > warn_30d:
                alerts.append("⚠️ 30D alto")

        return " | ".join(alerts) if alerts else "-"

    def _operational_reason_from_token(self, token) -> str:
        category = token.category or ""
        notes = token.notes or []
        joined_notes = " | ".join(notes)

        ch24 = token.change_24h_pct
        ch7 = token.change_7d_pct
        ch30 = token.change_30d_pct
        volume = token.volume_24h_usd or 0
        market_cap = token.market_cap_usd or 0

        warn_30d = getattr(self, "operational_rules", {}).get("warn_30d_above", 150)

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

        if ch30 is not None and ch30 > warn_30d:
            return f"30D > {warn_30d}%"

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

    def _operational_bucket_from_token(self, token) -> str:
        action = self._action_from_token(token)

        if action.startswith("🚀"):
            return "prioridad_operativa"
        if action.startswith("🟢"):
            return "candidato_activo"
        if "Rebote táctico" in action:
            return "rebote_tactico"
        if "Esperar retroceso" in action:
            return "esperar_retroceso"
        if "Exceso 30D" in action:
            return "exceso_30d"
        if "Extendido" in action:
            return "extendido"
        if "No perseguir" in action:
            return "no_perseguir"
        if action.startswith("🟡"):
            return "vigilar"
        if action.startswith("⛔"):
            return "descartar"
        return "revisar"


    def _build_token_summary(self, tokens) -> dict:
        summary = {
            "total": len(tokens),
            "a_plus": 0,
            "a": 0,
            "b": 0,
            "c": 0,
        }

        for token in tokens:
            category = token.category or ""
            if category.startswith("A+"):
                summary["a_plus"] += 1
            elif category.startswith("A "):
                summary["a"] += 1
            elif category.startswith("B "):
                summary["b"] += 1
            elif category.startswith("C "):
                summary["c"] += 1

        return summary





    def _priority_tier_from_token(self, token) -> str:
        labels = getattr(self, "priority_tiers", {}).get("labels", {})
        t1 = labels.get("t1", "T1 limpio")
        t2 = labels.get("t2", "T2 válido con alerta")
        t3 = labels.get("t3", "T3 vigilancia")
        t4 = labels.get("t4", "T4 riesgo alto")

        action = self._action_from_token(token)
        category = token.category or ""
        alerts = self._alerts_from_token(token)

        high_risk_alerts = (
            "🔴 24h extremo",
            "🟠 24h extendido",
            "⚠️ 30D extremo",
            "🔴 caída 24h fuerte",
        )

        if category.startswith("C ") or action.startswith("⛔"):
            return t4

        if any(alert in alerts for alert in high_risk_alerts) or action.startswith("🔴") or action.startswith("🟠"):
            return t4

        if category.startswith("B ") or action.startswith("🟡 Vigilar"):
            return t3

        if alerts and alerts != "-":
            return t2

        if category.startswith("A+") or category.startswith("A "):
            return t1

        return t3

    def _priority_tier_rank(self, tier: str) -> int:
        if str(tier).startswith("T1"):
            return 1
        if str(tier).startswith("T2"):
            return 2
        if str(tier).startswith("T3"):
            return 3
        if str(tier).startswith("T4"):
            return 4
        return 9


    def _build_alert_summary(self, tokens) -> dict:
        summary = {
            "tokens_with_alerts": 0,
            "alert_counts": {},
        }

        for token in tokens:
            alerts_text = self._alerts_from_token(token)
            if not alerts_text or alerts_text == "-":
                continue

            summary["tokens_with_alerts"] += 1
            for alert in alerts_text.split(" | "):
                summary["alert_counts"][alert] = summary["alert_counts"].get(alert, 0) + 1

        return summary



    def _build_priority_tier_summary(self, tokens) -> dict:
        summary = {}

        for token in tokens:
            tier = self._priority_tier_from_token(token)
            summary[tier] = summary.get(tier, 0) + 1

        return dict(sorted(summary.items(), key=lambda item: self._priority_tier_rank(item[0])))


    def _build_top_operational(self, tokens) -> dict:
        max_per_group = int(getattr(self, "operational_rules", {}).get("top_operational_max_per_group", 8))
        groups = {
            "prioridad_operativa": [],
            "candidato_activo": [],
            "rebote_tactico": [],
            "esperar_retroceso": [],
            "extendido": [],
            "exceso_30d": [],
            "no_perseguir": [],
        }

        for token in tokens:
            bucket = self._operational_bucket_from_token(token)
            if bucket in groups and len(groups[bucket]) < max_per_group:
                groups[bucket].append(token.symbol)

        return groups


    def export(self, result: ScanResult, output_dir: str = "outputs") -> dict:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        token_rows = []
        for t in result.tokens:
            token_rows.append({
                "app_version": self.config.get("app", {}).get("version", "unknown"),
                "schema_version": "ranking_v2",
                "coin_id": t.id,
                "asset_key": f"cg:{str(t.id).lower()}" if t.id else "",
                "token": t.symbol,
                "name": t.name,
                "sector": t.sector_name,
                "sector_group": self._sector_group_label(self._sector_group_from_name(t.sector_name)),
                "score": t.score,
                "category": t.category,
                "visual_color": self._visual_color_from_category(t.category),
                "action": self._action_from_token(t),
                "operational_reason": self._operational_reason_from_token(t),
                "operational_bucket": self._operational_bucket_from_token(t),
                "alerts": self._alerts_from_token(t),
                "priority_tier": self._priority_tier_from_token(t),
                "trend_signal": t.trend_signal,
                "trend_score": t.trend_score,
                "trend_sources": " | ".join(t.trend_sources),
                "spot_pair": t.spot_pair,
                "exchange": t.exchange,
                "pair_last_price": t.pair_last_price,
                "pair_price_deviation_pct": t.pair_price_deviation_pct,
                "pair_identity_status": t.pair_identity_status,
                "price_usd": t.price_usd,
                "market_cap_usd": t.market_cap_usd,
                "volume_24h_usd": t.volume_24h_usd,
                "change_24h_pct": t.change_24h_pct,
                "change_7d_pct": t.change_7d_pct,
                "change_30d_pct": t.change_30d_pct,
                "notes": " | ".join(t.notes),
            })

        df = pd.DataFrame(token_rows)
        csv_path = out / "ranking.csv"
        xlsx_path = out / "ranking.xlsx"
        json_path = out / "latest_scan.json"

        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        df.to_excel(xlsx_path, index=False)

        with json_path.open("w", encoding="utf-8") as f:
            json.dump({
                "app_name": self.config.get("app", {}).get("name", "Spot Sector Scanner"),
                "app_version": self.config.get("app", {}).get("version", "unknown"),
                "schema_version": "scan_v2",
                "created_at": result.created_at.isoformat(),
                "market_mode": result.market_mode,
                "market_context": result.market_context,
                "tokens": token_rows,
                "sectors": [
                    {
                        "id": s.id,
                        "name": s.name,
                        "source": s.source,
                        "score": s.score,
                        "status": s.status,
                        "market_cap_usd": s.market_cap_usd,
                        "volume_24h_usd": s.volume_24h_usd,
                        "change_24h_pct": s.change_24h_pct,
                        "notes": s.notes,
                    }
                    for s in result.sectors
                ]
            }, f, ensure_ascii=False, indent=2)

        return {"csv": str(csv_path), "xlsx": str(xlsx_path), "json": str(json_path)}
