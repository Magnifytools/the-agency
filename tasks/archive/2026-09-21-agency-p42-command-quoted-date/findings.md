# Hallazgos

- `origin/main` c336f5d: la expresión de reprogramación divide por el primer `para` incluso dentro de un título entrecomillado.
- Línea base: `test_commands.py` con PostgreSQL real, 31 aprobadas.
- La regresión HTTP con «Informe para cliente» y «Visita al cliente» falló antes del arreglo: ambos recibos quedaron en `failed` en lugar de `executed`.
- Con el parser corregido, las 33 pruebas de comandos pasan; los casos existentes cubren fecha ambigua, `sin fecha` y título sin comillas.
