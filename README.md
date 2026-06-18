# Spot Sector Scanner MVP 2.9.8 AUDIT

Aplicativo base en Python para escanear sectores cripto, puntuar categorías y clasificar tokens spot USDT/USDC.

## Qué incluye esta versión

- Configuración editable en `config.yaml`.
- Escala visual de colores de 3 y 5 puntos.
- Modelos base: Sector, TokenCandidate, ScanResult.
- Motor de contexto BTC/ETH.
- Motor de puntuación sectorial.
- Motor de puntuación de tokens.
- Servicio CoinGecko inicial.
- Servicio Binance público inicial para validar pares spot.
- UI de consola con Rich.
- Exportación CSV/XLSX.

## Instalación

```bash
cd SpotSectorScanner_MVP1
pip install -r requirements.txt
python main.py
```

## Nota

Esta primera versión está diseñada para validar arquitectura y lógica.
No ejecuta operaciones. No es asesoría financiera. Solo genera candidatos para análisis técnico posterior.
## Cambios MVP 1.1

- Se agrega validación de pares spot en LBank.
- Se crea `PairValidator` para revisar exchanges en orden: Binance → LBank.
- Se agrega pausa entre consultas CoinGecko para reducir errores 429.
- Se deduplican tokens que aparecen en múltiples categorías.
- Se refuerza la regla excluyente: sin par spot USDT/USDC validado, el token no puede ser B/A/A+.
## Cambios MVP 1.2

- Se actualiza versión a `0.1.2`.
- Se agrega validación de pares spot en Bybit.
- Orden de validación de exchanges: Binance → Bybit → LBank.
- Se mantiene LBank como respaldo para tokens no disponibles en Binance/Bybit.
## Cambios MVP 1.3

- Pulido del scanner CoinGecko:
  - reintentos automáticos ante errores 429;
  - filtro de categorías por `excluded_category_ids` y `excluded_category_keywords`;
  - filtro mínimo de market cap y volumen por sector;
  - boost a sectores preferidos configurables;
  - gates de calidad para impedir falsos positivos con bajo market cap, bajo volumen, sin spot o 24h demasiado negativo.
- Base opcional de CoinMarketCap:
  - nuevo `services/coinmarketcap_service.py`;
  - requiere variable de entorno `CMC_API_KEY` o `coinmarketcap.api_key` en `config.yaml`;
  - en MVP 1.3 CoinMarketCap aporta referencia sectorial; la extracción de tokens CMC queda para MVP 1.4.
## Cambios MVP 1.4

- Se actualiza versión a `0.1.4`.
- Se agrega spinner visual después de `Ejecutando scan inicial...`.
- El `latest_scan.json` registra estado de CoinMarketCap:
  - `coinmarketcap_api_configured`;
  - `coinmarketcap_categories_loaded`;
  - `coinmarketcap_status`.
- La exportación de sectores incluye `source` para diferenciar `CoinGecko` vs `CoinMarketCap`.
## Cambios MVP 1.5

- Se actualiza versión a `0.1.5`.
- Se agregan iconos y líneas separadas en la consola:
  - `📡 Fuentes objetivo del scanner`
  - `🔎 Ejecutando scan inicial...`
  - `📡 Fuentes consultadas`
  - `🧭 Modo mercado: defensivo_selectivo 🟡`
- Se mantiene una línea en blanco antes de las notas de contexto.
- La tabla de sectores ahora muestra la columna `Fuente`.
## Cambios MVP 1.6

- Se actualiza versión a `0.1.6`.
- Se excluyen por defecto categorías que estaban generando ruido operativo:
  - `Tokenized Stock`;
  - `Tokenized Private Credit`;
  - `Ondo Tokenized Assets`;
  - `Telegram Apps`.
- La exclusión queda en `config.yaml`, por lo que puede revertirse o ajustarse sin tocar código.
## Cambios MVP 1.7

- Se actualiza versión a `0.1.7`.
- Se excluye `Synthetic Dollar`, porque estaba quedando como único sector tras limpiar categorías ruidosas.
- Se amplía el scanner:
  - `max_sectors: 10`
  - `tokens_per_sector: 50`
  - `coingecko_pause_seconds: 1.5`
