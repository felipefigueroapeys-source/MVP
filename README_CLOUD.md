# Ejecución en GitHub Actions — 2.9.8

El workflow está en `.github/workflows/scanner_daily.yml`.

- Horario configurado: `0 13 * * *` en UTC.
- GitHub puede iniciar cron con retraso; el evento, run ID y horario esperado quedan registrados en `outputs/diagnostics/timing_report.json`.
- Después de ejecutar el scanner, `scripts/verify_outputs.py` comprueba versión, esquema, filas, hashes y coherencia temporal.
- Solo los resultados verificados se envían al repositorio.
- El artifact se genera incluso si la verificación falla, para poder revisar el diagnóstico.

La segunda corrida post-sesión América queda pendiente hasta confirmar primero el comportamiento real del horario automático.
