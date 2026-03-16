import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Zap, Plus, Power, Trash2, ChevronDown, ChevronUp, Clock, CheckCircle2, XCircle } from "lucide-react"
import { toast } from "sonner"
import { automationsApi } from "@/lib/api"
import type { AutomationRule, AutomationRuleCreate, AutomationTriggerOption, AutomationActionOption, AutomationLogEntry } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { EmptyState } from "@/components/ui/empty-state"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { getErrorMessage } from "@/lib/utils"

export default function AutomationsPage() {
  const queryClient = useQueryClient()
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [deleteId, setDeleteId] = useState<number | null>(null)
  const [activeTab, setActiveTab] = useState<"rules" | "logs">("rules")

  const { data: rules = [], isLoading } = useQuery({
    queryKey: ["automations"],
    queryFn: automationsApi.list,
  })

  const { data: logs = [] } = useQuery({
    queryKey: ["automation-logs"],
    queryFn: () => automationsApi.logs(undefined, 100),
    enabled: activeTab === "logs",
  })

  const { data: triggerOptions } = useQuery({
    queryKey: ["automation-triggers"],
    queryFn: automationsApi.triggers,
  })

  const toggleMutation = useMutation({
    mutationFn: automationsApi.toggle,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["automations"] })
      toast.success("Regla actualizada")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error")),
  })

  const deleteMutation = useMutation({
    mutationFn: automationsApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["automations"] })
      toast.success("Regla eliminada")
      setDeleteId(null)
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error")),
  })

  const activeCount = rules.filter((r) => r.is_active).length
  const totalRuns = rules.reduce((acc, r) => acc + r.run_count, 0)

  const triggerLabels: Record<string, string> = {}
  const actionLabels: Record<string, string> = {}
  if (triggerOptions) {
    triggerOptions.triggers.forEach((t) => { triggerLabels[t.key] = t.label })
    triggerOptions.actions.forEach((a) => { actionLabels[a.key] = a.label })
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Automatizaciones</h1>
          <p className="text-muted-foreground text-sm mt-1">
            Reglas que se ejecutan cuando ocurren eventos en la agencia
          </p>
        </div>
        <Button onClick={() => setShowCreateDialog(true)}>
          <Plus className="h-4 w-4 mr-2" />
          Nueva regla
        </Button>
      </div>

      {/* KPIs */}
      <div className="grid gap-4 grid-cols-2 md:grid-cols-4">
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-muted-foreground">Total reglas</p>
            <p className="text-2xl font-bold">{rules.length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-muted-foreground">Activas</p>
            <p className="text-2xl font-bold text-success">{activeCount}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-muted-foreground">Inactivas</p>
            <p className="text-2xl font-bold text-muted-foreground">{rules.length - activeCount}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <p className="text-xs text-muted-foreground">Ejecuciones totales</p>
            <p className="text-2xl font-bold">{totalRuns}</p>
          </CardContent>
        </Card>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border">
        <button
          className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${activeTab === "rules" ? "border-brand text-brand" : "border-transparent text-muted-foreground hover:text-foreground"}`}
          onClick={() => setActiveTab("rules")}
        >
          Reglas
        </button>
        <button
          className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${activeTab === "logs" ? "border-brand text-brand" : "border-transparent text-muted-foreground hover:text-foreground"}`}
          onClick={() => setActiveTab("logs")}
        >
          Historial
        </button>
      </div>

      {/* Content */}
      {activeTab === "rules" ? (
        isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="rounded-xl border border-border bg-card p-4 space-y-2">
                <div className="animate-pulse rounded-md bg-muted h-5 w-1/3" />
                <div className="animate-pulse rounded-md bg-muted h-3 w-1/2" />
              </div>
            ))}
          </div>
        ) : rules.length === 0 ? (
          <EmptyState
            icon={Zap}
            title="Sin automatizaciones"
            description="Crea reglas para automatizar acciones cuando ocurren eventos. Por ejemplo: crear una tarea cuando un proyecto cambia de estado."
            actionLabel="Nueva regla"
            onAction={() => setShowCreateDialog(true)}
          />
        ) : (
          <div className="space-y-3">
            {rules.map((rule) => (
              <RuleCard
                key={rule.id}
                rule={rule}
                triggerLabel={triggerLabels[rule.trigger] || rule.trigger}
                actionLabel={actionLabels[rule.action_type] || rule.action_type}
                isExpanded={expandedId === rule.id}
                onToggleExpand={() => setExpandedId(expandedId === rule.id ? null : rule.id)}
                onToggleActive={() => toggleMutation.mutate(rule.id)}
                onDelete={() => setDeleteId(rule.id)}
              />
            ))}
          </div>
        )
      ) : (
        <LogsList logs={logs} triggerLabels={triggerLabels} />
      )}

      {/* Create Dialog */}
      {triggerOptions && (
        <CreateAutomationDialog
          open={showCreateDialog}
          onOpenChange={setShowCreateDialog}
          triggers={triggerOptions.triggers}
          actions={triggerOptions.actions}
        />
      )}

      {/* Delete Confirm */}
      <ConfirmDialog
        open={deleteId !== null}
        onOpenChange={(open) => !open && setDeleteId(null)}
        title="Eliminar automatización"
        description="¿Seguro que quieres eliminar esta regla? Se borrarán también todos sus logs de ejecución."
        onConfirm={() => deleteId && deleteMutation.mutate(deleteId)}
      />
    </div>
  )
}

