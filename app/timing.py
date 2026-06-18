from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import csv
import json
import time


class TimingDiagnostics:
    """Medición simple de tiempos por etapa, expresada principalmente en minutos."""

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        self.enabled = bool(config.get("enabled", True))
        self.output_dir = Path(config.get("output_dir", "outputs/diagnostics"))
        self.print_summary = bool(config.get("print_summary", True))
        self.started_at = datetime.now(timezone.utc)
        self.finished_at: datetime | None = None
        self._t0 = time.perf_counter()
        self.steps: list[dict[str, Any]] = []
        self.metadata: dict[str, Any] = {}

    @contextmanager
    def step(self, name: str, **extra: Any):
        if not self.enabled:
            yield
            return

        start_perf = time.perf_counter()
        start_at = datetime.now(timezone.utc)
        error = None

        try:
            yield
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            end_perf = time.perf_counter()
            end_at = datetime.now(timezone.utc)
            seconds = round(end_perf - start_perf, 3)
            minutes = round(seconds / 60, 3)
            row = {
                "step": name,
                "started_at": start_at.isoformat(),
                "finished_at": end_at.isoformat(),
                "seconds": seconds,
                "minutes": minutes,
                "error": error or "",
            }
            row.update(extra)
            self.steps.append(row)

    def add_metadata(self, key: str, value: Any) -> None:
        if self.enabled:
            self.metadata[key] = value

    def finish(self) -> dict[str, Any]:
        self.finished_at = datetime.now(timezone.utc)
        return self.report()

    def report(self) -> dict[str, Any]:
        finished = self.finished_at or datetime.now(timezone.utc)
        total_seconds = round(time.perf_counter() - self._t0, 3)
        return {
            "enabled": self.enabled,
            "started_at": self.started_at.isoformat(),
            "finished_at": finished.isoformat(),
            "total_seconds": total_seconds,
            "total_minutes": round(total_seconds / 60, 3),
            "steps": self.steps,
            "metadata": self.metadata,
        }

    def write(self) -> dict[str, str]:
        if not self.enabled:
            return {}

        self.output_dir.mkdir(parents=True, exist_ok=True)
        report = self.finish()

        json_path = self.output_dir / "timing_report.json"
        csv_path = self.output_dir / "timing_report.csv"

        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        fieldnames = ["step", "started_at", "finished_at", "minutes", "seconds", "error"]
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for step in self.steps:
                writer.writerow({k: step.get(k, "") for k in fieldnames})

        return {"timing_report_json": str(json_path), "timing_report_csv": str(csv_path)}

    def format_summary_lines(self) -> list[str]:
        if not self.enabled or not self.print_summary:
            return []

        report = self.report()
        lines = [
            "⏱ Diagnóstico de tiempos",
            f"   Total Python: {report['total_minutes']:.2f} min",
        ]

        for step in self.steps:
            lines.append(f"   {step['step']}: {float(step.get('minutes', 0)):.2f} min")

        perf = self.metadata.get("performance_report")
        if isinstance(perf, dict):
            lines.append(
                "   Performance: "
                f"nuevos={perf.get('tracked_new', 0)}, "
                f"actualizados={perf.get('updated_entries', 0)}, "
                f"total={perf.get('entries_total', 0)}"
            )

        return lines
