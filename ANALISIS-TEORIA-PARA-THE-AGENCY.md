# Análisis de Recursos Teóricos para The Agency

## Contexto

David está construyendo "The Agency", una plataforma de gestión de agencia SEO (FastAPI + React 19 + PostgreSQL). La app actual tiene al ~60-70% de funcionalidad: CRUD de clientes/tareas/proyectos, gestión financiera, leads, propuestas, digests semanales con IA, growth ideas, y un sistema de permisos por módulo. Falta completar: el asistente IA proactivo (insights/briefings), reporting automático con export, y refinar la UX general.

Se han revisado los siguientes materiales teóricos:
- **SEO MBA Executive Presence** (Tom Critchlow) - 4 módulos + Practice Scenarios
- **El arte de presentar** (libro, PDF)
- **Superhéroe de las presentaciones** (libro, PDF)
- **Mejoras aplicables a la app Fit Content** (Excel con feedback de cliente)

---

## 1. CONOCIMIENTO EXTRAÍDO

### 1.1 Estrategia SEO (Critchlow Part 1)

**Framework de Estrategia (Richard Rumelt):**
- Buena estrategia = Diagnóstico + Política guía + Acciones coherentes
- Estrategia ACTIVA (construir cosas nuevas) vs PASIVA (arreglar cosas)
- "Full accounting": estimación completa de recursos necesarios
- La estrategia NO es una lista de fixes; es una narrativa coherente

**Jerarquía de Maslow para Pitches:**
1. Una sola petición clara
2. Compelling (convincente)
3. Respaldada por evidencia
4. Consensuada por stakeholders
5. Con próximos pasos claros

**Posicionamiento de Propuestas:**
- Usar números anuales (no mensuales) - más impacto
- Pensar en TAM (Total Addressable Market)
- Alinear con la experiencia del usuario
- Pre-wiring: pre-acordar con stakeholders antes de la presentación formal (enfoque McKinsey)

**Tipos de evidencia para respaldar propuestas:**
- Proyectos piloto
- Casos de estudio de competidores
- Datos de encuestas
- Tests A/B

### 1.2 Valor del SEO y Conexión con Revenue (Critchlow Part 2)

**4 Capas de Entendimiento del Negocio:**
1. User Insights (comportamiento del usuario)
2. Business Segments (segmentos de negocio)
3. Revenue Metrics (métricas de ingresos)
4. Revenue Mechanics (mecánica de ingresos)

**Árboles de Rentabilidad:**
- Modelo Media: tráfico → pageviews → ad revenue
- Modelo Lead Gen: tráfico → leads → conversiones → revenue
- Cada modelo de negocio afecta diferente al SEO

**Matriz de Madurez SEO → Revenue:**
1. **Broken** - Sin tracking
2. **Proxy** - Solo métricas de vanidad (rankings, tráfico)
3. **Connected** - SEO vinculado a revenue
4. **Sophisticated** - Modelos de atribución multi-touch
5. **Advanced** - Predicción y optimización en tiempo real

**Fuentes de datos a conectar:**
- Web Analytics (GA4)
- Product Analytics
- Sales CRM
- Finance/Billing

### 1.3 Modelos de Inversión (Critchlow Part 3)

**Jerarquía: Modelo > Escenario > Forecast**
- "Todos los modelos están equivocados, pero algunos son útiles"
- La experiencia de negocio > habilidades de modelado de datos

**2 Puntos de partida:**
1. Petición externa ("¿Cuánto tráfico podemos ganar?")
2. Modelo estratégico ("Así es como deberíamos invertir")

**Lo que necesita cada stakeholder:**
- CEO: top line (ingresos, crecimiento)
- COO/CTO/CMO: recursos (equipo, herramientas, timeline)
- CFO: bottom line (ROI, márgenes, payback)

