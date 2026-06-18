from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import csv
import hashlib
import json
import shutil
import statistics


class PerformanceTracker:
    """
    Forward testing del scanner con auditoría de integridad.

    MVP 2.9.8 AUDIT:
    - usa CoinGecko ID como identidad primaria; el ticker queda solo como etiqueta;
    - no rellena varios horizontes vencidos con el mismo precio actual;
    - solo acepta mediciones dentro de una ventana temporal configurable;
    - marca horizontes perdidos, datos legacy, duplicados y outliers;
    - separa señales operables, observaciones y grupo de control;
    - agrupa señales repetidas mediante cooldown de episodio;
    - consulta precios externos por lotes, no token por token;
    - registra retorno bruto y neto estimado de costos;
    - guarda máximos/mínimos observados y target hits vistos en corridas;
    - genera audit_report.json, audit_issues.csv y output_manifest.json.

    Importante: los target hits observados no equivalen a máximos intradía. Solo reflejan
    los precios vistos en las ejecuciones del scanner. Una segunda corrida post-América
    mejorará la aproximación, pero OHLC intraperiodo seguirá siendo la referencia ideal.
    """

    SCHEMA_VERSION = "audit_v2"
    TARGET_THRESHOLDS = [2, 5, 10, 15, 20]

    def __init__(self, full_config: dict[str, Any], price_provider: Any):
        # Acepta configuración completa (preferida) o solo performance_tracker por compatibilidad.
        if "performance_tracker" in (full_config or {}):
            self.full_config = full_config or {}
            self.config = self.full_config.get("performance_tracker", {}) or {}
            self.app_version = str(self.full_config.get("app", {}).get("version", "unknown"))
            self.app_name = str(self.full_config.get("app", {}).get("name", "Spot Sector Scanner"))
        else:
            self.full_config = {}
            self.config = full_config or {}
            self.app_version = str(self.config.get("app_version", "unknown"))
            self.app_name = "Spot Sector Scanner"

        self.enabled = bool(self.config.get("enabled", False))
        self.price_provider = price_provider

        self.output_dir = Path(self.config.get("output_dir", "outputs/performance"))
        self.entries_path = self.output_dir / "tracked_entries.csv"
        self.summary_path = self.output_dir / "performance_summary.csv"
        self.latest_report_path = self.output_dir / "latest_performance_report.json"
        self.audit_report_path = self.output_dir / "audit_report.json"
        self.audit_issues_path = self.output_dir / "audit_issues.csv"
        self.manifest_path = self.output_dir / "output_manifest.json"
        self.backup_dir = self.output_dir / "backups"

        self.horizons = [int(h) for h in self.config.get("horizons_hours", [24, 48, 72, 168, 336, 720])]
        self.tolerances = self._load_tolerances()
        self.outlier_abs_return_pct = float(self.config.get("outlier_abs_return_pct", 100.0))
        self.estimated_cost_pct = float(self.config.get("estimated_round_trip_cost_pct", 0.25))
        self.max_tracking_age_hours = float(self.config.get("max_tracking_age_hours", 744))
        self.min_observed_age_hours = float(self.config.get("min_observed_age_hours", 1.0))
        self.episode_cooldown_hours = float(self.config.get("episode_cooldown_hours", 72))
        self.control_cooldown_hours = float(self.config.get("control_cooldown_hours", 24))
        self.backup_on_migration = bool(self.config.get("backup_on_schema_migration", True))

        self.trade_buckets = set(self.config.get(
            "trade_entry_buckets",
            ["prioridad_operativa", "candidato_activo", "rebote_tactico", "vigilar"],
        ))
        self.observation_buckets = set(self.config.get(
            "observation_only_buckets",
            ["esperar_retroceso", "extendido", "exceso_30d", "no_perseguir", "descartar", "revisar"],
        ))

        self.stats = {
            "rows_checked": 0,
            "rows_migrated_legacy": 0,
            "identities_backfilled": 0,
            "identity_unresolved": 0,
            "horizon_checks_due": 0,
            "horizon_updates_exact": 0,
            "horizons_marked_missed": 0,
            "observed_price_updates": 0,
            "prices_from_scan": 0,
            "external_batch_calls": 0,
            "external_ids_requested": 0,
            "external_ids_success": 0,
            "external_ids_failed": 0,
            "duplicates_suppressed": 0,
            "target_hits_gross_new": 0,
            "target_hits_net_new": 0,
        }

    def run(self, result) -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "tracked_new": 0, "updated_entries": 0}

        self.output_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        catalog = self._build_scan_catalog(result)

        existing = self._read_entries()
        backup_path = self._backup_before_migration(existing, now)
        self._migrate_rows(existing, catalog)

        tracked_new = self._add_current_scan(result, existing, now)

        # Se reconstruye el catálogo para incluir todos los tokens del scan; los nuevos registros
        # usan el mismo asset_key y precio del resultado actual.
        price_map, source_map = self._resolve_prices(existing, now, catalog)
        update_stats = self._update_existing_entries(existing, now, price_map, source_map)

        self._write_entries(existing)
        summary = self._build_summary(existing)
        self._write_summary(summary)

        target_summary = self._build_target_summary(existing, net=False)
        target_summary_net = self._build_target_summary(existing, net=True)
        target_hit_summary = self._build_target_hit_summary(existing, net=False)
        target_hit_summary_net = self._build_target_hit_summary(existing, net=True)

        issues = self._build_audit_issues(existing)
        self._write_audit_issues(issues)
        audit_report = self._build_audit_report(existing, summary, issues, now)
        self.audit_report_path.write_text(json.dumps(audit_report, ensure_ascii=False, indent=2), encoding="utf-8")

        report = {
            "enabled": True,
            "app_name": self.app_name,
            "app_version": self.app_version,
            "schema_version": self.SCHEMA_VERSION,
            "created_at": now.isoformat(),
            "tracked_new": tracked_new,
            "updated_entries": update_stats["updated_entries"],
            "observed_updates": update_stats["observed_updates"],
            "entries_total": len(existing),
            "summary_rows": len(summary),
            "clean_trade_entries": sum(1 for r in existing if self._is_clean_trade_entry(r)),
            "legacy_entries_excluded": sum(1 for r in existing if r.get("schema_version") != self.SCHEMA_VERSION),
            "target_summary": target_summary,
            "target_summary_net": target_summary_net,
            "target_hit_summary": target_hit_summary,
            "target_hit_summary_net": target_hit_summary_net,
            "data_quality": audit_report.get("summary", {}),
            "performance_stats": self.stats,
            "backup_created": str(backup_path) if backup_path else None,
            "files": {
                "tracked_entries": str(self.entries_path),
                "performance_summary": str(self.summary_path),
                "latest_performance_report": str(self.latest_report_path),
                "audit_report": str(self.audit_report_path),
                "audit_issues": str(self.audit_issues_path),
                "output_manifest": str(self.manifest_path),
            },
        }
        self.latest_report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        manifest = self._build_manifest(existing, summary, issues, now)
        self.manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    # ------------------------------------------------------------------
    # Configuración e identidad
    # ------------------------------------------------------------------

    def _load_tolerances(self) -> dict[int, float]:
        raw = self.config.get("horizon_tolerance_hours", {}) or {}
        defaults = {24: 8, 48: 8, 72: 8, 168: 12, 336: 18, 720: 24}
        out = {}
        for h in self.horizons:
            value = raw.get(str(h), raw.get(h, defaults.get(h, 8)))
            out[h] = float(value)
        return out

    def _asset_key(self, coin_id: str | None) -> str:
        coin_id = str(coin_id or "").strip().lower()
        return f"cg:{coin_id}" if coin_id else ""

    def _normal(self, value: Any) -> str:
        return " ".join(str(value or "").strip().lower().split())

    def _build_scan_catalog(self, result) -> dict[str, Any]:
        by_asset: dict[str, dict[str, Any]] = {}
        by_symbol_name: dict[tuple[str, str], list[dict[str, Any]]] = {}
        by_symbol: dict[str, list[dict[str, Any]]] = {}

        for token in getattr(result, "tokens", []):
            coin_id = str(getattr(token, "id", "") or "").strip().lower()
            symbol = str(getattr(token, "symbol", "") or "").upper()
            name = str(getattr(token, "name", "") or "")
            price = self._safe_float(getattr(token, "price_usd", None))
            asset_key = self._asset_key(coin_id)
            item = {
                "coin_id": coin_id,
                "asset_key": asset_key,
                "symbol": symbol,
                "name": name,
                "price": price,
                "token": token,
            }
            if asset_key:
                by_asset[asset_key] = item
            by_symbol_name.setdefault((symbol, self._normal(name)), []).append(item)
            by_symbol.setdefault(symbol, []).append(item)

        return {
            "by_asset": by_asset,
            "by_symbol_name": by_symbol_name,
            "by_symbol": by_symbol,
        }

    def _backfill_identity(self, row: dict[str, str], catalog: dict[str, Any]) -> bool:
        if row.get("coin_id"):
            row["asset_key"] = self._asset_key(row.get("coin_id"))
            row["identity_status"] = row.get("identity_status") or "verified_coin_id"
            return True

        symbol = str(row.get("token") or "").upper()
        name = self._normal(row.get("name"))
        matches = catalog["by_symbol_name"].get((symbol, name), [])
        if len(matches) == 1 and matches[0].get("coin_id"):
            row["coin_id"] = matches[0]["coin_id"]
            row["asset_key"] = matches[0]["asset_key"]
            row["identity_status"] = "backfilled_symbol_name"
            self.stats["identities_backfilled"] += 1
            return True

        # Fallback solo si el ticker es único dentro del scan actual.
        symbol_matches = catalog["by_symbol"].get(symbol, [])
        if len(symbol_matches) == 1 and symbol_matches[0].get("coin_id"):
            row["coin_id"] = symbol_matches[0]["coin_id"]
            row["asset_key"] = symbol_matches[0]["asset_key"]
            row["identity_status"] = "backfilled_unique_symbol"
            self.stats["identities_backfilled"] += 1
            return True

        row["identity_status"] = "legacy_symbol_unresolved"
        row["asset_key"] = ""
        self.stats["identity_unresolved"] += 1
        return False

    # ------------------------------------------------------------------
    # Migración y respaldo
    # ------------------------------------------------------------------

    def _backup_before_migration(self, rows: list[dict[str, str]], now: datetime) -> Path | None:
        if not rows or not self.backup_on_migration or not self.entries_path.exists():
            return None
        if not any(r.get("schema_version") != self.SCHEMA_VERSION for r in rows):
            return None

        self.backup_dir.mkdir(parents=True, exist_ok=True)
        marker = self.backup_dir / f".migration_{self.SCHEMA_VERSION}_backup_done"
        if marker.exists():
            return None
        backup = self.backup_dir / f"tracked_entries_pre_{self.SCHEMA_VERSION}_{now.strftime('%Y%m%d_%H%M%S')}.csv"
        shutil.copy2(self.entries_path, backup)
        marker.write_text(now.isoformat(), encoding="utf-8")
        return backup

    def _migrate_rows(self, rows: list[dict[str, str]], catalog: dict[str, Any]) -> None:
        for row in rows:
            is_legacy = row.get("schema_version") != self.SCHEMA_VERSION
            if is_legacy:
                self.stats["rows_migrated_legacy"] += 1
                row.setdefault("app_version", "legacy")
                row.setdefault("schema_version", "legacy_v1")

            self._backfill_identity(row, catalog)
            self._ensure_base_columns(row)
            self._ensure_horizon_columns(row)
            self._ensure_target_columns(row)

            if is_legacy:
                # Los históricos se conservan, pero no contaminan la línea base auditada.
                row["audit_eligible"] = "no"
                row["audit_exclusion_reason"] = "legacy_unverified_measurement"
                row["episode_status"] = row.get("episode_status") or "legacy"
                for h in self.horizons:
                    if row.get(f"return_{h}h_pct") and not row.get(f"measurement_status_{h}h"):
                        row[f"measurement_status_{h}h"] = "legacy_unverified"
                        gross = self._safe_float(row.get(f"return_{h}h_pct"))
                        if gross is not None:
                            row[f"return_net_{h}h_pct"] = self._fmt(gross - self.estimated_cost_pct)
                    elif not row.get(f"measurement_status_{h}h"):
                        row[f"measurement_status_{h}h"] = ""

    def _ensure_base_columns(self, row: dict[str, str]) -> None:
        defaults = {
            "app_version": row.get("app_version", "legacy"),
            "schema_version": row.get("schema_version", "legacy_v1"),
            "coin_id": row.get("coin_id", ""),
            "asset_key": row.get("asset_key", ""),
            "identity_status": row.get("identity_status", "legacy_symbol_only"),
            "entry_intent": row.get("entry_intent", self._entry_intent_from_row(row)),
            "audit_role": row.get("audit_role", self._audit_role_from_row(row)),
            "audit_eligible": row.get("audit_eligible", "no"),
            "audit_exclusion_reason": row.get("audit_exclusion_reason", ""),
            "episode_id": row.get("episode_id", ""),
            "episode_status": row.get("episode_status", ""),
            "duplicate_signal": row.get("duplicate_signal", "no"),
            "duplicate_of_entry_id": row.get("duplicate_of_entry_id", ""),
            "estimated_cost_pct": row.get("estimated_cost_pct", self._fmt(self.estimated_cost_pct)),
            "observed_checks_count": row.get("observed_checks_count", "0"),
            "max_observed_return_pct": row.get("max_observed_return_pct", ""),
            "max_observed_return_net_pct": row.get("max_observed_return_net_pct", ""),
            "max_observed_time_utc": row.get("max_observed_time_utc", ""),
            "min_observed_return_pct": row.get("min_observed_return_pct", ""),
            "min_observed_return_net_pct": row.get("min_observed_return_net_pct", ""),
            "min_observed_time_utc": row.get("min_observed_time_utc", ""),
            "last_observed_price": row.get("last_observed_price", ""),
            "last_observed_time_utc": row.get("last_observed_time_utc", ""),
            "last_observed_source": row.get("last_observed_source", ""),
        }
        for key, value in defaults.items():
            row.setdefault(key, value)

    def _ensure_horizon_columns(self, row: dict[str, str]) -> None:
        for h in self.horizons:
            row.setdefault(f"price_{h}h", "")
            row.setdefault(f"return_{h}h_pct", "")
            row.setdefault(f"return_net_{h}h_pct", "")
            row.setdefault(f"checked_{h}h_utc", "")
            row.setdefault(f"price_source_{h}h", "")
            row.setdefault(f"measurement_status_{h}h", "")
            row.setdefault(f"age_at_check_{h}h", "")
            row.setdefault(f"outlier_{h}h", "")

    def _ensure_target_columns(self, row: dict[str, str]) -> None:
        for t in self.TARGET_THRESHOLDS:
            for suffix in ("gross", "net"):
                p = f"target_{t}pct_{suffix}"
                row.setdefault(f"{p}_hit", "no")
                row.setdefault(f"{p}_hit_time_utc", "")
                row.setdefault(f"{p}_return_pct", "")
                row.setdefault(f"{p}_source", "")

    # ------------------------------------------------------------------
    # Registro de nuevas señales y episodios
    # ------------------------------------------------------------------

    def _scan_id_from_result(self, result) -> str:
        created_at = getattr(result, "created_at", None)
        if isinstance(created_at, datetime):
            return created_at.strftime("%Y%m%d_%H%M%S")
        if isinstance(created_at, str):
            return created_at.replace(":", "").replace("-", "").replace(".", "_")[:32]
        return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    def _entry_id(self, scan_id: str, asset_key: str, symbol: str) -> str:
        stable = asset_key.replace(":", "_") if asset_key else symbol.upper()
        return f"{scan_id}::{stable}"

    def _track_bucket(self, token) -> str | None:
        category = getattr(token, "category", "") or ""
        tier = getattr(token, "priority_tier", "") or ""
        action = getattr(token, "action", "") or ""
        alerts = getattr(token, "alerts", "") or ""
        trend = getattr(token, "trend_signal", "-") or "-"
        score = int(getattr(token, "score", 0) or 0)
        cfg = self.config.get("track_groups", {})

        if cfg.get("a_plus", True) and category.startswith("A+"):
            return "A+"
        if category.startswith("A "):
            if cfg.get("a_t2", True) and tier == "T2 válido con alerta":
                return "A_T2"
            if cfg.get("a_t1", True):
                return "A_T1"
        if category.startswith("B "):
            if cfg.get("b_trending", True) and trend != "-":
                return "B_TREND"
            if cfg.get("b_high_score", True) and score >= int(self.config.get("b_high_score_min", 13)):
                return "B_HIGH_SCORE"
        if cfg.get("t4_control", True) and (
            tier == "T4 riesgo alto" or "extremo" in alerts.lower() or action.startswith("🔴")
        ):
            return "T4_CONTROL"
        return None

    def _operational_bucket(self, token) -> str:
        value = str(getattr(token, "operational_bucket", "") or "").strip()
        if value:
            return value
        action = str(getattr(token, "action", "") or "")
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

    def _entry_intent_from_bucket(self, bucket: str, track_bucket: str = "") -> str:
        if track_bucket == "T4_CONTROL":
            return "control"
        if bucket in self.trade_buckets:
            return "enter_now"
        if bucket == "esperar_retroceso":
            return "wait_for_trigger"
        if bucket in {"extendido", "exceso_30d", "no_perseguir", "descartar"}:
            return "avoid_entry"
        return "observation"

    def _entry_intent_from_row(self, row: dict[str, str]) -> str:
        bucket = str(row.get("operational_bucket") or "")
        return self._entry_intent_from_bucket(bucket, str(row.get("track_bucket") or ""))

    def _audit_role_from_row(self, row: dict[str, str]) -> str:
        intent = row.get("entry_intent") or self._entry_intent_from_row(row)
        if intent == "enter_now":
            return "trade"
        if intent == "control":
            return "control"
        return "observation"

    def _latest_episode_map(self, rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
        latest: dict[tuple[str, str], dict[str, str]] = {}
        for row in rows:
            if row.get("schema_version") != self.SCHEMA_VERSION:
                continue
            if row.get("audit_eligible") != "yes":
                continue
            asset_key = row.get("asset_key") or ""
            role = row.get("audit_role") or ""
            if not asset_key or role not in {"trade", "control"}:
                continue
            dt = self._parse_datetime(row.get("scan_time_utc"))
            if not dt:
                continue
            key = (asset_key, role)
            current = latest.get(key)
            current_dt = self._parse_datetime(current.get("scan_time_utc")) if current else None
            if current is None or (current_dt and dt > current_dt):
                latest[key] = row
        return latest

    def _add_current_scan(self, result, rows: list[dict[str, str]], now: datetime) -> int:
        scan_id = self._scan_id_from_result(result)
        existing_ids = {r.get("entry_id") for r in rows}
        episodes = self._latest_episode_map(rows)
        added = 0
        t4_count = 0
        max_t4 = int(self.config.get("max_t4_control", 12))

        for token in getattr(result, "tokens", []):
            track_bucket = self._track_bucket(token)
            if not track_bucket:
                continue
            if track_bucket == "T4_CONTROL":
                if t4_count >= max_t4:
                    continue
                t4_count += 1

            coin_id = str(getattr(token, "id", "") or "").strip().lower()
            asset_key = self._asset_key(coin_id)
            symbol = str(getattr(token, "symbol", "") or "").upper()
            if not symbol or not asset_key:
                continue

            entry_id = self._entry_id(scan_id, asset_key, symbol)
            if entry_id in existing_ids:
                continue

            op_bucket = self._operational_bucket(token)
            intent = self._entry_intent_from_bucket(op_bucket, track_bucket)
            role = "trade" if intent == "enter_now" else "control" if intent == "control" else "observation"
            audit_eligible = role in {"trade", "control"}
            duplicate = False
            duplicate_of = ""
            exclusion_reason = ""

            if role == "observation":
                audit_eligible = False
                exclusion_reason = f"observation_only:{intent}"
            else:
                previous = episodes.get((asset_key, role))
                previous_time = self._parse_datetime(previous.get("scan_time_utc")) if previous else None
                cooldown = self.control_cooldown_hours if role == "control" else self.episode_cooldown_hours
                if previous and previous_time and (now - previous_time).total_seconds() / 3600 < cooldown:
                    audit_eligible = False
                    duplicate = True
                    duplicate_of = previous.get("entry_id", "")
                    exclusion_reason = f"duplicate_within_{cooldown:g}h"
                    self.stats["duplicates_suppressed"] += 1

            reference_price = self._safe_float(getattr(token, "price_usd", None))
            row = {
                "entry_id": entry_id,
                "scan_id": scan_id,
                "scan_time_utc": now.isoformat(),
                "app_version": self.app_version,
                "schema_version": self.SCHEMA_VERSION,
                "coin_id": coin_id,
                "asset_key": asset_key,
                "identity_status": "verified_coin_id",
                "token": symbol,
                "name": getattr(token, "name", "") or "",
                "track_bucket": track_bucket,
                "category": getattr(token, "category", "") or "",
                "score": str(getattr(token, "score", "") or ""),
                "action": getattr(token, "action", "") or "",
                "operational_bucket": op_bucket,
                "operational_reason": getattr(token, "operational_reason", "") or "",
                "alerts": getattr(token, "alerts", "") or "",
                "priority_tier": getattr(token, "priority_tier", "") or "",
                "trend_signal": getattr(token, "trend_signal", "") or "",
                "sector": getattr(token, "sector_name", "") or "",
                "exchange": getattr(token, "exchange", "") or "",
                "spot_pair": getattr(token, "spot_pair", "") or "",
                "pair_identity_status": getattr(token, "pair_identity_status", "") or "",
                "pair_price_deviation_pct": self._fmt(getattr(token, "pair_price_deviation_pct", None)),
                "reference_price": self._fmt(reference_price),
                "reference_price_available": "yes" if reference_price is not None else "no",
                "market_cap_usd": self._fmt(getattr(token, "market_cap_usd", None)),
                "volume_24h_usd": self._fmt(getattr(token, "volume_24h_usd", None)),
                "change_24h_pct_at_scan": self._fmt(getattr(token, "change_24h_pct", None)),
                "change_7d_pct_at_scan": self._fmt(getattr(token, "change_7d_pct", None)),
                "change_30d_pct_at_scan": self._fmt(getattr(token, "change_30d_pct", None)),
                "entry_intent": intent,
                "audit_role": role,
                "audit_eligible": "yes" if audit_eligible else "no",
                "audit_exclusion_reason": exclusion_reason,
                "episode_id": f"{asset_key}:{scan_id}" if audit_eligible else "",
                "episode_status": "open" if audit_eligible else "excluded",
                "duplicate_signal": "yes" if duplicate else "no",
                "duplicate_of_entry_id": duplicate_of,
                "estimated_cost_pct": self._fmt(self.estimated_cost_pct),
                "observed_checks_count": "0",
                "max_observed_return_pct": "",
                "max_observed_return_net_pct": "",
                "max_observed_time_utc": "",
                "min_observed_return_pct": "",
                "min_observed_return_net_pct": "",
                "min_observed_time_utc": "",
                "last_observed_price": "",
                "last_observed_time_utc": "",
                "last_observed_source": "",
            }
            self._ensure_horizon_columns(row)
            self._ensure_target_columns(row)
            rows.append(row)
            existing_ids.add(entry_id)
            added += 1
            if audit_eligible:
                episodes[(asset_key, role)] = row

        return added

    # ------------------------------------------------------------------
    # Resolución eficiente de precios
    # ------------------------------------------------------------------

    def _row_needs_price(self, row: dict[str, str], now: datetime) -> bool:
        if row.get("schema_version") != self.SCHEMA_VERSION or row.get("audit_eligible") != "yes":
            return False
        scan_time = self._parse_datetime(row.get("scan_time_utc"))
        if not scan_time:
            return False
        age = (now - scan_time).total_seconds() / 3600
        if age < 0 or age > self.max_tracking_age_hours:
            return False
        if age >= self.min_observed_age_hours:
            return True
        for h in self.horizons:
            status = row.get(f"measurement_status_{h}h", "")
            if status in {"exact_window", "missed_window"}:
                continue
            tol = self.tolerances[h]
            if h - tol <= age <= h + tol:
                return True
        return False

    def _resolve_prices(
        self,
        rows: list[dict[str, str]],
        now: datetime,
        catalog: dict[str, Any],
    ) -> tuple[dict[str, float], dict[str, str]]:
        price_map: dict[str, float] = {}
        source_map: dict[str, str] = {}

        for asset_key, item in catalog["by_asset"].items():
            price = self._safe_float(item.get("price"))
            if price is not None and price > 0:
                price_map[asset_key] = price
                source_map[asset_key] = "scan_current_by_coin_id"

        needed_ids = set()
        for row in rows:
            if not self._row_needs_price(row, now):
                continue
            asset_key = row.get("asset_key") or ""
            coin_id = str(row.get("coin_id") or "").lower()
            if asset_key and asset_key in price_map:
                continue
            if coin_id:
                needed_ids.add(coin_id)

        if needed_ids:
            external = self._fetch_prices_by_ids(sorted(needed_ids))
            for coin_id, price in external.items():
                if price is None or price <= 0:
                    continue
                key = self._asset_key(coin_id)
                price_map[key] = price
                source_map[key] = "coingecko_batch_by_id"

        return price_map, source_map

    def _fetch_prices_by_ids(self, coin_ids: list[str]) -> dict[str, float]:
        self.stats["external_ids_requested"] += len(coin_ids)
        if not coin_ids:
            return {}

        result: dict[str, float] = {}
        try:
            if hasattr(self.price_provider, "get_prices_by_ids"):
                self.stats["external_batch_calls"] += 1
                data = self.price_provider.get_prices_by_ids(coin_ids)
                if isinstance(data, dict):
                    for coin_id, value in data.items():
                        if isinstance(value, dict):
                            value = value.get("usd") or value.get("current_price")
                        price = self._safe_float(value)
                        if price is not None and price > 0:
                            result[str(coin_id).lower()] = price
            elif hasattr(self.price_provider, "get_price_by_id"):
                for coin_id in coin_ids:
                    self.stats["external_batch_calls"] += 1
                    price = self._safe_float(self.price_provider.get_price_by_id(coin_id))
                    if price is not None and price > 0:
                        result[coin_id] = price
        except Exception:
            result = {}

        self.stats["external_ids_success"] += len(result)
        self.stats["external_ids_failed"] += max(0, len(coin_ids) - len(result))
        return result

    # ------------------------------------------------------------------
    # Actualización temporal y target hit observado
    # ------------------------------------------------------------------

    def _update_existing_entries(
        self,
        rows: list[dict[str, str]],
        now: datetime,
        price_map: dict[str, float],
        source_map: dict[str, str],
    ) -> dict[str, int]:
        updated_entries = 0
        observed_updates = 0

        for row in rows:
            self.stats["rows_checked"] += 1
            if row.get("schema_version") != self.SCHEMA_VERSION or row.get("audit_eligible") != "yes":
                continue

            scan_time = self._parse_datetime(row.get("scan_time_utc"))
            reference = self._safe_float(row.get("reference_price"))
            asset_key = row.get("asset_key") or ""
            if not scan_time or reference is None or reference <= 0 or not asset_key:
                continue

            age = (now - scan_time).total_seconds() / 3600
            if age < 0:
                continue

            # Marca horizontes ya perdidos; nunca los rellena con un precio tardío.
            for h in self.horizons:
                status_key = f"measurement_status_{h}h"
                if row.get(status_key) in {"exact_window", "missed_window"}:
                    continue
                if row.get(f"return_{h}h_pct"):
                    # Un valor sin estado en schema auditado se considera no verificable.
                    row[status_key] = "unverified_existing"
                    continue
                if age > h + self.tolerances[h]:
                    row[status_key] = "missed_window"
                    self.stats["horizons_marked_missed"] += 1

            price = price_map.get(asset_key)
            source = source_map.get(asset_key, "")
            if price is None or price <= 0:
                continue

            gross = ((price - reference) / reference) * 100
            net = gross - self.estimated_cost_pct

            # Observación continua en cada corrida, útil para TP programado aproximado.
            if self.min_observed_age_hours <= age <= self.max_tracking_age_hours:
                self._update_observed(row, price, gross, net, now, source)
                observed_updates += 1
                self.stats["observed_price_updates"] += 1

            # Solo un horizonte exacto por fila y corrida: el más cercano dentro de tolerancia.
            candidates = []
            for h in self.horizons:
                if row.get(f"measurement_status_{h}h"):
                    continue
                tol = self.tolerances[h]
                if h - tol <= age <= h + tol:
                    candidates.append((abs(age - h), h))

            if not candidates:
                continue

            _, h = min(candidates)
            self.stats["horizon_checks_due"] += 1
            row[f"price_{h}h"] = self._fmt(price)
            row[f"return_{h}h_pct"] = self._fmt(gross)
            row[f"return_net_{h}h_pct"] = self._fmt(net)
            row[f"checked_{h}h_utc"] = now.isoformat()
            row[f"price_source_{h}h"] = source
            row[f"measurement_status_{h}h"] = "exact_window"
            row[f"age_at_check_{h}h"] = self._fmt(age)
            row[f"outlier_{h}h"] = "yes" if abs(gross) > self.outlier_abs_return_pct else "no"
            updated_entries += 1
            self.stats["horizon_updates_exact"] += 1

            if source.startswith("scan_current"):
                self.stats["prices_from_scan"] += 1

        return {"updated_entries": updated_entries, "observed_updates": observed_updates}

    def _update_observed(
        self,
        row: dict[str, str],
        price: float,
        gross: float,
        net: float,
        now: datetime,
        source: str,
    ) -> None:
        count = int(self._safe_float(row.get("observed_checks_count")) or 0) + 1
        row["observed_checks_count"] = str(count)
        row["last_observed_price"] = self._fmt(price)
        row["last_observed_time_utc"] = now.isoformat()
        row["last_observed_source"] = source

        current_max = self._safe_float(row.get("max_observed_return_pct"))
        if current_max is None or gross > current_max:
            row["max_observed_return_pct"] = self._fmt(gross)
            row["max_observed_return_net_pct"] = self._fmt(net)
            row["max_observed_time_utc"] = now.isoformat()

        current_min = self._safe_float(row.get("min_observed_return_pct"))
        if current_min is None or gross < current_min:
            row["min_observed_return_pct"] = self._fmt(gross)
            row["min_observed_return_net_pct"] = self._fmt(net)
            row["min_observed_time_utc"] = now.isoformat()

        if abs(gross) <= self.outlier_abs_return_pct:
            self._mark_target_hits(row, gross, now, source, net=False)
        if abs(net) <= self.outlier_abs_return_pct:
            self._mark_target_hits(row, net, now, source, net=True)

    def _mark_target_hits(self, row: dict[str, str], value: float, now: datetime, source: str, net: bool) -> None:
        suffix = "net" if net else "gross"
        for t in self.TARGET_THRESHOLDS:
            if value < t:
                continue
            p = f"target_{t}pct_{suffix}"
            if row.get(f"{p}_hit") == "yes":
                continue
            row[f"{p}_hit"] = "yes"
            row[f"{p}_hit_time_utc"] = now.isoformat()
            row[f"{p}_return_pct"] = self._fmt(value)
            row[f"{p}_source"] = source
            if net:
                self.stats["target_hits_net_new"] += 1
            else:
                self.stats["target_hits_gross_new"] += 1

    # ------------------------------------------------------------------
    # Resúmenes limpios y legacy
    # ------------------------------------------------------------------

    def _is_clean_trade_entry(self, row: dict[str, str]) -> bool:
        return (
            row.get("schema_version") == self.SCHEMA_VERSION
            and row.get("audit_eligible") == "yes"
            and row.get("audit_role") == "trade"
            and row.get("identity_status") in {"verified_coin_id", "backfilled_symbol_name", "backfilled_unique_symbol"}
        )

    def _clean_horizon_values(self, rows: list[dict[str, str]], h: int, net: bool = False) -> list[float]:
        key = f"return_net_{h}h_pct" if net else f"return_{h}h_pct"
        out = []
        for row in rows:
            if not self._is_clean_trade_entry(row):
                continue
            if row.get(f"measurement_status_{h}h") != "exact_window":
                continue
            if row.get(f"outlier_{h}h") == "yes":
                continue
            value = self._safe_float(row.get(key))
            if value is not None and abs(value) <= self.outlier_abs_return_pct:
                out.append(value)
        return out

    def _all_raw_values(self, rows: list[dict[str, str]], h: int) -> list[float]:
        vals = [self._safe_float(r.get(f"return_{h}h_pct")) for r in rows]
        return [v for v in vals if v is not None]

    def _build_summary(self, rows: list[dict[str, str]]) -> list[dict[str, str]]:
        groups: dict[tuple[str, str, str], list[dict[str, str]]] = {}
        for row in rows:
            key = (row.get("track_bucket", ""), row.get("category", ""), row.get("audit_role", ""))
            groups.setdefault(key, []).append(row)

        out_rows = []
        for (bucket, category, role), group_rows in sorted(groups.items()):
            out: dict[str, str] = {
                "track_bucket": bucket,
                "category": category,
                "audit_role": role,
                "entries_total": str(len(group_rows)),
                "entries_schema_audit": str(sum(1 for r in group_rows if r.get("schema_version") == self.SCHEMA_VERSION)),
                "entries_audit_eligible": str(sum(1 for r in group_rows if r.get("audit_eligible") == "yes")),
                "entries_duplicates": str(sum(1 for r in group_rows if r.get("duplicate_signal") == "yes")),
                "entries_legacy": str(sum(1 for r in group_rows if r.get("schema_version") != self.SCHEMA_VERSION)),
            }

            for h in self.horizons:
                raw_vals = self._all_raw_values(group_rows, h)
                clean_gross = self._clean_horizon_values(group_rows, h, net=False)
                clean_net = self._clean_horizon_values(group_rows, h, net=True)
                out[f"samples_{h}h_raw"] = str(len(raw_vals))
                out[f"samples_{h}h_exact_clean"] = str(len(clean_gross))
                out[f"missed_{h}h"] = str(sum(1 for r in group_rows if r.get(f"measurement_status_{h}h") == "missed_window"))
                out[f"legacy_unverified_{h}h"] = str(sum(1 for r in group_rows if r.get(f"measurement_status_{h}h") == "legacy_unverified"))
                out[f"outliers_{h}h"] = str(sum(1 for r in group_rows if r.get(f"outlier_{h}h") == "yes"))

                self._put_stats(out, f"gross_{h}h", clean_gross)
                self._put_stats(out, f"net_{h}h", clean_net)
                out[f"avg_return_{h}h_pct_raw_all"] = self._fmt(sum(raw_vals) / len(raw_vals)) if raw_vals else ""

            self._add_group_targets(out, group_rows)
            self._add_group_target_hits(out, group_rows)
            out_rows.append(out)
        return out_rows

    def _put_stats(self, out: dict[str, str], prefix: str, vals: list[float]) -> None:
        if not vals:
            out[f"avg_{prefix}_pct"] = ""
            out[f"median_{prefix}_pct"] = ""
            out[f"win_rate_{prefix}_pct"] = ""
            return
        out[f"avg_{prefix}_pct"] = self._fmt(sum(vals) / len(vals))
        out[f"median_{prefix}_pct"] = self._fmt(statistics.median(vals))
        out[f"win_rate_{prefix}_pct"] = self._fmt((sum(1 for v in vals if v > 0) / len(vals)) * 100)

    def _target_specs(self, net: bool = False):
        p = "return_net" if net else "return"
        return [
            {"key": "target_24h_min_2pct", "return_key": f"{p}_24h_pct", "h": 24, "label": "Día ≥2%", "predicate": lambda v: v >= 2},
            {"key": "target_24h_ideal_2_to_5pct", "return_key": f"{p}_24h_pct", "h": 24, "label": "Día 2-5%", "predicate": lambda v: 2 <= v <= 5},
            {"key": "target_24h_over_5pct", "return_key": f"{p}_24h_pct", "h": 24, "label": "Día >5%", "predicate": lambda v: v > 5},
            {"key": "target_72h_min_5pct", "return_key": f"{p}_72h_pct", "h": 72, "label": "3D ≥5%", "predicate": lambda v: v >= 5},
            {"key": "target_72h_ideal_5_to_10pct", "return_key": f"{p}_72h_pct", "h": 72, "label": "3D 5-10%", "predicate": lambda v: 5 <= v <= 10},
            {"key": "target_72h_over_10pct", "return_key": f"{p}_72h_pct", "h": 72, "label": "3D >10%", "predicate": lambda v: v > 10},
            {"key": "target_168h_min_10pct", "return_key": f"{p}_168h_pct", "h": 168, "label": "Semana ≥10%", "predicate": lambda v: v >= 10},
            {"key": "target_168h_ideal_10_to_15pct", "return_key": f"{p}_168h_pct", "h": 168, "label": "Semana 10-15%", "predicate": lambda v: 10 <= v <= 15},
            {"key": "target_168h_over_15pct", "return_key": f"{p}_168h_pct", "h": 168, "label": "Semana >15%", "predicate": lambda v: v > 15},
            {"key": "target_720h_min_10pct", "return_key": f"{p}_720h_pct", "h": 720, "label": "Mes ≥10%", "predicate": lambda v: v >= 10},
            {"key": "target_720h_ideal_10_to_20pct", "return_key": f"{p}_720h_pct", "h": 720, "label": "Mes 10-20%", "predicate": lambda v: 10 <= v <= 20},
            {"key": "target_720h_over_20pct", "return_key": f"{p}_720h_pct", "h": 720, "label": "Mes >20%", "predicate": lambda v: v > 20},
        ]

    def _eligible_values_for_spec(self, rows: list[dict[str, str]], spec: dict[str, Any]) -> list[float]:
        vals = []
        h = spec["h"]
        for row in rows:
            if not self._is_clean_trade_entry(row):
                continue
            if row.get(f"measurement_status_{h}h") != "exact_window" or row.get(f"outlier_{h}h") == "yes":
                continue
            v = self._safe_float(row.get(spec["return_key"]))
            if v is not None:
                vals.append(v)
        return vals

    def _add_group_targets(self, out: dict[str, str], rows: list[dict[str, str]]) -> None:
        for net in (False, True):
            suffix = "net" if net else "gross"
            for spec in self._target_specs(net=net):
                vals = self._eligible_values_for_spec(rows, spec)
                count = sum(1 for v in vals if spec["predicate"](v))
                out[f"{spec['key']}_{suffix}_count"] = str(count)
                out[f"{spec['key']}_{suffix}_samples"] = str(len(vals))
                out[f"{spec['key']}_{suffix}_rate_pct"] = self._fmt((count / len(vals)) * 100) if vals else ""

    def _add_group_target_hits(self, out: dict[str, str], rows: list[dict[str, str]]) -> None:
        eligible = [r for r in rows if self._is_clean_trade_entry(r) and int(self._safe_float(r.get("observed_checks_count")) or 0) > 0]
        n = len(eligible)
        for suffix in ("gross", "net"):
            for t in self.TARGET_THRESHOLDS:
                p = f"target_{t}pct_{suffix}"
                count = sum(1 for r in eligible if r.get(f"{p}_hit") == "yes")
                out[f"{p}_hit_count"] = str(count)
                out[f"{p}_hit_samples"] = str(n)
                out[f"{p}_hit_rate_pct"] = self._fmt((count / n) * 100) if n else ""

    def _build_target_summary(self, rows: list[dict[str, str]], net: bool) -> dict[str, Any]:
        out: dict[str, Any] = {"basis": "net_estimated" if net else "gross", "schema": self.SCHEMA_VERSION}
        for spec in self._target_specs(net=net):
            vals = self._eligible_values_for_spec(rows, spec)
            count = sum(1 for v in vals if spec["predicate"](v))
            out[f"{spec['key']}_count"] = count
            out[f"{spec['key']}_samples"] = len(vals)
            out[f"{spec['key']}_rate_pct"] = round((count / len(vals)) * 100, 2) if vals else None

        label = "netas estimadas" if net else "brutas"
        out["text"] = (
            f"🎯 Metas {label} auditadas: "
            f"Día ≥2%: {out['target_24h_min_2pct_count']}/{out['target_24h_min_2pct_samples']} "
            f"(2-5%: {out['target_24h_ideal_2_to_5pct_count']}, >5%: {out['target_24h_over_5pct_count']}) | "
            f"3D ≥5%: {out['target_72h_min_5pct_count']}/{out['target_72h_min_5pct_samples']} "
            f"(5-10%: {out['target_72h_ideal_5_to_10pct_count']}, >10%: {out['target_72h_over_10pct_count']}) | "
            f"Semana ≥10%: {out['target_168h_min_10pct_count']}/{out['target_168h_min_10pct_samples']} "
            f"(10-15%: {out['target_168h_ideal_10_to_15pct_count']}, >15%: {out['target_168h_over_15pct_count']}) | "
            f"Mes ≥10%: {out['target_720h_min_10pct_count']}/{out['target_720h_min_10pct_samples']}"
        )
        out["note"] = "Solo incluye entradas nuevas auditables y mediciones dentro de la ventana temporal exacta."
        return out

    def _build_target_hit_summary(self, rows: list[dict[str, str]], net: bool) -> dict[str, Any]:
        eligible = [r for r in rows if self._is_clean_trade_entry(r) and int(self._safe_float(r.get("observed_checks_count")) or 0) > 0]
        n = len(eligible)
        suffix = "net" if net else "gross"
        out: dict[str, Any] = {
            "basis": "net_estimated" if net else "gross",
            "evaluated_episode_entries": n,
            "note": "Target hit observado en ejecuciones del scanner; no equivale a máximo intradía.",
        }
        pieces = []
        for t in self.TARGET_THRESHOLDS:
            p = f"target_{t}pct_{suffix}"
            count = sum(1 for r in eligible if r.get(f"{p}_hit") == "yes")
            out[f"target_{t}pct_hit_count"] = count
            out[f"target_{t}pct_hit_samples"] = n
            out[f"target_{t}pct_hit_rate_pct"] = round((count / n) * 100, 2) if n else None
            pieces.append(f"+{t}%: {count}/{n}")
        label = "neto estimado" if net else "bruto"
        out["text"] = f"🎯 Target hit observado {label}: " + " | ".join(pieces)
        return out

    # ------------------------------------------------------------------
    # Auditoría
    # ------------------------------------------------------------------

    def _build_audit_issues(self, rows: list[dict[str, str]]) -> list[dict[str, str]]:
        issues = []
        for row in rows:
            base = {
                "entry_id": row.get("entry_id", ""),
                "asset_key": row.get("asset_key", ""),
                "token": row.get("token", ""),
                "name": row.get("name", ""),
                "scan_time_utc": row.get("scan_time_utc", ""),
            }
            if row.get("schema_version") != self.SCHEMA_VERSION:
                issues.append({**base, "severity": "warning", "issue": "legacy_unverified", "detail": "Excluido de métricas auditadas."})
            if not row.get("asset_key"):
                issues.append({**base, "severity": "high", "issue": "identity_unresolved", "detail": row.get("identity_status", "")})
            if row.get("duplicate_signal") == "yes":
                issues.append({**base, "severity": "info", "issue": "duplicate_signal", "detail": row.get("duplicate_of_entry_id", "")})
            if row.get("schema_version") == self.SCHEMA_VERSION and row.get("audit_role") == "observation":
                issues.append({**base, "severity": "info", "issue": "observation_only", "detail": row.get("audit_exclusion_reason", "")})
            for h in self.horizons:
                status = row.get(f"measurement_status_{h}h")
                if status == "missed_window":
                    issues.append({**base, "severity": "warning", "issue": f"missed_window_{h}h", "detail": f"Tolerancia ±{self.tolerances[h]:g}h"})
                if row.get(f"outlier_{h}h") == "yes":
                    issues.append({**base, "severity": "high", "issue": f"outlier_{h}h", "detail": row.get(f"return_{h}h_pct", "")})
        return issues

    def _build_audit_report(
        self,
        rows: list[dict[str, str]],
        summary: list[dict[str, str]],
        issues: list[dict[str, str]],
        now: datetime,
    ) -> dict[str, Any]:
        counts = Counter(i["issue"] for i in issues)
        high = sum(1 for i in issues if i["severity"] == "high")
        warning = sum(1 for i in issues if i["severity"] == "warning")
        clean_trade = sum(1 for r in rows if self._is_clean_trade_entry(r))
        exact_measurements = sum(
            1 for r in rows for h in self.horizons if r.get(f"measurement_status_{h}h") == "exact_window"
        )
        legacy = sum(1 for r in rows if r.get("schema_version") != self.SCHEMA_VERSION)
        unresolved = sum(1 for r in rows if not r.get("asset_key"))
        duplicates = sum(1 for r in rows if r.get("duplicate_signal") == "yes")
        observation = sum(1 for r in rows if r.get("audit_role") == "observation")

        if high:
            grade = "C"
            status = "requires_attention"
        elif warning or legacy:
            grade = "B"
            status = "clean_baseline_building"
        else:
            grade = "A"
            status = "audited"

        return {
            "app_version": self.app_version,
            "schema_version": self.SCHEMA_VERSION,
            "created_at": now.isoformat(),
            "summary": {
                "status": status,
                "grade": grade,
                "entries_total": len(rows),
                "clean_trade_episode_entries": clean_trade,
                "exact_window_measurements": exact_measurements,
                "legacy_entries_excluded": legacy,
                "identity_unresolved": unresolved,
                "duplicate_signals_excluded": duplicates,
                "observation_only_entries": observation,
                "high_severity_issues": high,
                "warning_issues": warning,
            },
            "issue_counts": dict(sorted(counts.items())),
            "rules": {
                "coin_id_required": True,
                "legacy_excluded_from_clean_metrics": True,
                "horizon_tolerance_hours": {str(k): v for k, v in self.tolerances.items()},
                "episode_cooldown_hours": self.episode_cooldown_hours,
                "estimated_round_trip_cost_pct": self.estimated_cost_pct,
                "outlier_abs_return_pct": self.outlier_abs_return_pct,
                "target_hit_is_observed_not_intraday": True,
            },
            "summary_rows": len(summary),
            "files": {
                "issues": str(self.audit_issues_path),
                "tracked_entries": str(self.entries_path),
                "performance_summary": str(self.summary_path),
            },
        }

    # ------------------------------------------------------------------
    # IO y manifiesto
    # ------------------------------------------------------------------

    def _read_entries(self) -> list[dict[str, str]]:
        if not self.entries_path.exists():
            return []
        with self.entries_path.open("r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    def _write_entries(self, rows: list[dict[str, str]]) -> None:
        self._write_csv(self.entries_path, rows)

    def _write_summary(self, rows: list[dict[str, str]]) -> None:
        self._write_csv(self.summary_path, rows)

    def _write_audit_issues(self, rows: list[dict[str, str]]) -> None:
        self._write_csv(self.audit_issues_path, rows, fallback_fields=[
            "severity", "issue", "entry_id", "asset_key", "token", "name", "scan_time_utc", "detail"
        ])

    def _write_csv(self, path: Path, rows: list[dict[str, str]], fallback_fields: list[str] | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not rows:
            fields = fallback_fields or []
            with path.open("w", encoding="utf-8", newline="") as f:
                if fields:
                    csv.DictWriter(f, fieldnames=fields).writeheader()
            return
        fieldnames = []
        for row in rows:
            for key in row.keys():
                if key not in fieldnames:
                    fieldnames.append(key)
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def _build_manifest(
        self,
        entries: list[dict[str, str]],
        summary: list[dict[str, str]],
        issues: list[dict[str, str]],
        now: datetime,
    ) -> dict[str, Any]:
        files = {
            "tracked_entries": (self.entries_path, len(entries)),
            "performance_summary": (self.summary_path, len(summary)),
            "audit_issues": (self.audit_issues_path, len(issues)),
            "audit_report": (self.audit_report_path, None),
            "latest_performance_report": (self.latest_report_path, None),
        }
        payload = {}
        for name, (path, rows) in files.items():
            payload[name] = {
                "path": str(path),
                "exists": path.exists(),
                "size_bytes": path.stat().st_size if path.exists() else 0,
                "sha256": self._sha256(path) if path.exists() else None,
                "rows": rows,
            }
        return {
            "app_version": self.app_version,
            "schema_version": self.SCHEMA_VERSION,
            "created_at": now.isoformat(),
            "files": payload,
        }

    def _sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _safe_float(self, value) -> float | None:
        if value in (None, "", "-"):
            return None
        try:
            return float(value)
        except Exception:
            return None

    def _fmt(self, value) -> str:
        value = self._safe_float(value)
        return "" if value is None else f"{value:.8f}"

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
