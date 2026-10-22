-- 003 — La poda por defecto cegaba el contenido que había que vigilar.
--
-- El 24-jul-2026 David añadió un punto a mano en una card de profesor de
-- /cafyd-online/, purgó la caché y pidió una comprobación. Vigil dijo que no
-- había cambios. No era la caché ni el flag de "HTML crudo": el selector por
-- defecto `[aria-live]` se llevaba las cards por delante ANTES de calcular
-- ningún hash, así que el cambio no existía para ninguna de las cuatro
-- dimensiones.
--
-- Elementor marca `aria-live="polite"` cada `.swiper-wrapper` y el tema de Fit
-- Generation cada `.fg-flipcard__inner`. En esa página son 28 nodos y las 25
-- cards viven dentro de uno: 1.039 palabras de 6.614, invisibles.
-- El otro selector, `.carousel`, no casa un solo nodo en el site.
--
-- Un falso positivo se ve y se corrige. Este era un falso NEGATIVO: Vigil
-- decía "sin cambios" exactamente igual que cuando de verdad no los hay.

-- =============================================================================
-- 1. Reescribir el default heredado
-- =============================================================================
-- Solo se toca la fila que aún tenga el valor original, byte a byte. Si alguien
-- ya lo editó a mano, su configuración manda y esta migración la respeta.
--
-- El DEFAULT de la columna se queda como está: SQLite no sabe cambiarlo sin
-- recrear la tabla, y recrear la que guarda el webhook cifrado por un valor por
-- defecto no compensa. A partir de ahora el default lo pone el código
-- (`app/services/capture_defaults.py`), que es quien inserta en
-- `client_settings` al crear un cliente. La constante de la columna ya no
-- decide nada.
update client_settings
   set default_ignore_selectors =
         '["nav","footer","header",".cookie-banner","#onetrust-consent-sdk"]',
       updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
 where default_ignore_selectors =
       '["nav","footer","header",".cookie-banner","#onetrust-consent-sdk","[aria-live]",".carousel"]';

-- Y en los watches que copiaron el default a su override.
update watches
   set ignore_selectors =
         '["nav","footer","header",".cookie-banner","#onetrust-consent-sdk"]',
       updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
 where ignore_selectors =
       '["nav","footer","header",".cookie-banner","#onetrust-consent-sdk","[aria-live]",".carousel"]';

-- =============================================================================
-- 2. Que el arreglo no dispare una avalancha de avisos falsos
-- =============================================================================
-- Dejar de podar 1.039 palabras cambia el hash de contenido de TODAS las URLs, y
-- acotar los enlaces al contenido cambia el de enlaces. Sin esto, el primer
-- barrido tras el deploy mandaría a Slack un "contenido cambiado" por cada URL
-- del cliente. Un digest que grita cuando no ha pasado nada se deja de leer, y a
-- partir de ahí la herramienta ya no sirve para nada.
--
-- `classify()` ya sabe callarse cuando no hay con qué comparar: sin
-- `last_snapshot_id` no recupera el texto anterior y no clasifica contenido; con
-- `links_json` a NULL no clasifica enlaces. Una noche de silencio en esas dos
-- dimensiones a cambio de no envenenar el canal.
--
-- El SEO NO se toca: `seo_json` y `hash_seo` siguen ahí, así que title,
-- canonical, robots y H1 se siguen vigilando esta misma noche. Que es lo que de
-- verdad no puede quedarse sin cobertura ni un día.
--
-- Los snapshots tampoco se borran: solo se suelta el puntero al último. El
-- histórico y las capturas fijadas siguen intactos.
update watch_state
   set last_snapshot_id = NULL,
       links_json       = NULL,
       updated_at       = strftime('%Y-%m-%dT%H:%M:%SZ', 'now');

-- =============================================================================
-- 3. Avisar cuando la sección vigilada deja de existir
-- =============================================================================
-- A partir de ahora `content_selector` acota texto, enlaces y HTML: sirve para
-- decir "vigila solo esta sección". Eso abre una forma nueva de la misma ceguera
-- que arregla esta migración: el cliente renombra la clase, el selector deja de
-- casar y Vigil pasa a mirar otra cosa sin decir nada.
--
-- Cuando eso ocurre se vigila la página entera (mirar de más se lee y se
-- descarta; mirar de menos es silencio) y se enciende esta marca, que la ficha
-- de la URL enseña igual que enseña "puede que necesite render JS".
alter table watch_state add column scope_missed integer not null default 0;