**5 Ingredientes de un buen modelo:**
1. Segmentar por unidad de negocio (NO por tipo de página)
2. Usar métricas acordadas con el cliente
3. Exponer asunciones claramente
4. Modelar el caso nulo (qué pasa si no se hace nada)
5. Escenarios, no respuestas únicas (conservador/agresivo)

**Modelos de ejemplo reales:**
- Airbnb: 3 tiers de clientes, escenarios conservative/aggressive, inversión $600K-$1.7M
- The Sill: páginas existentes + nuevas, crecimiento de tráfico, categorías de inversión
- Tide: modelado keyword-level con volumen → clics → leads → revenue por categoría

### 1.4 Presentaciones Efectivas (Critchlow Part 4)

**Framework SCQA:**
- **S**ituación: contexto compartido
- **C**omplicación: el problema/tensión
- **Q** (Question): la pregunta que surge
- **A** (Answer): la respuesta/propuesta

**Estructura de presentación:**
- Executive Summary (5-10 slides) + Slides completos (secciones A/B/C) + Apéndice
- Presentaciones para decidir vs para educar

**Reglas de slides:**
- Títulos descriptivos y paralelos
- Una cosa por slide
- Imágenes solo si aportan
- Reducir complejidad
- Usar el apéndice para detalles

**Mejores prácticas en gráficos:**
- Etiquetar directamente (no leyendas separadas)
- Siempre mostrar la fuente
- Anotar eventos clave

### 1.5 Libros de Presentaciones (Negocio)

**"El arte de presentar":**
- Metodología para estructurar presentaciones persuasivas
- Técnicas de storytelling aplicadas a negocio
- Diseño visual que acompaña al mensaje
- Importancia del inicio y cierre de la presentación

**"Superhéroe de las presentaciones":**
- Framework práctico para presentaciones de impacto
- Técnicas de comunicación verbal y no verbal
- Cómo manejar preguntas y objeciones
- Slides como apoyo visual, no como teleprompter

### 1.6 Practice Scenarios (Aplicación Práctica)

**Caso Barkbox:** Estimación de tráfico para nuevo producto, benchmarking con competidores, alineación estratégica
**Caso The Sill:** Creación de estrategia desde agencia, principios guía, modelo de inversión con full accounting
**Caso Baronfig:** Modelado ROI de reviews, superación de objeciones del CEO con evidencia y visualización

---

## 2. FUNCIONALIDADES PROPUESTAS PARA THE AGENCY

### 2.1 Sistema de Propuestas Mejorado (ya existe base - enriquecer)

**Estado actual:** Existe modelo `Proposal` con campos SCQA (situation, problem, cost_of_inaction, opportunity, approach), pricing_options, y generated_content con IA.

**Mejoras basadas en la teoría:**
- **Templates SCQA guiados**: wizard step-by-step que guíe al usuario a rellenar S, C, Q y A con prompts contextuales
- **Generación de pricing con escenarios**: siempre generar 2-3 opciones (conservador/medio/agresivo) con diferentes niveles de inversión
- **Sección de evidencia**: campo para adjuntar casos de estudio, datos de competidores, resultados de pilots
- **Estimador de ROI integrado**: usando los modelos de inversión de Critchlow (tráfico → conversiones → revenue)
- **Cálculo automático de "caso nulo"**: qué pasa si el cliente no invierte (pérdida estimada de tráfico/revenue)
- **Preview con formato profesional**: exportar a PDF con estructura Executive Summary + Detalles + Apéndice

### 2.2 Modelos de Inversión SEO (NUEVA funcionalidad)

**Concepto:** Módulo para crear modelos de inversión SEO por cliente, basado en los templates del curso.

**Modelos a implementar:**
- **Modelo por segmento de negocio**: dividir el SEO del cliente por líneas de negocio (no por tipo de página)
- **Modelo keyword-level**: volumen de búsqueda → CTR estimado → clics → conversión → revenue
- **Modelo de crecimiento existente + nuevo**: páginas existentes (optimizar) + páginas nuevas (crear)

