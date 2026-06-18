# Actualización 2.9.8 AUDIT

## Por qué la auditoría se aplica ahora

El último conjunto recibido mostró simultáneamente:

- reporte de performance con 1.015 entradas declaradas;
- archivos históricos que no siempre coinciden con ese conteo;
- lógica de metas todavía antigua;
- tracker consumiendo la mayor parte del tiempo total;
- cerca de la mitad de las consultas externas fallidas;
- posibilidad de mezclar tickers ambiguos y de rellenar horizontes tardíos.

Seguir ajustando el score sobre esa base podía producir sobreajuste. Por eso la 2.9.8 corrige primero la medición y deja el rediseño de scores por horizonte para cuando exista una muestra auditada suficiente.

## Migración

1. Reemplazar el proyecto de GitHub por el contenido de esta carpeta.
2. No borrar `outputs/performance/tracked_entries.csv`.
3. Ejecutar una vez manualmente desde Actions.
4. El sistema crea respaldo automático en `outputs/performance/backups/`.
5. Confirmar que el workflow termine en el paso `Verify version and output consistency`.
6. Descargar el artifact y comprobar que `latest_performance_report.json` diga:

```text
app_version: 2.9.8
schema_version: audit_v2
```

## Decisión aplazada

La separación `Score_D1`, `Score_3D`, `Score_7D` y `Score_30D` no se implementa todavía. Debe calibrarse usando datos limpios de la 2.9.8 para no consolidar sesgos de la base legacy.
