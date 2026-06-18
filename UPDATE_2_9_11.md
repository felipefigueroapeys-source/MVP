# UPDATE 2.9.11 — Clean rebuild / version consistency

Esta versión recompone el paquete completo para evitar mezclas parciales entre 2.9.9, 2.9.10 y archivos corruptos del repositorio.

## Correcciones

- `app.version` actualizado a `2.9.11` en `config.yaml`.
- Workflow limpia `token.py` raíz si existe, para no bloquear `pip`.
- Workflow muestra la versión real leída desde `config.yaml` antes de correr el scanner.
- `requirements.txt` limpio, solo con dependencias válidas.
- `main.py` ahora termina con `exit code 1` si falla el scan, evitando que el verificador use outputs viejos.
- Verificador imprime la versión esperada cuando detecta outputs cruzados.
- Se mantiene OHLC LBank-first + fallback Binance/Bybit/CoinGeckoRange.

## Instalación recomendada

Reemplazar el repo completo con el contenido de este ZIP. No aplicar archivo por archivo sobre una mezcla antigua.