- Se agrega fallback de sectores preferidos para evitar que el scanner quede con 1 solo sector:
  - RWA
  - AI
  - DePIN
  - Gaming
  - Layer
  - Solana
  - BNB
  - DeFi
## Cambios MVP 1.7.1

- Corrección de error: faltaba el método `_apply_sector_fallback_if_needed` en `AppController`.
- Se mantiene la lógica de fallback de sectores preferidos de la MVP 1.7.
## Cambios MVP 1.8

- Se actualiza versión a `0.1.8`.
- Se corrige el color visual de los tokens:
  - `A+ Prioridad alta` = 🟩
  - `A Candidata fuerte` = 🟢
  - `B Vigilancia` = 🟡
  - `C Descartada` = 🔴
- El color ahora depende de la categoría final, no del score bruto.
- Se mantiene la tabla de sectores.
- En sectores, la columna `Estado` queda reemplazada por `Uso = ✅ Considerado`.
- Se agrega línea en prosa con los sectores considerados.
- Se agrega columna `Acción` en la tabla de tokens:
  - `🚀 Revisar técnico`
  - `🟢 Revisar entrada`
  - `🟡 Esperar pullback`
  - `🟡 Vigilancia`
  - `🟠 Extendido`
  - `🔴 No perseguir`
  - `⛔ Descartar`
## Cambios MVP 1.9

- Se actualiza versión a `0.1.9`.
- El ranking ahora se ordena por categoría final:
  - A+ primero;
  - A después;
  - B después;
  - C al final.
- Esto evita que tokens `C Descartada` con score bruto alto aparezcan arriba.
- El export CSV/XLSX/JSON ahora incluye:
  - `visual_color`;
  - `action`.
- `latest_scan.json` incluye `token_summary` dentro de `market_context`.
## Cambios MVP 1.9.1

- Corrección de error: faltaba insertar correctamente `_sort_tokens_operationally` dentro de `AppController`.
- Se mantiene el orden operativo por categoría final.
## Cambios MVP 2.0

- Se actualiza versión a `2.0.0`.
- Se agrega configuración visual en `config.yaml`:
  - `show_discarded_in_console`;
  - `max_tokens_console`;
  - `group_tokens_by_category`;
  - `show_token_summary`;
  - `show_operational_reason`.
- La consola oculta por defecto los tokens `C Descartada`.
- Los tokens descartados siguen exportándose en `CSV`, `XLSX` y `JSON`.
- Se agrega resumen visual de distribución A+/A/B/C.
- La tabla de tokens se separa por secciones:
  - `🟩 A+ PRIORIDAD ALTA`;
  - `🟢 A CANDIDATAS FUERTES`;
  - `🟡 B VIGILANCIA`.
- Se agrega columna `Motivo` para explicar la acción operativa.
## Cambios MVP 2.1

- Se actualiza versión a `2.1.0`.
- Se elimina lenguaje de análisis técnico desde la consola.
- Nuevas acciones operativas:
  - `🚀 Prioridad operativa`;
  - `🟢 Candidato activo`;
  - `🟡 Esperar retroceso`;
  - `🟡 Vigilar`;
  - `🔴 No perseguir`;
  - `⛔ Descartar`.
- Se reemplaza `Revisar técnico` por `Prioridad operativa`.
- Se separan activos base/referencia en consola:
  - BTC, ETH, BNB, SOL, XRP, ADA, BCH, LTC, AVAX, SUI, HBAR, APT, ETC, ALGO, CRO, PI, XAUT, PAXG.
- Los activos base siguen exportándose normalmente.
## Cambios MVP 2.1.1

- Corrección de consistencia: las acciones exportadas en `latest_scan.json`, `ranking.csv` y `ranking.xlsx` ahora usan el mismo lenguaje operativo que la consola.
- Se reemplazan etiquetas antiguas:
  - `🚀 Revisar técnico` → `🚀 Prioridad operativa`;
  - `🟢 Revisar entrada` → `🟢 Candidato activo`;
  - `🟡 Esperar pullback` → `🟡 Esperar retroceso`;
  - `🟡 Vigilancia` → `🟡 Vigilar`.
