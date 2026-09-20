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
        JobDefinition(JobSpec("overdue_automations", 7, 86400, daily=True, run_on_startup=False), "Revisar reglas de tareas vencidas",
                      "Comprueba las reglas del módulo de automatizaciones.",
                      None if is_enabled("automations") else "El módulo de automatizaciones está desactivado."),
        JobDefinition(JobSpec("scheduled_communications", 8, 60), "Preparar avisos programados",
                      "Revisa las programaciones. Cada aviso conserva su motivo de espera y su recibo de envío.",
                      None if settings.SCHEDULED_COMMUNICATIONS_ENABLED else "Los avisos programados están pausados."),
        JobDefinition(JobSpec("calendar", 9, 900, 600), "Actualizar calendarios",
                      "Sincroniza los calendarios conectados de las personas activas.",
                      None if settings.GOOGLE_CLIENT_ID and settings.SCHEDULED_COMMUNICATIONS_ENABLED
                      else "La sincronización de calendarios no está configurada o los avisos están pausados."),
        JobDefinition(JobSpec("retention", 10, 86400), "Limpiar registros antiguos",
                      "Aplica la retención de logs y notificaciones antiguas; conserva las incidencias actuales."),
        JobDefinition(JobSpec("inbox_classification", 11, 30, 180), "Clasificar notas de Inbox",
                      "Recupera notas pendientes y propone asociaciones. Nunca crea tareas sin tu decisión."),
    )
