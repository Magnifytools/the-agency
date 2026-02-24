# Instrucciones: Evolución a PM Activo con IA

> **Para:** Claude Code trabajando en Agency Manager
> **Fecha:** 3 Feb 2026
> **Objetivo:** Transformar Agency Manager de CRUD pasivo a PM activo con IA

---

## ⚠️ ANTES DE EMPEZAR

```bash
pwd  # Debe mostrar: .../Código/agency-manager
ls   # Debe mostrar: backend/, frontend/, data/
```

---

## Estado actual (40%)

**Ya implementado:**
- CRUD clientes, tareas, categorías
- Auth JWT
- Cierre mensual con checklist
- Alertas financieras básicas
- Modelos TimeEntries, Invoices, AuditLogs (sin API)

**Lo que falta para ser PM activo:**
- Asistente IA proactivo
- Gestión de proyectos (no solo tareas sueltas)
- Comunicación y seguimiento
- Alertas inteligentes
- Reporting automático

---

## FUNCIONALIDADES A IMPLEMENTAR

### 1. ASISTENTE IA PROACTIVO (El corazón del PM)

#### Concepto
Un asistente que analiza el estado de clientes/proyectos y da recomendaciones proactivas. No espera a que le pregunten, avisa cuando algo necesita atención.

#### Tabla `pm_insights`
```sql
CREATE TABLE pm_insights (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id),

  -- Tipo de insight
  insight_type VARCHAR(50) NOT NULL,  -- 'deadline', 'stalled', 'overdue', 'followup', 'workload', 'suggestion'
  priority VARCHAR(20) NOT NULL,       -- 'high', 'medium', 'low'

  -- Contexto
  client_id UUID REFERENCES clients(id),
  project_id UUID REFERENCES projects(id),
  task_id UUID REFERENCES tasks(id),

  -- Contenido
  title VARCHAR(200) NOT NULL,
  description TEXT NOT NULL,
  suggested_action TEXT,

  -- Estado
  status VARCHAR(20) DEFAULT 'active',  -- 'active', 'dismissed', 'acted'
  dismissed_at TIMESTAMP,
  acted_at TIMESTAMP,

  -- Metadata
  generated_at TIMESTAMP DEFAULT NOW(),
  expires_at TIMESTAMP,  -- Algunos insights expiran

  created_at TIMESTAMP DEFAULT NOW()
);
```

#### Tipos de insights que genera

1. **Deadline próximo**
   - "⏰ La tarea 'Informe mensual Cliente X' vence en 2 días"
   - Trigger: tareas con due_date en próximos 3 días

2. **Proyecto estancado**
   - "⚠️ Cliente X no tiene actividad desde hace 15 días"
   - Trigger: cliente sin tareas actualizadas en X días

3. **Tarea vencida**
   - "🔴 Tienes 3 tareas vencidas con Cliente Y"
   - Trigger: tareas con due_date pasado y status != completed

4. **Seguimiento pendiente**
   - "📞 Hace 10 días que no contactas con Cliente Z"
   - Trigger: último log de comunicación > X días

5. **Carga de trabajo**
   - "📊 Esta semana tienes 12 tareas asignadas, 4 más que la semana pasada"
   - Trigger: análisis semanal de carga

6. **Sugerencia proactiva**
   - "💡 Cliente X lleva 3 meses, es buen momento para proponer ampliación"
   - Trigger: hitos temporales + análisis de contexto

#### Endpoint para generar insights (cron job o manual)
```
POST /api/pm/generate-insights
```

**Prompt para generar insights:**
```
Eres el PM asistente de una agencia SEO. Analiza el estado actual y genera insights accionables.

DATOS ACTUALES:
- Clientes activos: {clientes}
- Tareas pendientes: {tareas_pendientes}
- Tareas vencidas: {tareas_vencidas}
- Última actividad por cliente: {ultima_actividad}
- Comunicaciones recientes: {comunicaciones}

GENERA INSIGHTS:
Para cada situación que requiera atención, genera un insight con:
- tipo: deadline | stalled | overdue | followup | workload | suggestion
- prioridad: high | medium | low
- título: frase corta y clara
- descripción: contexto y datos
- acción_sugerida: qué hacer

Prioriza lo urgente. Sé específico con nombres y fechas.
Máximo 5-7 insights para no abrumar.

Formato JSON:
[
  {
    "type": "...",
    "priority": "...",
    "client_id": "..." or null,
    "title": "...",
    "description": "...",
    "suggested_action": "..."
  }
]
```

#### UI del Asistente

**Panel de Insights (Dashboard principal):**
- Lista de insights activos ordenados por prioridad
- Cada insight muestra: icono + título + descripción + botones [Actuar | Descartar]
- "Actuar" lleva a la tarea/cliente relevante
- "Descartar" marca como dismissed

**Widget flotante (opcional):**
- Icono en esquina con contador de insights pendientes
- Click abre panel lateral con insights

---

### 2. GESTIÓN DE PROYECTOS (no solo tareas sueltas)