**Campos del modelo:**
- Segmentos del negocio del cliente
- Métricas actuales (tráfico, conversiones, AOV)
- Asunciones expuestas (growth rate, CTR, conversion rate)
- Escenarios: conservador / base / agresivo
- Inversión requerida desglosada (horas equipo, herramientas, contenido, desarrollo)
- Caso nulo (proyección sin inversión)
- ROI y payback period por escenario

**Conexión con propuestas:** Los modelos alimentan directamente la sección de pricing de las propuestas.

### 2.3 Reporting con Framework SCQA (mejorar lo existente)

**Estado actual:** Existe `GeneratedReport` con tipos client_status, weekly_summary, project_status.

**Mejoras:**
- **Estructura SCQA para informes de cliente**: cada informe sigue Situación → Complicación → Pregunta → Respuesta
- **Executive Summary automático**: IA genera resumen de 3-5 líneas al inicio
- **Gráficos inline**: progreso del proyecto, horas invertidas vs presupuesto, tendencia de KPIs
- **Sección "Próximos pasos" con acciones claras**: no solo listar tareas, sino vincularlas al modelo de inversión
- **Export a PDF profesional** con branding de la agencia
- **Diferentes formatos según audiencia**: CEO (resumen ejecutivo, ROI), CMO (métricas, progreso), Operativo (tareas, timelines)

### 2.4 Dashboard de Cliente con Árbol de Rentabilidad (NUEVA vista)

**Concepto:** En el detalle de cada cliente, mostrar un "profitability tree" visual que conecte las acciones SEO con el revenue.

**Componentes:**
- Tráfico orgánico actual → Meta de tráfico
- Conversion rate → Leads/Ventas
- AOV/LTV → Revenue
- Inversión SEO → ROI

**Configuración por cliente:**
- Modelo de negocio (e-commerce, lead gen, media, SaaS)
- Métricas clave (AOV, conversion rate, LTV)
- Fuentes de datos conectadas (GSC, GA4 via project fields existentes)

### 2.5 Matriz de Madurez SEO por Cliente (NUEVA funcionalidad)

**Concepto:** Asignar y trackear el nivel de madurez SEO→Revenue de cada cliente.

**Niveles (de Critchlow):**
1. Broken - sin tracking
2. Proxy - solo rankings/tráfico
3. Connected - SEO vinculado a revenue
4. Sophisticated - atribución multi-touch
5. Advanced - predicción y optimización

**Uso:** Determina qué tipo de informes y métricas mostrar al cliente, y qué ofrecer como siguiente paso.

### 2.6 Templates de Proyecto Enriquecidos (mejorar lo existente)

**Estado actual:** Existe `ServiceTemplate` con fases y el campo `prompt_context` para IA.

**Mejoras basadas en la teoría:**
- **Full accounting por template**: cada template incluye estimación realista de recursos (horas David, horas Nacho, herramientas, costes externos)
- **Criterios de éxito medibles**: KPIs específicos por tipo de proyecto vinculados al modelo de negocio del cliente
- **Dependencias entre fases**: ya existe `depends_on` en tasks - usarlo para crear caminos críticos
- **Checklist de entrega por fase**: qué deliverables esperar en cada milestone

### 2.7 Sistema de Evidencia y Casos de Estudio (NUEVA funcionalidad)

**Concepto:** Biblioteca interna de evidencia reutilizable para propuestas.

**Tipos de evidencia:**
- Resultados propios (antes/después por cliente - anonimizado si es necesario)
- Casos de estudio de competidores del cliente
- Datos de industria / benchmarks
- Resultados de tests A/B

**Uso:** Al crear una propuesta, se puede seleccionar evidencia relevante de la biblioteca para incluir automáticamente.

### 2.8 Growth Ideas con Framework ICE mejorado (ya existe - enriquecer)

**Estado actual:** Existe `GrowthIdea` con ICE scoring y funnel stages.

