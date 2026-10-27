"""One catalog for scheduler gates and the admin status view. No stored flags."""
from dataclasses import dataclass

from backend.config import settings
from backend.core.modules import is_enabled
from backend.services.job_runtime import JobSpec


@dataclass(frozen=True)
class JobDefinition:
    spec: JobSpec
    label: str
    description: str
    paused_reason: str | None = None

    @property
    def enabled(self):
        return self.paused_reason is None


def job_definitions() -> tuple[JobDefinition, ...]:
    return (
        JobDefinition(JobSpec("incidents", 1, 30), "Revisar alertas accionables",
                      "Comprueba tareas, proyectos y resúmenes para cada destinatario autorizado.",
                      None if settings.INCIDENTS_ENABLED else "La revisión automática de alertas está desactivada."),
        # The delivery spec is a status identity, never an exclusive worker lock.
        JobDefinition(JobSpec("deliveries", 2, 5), "Procesar entregas",
                      "Comprueba la cola. La confirmación de cada envío figura en su recibo.",
                      None if settings.DELIVERY_WORKER_ENABLED else "El procesamiento de entregas está pausado."),
        JobDefinition(JobSpec("engine", 3, max(1, settings.ENGINE_SYNC_INTERVAL_HOURS) * 3600, 900, retry_seconds=900),
                      "Actualizar datos de Engine", "Actualiza las métricas, resúmenes y alertas de clientes vinculados.",
                      None if settings.ENGINE_SYNC_ENABLED and settings.ENGINE_API_URL and settings.ENGINE_SERVICE_KEY
                      else "La sincronización de Engine está desactivada o falta su conexión."),
        JobDefinition(JobSpec("holded", 4, 86400, 900, retry_seconds=1800), "Actualizar datos de Holded",
                      "Sincroniza contactos, facturas y gastos de la integración configurada.",
                      None if settings.HOLDED_API_KEY else "Holded no está conectado."),
        JobDefinition(JobSpec("advanced_reset", 5, 86400, daily=True), "Continuar tareas avanzadas",
                      "Devuelve a En curso las tareas avanzadas en días anteriores."),
        JobDefinition(JobSpec("recurrence", 6, 300), "Generar tareas recurrentes",
                      "Revisa las reglas elegibles de hoy. Las pausas y reglas pendientes se consultan en sus plantillas."),
        JobDefinition(JobSpec("scheduled_communications", 8, 60), "Preparar avisos programados",
                      "Revisa las programaciones. Cada aviso conserva su motivo de espera y su recibo de envío.",
                      None if settings.SCHEDULED_COMMUNICATIONS_ENABLED else "Los avisos programados están pausados."),
        JobDefinition(JobSpec("calendar", 9, 900, 600), "Actualizar calendarios",
                      "Sincroniza los calendarios conectados de las personas activas.",
                      None if settings.GOOGLE_CLIENT_ID and settings.SCHEDULED_COMMUNICATIONS_ENABLED
                      else "La sincronización de calendarios no está configurada o los avisos están pausados."),
        JobDefinition(JobSpec("retention", 10, 86400), "Limpiar registros antiguos",
                      "Aplica la retención de logs, notificaciones antiguas y eventos de Google Calendar pasados; conserva las incidencias actuales."),
        JobDefinition(JobSpec("inbox_classification", 11, 30, 180), "Clasificar notas de Inbox",
                      "Recupera notas pendientes y propone asociaciones. Nunca crea tareas sin tu decisión."),
        JobDefinition(JobSpec("gsc", 12, 86400, 1800, retry_seconds=3600), "Importar Search Console",
                      "Guarda los datos diarios finales de las propiedades de los clientes activos.",
                      None if settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET
                      else "Google OAuth no está configurado."),
        # Lock 17 (15/16 son de Webs). Usa la cuenta que `gsc` asigna a cada propiedad.
        JobDefinition(JobSpec("gsc_detail", 17, 86400, 3600, retry_seconds=3600),
                      "Importar consultas y páginas de Search Console",
                      "Guarda 120 días de cifras diarias por consulta y por página de las propiedades de los clientes activos.",
                      None if settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET
                      else "Google OAuth no está configurado."),
        JobDefinition(JobSpec("ga4", 14, 86400, 1800, retry_seconds=3600), "Importar Google Analytics 4",
                      "Guarda sesiones, conversiones y tráfico desde IA de las propiedades GA4 de los clientes activos.",
                      None if settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET
                      else "Google OAuth no está configurado."),
        # Lock 13: era el job ``vigil`` (retirado en la fase 3b). No reutilizarlo:
        # una réplica con la versión anterior aún podría tomarlo durante el despliegue.
        # Cada 60 s mira sólo las URLs que tocan (cada 5 min; 60 s si fallan).
        # Lock 15; el 16 queda reservado para web_sweep y el 17 para gsc_detail.
        JobDefinition(JobSpec("uptime", 15, 60, timeout_seconds=150, retry_seconds=60), "Comprobar las webs de los clientes",
                      "Mira si responden las URLs vigiladas y avisa de caídas y recuperaciones (bandeja y Slack del cliente).",
                      None if settings.UPTIME_ENABLED else "El monitor de caídas está apagado (UPTIME_ENABLED)."),
        # Lock 16. Cada 60 s: primero lo pedido a mano ("Comprobar ahora") y, a
        # partir de WEB_SWEEP_LOCAL_TIME, el barrido diario de UN cliente por ciclo.
        JobDefinition(JobSpec("web_sweep", 16, 60, timeout_seconds=900, retry_seconds=300),
                      "Vigilar cambios en las webs de los clientes",
                      "Compara SEO, texto, enlaces y maquetación de las URLs vigiladas y avisa en el Slack de cada cliente.",
                      None if settings.WEB_SWEEP_ENABLED
                      else "La vigilancia de cambios está apagada (WEB_SWEEP_ENABLED)."),
        # Lock 18. Diario: caducidad de certificado y dominio (con UPTIME_ENABLED) y
        # robots.txt + sitemap (con WEB_SWEEP_ENABLED). Ver services/web/health.py.
        JobDefinition(JobSpec("web_health", 18, 86400, timeout_seconds=1800, daily=True, retry_seconds=3600),
                      "Revisar dominio, certificado, robots.txt y sitemap",
                      "Mira cuándo caducan el certificado y el dominio de cada web vigilada, y el robots.txt y el sitemap de las webs con vigilancia de cambios.",
                      None if settings.UPTIME_ENABLED or settings.WEB_SWEEP_ENABLED
                      else "El monitor de caídas y la vigilancia de cambios están apagados."),
        # Lock 19. Cada 60 s: enlaces de tareas recién completadas y reintentos.
        JobDefinition(JobSpec("publish_checks", 19, 60, timeout_seconds=150, retry_seconds=60),
                      "Revisar páginas publicadas",
                      "Cuando se completa una tarea con enlace a la web del cliente, comprueba que la página responde, es indexable y tiene canonical, title y description.",
                      None if settings.PUBLISH_CHECK_ENABLED
                      else "La revisión tras publicar está apagada (PUBLISH_CHECK_ENABLED)."),
    )