#### Concepto
Actualmente solo hay tareas. Falta el nivel "Proyecto" que agrupa tareas y tiene fases/milestones.

#### Tabla `projects`
```sql
CREATE TABLE projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id UUID REFERENCES clients(id) ON DELETE CASCADE,

  name VARCHAR(200) NOT NULL,
  description TEXT,

  -- Tipo y template
  project_type VARCHAR(50),  -- 'seo_audit', 'content_strategy', 'linkbuilding', 'technical_seo', 'custom'

  -- Fechas
  start_date DATE,
  target_end_date DATE,
  actual_end_date DATE,

  -- Estado
  status VARCHAR(30) DEFAULT 'active',  -- 'planning', 'active', 'on_hold', 'completed', 'cancelled'
  progress_percent INTEGER DEFAULT 0,

  -- Financiero
  budget_hours DECIMAL(10,2),
  budget_amount DECIMAL(10,2),

  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);
```

#### Tabla `project_phases` (milestones)
```sql
CREATE TABLE project_phases (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,

  name VARCHAR(100) NOT NULL,
  description TEXT,
  order_index INTEGER NOT NULL,

  start_date DATE,
  due_date DATE,
  completed_at TIMESTAMP,

  status VARCHAR(20) DEFAULT 'pending',  -- 'pending', 'in_progress', 'completed'

  created_at TIMESTAMP DEFAULT NOW()
);
```

#### Modificar tabla `tasks`
```sql
ALTER TABLE tasks ADD COLUMN project_id UUID REFERENCES projects(id);
ALTER TABLE tasks ADD COLUMN phase_id UUID REFERENCES project_phases(id);
ALTER TABLE tasks ADD COLUMN depends_on UUID REFERENCES tasks(id);  -- Dependencia
```

#### Templates de proyecto
```json
{
  "seo_audit": {
    "name": "Auditoría SEO",
    "phases": [
      { "name": "Análisis técnico", "default_days": 5 },
      { "name": "Análisis de contenido", "default_days": 5 },
      { "name": "Análisis de enlaces", "default_days": 3 },
      { "name": "Informe y recomendaciones", "default_days": 3 }
    ],
    "default_tasks": [
      { "phase": 0, "title": "Crawl con Screaming Frog" },
      { "phase": 0, "title": "Revisar Core Web Vitals" },
      { "phase": 1, "title": "Análisis de thin content" },
      // ...
    ]
  },
  "content_strategy": { ... },
  "linkbuilding": { ... }
}
```

#### UI de Proyectos

**Lista de proyectos:**
- Filtros: cliente, estado, tipo
- Cards o tabla con: nombre, cliente, progreso %, fechas, estado

**Detalle de proyecto:**
- Header: nombre, cliente, fechas, estado, progreso
- Timeline/Gantt simple con fases
- Lista de tareas agrupadas por fase
- Panel lateral: resumen, horas, presupuesto

**Crear proyecto:**
- Seleccionar cliente
- Elegir template o crear desde cero
- Definir fechas
- Generar tareas automáticamente desde template

---

### 3. COMUNICACIÓN Y SEGUIMIENTO

#### Concepto
Log de todas las comunicaciones con clientes para saber cuándo fue el último contacto y qué se habló.

#### Tabla `communication_logs`
```sql
CREATE TABLE communication_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id UUID REFERENCES clients(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id),

  -- Tipo
  channel VARCHAR(30) NOT NULL,  -- 'email', 'call', 'meeting', 'whatsapp', 'slack', 'other'
  direction VARCHAR(10) NOT NULL,  -- 'inbound', 'outbound'

  -- Contenido
  subject VARCHAR(200),
  summary TEXT NOT NULL,

  -- Metadata
  contact_name VARCHAR(100),  -- Con quién hablaste del cliente
  occurred_at TIMESTAMP NOT NULL,

  -- Seguimiento
  requires_followup BOOLEAN DEFAULT false,
  followup_date DATE,
  followup_notes TEXT,

  created_at TIMESTAMP DEFAULT NOW()
);
```

#### UI de Comunicaciones

**En detalle de cliente:**
- Tab "Comunicaciones" con timeline de contactos
- Botón "+ Registrar comunicación"
- Filtros por canal, fecha

**Modal de registro:**
- Canal (dropdown)
- Dirección (enviado/recibido)
- Asunto
- Resumen (textarea)
- ¿Requiere seguimiento? + fecha

**Alertas de seguimiento:**
- El asistente IA detecta followups vencidos
- Genera insights tipo "followup"

---

### 4. ALERTAS INTELIGENTES

#### Configuración de alertas (tabla)
```sql
CREATE TABLE alert_settings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id),

  -- Umbrales
  days_without_activity INTEGER DEFAULT 14,
  days_before_deadline INTEGER DEFAULT 3,
  days_without_contact INTEGER DEFAULT 10,
  max_tasks_per_week INTEGER DEFAULT 15,

  -- Canales (futuro)
  notify_in_app BOOLEAN DEFAULT true,
  notify_email BOOLEAN DEFAULT false,

  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);
```