**Mejoras:**
- **Vincular a modelos de inversión**: cada idea puede tener un mini-modelo de inversión asociado
- **Tracking de resultados**: campo `is_successful` existe pero falta UI para documentar resultados vs hipótesis
- **Exportar como caso de estudio**: ideas exitosas se convierten en evidencia reutilizable

---

## 3. PLANTILLAS A ADAPTAR

### 3.1 Plantilla de Modelo de Inversión SEO

Basada en los spreadsheets de Critchlow (Airbnb, The Sill, Tide):

**Estructura:**

| Sección | Campos |
|---------|--------|
| Segmentación | Líneas de negocio del cliente, URLs/keywords por segmento |
| Métricas actuales | Tráfico, posiciones, CTR, conversiones, AOV |
| Asunciones | Growth rates, CTR targets, conversion rates |
| Escenario Conservador | +X% tráfico, Y conversiones, Z revenue |
| Escenario Agresivo | +X% tráfico, Y conversiones, Z revenue |
| Caso Nulo | Proyección sin inversión (decay rate) |
| Inversión | Horas equipo, herramientas, contenido, desarrollo |
| ROI | Revenue incremental / Inversión total, payback months |

### 3.2 Plantilla de Propuesta SCQA

**Estructura del documento generado:**

1. **Executive Summary** (1 página)
   - Situación actual del cliente
   - Oportunidad identificada
   - Inversión recomendada y ROI esperado

2. **Análisis** (Situación + Complicación)
   - Diagnóstico del estado actual
   - Problemas/oportunidades identificados
   - Coste de la inacción

3. **Propuesta** (Question + Answer)
   - Enfoque estratégico
   - Fases y timeline
   - Entregables por fase

4. **Opciones de Inversión** (2-3 opciones)
   - Conservador / Recomendado / Premium
   - Desglose de cada opción
   - ROI esperado por opción

5. **Evidencia**
   - Casos de estudio relevantes
   - Datos de mercado

6. **Apéndice**
   - Modelo de inversión detallado
   - Asunciones y metodología

### 3.3 Plantilla de Informe de Cliente (SCQA)

**Estructura:**

1. Resumen ejecutivo (generado por IA)
2. Situación: métricas del periodo
3. Complicación: desafíos o cambios detectados
4. Respuesta: acciones tomadas y resultados
5. Próximos pasos: acciones concretas con responsable y fecha
6. KPIs vs objetivos

---

## 4. CONSEJOS Y MEJORES PRÁCTICAS

### 4.1 Para la UX de la App

- **Lead with the point**: en cada vista, lo más importante primero (no enterrar insights debajo de datos)
- **Una cosa por vista**: no sobrecargar dashboards (inspirado en "una cosa por slide")
- **Títulos descriptivos**: en lugar de "Dashboard", usar "Resumen del mes: 3 clientes necesitan atención"
- **Reduce complejidad**: mover detalles a secciones expandibles o pestañas secundarias
- **Etiquetado directo en gráficos**: no usar leyendas separadas, etiquetar directamente los datos
- **Siempre mostrar la fuente/fecha de los datos**: especialmente en métricas y KPIs

### 4.2 Para el Asistente IA (Insights/Briefings)

- **Máximo 5-7 insights** para no abrumar (regla de Critchlow)
- **Priorizar lo urgente**: insights sobre deadlines y tareas vencidas siempre primero
- **Ser específico con nombres y fechas**: "Cliente X no tiene actividad desde hace 15 días" > "Hay clientes sin actividad"
- **Sugerencias proactivas con base en hitos**: "Cliente X lleva 3 meses, buen momento para proponer ampliación"
- **El briefing diario debe ser accionable**: no informativo, sino "haz esto hoy"

### 4.3 Para Propuestas y Comunicación con Clientes