## Cambios MVP 2.2

- Se actualiza versión a `2.2.0`.
- Se agrega bloque `operational_rules` en `config.yaml`:
  - `warn_30d_above`;
  - `cap_to_b_if_30d_above`;
  - `active_requires_7d_positive`;
  - `top_operational_max_per_group`.
- Se agrega `🎯 Top operativo` en consola.
- Se diferencian nuevas acciones:
  - `🟡 Rebote táctico`;
  - `⚠️ Exceso 30D`.
- Se mejora el motivo operativo:
  - `24h/7D/30D alineados`;
  - `Rebote con 7D negativo`;
  - `Fuerza previa, retroceso actual`;
  - `30D >150%`.
- Los exports ahora incluyen:
  - `operational_reason`;
  - `operational_bucket`.
## Cambios MVP 2.2.1

- Corrección de error: faltaba insertar correctamente `_build_top_operational` dentro de `AppController`.
- Se mantiene el bloque `🎯 Top operativo`.
- Se mantiene la exportación de `operational_reason` y `operational_bucket`.
## Cambios MVP 2.2.2

- Corrección de error: faltaba inicializar `self.operational_rules` dentro de `AppController`.
- Se agrega fallback seguro con `getattr(self, "operational_rules", {})` para evitar errores si el atributo no existe.
- Se mantiene la lógica de `🎯 Top operativo`, `operational_reason` y `operational_bucket`.
## Cambios MVP 2.3

- Se actualiza versión a `2.3.0`.
- Se agrega bloque `alert_rules` en `config.yaml`.
- Se agregan alertas múltiples independientes de la acción principal:
  - `🟠 24h extendido`;
  - `🔴 24h extremo`;
  - `⚠️ 7D muy alto`;
  - `⚠️ 30D alto`;
  - `⚠️ 30D extremo`;
  - `🔴 caída 24h fuerte`.
- Se agrega columna `Alertas` en consola.
- Los exports ahora incluyen `alerts`.
- `latest_scan.json` ahora incluye `alert_summary` dentro de `market_context`.
- La consola muestra `⚠️ Resumen alertas`.
## Cambios MVP 2.4

- Se actualiza versión a `2.4.0`.
- Se agrega alerta suave:
  - `🟡 24h cerca de extensión`, por defecto sobre 12% y hasta 15%.
- Se agrega `priority_tier`:
  - `T1 limpio`;
  - `T2 válido con alerta`;
  - `T3 vigilancia`;
  - `T4 riesgo alto`.
- Se agrega columna `Tier` en consola.
- Los exports ahora incluyen `priority_tier`.
- `latest_scan.json` ahora incluye `priority_tier_summary`.
- Se agrega resumen visual `🏷️ Priority tiers` en consola.
## Cambios MVP 2.5

- Se actualiza versión a `2.5.0`.
- Se agrega módulo `trend_signals`.
- Se integra `CoinGecko Trending` como señal externa de interés.
- Se agregan campos en consola y exports:
  - `trend_signal`;
  - `trend_score`;
  - `trend_sources`.
- Por defecto, `trend_signal` es informativo:
  - no modifica `score`;
  - no cambia `Categoría`;
  - no altera `Tier`.
- Configuración nueva:
  - `trend_signals.enabled`;
  - `trend_signals.coingecko_trending`;
  - `trend_signals.apply_to_score`;
  - `trend_signals.points_coingecko_trending`;
  - `trend_signals.max_trending_tokens`.
## Cambios MVP 2.6

- Se actualiza versión a `2.6.0`.
- Se agrega expansión sectorial controlada.
- Sectores recomendados incorporados:
  - DePIN;
  - Restaking / Liquid Restaking;
  - Payments / Settlement;
  - Data Availability / Modular Blockchain;
  - Oracle / Data / Middleware.
