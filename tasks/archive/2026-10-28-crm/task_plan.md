# CRM: reactivar y completar el Pipeline (28 oct 2026)

Decisión de David: reactivarlo y completarlo (análisis Ruk Lab).

1. Reactivar: quitar "leads" de los módulos ocultos (backend y frontend). El
   Buffer ("growth") y Propuestas siguen ocultos.
2. Arreglos: el valor ponderado sólo cuenta leads abiertos; el widget del
   dashboard pide el permiso real ("growth", no "leads").
3. Historial de etapas (`lead_status_history`, migración `lead_status_history_v1`,
   relleno con la etapa actual en el alta): embudo con cuántos llegan a cada
   etapa, conversión a la siguiente, días en cada etapa y tasa de cierre.
4. Avisos: lead nuevo → campana de los admins y de quien lo lleva; seguimiento
   vencido → incidencia `lead_followup_due`; seguimientos en Mi agenda.
5. Entrada: desde Por aclarar ("Lead") y por webhook de formulario
   (`POST /api/public/leads`, token `LEADS_WEBHOOK_TOKEN`; sin token, 404).

Fuera: propuesta aceptada → ganado (Propuestas está oculto y nunca se usó).
