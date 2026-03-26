# Agency PM AutoResearch Program

> Análisis autónomo del estado de proyectos, tareas y equipo.
> Loop: fetch datos → analizar → generar alerts/recomendaciones → auto-evaluar

## Objetivo

Actuar como PM inteligente: detectar problemas antes de que sean crisis,
identificar oportunidades de mejora, y generar acciones concretas.

## Datos disponibles (via Agency API)

| Fuente | Endpoint | Datos |
|--------|----------|-------|
| Dashboard | `/api/dashboard/overview` | KPIs: clientes activos, tareas, horas, budget |
| Dashboard | `/api/dashboard/today` | Tareas del día |
| Tareas | `/api/tasks?status=X` | Tareas por estado |
| Timer | `/api/timer/active` | Timer activo |
| Time entries | `/api/time-entries` | Registros de tiempo |
| Clientes | `/api/clients` | Lista de clientes |
| Proyectos | `/api/projects` | Proyectos activos |
| Inbox | `/api/inbox/count` | Items sin procesar |
| Insights | `/api/pm/insights` | Insights generados |

## Proceso por iteración

### Iteración 1: Estado general
- Fetch dashboard overview + today tasks
- Detectar: tareas vencidas, clientes sin actividad, inbox lleno
- Hallazgo: "X tareas vencidas, Y clientes sin interacción en 2 semanas"

### Iteración 2: Análisis de tiempo
- Fetch time entries últimos 7 días
- Detectar: distribución de horas por cliente, ratio tiempo/facturación
- Hallazgo: "El 80% del tiempo va a cliente X pero factura el 20%"

### Iteración 3: Proyectos estancados
- Fetch proyectos + tareas por proyecto
- Detectar: proyectos sin tareas en progreso, sin time entries recientes
- Hallazgo: "Proyecto Z no tiene actividad en 10 días"

### Iteración 4: Carga de trabajo
- Fetch tareas asignadas por usuario
- Detectar: desequilibrio de carga, burnout potencial
- Hallazgo: "Nacho tiene 15 tareas activas, David 3"

### Iteración 5: Recomendaciones
- Compilar hallazgos
- Generar: acciones priorizadas para la semana
- Output: "Top 3 cosas que hacer esta semana"

## Criterios de calidad

Score 1-10:
- **Accionable** (3 pts): dice qué hacer, no solo qué pasa
- **Con datos** (3 pts): números concretos
- **Urgente** (2 pts): ¿requiere acción esta semana?
- **Impacto** (2 pts): ¿afecta a facturación/cliente/equipo?

## Output
- `findings.json`: hallazgos con score
- `weekly_brief.md`: resumen semanal para David