- **Números anuales, no mensuales**: "200K€ en revenue incremental al año" impacta más que "16.6K€/mes"
- **Siempre mostrar el caso nulo**: qué pasa si NO se invierte
- **Escenarios, nunca una respuesta única**: conservador/agresivo da flexibilidad
- **Pre-wiring**: antes de enviar propuesta formal, validar la idea informalmente con el cliente
- **Segmentar por unidad de negocio**: el cliente entiende "vamos a crecer tu línea de producto X" mejor que "vamos a optimizar tus category pages"

### 4.4 Feedback del Excel de Mejoras (Fit Content)

Patrones de problemas detectados que aplican a The Agency:
- **Consistencia de datos**: verificar que los datos mostrados coincidan con las fuentes (GSC, GA4)
- **Tooltips explicativos**: cada métrica necesita un tooltip que explique de dónde viene y qué significa
- **Filtros que no rompan otros filtros**: al cambiar un filtro no debe resetear los demás
- **Funcionalidades "previstas" que no funcionan**: marcar claramente el estado de cada feature (beta, coming soon, etc.)
- **Errores de gráficas**: siempre tener datos suficientes para mostrar gráficas con sentido
- **Descripciones en todas las secciones**: ayuda a entender qué esperar

---

## 5. INSTRUCCIONES PARA CLAUDE CODE

### INSTRUCCIÓN 1: Enriquecer el Sistema de Propuestas con SCQA

```
CONTEXTO: The Agency tiene un modelo Proposal con campos SCQA (situation, problem, cost_of_inaction, opportunity, approach, pricing_options, generated_content).

TAREA: Mejorar la UI de propuestas para que siga un wizard SCQA:

1. Step 1 - Situación: campos situation + datos del cliente (se autocompletan desde client/project)
2. Step 2 - Complicación: campos problem + cost_of_inaction
3. Step 3 - Oportunidad: campos opportunity + approach + relevant_cases
4. Step 4 - Inversión: pricing_options como tabla editable con 2-3 opciones (nombre, precio, qué incluye, ROI estimado)
5. Step 5 - Preview: generar propuesta con IA usando el prompt SCQA y mostrar preview

PROMPT PARA GENERAR PROPUESTA:
"Genera una propuesta profesional de servicios SEO usando el framework SCQA.

DATOS DEL CLIENTE: {client_name}, {company}, {website}
SITUACIÓN: {situation}
COMPLICACIÓN: {problem}
COSTE DE INACCIÓN: {cost_of_inaction}
OPORTUNIDAD: {opportunity}
ENFOQUE: {approach}
CASOS RELEVANTES: {relevant_cases}
OPCIONES DE PRECIO: {pricing_options}

Genera un JSON con esta estructura:
{
  "executive_summary": "resumen de 3-5 líneas",
  "situation_analysis": "análisis detallado de la situación",
  "complications": "problemas y tensiones identificadas",
  "proposal": "propuesta detallada con enfoque y fases",
  "investment_options": [
    {"name": "Conservador", "price": X, "includes": [...], "expected_roi": "..."},
    {"name": "Recomendado", "price": Y, "includes": [...], "expected_roi": "..."},
    {"name": "Premium", "price": Z, "includes": [...], "expected_roi": "..."}
  ],
  "evidence": "casos y datos de soporte",
  "next_steps": ["paso 1", "paso 2", "paso 3"]
}"

ARCHIVOS A MODIFICAR:
- frontend/src/pages/proposals-page.tsx (wizard multi-step)
- backend/api/routes/proposals.py (enriquecer endpoint generate)
- backend/services/ (crear proposal_generator.py)
```

### INSTRUCCIÓN 2: Módulo de Modelos de Inversión SEO