function RuleCard({
  rule,
  triggerLabel,
  actionLabel,
  isExpanded,
  onToggleExpand,
  onToggleActive,
  onDelete,
}: {
  rule: AutomationRule
  triggerLabel: string
  actionLabel: string
  isExpanded: boolean
  onToggleExpand: () => void
  onToggleActive: () => void
  onDelete: () => void
}) {
  return (
    <div className={`rounded-xl border bg-card transition-all ${rule.is_active ? "border-border" : "border-border/50 opacity-60"}`}>
      <div className="flex items-center gap-3 p-4">
        <button
          onClick={onToggleActive}
          className={`flex-shrink-0 p-1.5 rounded-lg transition-colors ${rule.is_active ? "bg-success/10 text-success hover:bg-success/20" : "bg-muted text-muted-foreground hover:bg-muted/80"}`}
          title={rule.is_active ? "Desactivar" : "Activar"}
        >
          <Power className="h-4 w-4" />
        </button>

        <div className="flex-1 min-w-0 cursor-pointer" onClick={onToggleExpand}>
          <div className="flex items-center gap-2">
            <h3 className="font-medium text-sm truncate">{rule.name}</h3>
            {!rule.is_active && <Badge variant="secondary">Inactiva</Badge>}
          </div>
          <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <Zap className="h-3 w-3" /> {triggerLabel}
            </span>
            <span>→</span>
            <span>{actionLabel}</span>
            {rule.run_count > 0 && (
              <span className="flex items-center gap-1">
                <Clock className="h-3 w-3" /> {rule.run_count}x
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-1">
          <button onClick={onToggleExpand} className="p-1.5 rounded hover:bg-muted text-muted-foreground">
            {isExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </button>
          <button onClick={onDelete} className="p-1.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive">
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      {isExpanded && (
        <div className="px-4 pb-4 border-t border-border pt-3 space-y-3 text-sm">
          {rule.description && (
            <p className="text-muted-foreground">{rule.description}</p>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-1">Condiciones</p>
              {Object.keys(rule.conditions).length > 0 ? (
                <pre className="text-xs bg-surface p-2 rounded overflow-auto max-h-32">
                  {JSON.stringify(rule.conditions, null, 2)}
                </pre>
              ) : (
                <p className="text-xs text-muted-foreground">Sin filtros (se aplica siempre)</p>
              )}
            </div>
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-1">Configuración acción</p>
              {Object.keys(rule.action_config).length > 0 ? (
                <pre className="text-xs bg-surface p-2 rounded overflow-auto max-h-32">
                  {JSON.stringify(rule.action_config, null, 2)}
                </pre>
              ) : (
                <p className="text-xs text-muted-foreground">Config por defecto</p>
              )}
            </div>
          </div>

          <div className="flex gap-4 text-xs text-muted-foreground">
            {rule.creator_name && <span>Creada por: {rule.creator_name}</span>}
            {rule.last_run_at && (
              <span>Última ejecución: {new Date(rule.last_run_at).toLocaleString("es-ES")}</span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function LogsList({ logs, triggerLabels }: { logs: AutomationLogEntry[]; triggerLabels: Record<string, string> }) {
  if (logs.length === 0) {
    return (
      <EmptyState
        icon={Clock}
        title="Sin historial"
        description="Aquí aparecerán las ejecuciones de las automatizaciones."
      />
    )
  }

  return (
    <div className="space-y-2">
      {logs.map((log) => (
        <div key={log.id} className="flex items-center gap-3 p-3 rounded-lg border border-border bg-card text-sm">
          {log.success ? (
            <CheckCircle2 className="h-4 w-4 text-success flex-shrink-0" />
          ) : (
            <XCircle className="h-4 w-4 text-destructive flex-shrink-0" />
          )}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-medium truncate">{log.rule_name || `Regla #${log.rule_id}`}</span>
              <Badge variant="secondary" className="text-[10px]">
                {triggerLabels[log.trigger_event] || log.trigger_event}
              </Badge>
            </div>
            {log.error_message && (
              <p className="text-xs text-destructive mt-0.5 truncate">{log.error_message}</p>
            )}
          </div>
          <span className="text-xs text-muted-foreground flex-shrink-0">
            {new Date(log.executed_at).toLocaleString("es-ES", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
          </span>
        </div>
      ))}
    </div>
  )
}

function CreateAutomationDialog({
  open,
  onOpenChange,
  triggers,
  actions,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  triggers: AutomationTriggerOption[]
  actions: AutomationActionOption[]
}) {
  const queryClient = useQueryClient()
  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [trigger, setTrigger] = useState("")
  const [actionType, setActionType] = useState("")
  const [conditionsStr, setConditionsStr] = useState("{}")
  const [actionConfigStr, setActionConfigStr] = useState("{}")

  const selectedTrigger = triggers.find((t) => t.key === trigger)
  const selectedAction = actions.find((a) => a.key === actionType)

  const createMutation = useMutation({
    mutationFn: (data: AutomationRuleCreate) => automationsApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["automations"] })
      toast.success("Automatización creada")
      onOpenChange(false)
      setName("")
      setDescription("")
      setTrigger("")
      setActionType("")
      setConditionsStr("{}")
      setActionConfigStr("{}")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al crear")),
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()

    let conditions = {}
    let actionConfig = {}
    try {
      conditions = JSON.parse(conditionsStr)
    } catch {
      toast.error("JSON de condiciones inválido")
      return
    }
    try {
      actionConfig = JSON.parse(actionConfigStr)
    } catch {
      toast.error("JSON de configuración inválido")
      return
    }

    createMutation.mutate({
      name,
      description: description || undefined,
      trigger: trigger as AutomationRuleCreate["trigger"],
      conditions,
      action_type: actionType as AutomationRuleCreate["action_type"],
      action_config: actionConfig,
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>Nueva automatización</DialogTitle>
      </DialogHeader>
      <form onSubmit={handleSubmit} className="space-y-4 mt-4">
        <div className="space-y-2">
          <Label>Nombre *</Label>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Ej: Notificar al completar tarea SEO"
            required
          />
        </div>

        <div className="space-y-2">
          <Label>Descripción</Label>
          <Input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Qué hace esta regla"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label>Cuando (trigger) *</Label>
            <Select value={trigger} onChange={(e) => setTrigger(e.target.value)} required>
              <option value="">Seleccionar...</option>
              {triggers.map((t) => (
                <option key={t.key} value={t.key}>
                  {t.label}
                </option>
              ))}
            </Select>
            {selectedTrigger && (
              <p className="text-xs text-muted-foreground">{selectedTrigger.description}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label>Entonces (acción) *</Label>
            <Select value={actionType} onChange={(e) => setActionType(e.target.value)} required>
              <option value="">Seleccionar...</option>
              {actions.map((a) => (
                <option key={a.key} value={a.key}>
                  {a.label}
                </option>
              ))}
            </Select>
            {selectedAction && (
              <p className="text-xs text-muted-foreground">{selectedAction.description}</p>
            )}
          </div>
        </div>

        <div className="space-y-2">
          <Label>Condiciones (JSON)</Label>
          <textarea
            value={conditionsStr}
            onChange={(e) => setConditionsStr(e.target.value)}
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm font-mono min-h-[60px] focus:outline-none focus:ring-2 focus:ring-brand/40"
            placeholder='{"project_id": 5, "status": "active"}'
          />
          <p className="text-xs text-muted-foreground">
            Filtra cuándo se ejecuta. Ej: {`{"client_id": 1}`} solo para ese cliente. Vacío = siempre.
          </p>
        </div>

        <div className="space-y-2">
          <Label>Config. de acción (JSON)</Label>
          <textarea
            value={actionConfigStr}
            onChange={(e) => setActionConfigStr(e.target.value)}
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm font-mono min-h-[60px] focus:outline-none focus:ring-2 focus:ring-brand/40"
            placeholder='{"title": "Review entregable", "priority": "high"}'
          />
          <p className="text-xs text-muted-foreground">
            Parámetros de la acción. Depende del tipo seleccionado.
          </p>
        </div>

        <div className="flex justify-end gap-2 pt-4">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button type="submit" disabled={createMutation.isPending}>
            {createMutation.isPending ? "Creando..." : "Crear regla"}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}