#### Tipos de alertas (generadas por el sistema)

| Tipo | Trigger | Prioridad |
|------|---------|-----------|
| `task_overdue` | due_date < hoy AND status != completed | high |
| `task_due_soon` | due_date en próximos X días | medium |
| `client_stalled` | última tarea actualizada hace > X días | medium |
| `client_no_contact` | última comunicación hace > X días | medium |
| `workload_high` | tareas asignadas > umbral | low |
| `project_behind` | progreso < esperado según fechas | high |

---

### 5. REPORTING AUTOMÁTICO

#### Concepto
Generar informes de estado por cliente o globales, automáticamente o bajo demanda.

#### Endpoint
```
POST /api/reports/generate
Body: {
  "type": "client_status" | "weekly_summary" | "project_status",
  "client_id": "..." (opcional),
  "project_id": "..." (opcional),
  "period": "week" | "month"
}
```

#### Prompt para generar informe de cliente
```
Genera un informe de estado para el cliente.

DATOS DEL CLIENTE:
- Nombre: {cliente.name}
- Proyectos activos: {proyectos}
- Tareas completadas este mes: {tareas_completadas}
- Tareas pendientes: {tareas_pendientes}
- Horas invertidas: {horas}
- Últimas comunicaciones: {comunicaciones}

FORMATO DEL INFORME:

## Resumen Ejecutivo
[2-3 frases con estado general]

## Progreso del Mes
- Tareas completadas: X
- Tareas en curso: X
- Horas dedicadas: X

## Logros Destacados
- [Logro 1]
- [Logro 2]

## Próximos Pasos
- [Tarea prioritaria 1]
- [Tarea prioritaria 2]

## Observaciones
[Notas o alertas relevantes]
```

#### UI de Reporting

**Página "Informes":**
- Botón "Generar informe"
- Seleccionar tipo + cliente/proyecto
- Preview del informe generado
- Acciones: Descargar PDF | Copiar | Enviar por email

**En detalle de cliente:**
- Botón "Generar informe" rápido

---

### 6. BRIEFING DIARIO (Quick Win)

#### Concepto
Al abrir la app, mostrar un resumen de qué hay que hacer hoy.

#### Endpoint
```
GET /api/pm/daily-briefing
```

#### Prompt
```
Genera el briefing diario para el usuario.

DATOS:
- Tareas para hoy: {tareas_hoy}
- Tareas vencidas: {tareas_vencidas}
- Reuniones/seguimientos pendientes: {followups}
- Insights activos: {insights}

FORMATO:

## Buenos días 👋

### 🎯 Prioridades de hoy
1. [Tarea más urgente]
2. [Tarea importante]
3. [Otra tarea]

### ⚠️ Requiere atención
- [Alerta o insight importante]

### 📅 Seguimientos pendientes
- [Cliente X - tema]

### 💡 Sugerencia del día
[Una recomendación proactiva]
```

#### UI
- Modal o sección en Dashboard que aparece al entrar
- Botón "Ver briefing" en header

---

## PRIORIDAD DE IMPLEMENTACIÓN

1. **Proyectos** (estructura base)
   - Tabla projects + phases
   - Modificar tasks para vincular
   - CRUD básico
   - Templates de proyecto

2. **Comunicaciones**
   - Tabla communication_logs
   - CRUD en detalle de cliente
   - Quick win, muy útil

3. **Asistente IA / Insights**
   - Tabla pm_insights
   - Endpoint de generación
   - UI de panel de insights
   - Briefing diario

4. **Alertas inteligentes**
   - Tabla alert_settings
   - Lógica de detección
   - Integrar con insights

5. **Reporting**
   - Endpoints de generación
   - UI de informes
   - Export PDF

---

## ENDPOINTS A CREAR

```
# Proyectos
GET    /api/projects
POST   /api/projects
GET    /api/projects/:id
PUT    /api/projects/:id
DELETE /api/projects/:id
GET    /api/projects/:id/tasks
POST   /api/projects/:id/phases
GET    /api/project-templates

# Comunicaciones
GET    /api/clients/:id/communications
POST   /api/clients/:id/communications
PUT    /api/communications/:id
DELETE /api/communications/:id

# PM Asistente
GET    /api/pm/insights
POST   /api/pm/generate-insights
PUT    /api/pm/insights/:id/dismiss
PUT    /api/pm/insights/:id/act
GET    /api/pm/daily-briefing

# Alertas
GET    /api/settings/alerts
PUT    /api/settings/alerts

# Reporting
POST   /api/reports/generate
GET    /api/reports/:id
```

---

## NOTAS TÉCNICAS

- Usar Claude API para generación de insights, briefings e informes
- Cron job diario (o al login) para generar insights
- Guardar insights en BD para no regenerar constantemente
- Los insights expiran (algunos) para no acumular ruido
- El briefing se puede cachear por día

---

*Documento generado: 3 Feb 2026*