```
CONTEXTO: The Agency necesita un módulo para crear modelos de inversión SEO por cliente, basado en la metodología de Tom Critchlow (SEO MBA).

TAREA: Crear un nuevo módulo "Investment Models" con:

BACKEND:
1. Nuevo modelo SQLAlchemy `InvestmentModel`:
   - id, client_id, project_id (optional), name, description
   - model_type: 'segment_based' | 'keyword_level' | 'growth_existing_new'
   - segments: JSON (lista de segmentos con métricas)
   - assumptions: JSON (growth_rate, ctr, conversion_rate, aov, decay_rate)
   - scenarios: JSON (conservative: {...}, aggressive: {...})
   - investment_breakdown: JSON (team_hours, tools, content, development, external)
   - null_case: JSON (proyección sin inversión)
   - created_by, created_at, updated_at

2. CRUD endpoints: GET/POST/PUT/DELETE /api/investment-models
3. Endpoint especial: POST /api/investment-models/{id}/calculate - recalcula ROI por escenario

FRONTEND:
1. Nueva página investment-models-page.tsx
2. Formulario con tabs: Segmentos | Asunciones | Escenarios | Inversión | Resultados
3. Gráfico comparativo de escenarios (usar Recharts)
4. Tabla resumen: Revenue incremental, Inversión total, ROI, Payback months
5. Botón "Usar en propuesta" que vincula el modelo a una propuesta

PERMISOS: Añadir módulo 'investment_models' al sistema de permisos
```

### INSTRUCCIÓN 3: Mejorar Reporting con SCQA y Export PDF

```
CONTEXTO: The Agency tiene GeneratedReport con IA (tipos: client_status, weekly_summary, project_status). Los informes se generan pero no tienen estructura SCQA ni export profesional.

TAREA:

1. ESTRUCTURA SCQA para informes:
   Modificar el prompt de generación en backend/services/reports.py para que los informes sigan:
   - Resumen ejecutivo (3-5 líneas)
   - Situación: métricas del periodo, contexto
   - Complicación: desafíos, alertas, cambios
   - Respuesta: acciones tomadas, resultados
   - Próximos pasos: acciones concretas con fecha
   - KPIs vs objetivos (tabla)

2. DIFERENTES FORMATOS según audiencia:
   Añadir campo `audience` al modelo: 'executive' | 'marketing' | 'operational'
   - Executive: resumen corto, ROI, top-level metrics
   - Marketing: métricas detalladas, tendencias, comparativas
   - Operational: tareas completadas, timeline, blockers

3. EXPORT PDF:
   Usar reportlab para generar PDF con branding:
   - Logo Magnify (si existe) en header
   - Colores corporativos (#0044FF brand color del dark theme)
   - Tipografía profesional
   - Gráficos embebidos (convertir Recharts a imagen estática)
   - Pie de página con fecha y "Generado por The Agency"

ARCHIVOS:
- backend/services/reports.py (mejorar prompts y estructura)
- backend/api/routes/reports.py (añadir endpoint export-pdf)
- frontend/src/pages/reports-page.tsx (selector de audiencia, botón export)
```

### INSTRUCCIÓN 4: Dashboard de Cliente con Profitability Tree

```
CONTEXTO: The Agency tiene client-detail-page.tsx. Cada cliente tiene campos de negocio (website, monthly_budget, contract_type) y proyectos vinculados.

TAREA: Añadir una pestaña "Revenue Model" en el detalle de cliente con:

1. CONFIGURACIÓN del modelo de negocio:
   Nuevos campos en Client model:
   - business_model: 'ecommerce' | 'lead_gen' | 'media' | 'saas'
   - aov (average order value)
   - conversion_rate
   - ltv (lifetime value)
   - seo_maturity_level: 1-5 (Broken → Advanced)

2. VISUALIZACIÓN del profitability tree:
   Componente React con flujo visual:
   Tráfico Orgánico → [conversion_rate] → Leads/Ventas → [AOV/LTV] → Revenue
   ↑ SEO Investment → [ROI]

   Usar cards conectadas por flechas (estilo flowchart simple con CSS/SVG)

3. INDICADOR de madurez SEO:
   Barra de progreso 1-5 con etiquetas:
   Broken | Proxy | Connected | Sophisticated | Advanced
   Con tooltip explicando cada nivel y qué se necesita para subir

4. MÉTRICAS CLAVE por tipo de negocio:
   - E-commerce: Revenue orgánico, AOV, Transactions, Conv Rate
   - Lead Gen: Leads orgánicos, Cost per Lead, Pipeline value
   - Media: Pageviews orgánicas, RPM, Ad Revenue
   - SaaS: Signups orgánicos, Trial→Paid rate, MRR atribuido

ARCHIVOS:
- backend/db/models.py (nuevos campos en Client)
- backend/schemas/client.py (actualizar schemas)
- frontend/src/pages/client-detail-page.tsx (nueva pestaña)
- frontend/src/components/clients/ (nuevos componentes: ProfitabilityTree, MaturityIndicator)
```

