from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import csv
import json
import statistics

from services.market_data_client import Candle, MarketDataClient


class OHLCValidator:
    """Valida intradía los mejores candidatos con OHLC token + OHLC BTC.

    MVP 2.9.11:
    - rescata OHLC solo de los 10 mejores candidatos del scan actual;
    - intenta backfill OHLC de los 10 mejores candidatos históricos pendientes;
    - calcula MFE, MAE, targets intradía y retorno relativo contra BTC;
    - escribe resultados en outputs/ohlc sin alterar el ranking ni el tracker base.
    """

    SCHEMA_VERSION = "ohlc_v1"

    def __init__(self, full_config: dict[str, Any], market_client: MarketDataClient | None = None):
        self.full_config = full_config or {}
        self.config = self.full_config.get("ohlc_validator", {}) or {}
        self.app_version = str(self.full_config.get("app", {}).get("version", "unknown"))
        self.enabled = bool(self.config.get("enabled", False))
        self.output_dir = Path(self.config.get("output_dir", "outputs/ohlc"))
        self.tracked_entries_path = Path(self.full_config.get("performance_tracker", {}).get("output_dir", "outputs/performance")) / "tracked_entries.csv"
        self.report_path = self.output_dir / "latest_ohlc_report.json"
        self.validation_path = self.output_dir / "ohlc_validation.csv"
        self.candidates_path = self.output_dir / "ohlc_candidates_current.csv"
        self.historical_candidates_path = self.output_dir / "ohlc_candidates_historical.csv"

        self.current_top_n = int(self.config.get("current_top_n", 10))
        self.historical_top_n = int(self.config.get("historical_top_n", 10))
        self.horizon_hours = [int(h) for h in self.config.get("horizon_hours", [24, 72])]
        self.max_horizon_hours = max(self.horizon_hours or [72])
        self.interval_intraday = str(self.config.get("interval_intraday", "15m"))
        self.interval_swing = str(self.config.get("interval_swing", "1h"))
        self.preferred_exchanges = [str(x) for x in self.config.get("preferred_exchanges", ["Binance", "Bybit"])]
        self.quote_asset = str(self.config.get("quote_asset", "USDT")).upper()
        self.btc_symbol = str(self.config.get("btc_symbol", "BTCUSDT")).upper()
        self.max_lookback_days = int(self.config.get("max_lookback_days", 45))
        self.target_thresholds = [float(x) for x in self.config.get("target_thresholds_pct", [2, 5, 10, 15, 20])]
        self.cost_pct = float(self.config.get("estimated_round_trip_cost_pct", 0.25))
        self.eligible_operational_buckets = {str(x) for x in self.config.get("eligible_operational_buckets", [])}
        self.eligible_track_buckets = {str(x) for x in self.config.get("eligible_track_buckets", [])}
        self.allow_legacy_backfill = bool(self.config.get("allow_legacy_backfill", True))

        self.market_client = market_client or MarketDataClient(self.config)
        self.stats = {
            "current_candidates_selected": 0,
            "historical_candidates_selected": 0,
            "validations_attempted": 0,
            "validations_completed": 0,
            "validations_pending": 0,
            "validations_failed": 0,
            "token_ohlc_requests": 0,
            "btc_ohlc_requests": 0,
        }

    def run(self, result) -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False}
        self.output_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)

        current_candidates = self._select_current_top_candidates(result, now)
        historical_candidates = self._select_historical_candidates(now, current_candidates)
        self._write_csv(self.candidates_path, current_candidates)
        self._write_csv(self.historical_candidates_path, historical_candidates)

        previous = self._read_csv(self.validation_path)
        previous_by_entry = {r.get("entry_id", ""): r for r in previous if r.get("entry_id")}
        validations: list[dict[str, str]] = []

        # Conserva validaciones previas y actualiza solo candidatos seleccionados.
        updated_ids = set()
        for candidate in current_candidates + historical_candidates:
            entry_id = candidate.get("entry_id", "")
            updated = self._validate_candidate(candidate, now, previous_by_entry.get(entry_id))
            validations.append(updated)
            updated_ids.add(entry_id)

        for row in previous:
            if row.get("entry_id") not in updated_ids:
                validations.append(row)

        self._write_csv(self.validation_path, validations)
        report = self._build_report(now, current_candidates, historical_candidates, validations)
        self.report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    # ------------------------------------------------------------------
    # Selección de top 10 actual e histórico
    # ------------------------------------------------------------------

    def _select_current_top_candidates(self, result, now: datetime) -> list[dict[str, str]]:
        rows = []
        scan_id = now.strftime("%Y%m%d_%H%M%S")
        for token in getattr(result, "tokens", []):
            op_bucket = str(getattr(token, "operational_bucket", "") or "")
            track_bucket = self._track_bucket_from_token(token)
            if not self._eligible_signal(op_bucket, track_bucket):
                continue
            symbol = str(getattr(token, "symbol", "") or "").upper()
            spot_pair = str(getattr(token, "spot_pair", "") or f"{symbol}{self.quote_asset}").upper()
            if not symbol or not spot_pair:
                continue
            coin_id = str(getattr(token, "id", "") or "").lower()
            row = {
                "entry_id": f"ohlc_current::{scan_id}::{coin_id or symbol}",
                "source_scope": "current_scan_top10",
                "scan_time_utc": now.isoformat(),
                "coin_id": coin_id,
                "asset_key": f"cg:{coin_id}" if coin_id else "",
                "token": symbol,
                "name": str(getattr(token, "name", "") or ""),
                "track_bucket": track_bucket,
                "category": str(getattr(token, "category", "") or ""),
                "score": str(getattr(token, "score", "") or ""),
                "action": str(getattr(token, "action", "") or ""),
                "operational_bucket": op_bucket,
                "priority_tier": str(getattr(token, "priority_tier", "") or ""),
                "trend_signal": str(getattr(token, "trend_signal", "") or ""),
                "sector": str(getattr(token, "sector_name", "") or ""),
                "exchange": str(getattr(token, "exchange", "") or ""),
                "spot_pair": spot_pair,
                "reference_price": self._fmt(getattr(token, "price_usd", None)),
                "market_cap_usd": self._fmt(getattr(token, "market_cap_usd", None)),
                "volume_24h_usd": self._fmt(getattr(token, "volume_24h_usd", None)),
                "change_24h_pct_at_scan": self._fmt(getattr(token, "change_24h_pct", None)),
                "change_7d_pct_at_scan": self._fmt(getattr(token, "change_7d_pct", None)),
                "change_30d_pct_at_scan": self._fmt(getattr(token, "change_30d_pct", None)),
            }
            rows.append(row)

        rows = sorted(rows, key=self._candidate_sort_key, reverse=True)[: self.current_top_n]
        self.stats["current_candidates_selected"] = len(rows)
        return rows

    def _select_historical_candidates(self, now: datetime, current_candidates: list[dict[str, str]]) -> list[dict[str, str]]:
        rows = self._read_csv(self.tracked_entries_path)
        if not rows:
            self.stats["historical_candidates_selected"] = 0
            return []

        current_keys = {c.get("asset_key") or c.get("token") for c in current_candidates}
        candidates = []
        min_age = min(self.horizon_hours or [24])
        for row in rows:
            if not self.allow_legacy_backfill and row.get("schema_version") != "audit_v2":
                continue
            scan_time = self._parse_dt(row.get("scan_time_utc"))
            if not scan_time:
                continue
            age_h = (now - scan_time).total_seconds() / 3600
            if age_h < min_age:
                continue
            if age_h > self.max_lookback_days * 24:
                continue
            if not self._row_has_usable_symbol(row):
                continue
            op_bucket = str(row.get("operational_bucket") or self._bucket_from_action(row.get("action")) or "")
            track_bucket = str(row.get("track_bucket") or "")
            if not self._eligible_signal(op_bucket, track_bucket):
                continue
            key = row.get("asset_key") or row.get("token")
            # Evita duplicar la misma señal si ya fue elegida como top actual.
            if key in current_keys:
                continue
            candidate = dict(row)
            candidate["source_scope"] = "historical_top10_backfill"
            candidate["operational_bucket"] = op_bucket
            candidates.append(candidate)

        candidates = sorted(candidates, key=self._candidate_sort_key, reverse=True)[: self.historical_top_n]
        self.stats["historical_candidates_selected"] = len(candidates)
        return candidates

    def _eligible_signal(self, op_bucket: str, track_bucket: str) -> bool:
        if self.eligible_operational_buckets and op_bucket not in self.eligible_operational_buckets:
            return False
        if self.eligible_track_buckets and track_bucket not in self.eligible_track_buckets:
            return False
        return True

    def _track_bucket_from_token(self, token) -> str:
        category = str(getattr(token, "category", "") or "")
        priority = str(getattr(token, "priority_tier", "") or "")
        score = self._safe_float(getattr(token, "score", None)) or 0
        if "A+" in category:
            return "A+"
        if "A " in category or category.startswith("A"):
            return "A_T1" if "T1" in priority else "A"
        if score >= 12:
            return "B_HIGH_SCORE"
        return "B_TREND" if str(getattr(token, "trend_signal", "") or "-") != "-" else ""

    def _candidate_sort_key(self, row: dict[str, str]) -> tuple:
        op = str(row.get("operational_bucket") or self._bucket_from_action(row.get("action")) or "")
        op_rank = {
            "prioridad_operativa": 50,
            "candidato_activo": 40,
            "rebote_tactico": 30,
            "vigilar": 20,
        }.get(op, 0)
        track = str(row.get("track_bucket") or "")
        track_rank = {"A+": 50, "A_T1": 42, "A": 38, "B_HIGH_SCORE": 30, "B_TREND": 25}.get(track, 0)
        tier = str(row.get("priority_tier") or "")
        tier_rank = {"T1 limpio": 20, "T2 válido con alerta": 10, "T3 vigilancia": 3}.get(tier, 0)
        trend = 4 if str(row.get("trend_signal") or "-") != "-" else 0
        score = self._safe_float(row.get("score")) or 0
        vol = self._safe_float(row.get("volume_24h_usd")) or 0
        return (op_rank, track_rank, tier_rank, trend, score, vol)

    # ------------------------------------------------------------------
    # Validación OHLC
    # ------------------------------------------------------------------

    def _validate_candidate(self, candidate: dict[str, str], now: datetime, previous: dict[str, str] | None) -> dict[str, str]:
        self.stats["validations_attempted"] += 1
        base = self._base_validation_row(candidate, now)
        scan_time = self._parse_dt(candidate.get("scan_time_utc"))
        entry_price = self._safe_float(candidate.get("reference_price"))
        if not scan_time or not entry_price or entry_price <= 0:
            self.stats["validations_failed"] += 1
            return {**base, "ohlc_status": "failed", "error": "missing_scan_time_or_reference_price"}

        age_h = (now - scan_time).total_seconds() / 3600
        if age_h < min(self.horizon_hours or [24]):
            self.stats["validations_pending"] += 1
            return {**base, "ohlc_status": "pending_min_age", "age_hours": self._fmt(age_h)}

        end = min(now, scan_time + timedelta(hours=self.max_horizon_hours))
        interval = self.interval_intraday if self.max_horizon_hours <= 72 else self.interval_swing
        symbol = self._normalize_symbol(candidate.get("spot_pair") or f"{candidate.get('token')}{self.quote_asset}")
        exchanges = self._preferred_exchange_order(candidate.get("exchange"))
        source_exchange, token_candles, token_error = self.market_client.get_first_available_klines(
            exchanges, symbol, interval, scan_time, end, coin_id=candidate.get("coin_id")
        )
        self.stats["token_ohlc_requests"] += len(exchanges)
        if not source_exchange or not token_candles:
            self.stats["validations_failed"] += 1
            return {**base, "ohlc_status": "failed", "error": f"token_ohlc_unavailable:{token_error}"}

        btc_exchange, btc_candles, btc_error = self.market_client.get_first_available_klines(
            [source_exchange] + [e for e in self.preferred_exchanges if e != source_exchange],
            self.btc_symbol,
            interval,
            scan_time,
            end,
            coin_id="bitcoin",
        )
        self.stats["btc_ohlc_requests"] += 1
        if not btc_exchange or not btc_candles:
            # Permite guardar validación token aunque BTC falle.
            btc_candles = []

        row = dict(base)
        row.update({
            "ohlc_status": "completed",
            "ohlc_schema_version": self.SCHEMA_VERSION,
            "ohlc_validated_at_utc": now.isoformat(),
            "age_hours": self._fmt(age_h),
            "ohlc_exchange": source_exchange or "",
            "ohlc_symbol": symbol,
            "ohlc_interval": interval,
            "ohlc_start_utc": scan_time.isoformat(),
            "ohlc_end_utc": end.isoformat(),
            "token_candles": str(len(token_candles)),
            "btc_ohlc_exchange": btc_exchange or "",
            "btc_candles": str(len(btc_candles)),
            "btc_error": btc_error or "",
        })
        self._add_token_metrics(row, token_candles, entry_price, scan_time)
        self._add_btc_metrics(row, token_candles, btc_candles, scan_time)
        self.stats["validations_completed"] += 1
        return row

    def _add_token_metrics(self, row: dict[str, str], candles: list[Candle], entry_price: float, scan_time: datetime) -> None:
        highs = [(c.high, c.open_time_ms) for c in candles]
        lows = [(c.low, c.open_time_ms) for c in candles]
        max_price, max_ts = max(highs, key=lambda x: x[0])
        min_price, min_ts = min(lows, key=lambda x: x[0])
        mfe = (max_price / entry_price - 1) * 100
        mae = (min_price / entry_price - 1) * 100
        row["intraday_high_price"] = self._fmt(max_price)
        row["intraday_high_time_utc"] = self._ms_to_iso(max_ts)
        row["intraday_low_price"] = self._fmt(min_price)
        row["intraday_low_time_utc"] = self._ms_to_iso(min_ts)
        row["mfe_pct"] = self._fmt(mfe)
        row["mae_pct"] = self._fmt(mae)
        row["mfe_net_pct"] = self._fmt(mfe - self.cost_pct)

        first_target_time: dict[float, int] = {}
        for candle in candles:
            for t in self.target_thresholds:
                if t not in first_target_time and candle.high >= entry_price * (1 + t / 100):
                    first_target_time[t] = candle.open_time_ms
        for t in self.target_thresholds:
            key = self._target_key(t)
            hit = t in first_target_time
            row[f"target_{key}_intraday_hit"] = "yes" if hit else "no"
            row[f"target_{key}_time_utc"] = self._ms_to_iso(first_target_time[t]) if hit else ""
            row[f"target_{key}_hours_to_hit"] = self._fmt((first_target_time[t] / 1000 - scan_time.timestamp()) / 3600) if hit else ""

        for h in self.horizon_hours:
            horizon_time = scan_time + timedelta(hours=h)
            horizon_candle = self._nearest_candle_at_or_before(candles, horizon_time)
            if horizon_candle:
                ret = (horizon_candle.close / entry_price - 1) * 100
                row[f"close_{h}h"] = self._fmt(horizon_candle.close)
                row[f"return_{h}h_pct"] = self._fmt(ret)
                row[f"return_net_{h}h_pct"] = self._fmt(ret - self.cost_pct)
                row[f"close_{h}h_time_utc"] = horizon_candle.close_time_iso

    def _add_btc_metrics(self, row: dict[str, str], token_candles: list[Candle], btc_candles: list[Candle], scan_time: datetime) -> None:
        if not btc_candles:
            row["relative_status"] = "btc_ohlc_unavailable"
            return
        btc_entry = btc_candles[0].open
        if not btc_entry:
            row["relative_status"] = "btc_entry_unavailable"
            return
        row["btc_entry_price"] = self._fmt(btc_entry)

        btc_high = max(c.high for c in btc_candles)
        btc_low = min(c.low for c in btc_candles)
        row["btc_mfe_pct"] = self._fmt((btc_high / btc_entry - 1) * 100)
        row["btc_mae_pct"] = self._fmt((btc_low / btc_entry - 1) * 100)

        for h in self.horizon_hours:
            horizon_time = scan_time + timedelta(hours=h)
            btc_h = self._nearest_candle_at_or_before(btc_candles, horizon_time)
            token_ret = self._safe_float(row.get(f"return_{h}h_pct"))
            if btc_h:
                btc_ret = (btc_h.close / btc_entry - 1) * 100
                row[f"btc_close_{h}h"] = self._fmt(btc_h.close)
                row[f"btc_return_{h}h_pct"] = self._fmt(btc_ret)
                if token_ret is not None:
                    row[f"relative_return_{h}h_pct"] = self._fmt(token_ret - btc_ret)

        # Relativo aproximado usando cierres alineados por timestamp disponible.
        btc_by_open = {c.open_time_ms: c for c in btc_candles}
        rel_values = []
        token_entry = self._safe_float(row.get("reference_price"))
        for tc in token_candles:
            bc = btc_by_open.get(tc.open_time_ms)
            if bc and token_entry:
                token_ret = (tc.close / token_entry - 1) * 100
                btc_ret = (bc.close / btc_entry - 1) * 100
                rel_values.append((token_ret - btc_ret, tc.open_time_ms))
        if rel_values:
            max_rel, max_ts = max(rel_values, key=lambda x: x[0])
            min_rel, min_ts = min(rel_values, key=lambda x: x[0])
            row["max_relative_return_pct"] = self._fmt(max_rel)
            row["max_relative_return_time_utc"] = self._ms_to_iso(max_ts)
            row["min_relative_return_pct"] = self._fmt(min_rel)
            row["min_relative_return_time_utc"] = self._ms_to_iso(min_ts)
            row["relative_status"] = "ok"
        else:
            row["relative_status"] = "no_aligned_candles"

    # ------------------------------------------------------------------
    # Reporte
    # ------------------------------------------------------------------

    def _build_report(self, now: datetime, current: list[dict[str, str]], historical: list[dict[str, str]], validations: list[dict[str, str]]) -> dict[str, Any]:
        completed = [r for r in validations if r.get("ohlc_status") == "completed"]
        text = self._summary_text(completed)
        return {
            "enabled": True,
            "app_version": self.app_version,
            "schema_version": self.SCHEMA_VERSION,
            "created_at": now.isoformat(),
            "current_top_n": self.current_top_n,
            "historical_top_n": self.historical_top_n,
            "current_candidates": len(current),
            "historical_candidates": len(historical),
            "validations_total": len(validations),
            "validations_completed": len(completed),
            "stats": self.stats,
            "target_summary_intraday": self._target_summary(completed),
            "relative_summary": self._relative_summary(completed),
            "text": text,
            "files": {
                "ohlc_validation": str(self.validation_path),
                "ohlc_candidates_current": str(self.candidates_path),
                "ohlc_candidates_historical": str(self.historical_candidates_path),
                "latest_ohlc_report": str(self.report_path),
            },
            "notes": [
                "OHLC intradía se calcula solo para top 10 actuales y top 10 históricos pendientes.",
                "LBank/Binance/Bybit son fuentes públicas sin API key para klines spot; CoinGeckoRange es fallback histórico preliminar.",
                "El retorno relativo usa BTCUSDT en el mismo exchange si está disponible; si no, fallback al otro exchange.",
            ],
        }

    def _target_summary(self, rows: list[dict[str, str]]) -> dict[str, Any]:
        out = {"samples": len(rows)}
        for t in self.target_thresholds:
            key = self._target_key(t)
            count = sum(1 for r in rows if r.get(f"target_{key}_intraday_hit") == "yes")
            out[f"target_{key}_hit_count"] = count
            out[f"target_{key}_hit_rate_pct"] = round(count / len(rows) * 100, 2) if rows else None
        return out

    def _relative_summary(self, rows: list[dict[str, str]]) -> dict[str, Any]:
        out = {"samples": len(rows)}
        for h in self.horizon_hours:
            vals = [self._safe_float(r.get(f"relative_return_{h}h_pct")) for r in rows]
            vals = [v for v in vals if v is not None]
            out[f"relative_{h}h_samples"] = len(vals)
            out[f"relative_{h}h_avg_pct"] = round(sum(vals) / len(vals), 4) if vals else None
            out[f"relative_{h}h_median_pct"] = round(statistics.median(vals), 4) if vals else None
            out[f"relative_{h}h_positive_rate_pct"] = round(sum(1 for v in vals if v > 0) / len(vals) * 100, 2) if vals else None
        return out

    def _summary_text(self, rows: list[dict[str, str]]) -> str:
        if not rows:
            return "📊 OHLC intradía: sin validaciones completas aún; se abrirá base con los top 10 actuales/históricos."
        parts = []
        for t in (2, 5, 10):
            key = self._target_key(t)
            count = sum(1 for r in rows if r.get(f"target_{key}_intraday_hit") == "yes")
            parts.append(f"+{t}%: {count}/{len(rows)}")
        return "📊 OHLC intradía: " + " | ".join(parts)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _base_validation_row(self, c: dict[str, str], now: datetime) -> dict[str, str]:
        return {
            "entry_id": c.get("entry_id", ""),
            "source_scope": c.get("source_scope", ""),
            "scan_time_utc": c.get("scan_time_utc", ""),
            "app_version": self.app_version,
            "coin_id": c.get("coin_id", ""),
            "asset_key": c.get("asset_key", ""),
            "token": c.get("token", ""),
            "name": c.get("name", ""),
            "track_bucket": c.get("track_bucket", ""),
            "category": c.get("category", ""),
            "score": c.get("score", ""),
            "action": c.get("action", ""),
            "operational_bucket": c.get("operational_bucket", ""),
            "priority_tier": c.get("priority_tier", ""),
            "trend_signal": c.get("trend_signal", ""),
            "sector": c.get("sector", ""),
            "exchange_at_scan": c.get("exchange", ""),
            "spot_pair": c.get("spot_pair", ""),
            "reference_price": c.get("reference_price", ""),
            "market_cap_usd": c.get("market_cap_usd", ""),
            "volume_24h_usd": c.get("volume_24h_usd", ""),
            "change_24h_pct_at_scan": c.get("change_24h_pct_at_scan", ""),
            "change_7d_pct_at_scan": c.get("change_7d_pct_at_scan", ""),
            "change_30d_pct_at_scan": c.get("change_30d_pct_at_scan", ""),
        }

    def _preferred_exchange_order(self, exchange_at_scan: str | None) -> list[str]:
        order = []
        e = str(exchange_at_scan or "").strip()
        if e in self.preferred_exchanges:
            order.append(e)
        for x in self.preferred_exchanges:
            if x not in order:
                order.append(x)
        return order

    def _nearest_candle_at_or_before(self, candles: list[Candle], target: datetime) -> Candle | None:
        ts = int(target.timestamp() * 1000)
        eligible = [c for c in candles if c.open_time_ms <= ts]
        return eligible[-1] if eligible else (candles[0] if candles else None)

    def _row_has_usable_symbol(self, row: dict[str, str]) -> bool:
        return bool(row.get("spot_pair") or row.get("token")) and bool(self._safe_float(row.get("reference_price")))

    def _bucket_from_action(self, action: str | None) -> str:
        text = str(action or "").lower()
        if "prioridad" in text:
            return "prioridad_operativa"
        if "candidato" in text:
            return "candidato_activo"
        if "rebote" in text:
            return "rebote_tactico"
        if "vigilar" in text:
            return "vigilar"
        if "retroceso" in text:
            return "esperar_retroceso"
        if "extendido" in text:
            return "extendido"
        if "perseguir" in text:
            return "no_perseguir"
        return ""

    def _normalize_symbol(self, value: str) -> str:
        value = str(value or "").upper().replace("/", "").replace("_", "").strip()
        if value and not value.endswith(self.quote_asset) and value != self.btc_symbol:
            value = f"{value}{self.quote_asset}"
        return value

    def _target_key(self, t: float) -> str:
        return str(int(t)) if float(t).is_integer() else str(t).replace(".", "_")

    def _ms_to_iso(self, ms: int | float | None) -> str:
        if ms is None:
            return ""
        return datetime.fromtimestamp(float(ms) / 1000, tz=timezone.utc).isoformat()

    def _parse_dt(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None

    def _safe_float(self, value: Any) -> float | None:
        if value in (None, "", "-"):
            return None
        try:
            return float(value)
        except Exception:
            return None

    def _fmt(self, value: Any) -> str:
        v = self._safe_float(value)
        return "" if v is None else f"{v:.8f}"

    def _read_csv(self, path: Path) -> list[dict[str, str]]:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    def _write_csv(self, path: Path, rows: list[dict[str, str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fields: list[str] = []
        for row in rows:
            for key in row.keys():
                if key not in fields:
                    fields.append(key)
        with path.open("w", encoding="utf-8", newline="") as f:
            if not fields:
                return
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
