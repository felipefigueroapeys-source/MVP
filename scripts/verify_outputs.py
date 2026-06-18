from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import json
import sys
import yaml


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
PERF = OUTPUTS / "performance"
DIAG = OUTPUTS / "diagnostics"
OHLC = OUTPUTS / "ohlc"
REPORT_PATH = PERF / "verification_report.json"


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def csv_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return sum(1 for _ in csv.DictReader(f))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_dt(value: str | None):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def main() -> int:
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    expected_version = str(config.get("app", {}).get("version", "unknown"))

    required = {
        "latest_scan": OUTPUTS / "latest_scan.json",
        "ranking_csv": OUTPUTS / "ranking.csv",
        "ranking_xlsx": OUTPUTS / "ranking.xlsx",
        "performance_report": PERF / "latest_performance_report.json",
        "tracked_entries": PERF / "tracked_entries.csv",
        "performance_summary": PERF / "performance_summary.csv",
        "audit_report": PERF / "audit_report.json",
        "audit_issues": PERF / "audit_issues.csv",
        "manifest": PERF / "output_manifest.json",
        "timing_report": DIAG / "timing_report.json",
        "ohlc_report": OHLC / "latest_ohlc_report.json",
        "ohlc_validation": OHLC / "ohlc_validation.csv",
        "ohlc_candidates_current": OHLC / "ohlc_candidates_current.csv",
    }

    errors = []
    warnings = []
    for name, path in required.items():
        if not path.exists():
            errors.append(f"missing:{name}:{path}")

    result = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "expected_version": expected_version,
        "status": "failed",
        "errors": errors,
        "warnings": warnings,
        "checks": {},
    }

    if errors:
        PERF.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Output verification FAILED: missing files")
        for error in errors:
            print(" -", error)
        return 1

    scan = load_json(required["latest_scan"])
    performance = load_json(required["performance_report"])
    audit = load_json(required["audit_report"])
    manifest = load_json(required["manifest"])
    timing = load_json(required["timing_report"])
    ohlc = load_json(required["ohlc_report"])

    versions = {
        "latest_scan": str(scan.get("app_version", "")),
        "performance_report": str(performance.get("app_version", "")),
        "audit_report": str(audit.get("app_version", "")),
        "manifest": str(manifest.get("app_version", "")),
        "timing_metadata": str(timing.get("metadata", {}).get("app_version", "")),
        "ohlc_report": str(ohlc.get("app_version", "")),
    }
    result["checks"]["versions"] = versions
    for name, version in versions.items():
        if version != expected_version:
            errors.append(f"version_mismatch:{name}:expected={expected_version}:actual={version}")

    entries_rows = csv_rows(required["tracked_entries"])
    summary_rows = csv_rows(required["performance_summary"])
    issues_rows = csv_rows(required["audit_issues"])
    result["checks"]["row_counts"] = {
        "tracked_entries_csv": entries_rows,
        "performance_report_entries_total": performance.get("entries_total"),
        "performance_summary_csv": summary_rows,
        "performance_report_summary_rows": performance.get("summary_rows"),
        "audit_issues_csv": issues_rows,
    }
    if entries_rows != int(performance.get("entries_total", -1)):
        errors.append(f"row_count_mismatch:tracked_entries:{entries_rows}!={performance.get('entries_total')}")
    if summary_rows != int(performance.get("summary_rows", -1)):
        errors.append(f"row_count_mismatch:performance_summary:{summary_rows}!={performance.get('summary_rows')}")

    # El reporte incluido en timing debe ser el mismo que el latest report del run.
    timing_perf = timing.get("metadata", {}).get("performance_report", {})
    result["checks"]["timing_performance_entries_total"] = timing_perf.get("entries_total")
    if timing_perf.get("entries_total") != performance.get("entries_total"):
        errors.append("timing_report_performance_mismatch")
    if timing_perf.get("app_version") != expected_version:
        errors.append("timing_report_embeds_wrong_app_version")

    # Coherencia temporal del mismo run.
    scan_dt = parse_dt(scan.get("created_at"))
    perf_dt = parse_dt(performance.get("created_at"))
    if scan_dt and perf_dt:
        delta_minutes = abs((perf_dt - scan_dt).total_seconds()) / 60
        result["checks"]["scan_performance_time_delta_minutes"] = round(delta_minutes, 3)
        if delta_minutes > 15:
            errors.append(f"run_time_mismatch:{delta_minutes:.2f}min")

    # Verifica hashes y filas declarados en manifest.
    manifest_checks = {}
    manifest_paths = {
        "tracked_entries": required["tracked_entries"],
        "performance_summary": required["performance_summary"],
        "audit_issues": required["audit_issues"],
        "audit_report": required["audit_report"],
        "latest_performance_report": required["performance_report"],
    }
    for name, path in manifest_paths.items():
        declared = manifest.get("files", {}).get(name, {})
        actual_hash = sha256(path)
        hash_ok = declared.get("sha256") == actual_hash
        manifest_checks[name] = {"hash_ok": hash_ok, "declared_rows": declared.get("rows")}
        if not hash_ok:
            errors.append(f"manifest_hash_mismatch:{name}")
    result["checks"]["manifest"] = manifest_checks

    if performance.get("schema_version") != "audit_v2":
        errors.append(f"wrong_performance_schema:{performance.get('schema_version')}")
    if ohlc.get("schema_version") != "ohlc_v1":
        errors.append(f"wrong_ohlc_schema:{ohlc.get('schema_version')}")
    if scan.get("schema_version") != "scan_v2":
        errors.append(f"wrong_scan_schema:{scan.get('schema_version')}")

    result["errors"] = errors
    result["warnings"] = warnings
    result["status"] = "passed" if not errors else "failed"
    REPORT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    if errors:
        print(f"Output verification FAILED — expected app_version={expected_version}")
        for error in errors:
            print(" -", error)
        return 1

    print("Output verification PASSED")
    print(f"Version: {expected_version}")
    print(f"Tracked entries: {entries_rows}")
    print(f"Summary rows: {summary_rows}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
