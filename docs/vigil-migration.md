# Corte de Vigil → The Agency (Webs, fase 3)

Vigil (`/Código/Vigil`, vigil.magnifytools.com) se absorbe en The Agency. La
fase 2 trajo la vigilancia de cambios (`web_watches`, `web_changes`… y el job
`web_sweep`); esta guía mueve los datos y apaga Vigil sin perder el histórico
ni mandar avisos falsos al Slack de los clientes.

Piezas:

- `python -m backend.scripts.import_vigil` (fase 3a): copia `vigil.db` a las
  tablas `web_*` conservando los ids de Vigil. Detalle en su docstring.
- `python -m backend.scripts.web_calibrate` (fase 3a): un barrido por cliente
  que compara y guarda, pero no avisa a Slack.

**Nada de esto se hace sin David.** Los pasos que tocan producción o apagan
algo van marcados con **[OK de David]** y necesitan su visto bueno explícito en
ese momento.

---

## Antes de empezar

- La fase 2b (frontend de Webs) está desplegada y `WEB_SWEEP_ENABLED=false` en
  Railway (es el valor por defecto). Con el job apagado no corre ni el barrido
  diario ni "Comprobar ahora".
- Cada cliente de Vigil tiene su pareja en The Agency con el mismo slug en
  Ajustes del cliente (`Client.vigil_slug`, el mismo enlace que usa hoy el
  resumen de Vigil). Los que no la tengan se
  resuelven en el paso 4 con `--map slug=client_id` o `--skip slug`.
