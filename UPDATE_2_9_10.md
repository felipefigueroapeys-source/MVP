# UPDATE 2.9.11 — OHLC LBank-first + backfill histórico ampliado

## Objetivo
Lograr validaciones OHLC reales o preliminares para los 10 mejores candidatos actuales y 10 candidatos históricos pendientes.

## Cambios
- Agrega soporte OHLC LBank Spot vía `/v1/kline.do`.
- Prioriza el exchange original de la señal.
- Orden de fuentes por defecto: LBank → Binance → Bybit → CoinGeckoRange.
- Si Binance responde 451 o Bybit 403, la fuente se marca como bloqueada durante la corrida.
- Agrega fallback `CoinGeckoRange` por `coin_id` para backfill histórico preliminar.
- BTC simultáneo usa el mismo exchange cuando es posible; si no, fallback a las otras fuentes.

## Calidad de datos
- LBank/Binance/Bybit: OHLC real de exchange.
- CoinGeckoRange: velas sintéticas por puntos de precio. Útil para cruce histórico preliminar, no para validar mechas intradía con precisión.

## Próxima prueba
Después de subir esta versión a GitHub, ejecutar manualmente y revisar:

```text
outputs/ohlc/latest_ohlc_report.json
outputs/ohlc/ohlc_validation.csv
outputs/diagnostics/timing_report.json
```