- Sectores opcionales incorporados:
  - Gaming / GameFi;
  - SocialFi;
  - Telegram Apps;
  - Meme / Memes / Meme Coins.
- Se agrega `sector_group` en exports:
  - `core`;
  - `optional`;
  - `noisy`;
  - `other`.
- Se agrega columna `Grupo sector` en consola.
- Esta versión clasifica sectores; no sube automáticamente tokens por pertenecer a sectores opcionales o ruidosos.
## Versión estable 2.6.7

Punto estable operativo del Spot Sector Scanner.

Incluye:
- CoinGecko categorías + tokens + Trending.
- CoinMarketCap categorías activo.
- Exchanges principales: Binance, Bybit, LBank, OKX, Gate, KuCoin, MEXC y HTX.
- Clasificación A+ / A / B / C.
- Acción, motivo, alertas, tier y trend.
- Activos base integrados dentro de sus categorías reales.
- Orden visual B → A → A+.
- Mejor candidato al final de cada bloque.
- Lista final operativa en prosa:
  - 🟩 Prioritarios;
  - 🟢 Fuertes;
  - 🟡 Vigilados.
## MVP 2.8 — Performance Tracker

Agrega forward testing operativo del scanner.

Objetivo:
- registrar el precio de referencia al momento del scan;
- guardar candidatos relevantes;
- comparar rendimiento hipotético posterior a 24h, 48h, 72h, 7D, 14D y 30D;
- generar resumen por grupo de tracking.

Archivos nuevos:
- `outputs/performance/tracked_entries.csv`
- `outputs/performance/performance_summary.csv`
- `outputs/performance/latest_performance_report.json`

Grupos iniciales:
- `A+`
- `A_T1`
- `A_T2`
- `B_TREND`
- `B_HIGH_SCORE`
- `T4_CONTROL`

Importante:
- Esto no ejecuta compras.
- No hace análisis técnico.
- El `reference_price` es solo precio de referencia del scan para medir rendimiento posterior.


## MVP 2.9 — Cloud Runner GitHub Actions

Agrega ejecución automática en GitHub Actions.

Incluye:
- `.github/workflows/scanner_daily.yml`
- `README_CLOUD.md`
- ejecución manual con `workflow_dispatch`;
- ejecución diaria programada a las 14:00 UTC, equivalente aproximadamente a 10:00 AM Chile continental cuando Chile está en UTC-4;
- guardado de `outputs/` como artifact;
- commit automático de `outputs/` al repositorio cuando hay cambios.

Secret requerido:
- `CMC_API_KEY`
## MVP 2.9.3 — Performance Tracker corregido

Correcciones incluidas:
- `main.py` ejecuta `PerformanceTracker` después de exportar outputs.
- Si el tracker falla, no cae el scanner completo.
- `controller.py` guarda `price_usd` desde `current_price`.
- El `reference_price` del performance tracker usa el precio ya obtenido en el scan.
- Disminuye la demora por consultas extra token por token.
- Mejora la disponibilidad de `reference_price_available = yes`.

Estado validado:
- Scanner genera outputs normales.
- Performance tracker genera:
  - `outputs/performance/tracked_entries.csv`
  - `outputs/performance/performance_summary.csv`
  - `outputs/performance/latest_performance_report.json`
- Segunda corrida validada con 23/23 nuevos registros con precio de referencia disponible.
## MVP 2.9.4 — Timing Diagnostics

Agrega telemetría simple para identificar cuellos de botella antes de optimizar a ciegas.

Archivos nuevos:
- `app/timing.py`
- `outputs/diagnostics/timing_report.json`
- `outputs/diagnostics/timing_report.csv`

Etapas medidas:
- `init_ui_controller`
- `run_scan_total`
- `render_console`
- `export_outputs`
- `performance_tracker`
- `write_diagnostics`

Objetivo:
- confirmar si la demora viene del scanner/fuentes, del performance tracker, de exports o de otra etapa;
- mantener la lógica de selección intacta;
- permitir diagnóstico posterior desde los artifacts de GitHub Actions.
## MVP 2.9.5 — Performance Optimized + Goals

