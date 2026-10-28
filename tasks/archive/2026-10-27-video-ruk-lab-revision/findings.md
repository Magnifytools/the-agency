# Revisión del vídeo de Ruk Lab (Cristian Rico), segunda pasada — 27 oct 2026

Vídeo: https://www.youtube.com/watch?v=IuCGcT-l_u0 (63 min). La primera pasada
(18 oct, sesión 7c2c0c9b) lo redujo a 20 ideas en el plan "The Agency 2.0". Esta
pasada lo cruza minuto a minuto con el código de HOY de The Agency y de Anvil.

## Por qué hacía falta

- Tareas, backlog, recurrencia, cronómetro y vista del día se resolvieron en UNA
  fila como "Ya existe", sin mirar el detalle de lo que enseña (min. 33-41).
- CRM: "No por ahora, Leads oculto por falta de uso". No se miró qué aporta en el
  vídeo (aviso a Discord, seguimientos dentro de las tareas, embudo entre etapas,
  panel de operaciones con oportunidades).
- Informe mensual: "Hecho" con 4 totales. El del vídeo (min. 48) es otra cosa.
- Contenidos, tono, CTAs y WordPress se mandaron a The Engine, hoy congelado. Lo
  que toca ahora es Anvil.
- Accesos (min. 56) y el onboarding con accesos (min. 57) no se miraron.

Ya cubierto por el plan de intuitividad (`2026-10-27-intuitividad/`), NO repetir:
@menciones y aviso de comentarios, aviso al revisor al pasar a "En revisión",
"vence mañana", orden manual y "Mover a…" en Mi agenda, panel lateral.

## Tareas y recurrencia (Agency)

| Vídeo | Hoy | Hueco |
|---|---|---|
| Aplicar una plantilla a una tarea (KW research): crea los pasos, cada paso es tarea con su SOP | Plantillas de PROYECTO (`projects.py:633`); SOP sólo en recurrentes (`procedure_text`) | No hay plantillas de tarea ni biblioteca de procedimientos reutilizable |
| Cada paso tiene estado, responsable y fecha | Subtareas = `TaskChecklist` con responsable y fecha, sin estado ni agenda | La subtarea asignada a otro no le sale en Mi agenda |
| SOP: objetivo, quién/cuándo, herramientas (enlace a la plantilla), pasos | `procedure_text` + `procedure_url` | Sin biblioteca por rol/categoría; sólo vive dentro de la recurrente |
| Recurrencia fiable ("en ClickUp unos martes salía y otros no") | Idempotente (lock + recibo único) | Si el job no corre un día, esa repetición se pierde (no recupera); genera en festivos; sin "último día hábil", varios días por semana, trimestral |
| Seguimiento al ENTREGAR ("completada, pero que el cliente revise X") | `waiting` sólo para tareas no terminadas | No se puede cerrar una tarea y dejar un seguimiento colgando de ella |
| Vistas globales "por revisar" y "listas para compartir" | Sólo por cliente (`client-overview.tsx`) | Sin vista global para quien entrega |
| Informe semanal de horas por persona y proyecto | `weekly_report_service`, a mano, sin proyecto | Ni automático ni por proyecto |
| "El miércoles trabajé 31 h: se me quedó un contador" | Recorte silencioso a 8 h (`time_entries.py:675,794`) | Sin aviso de cronómetro olvidado |
| Ausencias del equipo (RR. HH.) | Festivos sí; vacaciones no | Capacidad no descuenta ausencias |

## CRM (Agency)

Existe entero pero oculto (`core/modules.py:36`, `AGENCY_HIDDEN_MODULES`): etapas
new→won/lost, actividades, valor, probabilidad, convertir lead→cliente.
Huecos frente al vídeo:
- Ningún aviso al entrar un lead; sólo se crean a mano (ni formulario web, ni
  webhook, ni desde Por aclarar, ni MCP).
- Los seguimientos de lead no van a Mi agenda ni a la campana (sólo un widget del
  dashboard, que además pide el permiso `leads` cuando el backend exige `growth`).
- Embudo: recuento y valor por etapa. Sin conversión entre etapas ni tiempo en
  etapa (no se guarda cuándo entró en cada una) ni tasa de cierre.
- Bug: el valor ponderado suma ganados y perdidos (`leads.py:123-127`).
- Aceptar o convertir una propuesta no marca el lead como ganado; ganar un lead
  crea sólo el cliente (sin contactos, proyecto ni alta).

