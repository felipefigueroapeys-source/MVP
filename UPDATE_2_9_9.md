# Spot Sector Scanner MVP 2.9.9 — OHLC intradía token + BTC

Objetivo: agregar las dos capas prioritarias definidas por Felipe:

1. OHLC intradía del token.
2. OHLC simultáneo de BTC.

La implementación limita el costo del scan: por cada corrida solo baja OHLC para los 10 mejores candidatos actuales y hasta 10 señales históricas pendientes.

## Fuentes

- Binance Spot `GET /api/v3/klines`.
- Bybit Spot `GET /v5/market/kline`.

No usa API keys.

## Nuevos módulos

- `services/market_data_client.py`
- `app/ohlc_validator.py`

## Nuevos outputs

- `outputs/ohlc/ohlc_candidates_current.csv`
- `outputs/ohlc/ohlc_candidates_historical.csv`
- `outputs/ohlc/ohlc_validation.csv`
- `outputs/ohlc/latest_ohlc_report.json`

## Métricas

- `mfe_pct`
- `mae_pct`
- `target_2_intraday_hit`
- `target_5_intraday_hit`
- `target_10_intraday_hit`
- `target_15_intraday_hit`
- `target_20_intraday_hit`
- `target_X_hours_to_hit`
- `btc_return_24h_pct`
- `btc_return_72h_pct`
- `relative_return_24h_pct`
- `relative_return_72h_pct`
- `max_relative_return_pct`

## Nota

La primera corrida abrirá base actual y hará backfill histórico limitado. Las señales actuales todavía no tendrán 24h completas; quedarán como `pending_min_age` hasta que exista edad suficiente.