Optimiza el Performance Tracker y agrega una línea final de metas.

Cambios:
- El tracker usa primero los precios del scan actual para actualizar registros antiguos.
- Evita consultas externas token por token cuando el precio ya está disponible.
- Consulta externo solo como respaldo.
- Agrega estadísticas internas:
  - `prices_from_scan`
  - `external_price_fetches`
  - `external_price_success`
  - `external_price_failed`
- Agrega resumen de metas:
  - diario 2-5%;
  - semanal 2-5%;
  - mensual 10-20%.
- El diagnóstico de tiempos ahora informa minutos además de segundos.

Salida esperada:
`🎯 Metas rendimiento: diario 2-5%: X/N | semanal 2-5%: X/N | mensual 10-20%: X/N`

## MVP 2.9.6 — Metas por temporalidad

Ajusta el Performance Tracker para evaluar metas mínimas por horizonte, en vez de bandas cerradas.

Metas:
- Diario 24h: éxito mínimo `>= +2%`; zona ideal `+2% a +5%`; sobre-meta `> +5%`.
- 3 días 72h: éxito mínimo `>= +5%`; zona ideal `+5% a +10%`; sobre-meta `> +10%`.
- Semanal 168h: éxito mínimo `>= +10%`; zona ideal `+10% a +15%`; sobre-meta `> +15%`.
- Mensual 720h: éxito mínimo `>= +10%`; zona ideal `+10% a +20%`; sobre-meta `> +20%`.

También agrega:
- mediana limpia por grupo;
- promedio limpio excluyendo outliers extremos;
- promedio bruto visible;
- conteo de outliers por horizonte;
- metas por grupo dentro de `performance_summary.csv`.

Nota: la medición actual evalúa el precio al corte exacto de cada horizonte. No detecta si la meta fue alcanzada intraperiodo antes del corte.
## MVP 2.9.7 — Target Hit Tracker

Agrega seguimiento de objetivos alcanzados para simular mejor una operación spot con TP programado.

Nuevas columnas en `tracked_entries.csv`:
- `target_2pct_hit`, `target_2pct_first_horizon`, `target_2pct_hit_time_utc`, `target_2pct_return_pct`
- `target_5pct_hit`, `target_5pct_first_horizon`, `target_5pct_hit_time_utc`, `target_5pct_return_pct`
- `target_10pct_hit`, `target_10pct_first_horizon`, `target_10pct_hit_time_utc`, `target_10pct_return_pct`
- `target_15pct_hit`, `target_15pct_first_horizon`, `target_15pct_hit_time_utc`, `target_15pct_return_pct`
- `target_20pct_hit`, `target_20pct_first_horizon`, `target_20pct_hit_time_utc`, `target_20pct_return_pct`

Nueva salida:
`🎯 Target hit observado: +2%: X/N | +5%: X/N | +10%: X/N | +15%: X/N | +20%: X/N`

Importante:
Esta medición detecta targets en los cortes del scanner. No detecta máximos intraperiodo entre corridas. Para simular una salida automática exacta al tocar +2% o +5%, en el futuro se necesita OHLC intraperiodo o aumentar frecuencia del scanner.

## MVP 2.9.8 — Auditoría e integridad de medición

Esta versión inicia una línea base auditada. Conserva los históricos anteriores, crea un respaldo automático y los marca como `legacy_unverified`; no los mezcla con las conclusiones nuevas hasta que puedan validarse.

### Correcciones principales

- Identidad por `CoinGecko ID` y `asset_key`, no solo por ticker.
- Validación de precio del par spot contra CoinGecko para detectar símbolos ambiguos.
- Exclusión token-level de stablecoins, wrappers, recibos de staking y fondos/tokenized stocks no comparables con el objetivo del scanner.
- Horizonte exacto con tolerancia configurable: un precio tardío ya no rellena 24h, 48h y 72h simultáneamente.
- Horizontes fuera de ventana quedan como `missed_window`.
- Señales repetidas quedan agrupadas por episodio y cooldown; se conservan, pero no cuentan como entradas independientes.
- `Esperar retroceso`, `Extendido`, `No perseguir` y similares se registran como observaciones, no como entradas teóricas.
- Consulta de precios externos en batch por CoinGecko ID.
- Retornos brutos y netos estimados, usando un costo ida/vuelta configurable de 0,25%.
- Máximo y mínimo observado en cada ejecución, además de target hit observado +2%, +5%, +10%, +15% y +20%.
- Verificación automática de versión, conteo de filas, hashes y coherencia temporal antes de guardar resultados en GitHub.