### INSTRUCCIÓN 5: Biblioteca de Evidencia Reutilizable

```
CONTEXTO: Para hacer propuestas convincentes, se necesita una biblioteca de evidencia (casos de estudio, benchmarks, resultados) que se pueda reutilizar.

TAREA:

BACKEND:
1. Nuevo modelo `EvidenceItem`:
   - id, title, description
   - evidence_type: 'case_study' | 'competitor_analysis' | 'industry_benchmark' | 'ab_test' | 'pilot_result'
   - industry: string (para filtrar por industria)
   - metrics: JSON (antes/después, % mejora, etc.)
   - source: string (origen del dato)
   - is_anonymized: boolean
   - client_id: optional (si viene de un cliente propio)
   - tags: JSON (lista de tags para búsqueda)
   - created_by, created_at

2. CRUD endpoints: /api/evidence
3. Endpoint: GET /api/evidence/search?industry=X&type=Y&tags=Z

FRONTEND:
1. Nueva página evidence-page.tsx con grid de cards
2. Filtros por tipo, industria, tags
3. Dialog para crear/editar evidencia
4. En propuestas: selector de evidencia que se autocompleta al buscar

PERMISOS: Añadir módulo 'evidence'
```

### INSTRUCCIÓN 6: Mejoras UX Generales (basadas en teoría + feedback)

```
CONTEXTO: Basado en las mejores prácticas de presentación (Critchlow + libros) y el feedback del Excel de Mejoras.

TAREAS:

1. TOOLTIPS en todas las métricas:
   - Cada KPI/métrica del dashboard debe tener un icono (?) con tooltip
   - El tooltip explica: qué mide, de dónde viene el dato, y qué significa un valor alto/bajo
   - Implementar como componente reutilizable MetricWithTooltip

2. TÍTULOS DESCRIPTIVOS en dashboards:
   - En lugar de "Dashboard", mostrar "Resumen del mes: X tareas completadas, Y pendientes"
   - En lugar de "Clientes", mostrar "X clientes activos | Y sin actividad reciente"
   - Generar estos títulos dinámicamente desde los datos

3. EMPTY STATES informativos:
   - Cada sección sin datos debe mostrar: qué esperar, cómo empezar, y un CTA claro
   - No mostrar tablas vacías o gráficas sin datos

4. SECCIÓN DE AYUDA por página:
   - Icono de ayuda que abre panel lateral con:
     - Descripción de la sección
     - Qué puedes hacer aquí
     - Tips y mejores prácticas

5. LABELS DE ESTADO en features no completadas:
   - Badge "Beta" o "Coming soon" en funcionalidades parciales
   - No dejar botones que no hacen nada sin indicar por qué
```

---

## Documento generado

Este documento consolida el análisis teórico extraído de los materiales de Tom Critchlow (SEO MBA Executive Presence), libros de presentaciones, y mejoras aplicables, proporcionando instrucciones concretas para implementar en "The Agency" una plataforma profesional de gestión de agencia SEO.

**Fecha de creación:** 25 de febrero de 2026
**Versión:** 1.0