- Si alguien ya dio de alta URLs a mano en Webs → Cambios para un cliente de
  Vigil, la importación se negará a pisarlas ("ya existe en The Agency con otro
  id"). Archívalas/bórralas antes o salta ese cliente.
- Ten a mano `VIGIL_SECRET_KEY` (variables del servicio de Vigil en Railway).
  Hace falta para descifrar los webhooks de Slack. No la pegues en el chat ni
  en la línea de órdenes.

## 1. Desplegar la 2b con el barrido apagado [OK de David]

Merge de la 2b a `main`. Comprobar en Railway que `WEB_SWEEP_ENABLED` no está a
`true`: la lista de URLs de un cliente (`GET /api/clients/{id}/web/watches`)
devuelve `enabled: false`. El monitor de
caídas (`UPTIME_ENABLED`) es independiente y puede seguir encendido.

## 2. Congelar Vigil [OK de David]

1. En Vigil, revisar (marcar como revisados) los cambios pendientes que ya no
   importan. Lo que se importe sin revisar abrirá la incidencia
   `client_web_critical_change` en la bandeja de The Agency si es crítico.
2. En el servicio de Vigil en Railway: `CRON_ENABLED=false` y redeploy. Desde
   ese momento Vigil no barre ni avisa.
3. No usar "Comprobar" en Vigil a partir de aquí: lo que escriba después de la
   descarga no llega a The Agency.

## 3. Descargar `vigil.db`

Una copia consistente (no el fichero a pelo: puede tener datos en el `-wal`).
Cualquiera de las dos:

- **Backup de admin**: con sesión de admin en Vigil, `POST /api/admin/backup`
  (hace un `VACUUM INTO` comprimido) y luego `GET /api/admin/backup/latest`.
  Descomprimir con `gunzip`.
- **Railway**: `railway ssh` en el servicio de Vigil y
  `python -c "import sqlite3; sqlite3.connect('vigil.db').execute(\"VACUUM INTO '/tmp/vigil-corte.db'\")"`
  (con la ruta real de `VIGIL_DB_PATH`, en el volumen; la imagen puede no traer
  el binario `sqlite3`); luego bajar ese fichero.

Guardar la copia fuera del repo (no se sube a git: lleva los webhooks cifrados).

## 4. Importar (primero simulacro) [OK de David]

Desde un portátil, contra la URL **pública** del Postgres de The Agency:

```bash
cd the-agency
export DATABASE_URL='postgresql+asyncpg://…'   # DATABASE_PUBLIC_URL de Railway, con +asyncpg
export VAULT_KEY='…'                            # el de The Agency en Railway (o SECRET_KEY si no hay VAULT_KEY)
# VIGIL_SECRET_KEY: mejor que la pida el script (no se muestra al teclearla)

backend/venv/bin/python -m backend.scripts.import_vigil --sqlite ~/vigil-corte.db --dry-run
```

- El simulacro hace la importación entera dentro de una transacción y la
  deshace: los recuentos son los reales. Imprime por tabla (en Vigil, nuevas,
  ya estaban, huérfanas, antes, después) y por cliente, más los avisos.
- Un slug sin pareja aborta y dice cuál. Resolver con `--map slug=client_id` o
  `--skip slug` (repetibles) y repetir el simulacro.
- `VAULT_KEY`/`SECRET_KEY` tiene que ser **el de producción**: el webhook se
  re-cifra con él. Con la clave de desarrollo el script se niega.

Cuando el simulacro sale limpio, la buena: la misma orden sin `--dry-run`. Es una
sola transacción con `ON CONFLICT (id) DO NOTHING`: si falla no deja nada a
medias y repetirla no duplica.

Qué hace con los ajustes del cliente: si el cliente ya tiene ajustes web en The
Agency (Slack del monitor de caídas, User-Agent), **mandan esos**; sólo se
rellenan las columnas vacías y el webhook de Vigil sólo entra si allí no había
ninguno. Lo que en Vigil era el valor por defecto entra como NULL (= lo que diga
`capture_defaults.py`).

Comprobar después en Webs → Cambios: las URLs, el histórico de cambios con quién
los revisó (los de usuarios que no existen en The Agency salen con su nombre de
Vigil) y, en Ajustes del cliente, que el Slack aparece configurado.

## 5. Barrido de calibración, sin Slack [OK de David]

La primera pasada desde The Agency sale por **otra IP** (la de Railway del
servicio de Agency) y con otro proceso. Si el WAF o el CDN de un cliente sirven
otra cosa a esa IP (bloqueo, país, versión de caché), todas sus URLs
"cambiarían" a la vez, y eso no debe llegar al canal del cliente.

Dentro del servicio de The Agency (que es donde se va a mirar a diario):

```bash
railway ssh   # servicio de The Agency
python -m backend.scripts.web_calibrate            # todos
python -m backend.scripts.web_calibrate --client-id 12
```

Cada cliente es un barrido `manual` con `notify=False`: compara contra la última
captura importada de Vigil, guarda lo que encuentre y no llama a Slack. No gasta
el barrido programado del día ni depende de `WEB_SWEEP_ENABLED`. La bandeja de
incidencias sí ve los críticos.

Revisar en Webs → Cambios:

- **Lo esperado**: casi nada. El `watch_state` importado lleva los hashes, el SEO
  y los enlaces de la última noche de Vigil, con el mismo extractor.
- **Un cliente entero "cambiado"** o "host cortado" en la salida: casi seguro
  WAF/geo/caché, no el cliente. Abrir un cambio y mirar el diff. Si es un
  bloqueo, ir al paso 7 antes de encender nada para ese cliente.
- **HTML cambiado en todas las URLs con `watch_html`**: puede ser la versión de
  `lxml` (otra serialización). Marcar como revisado; la siguiente noche ya
  compara HTML de The Agency contra HTML de The Agency.

Marcar como revisado lo que sea ruido de la calibración. Se puede repetir el
paso cuantas veces haga falta.

## 6. Encender el barrido [OK de David]

`WEB_SWEEP_ENABLED=true` en Railway y redeploy. Desde la siguiente
`WEB_SWEEP_LOCAL_TIME` (06:30 Madrid), un cliente por ciclo según su calendario,
con aviso a su Slack. Vigilar los primeros días que `web_sweep_runs.notify_status`
sea `sent`/`skipped_no_changes` y no `failed`.

## 7. Listas blancas de WAF [OK de David; lo hace David]

Algunos clientes dejaron pasar la IP de Vigil en su WAF (p. ej. el Cloudflare de
Fit Generation). Hay que cambiarla por la IP de salida de The Agency. Railway
sólo da IPs de salida estáticas en el plan **Pro**; en otro plan la IP puede
cambiar en cada despliegue y la lista blanca por IP no vale (alternativa: regla
por User-Agent, que es configurable por cliente en `client_web_settings.user_agent`).

---

## Retirada de Vigil

### 3b — Quitar la integración del código (un PR, sin tocar la BD)

Cuando lleve unos días barriendo bien desde The Agency:

- Fuera: job `vigil` (`job_catalog`, `background_tasks`), `services/vigil_service.py`,
  `api/routes/vigil.py`, `VIGIL_API_URL` / `VIGIL_SERVICE_KEY` de `config.py`, el
  bloque de Vigil en `services/client_status.py` (el estado ya lo dan las URLs
  propias), y en el front el bloque de Vigil de la ficha/Resultados, del estado y
  el campo `vigil_slug` de Ajustes del cliente.
- **Las columnas y tablas se quedan** (`vigil_summary`, `clients.vigil_slug`):
  el ORM deja de usarlas, pero P12 las sigue exigiendo hasta la 3c. Borrar ORM y
  datos en el mismo despliegue rompería el arranque de la versión anterior si
  hubiera que volver atrás.
- `scripts/import_vigil.py` se queda (por si hay que repetir la importación) y
  lee `clients.vigil_slug` con SQL, no con el ORM; si la columna ya no existe
  (tras la 3c), sólo vale `--map`. Se puede borrar, con sus tests y
  `tests/fixtures/vigil/`, cuando Vigil esté apagado.
- El lock 13 (job `vigil`) no se reutiliza.

### 3c — Migración de retirada (otro PR, después de la 3b en producción)

Un paso de retirada con su contrato, como `phase0_retirement_schema.py`:
contrato `schema_versions/vigil_retirement_v1.json` con
`drop_tables: ["vigil_summary"]` y `drop_columns: {"clients": ["vigil_slug"]}`
(el índice `uq_clients_vigil_slug` cae con la columna), módulo con
`Retirement(...)`, añadirlo a `RETIREMENTS` en `schema_baseline` y al final de
`MIGRATIONS` en `deployment_schema`. Probar subida con datos e instalación limpia
(ver `test_phase0_retirement_schema.py`).

### Apagar Vigil [OK de David en cada paso]

1. Parar el servicio de Vigil en Railway (no borrarlo todavía).
2. Tras ~30 días sin echarlo de menos: borrar el volumen (lleva `vigil.db` y sus
   backups) y el servicio. Conservar fuera de Railway la copia del paso 3.
3. Vercel: redirección `vigil.magnifytools.com` → `agency.magnifytools.com/web`
   (los enlaces viejos de Slack apuntan a Vigil; los cambios importados conservan
   su id, pero la ruta es otra, así que basta con llevar a Webs).
4. Archivar el repo de Vigil en GitHub.
5. `/Código/CLAUDE.md`: quitar Vigil de puertos y de la tabla de proyectos.