### Archivos nuevos

```text
outputs/performance/audit_report.json
outputs/performance/audit_issues.csv
outputs/performance/output_manifest.json
outputs/performance/verification_report.json
outputs/performance/backups/
```

### Cómo interpretar el primer run 2.9.8

Es normal que las métricas auditadas comiencen con muestra pequeña o cero. Los registros antiguos quedan preservados, pero excluidos de la línea limpia. Las conclusiones por 24h comienzan a ser válidas tras la primera medición dentro de 24h ±8h; 72h, semanal y mensual requieren su tiempo natural.

### Límite que permanece

`Target hit observado` solo ve los precios en las corridas del scanner. Una segunda corrida post-sesión América mejorará la aproximación. Para saber si una orden TP habría sido tocada exactamente entre corridas todavía se requiere OHLC intraperiodo.


## MVP 2.9.11 — OHLC intradía token + BTC

Agrega una capa de validación intradía liviana para no sobrecargar el scanner:

- Selecciona solo los 10 mejores candidatos del scan actual.
- Selecciona hasta 10 mejores señales históricas pendientes para backfill inicial.
- Descarga velas públicas de Binance y Bybit, sin API key.
- Valida `TOKENUSDT` y `BTCUSDT` en el mismo rango temporal.
- Calcula:
  - `mfe_pct` máxima excursión favorable.
  - `mae_pct` máxima excursión adversa.
  - targets intradía `+2%`, `+5%`, `+10%`, `+15%`, `+20%`.
  - tiempo hasta target.
  - retornos 24h y 72h.
  - retorno relativo contra BTC.

Archivos nuevos:

```text
outputs/ohlc/ohlc_candidates_current.csv
outputs/ohlc/ohlc_candidates_historical.csv
outputs/ohlc/ohlc_validation.csv
outputs/ohlc/latest_ohlc_report.json
```

Esta versión responde mejor la pregunta: “¿tocó realmente el objetivo intradía o solo lo vimos en una foto del scanner?”.


## MVP 2.9.11 — OHLC LBank-first + backfill histórico ampliado

Esta versión mantiene el objetivo de validar solo los mejores candidatos para no volver lento el scanner:

- top 10 candidatos actuales;
- top 10 candidatos históricos pendientes;
- OHLC token intradía;
- OHLC BTC simultáneo para retorno relativo.

Cambio principal: el validador OHLC ahora intenta primero el exchange original de la señal. Como muchas señales operables vienen de LBank, se agrega soporte para `GET /v1/kline.do` de LBank antes de caer a Binance o Bybit. Si Binance devuelve 451 o Bybit devuelve 403, la fuente se marca como bloqueada para la corrida y no se insiste innecesariamente.

También se agrega `CoinGeckoRange` como fallback histórico preliminar por `coin_id`. Este fallback no entrega OHLC real; crea velas sintéticas con open=high=low=close a partir de puntos de precio. Sirve para cruzar retornos históricos y retorno relativo contra BTC, pero las conclusiones de target intradía deben priorizar fuentes de exchange.

Archivos esperados:

```text
outputs/ohlc/ohlc_validation.csv
outputs/ohlc/ohlc_candidates_current.csv
outputs/ohlc/ohlc_candidates_historical.csv
outputs/ohlc/latest_ohlc_report.json
```

## MVP 2.9.11 — Clean rebuild / version consistency

Versión de saneamiento completo para evitar mezclas parciales del repositorio. Incluye workflow con limpieza de `token.py` raíz, `requirements.txt` válido, salida fatal si el scan falla y verificación estricta contra la versión declarada en `config.yaml`.