## Informes mensuales (Agency)

Flujo de hoy: "Para entregar" → Generar (la IA redacta hecho / necesitamos /
próximo desde tareas y seguimientos) → editor → PDF / enlace del cliente → marcar
entregado. Bloques de código: SEO (`digest_seo.py`) y GA4 (`digest_ga4.py`).

Bloque SEO hoy: clics, impresiones, CTR y posición del mes frente al anterior +
una línea interanual SÓLO de clics. GA4: visitas, conversiones e IA; el
interanual se calcula (`ga4_service.py:372`) y no se pinta.

Lo que enseña el vídeo y no está:
- Top consultas y top URLs del mes; páginas que crecen y que bajan.
- Oportunidades (consultas en posiciones ~8-20).
- Contenidos publicados en el mes y cómo van.
- Marca frente a sin marca (ya lo calcula Control SEO con `brand_terms`).
- Escritorio frente a móvil (NO se importa: GSC se pide sin `device`).
- Interanual completo (impresiones, posición; GA4).
- Bing (no merece la pena hoy).
Los datos de las primeras cuatro ya están en `gsc_query_daily/gsc_page_daily`
(120 días) y `gsc_query_monthly` (16 meses). Restricción: el detalle de Search
Console no puede ir a la IA (`test_el_detalle_de_search_console_no_llega_a_la_ia`):
el bloque nuevo se pinta con código, como el actual, y no entra en el prompt.

## Anvil

Alcance fijado en `docs/audits/2026-10-09/PLAN-MEJORA.md`: termina en el briefing;
redacción y revisión siguen en Notion. Por eso editor, publicar en WordPress y
pantalla de aprobación del cliente están fuera A PROPÓSITO.

Bloqueo previo a cualquier idea: rama `codex/anvil-improvements` con 1.446
ficheros sin commitear; de M01-M22 sólo M01 en producción; aceptación del piloto
0/8.

| Vídeo | Anvil | Nota |
|---|---|---|
| Tono por cliente | EXISTE (`services/brand.py`, en todas las skills) | R4 lo amplía |
| CTAs por cliente | PARCIAL: `offers` con URL; `cta_block` sólo en vídeo | Elegir CTA en el brief de post |
| Niveles de conciencia | PARCIAL: tofu/mofu/bofu | Suficiente |
| Términos de marca | NO; Agency sí (`clients.brand_terms`) | Una sola fuente: Agency |
| Calendario de contenidos | PARCIAL: lista/tablero por fase, sin rejilla de mes | |
| Gráfica GSC con líneas de publicación | PARCIAL: medición por pieza, sin gráfica | Encaja en "Qué ha pasado" de Agency |
| Oportunidades / bot diario | PARCIAL: por clúster y en decay; propuestas a mano | |
| Decay → cola de actualización | EXISTE | |
| Categorizador de keywords con IA | PARCIAL: agrupación por SERP y embeddings | Falta "pego 1.000 keywords" |
| Scripts de IA por lotes | NO | Claude + Sheets lo cubre |
| Comprobar enlaces del brief en el texto | NO (el validador existe) | Barato sobre el validador |
| MCP | NO (API `/v1` sólo canon) | |
| Integración con Agency | NO; decidido 22 oct: sólo un enlace por cliente | Revisar si se quieren las publicaciones en Agency |

## Accesos (¿un 1Password dentro de Agency?)

Hoy: secreto cifrado en servidor (Fernet, `VAULT_KEY`), compartir por persona,
registro de ver/copiar, 30/min, se oculta a los 30 s, fuera del Deshacer y del MCP.

Falta para sustituir a 1Password:
- **Segundo factor al entrar en Agency: no hay.** Con todas las contraseñas de
  clientes dentro, es requisito previo.
- Códigos 2FA (TOTP) de las cuentas compartidas.
- Autorrelleno desde la extensión de Chrome propia.
- Generador de contraseñas y aviso de repetidas o filtradas (HIBP por k-anonimato).
- Importar CSV de 1Password / Bitwarden / Chrome.
- Notas cifradas (hoy van en claro) y portapapeles que se vacía.
- Compartir por cliente o por rol, no sólo persona a persona.
- Salida de alguien: lista de lo que vio para rotarlo (el registro ya lo tiene).
- Enlace de un solo uso para que el CLIENTE entregue sus accesos (onboarding del vídeo).
Límite que no cambia: no es cifrado de extremo a extremo; con la BD y `VAULT_KEY`
se lee todo.
