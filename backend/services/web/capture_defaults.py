"""Los defaults de captura de un cliente (portado de Vigil).

Viven en CÓDIGO, no en el `DEFAULT` de la columna, por la misma razón que las
reglas del clasificador: son testables, se revisan en un diff y se corrigen sin
tocar el esquema. En Vigil el DEFAULT de `client_settings` quedó congelado en su
migración 001 y hubo que reescribir a mano las filas que aún lo tenían (003).

En The Agency las columnas de `client_web_settings` (`default_ignore_selectors`,
`default_ignore_regexes`, `max_concurrency`, `sweep_weekdays`…) NO tienen
DEFAULT y son NULL hasta que alguien las cambia: NULL = "lo que diga este
módulo hoy". Corregir un default aquí corrige a todos los clientes que no lo
personalizaron, sin migración (``effective_settings`` en ``sweep.py``).

## Qué NO va aquí, y por qué

Un selector de poda mal elegido no genera ruido: genera **silencio**. Lo podado
desaparece de las cuatro dimensiones —texto, enlaces, HTML y las señales SEO del
body— sin dejar rastro en ninguna pantalla. Vigil sigue diciendo "sin cambios"
con la misma cara con la que lo diría si de verdad no hubiera ninguno, y eso es
lo único que esta herramienta no se puede permitir.

Por eso el listado es corto y solo contiene chrome de navegación, que ningún
cliente edita como contenido. Dos selectores estuvieron aquí y salieron el
24-jul-2026:

  `[aria-live]`  Se puso pensando en contadores que se anuncian solos. Pero
    Elementor marca `aria-live="polite"` cada `.swiper-wrapper`, y el tema de
    Fit Generation cada `.fg-flipcard__inner`. Medido en `/cafyd-online/`: 28
    nodos con `aria-live`, y las 25 cards de profesores dentro de uno — 1.039
    palabras de 6.614 invisibles. Un `.` añadido a mano en una card no lo
    detectó NINGUNA dimensión, ni siquiera "HTML crudo".

  `.carousel`  No casa un solo nodo en fitgeneration.es. WordPress y Elementor
    usan `swiper`. Protegía de un carrusel imaginario.

Y la lección que dejan: **el texto de un carrusel no cambia solo**. Lo que
cambia en cada render es el estado (clase `active`, `transform` en línea), y de
eso ya se encarga `_strip_volatile_attrs`. Podar el carrusel entero para
ahorrarse ese ruido cuesta dejar de vigilar lo que hay dentro, que suele ser
justo el contenido que el cliente edita.

Si un cliente concreto necesita podar más, se hace en SU configuración, donde se
ve, y no en el default que heredan todos.
"""
from __future__ import annotations

# Chrome de navegación: se repite en todas las páginas y nadie lo edita como
# contenido. Un cambio aquí es del tema, no de la página.
DEFAULT_IGNORE_SELECTORS: tuple[str, ...] = (
    "nav",
    "footer",
    "header",
    ".cookie-banner",
    "#onetrust-consent-sdk",
)

# Fechas, horas y «hace 3 horas»: cambian solos cada noche y no significan nada.
# Estos SUSTITUYEN por un token en vez de borrar (ver `_apply_ignore_regexes`),
# así que no ciegan nada: el texto de alrededor se sigue comparando.
DEFAULT_IGNORE_REGEXES: tuple[str, ...] = (
    r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}",
    r"\d{1,2}:\d{2}(:\d{2})?",
    r"(?i)\bhace\s+\d+\s+\w+",
)

# Resto de la captura y del barrido. NULL en `client_web_settings` = esto.
DEFAULT_MAX_CONCURRENCY = 6
DEFAULT_REQUEST_TIMEOUT_S = 20
DEFAULT_CRAWL_DELAY_MS = 300
DEFAULT_DIGEST_MIN_SEVERITY = "info"
DEFAULT_SWEEP_WEEKDAYS: tuple[int, ...] = (1, 2, 3, 4, 5)
DEFAULT_SWEEP_SUMMARY_TO_SLACK = True
