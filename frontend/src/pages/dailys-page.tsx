import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { format } from "date-fns"
import { es } from "date-fns/locale"
import { ClipboardList, Sparkles, MessageCircle, Loader2, ChevronDown, ChevronUp, RefreshCw, Trash2 } from "lucide-react"
import { dailysApi } from "@/lib/api"
import type { DailyUpdate, ParsedProject, ParsedTask } from "@/lib/types"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"
import { useAuth } from "@/context/auth-context"

export default function DailysPage() {
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const [rawText, setRawText] = useState("")
  const [expandedId, setExpandedId] = useState<number | null>(null)

  const { data: dailys = [], isLoading } = useQuery({
    queryKey: ["dailys"],
    queryFn: () => dailysApi.list({ limit: 50 }),
  })

  const submitMutation = useMutation({
    mutationFn: (text: string) => dailysApi.submit({ raw_text: text }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dailys"] })
      setRawText("")
      toast.success("Daily procesado con IA correctamente")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al procesar daily")),
  })

  const reparseMutation = useMutation({
    mutationFn: (id: number) => dailysApi.reparse(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dailys"] })
      toast.success("Daily re-parseado")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al re-parsear")),
  })

  const discordMutation = useMutation({
    mutationFn: (id: number) => dailysApi.sendDiscord(id),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["dailys"] })
      if (data.success) {
        toast.success("Enviado a Discord")
      } else {
        toast.error(data.message)
      }
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al enviar a Discord")),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => dailysApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dailys"] })
      toast.success("Daily eliminado")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al eliminar")),
  })

  const handleSubmit = () => {
    if (!rawText.trim()) return
    submitMutation.mutate(rawText)
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold">Daily Updates</h1>
        <p className="text-muted-foreground">
          Pega tu daily y la IA lo clasifica por proyecto automáticamente
        </p>
      </div>

      {/* Submit form */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-brand" />
            Nuevo Daily
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <textarea
            value={rawText}
            onChange={(e) => setRawText(e.target.value)}
            placeholder="Pega aquí tu daily update tal cual lo escribes... La IA se encarga de clasificarlo por proyecto."
            className="w-full min-h-[200px] rounded-xl border border-border bg-background px-4 py-3 text-sm placeholder:text-muted-foreground/50 focus:outline-none focus:ring-2 focus:ring-brand/20 resize-y"
          />
          <div className="flex items-center justify-between">
            <p className="text-xs text-muted-foreground">
              {rawText.length > 0 ? `${rawText.length} caracteres` : "Soporta cualquier formato: bullets, párrafos, proyectos mezclados..."}
            </p>
            <Button
              onClick={handleSubmit}
              disabled={!rawText.trim() || submitMutation.isPending}
            >
              {submitMutation.isPending ? (
                <><Loader2 className="w-4 h-4 mr-2 animate-spin" />Procesando con IA...</>
              ) : (
                <><Sparkles className="w-4 h-4 mr-2" />Procesar Daily</>
              )}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Daily list */}
      <div className="space-y-4">
        <h2 className="text-lg font-semibold">Histórico</h2>

        {isLoading ? (
          <div className="flex justify-center py-12">
            <Loader2 className="w-6 h-6 animate-spin opacity-40" />
          </div>
        ) : dailys.length === 0 ? (
          <Card>
            <CardContent className="py-12">
              <div className="flex flex-col items-center text-center">
                <ClipboardList className="h-8 w-8 text-muted-foreground/30 mb-3" />
                <p className="text-sm font-medium text-foreground mb-1">Sin dailys todavía</p>
                <p className="text-xs text-muted-foreground">
                  Pega tu primer daily update arriba para empezar.
                </p>
              </div>
            </CardContent>
          </Card>
        ) : (
          dailys.map((daily) => (
            <DailyCard
              key={daily.id}
              daily={daily}
              expanded={expandedId === daily.id}
              onToggle={() => setExpandedId(expandedId === daily.id ? null : daily.id)}
              onReparse={() => reparseMutation.mutate(daily.id)}
              onSendDiscord={() => discordMutation.mutate(daily.id)}
              onDelete={() => deleteMutation.mutate(daily.id)}
              isReparsing={reparseMutation.isPending}
              isSending={discordMutation.isPending}
              currentUserId={user?.id}
            />
          ))
        )}
      </div>
    </div>
  )
}

function DailyCard({
  daily,
  expanded,
  onToggle,
  onReparse,
  onSendDiscord,
  onDelete,
  isReparsing,
  isSending,
  currentUserId,
}: {
  daily: DailyUpdate
  expanded: boolean
  onToggle: () => void
  onReparse: () => void
  onSendDiscord: () => void
  onDelete: () => void
  isReparsing: boolean
  isSending: boolean
  currentUserId?: number
}) {
  const parsed = daily.parsed_data
  const totalTasks = parsed
    ? parsed.projects.reduce((sum, p) => sum + p.tasks.length, 0) + parsed.general.length
    : 0

  return (
    <Card>
      <div
        className="flex items-center justify-between px-6 py-4 cursor-pointer hover:bg-muted/30 transition-colors"
        onClick={onToggle}
      >
        <div className="flex items-center gap-4 min-w-0">
          <div className="flex flex-col min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-sm">
                {daily.user_name || "Usuario"}
              </span>
              <span className="text-xs text-muted-foreground">
                {format(new Date(daily.date), "EEEE d MMM yyyy", { locale: es })}
              </span>
              <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
                daily.status === "sent"
                  ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"
                  : "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400"
              }`}>
                {daily.status === "sent" ? "Enviado" : "Borrador"}
              </span>
            </div>
            <span className="text-xs text-muted-foreground mt-0.5">
              {parsed
                ? `${parsed.projects.length} proyecto${parsed.projects.length !== 1 ? "s" : ""} · ${totalTasks} tarea${totalTasks !== 1 ? "s" : ""}`
                : "Sin parsear"}
              {parsed?.tomorrow.length ? ` · ${parsed.tomorrow.length} para mañana` : ""}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            title="Re-parsear con IA"
            onClick={(e) => { e.stopPropagation(); onReparse() }}
            disabled={isReparsing}
          >
            <RefreshCw className={`w-4 h-4 ${isReparsing ? "animate-spin" : ""}`} />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            title="Enviar a Discord"
            onClick={(e) => { e.stopPropagation(); onSendDiscord() }}
            disabled={isSending}
          >
            <MessageCircle className={`w-4 h-4 ${isSending ? "animate-pulse" : ""}`} />
          </Button>
          {(daily.user_id === currentUserId) && (
            <Button
              variant="ghost"
              size="sm"
              title="Eliminar"
              onClick={(e) => { e.stopPropagation(); onDelete() }}
              className="text-muted-foreground hover:text-destructive"
            >
              <Trash2 className="w-4 h-4" />
            </Button>
          )}
          {expanded ? <ChevronUp className="w-4 h-4 text-muted-foreground" /> : <ChevronDown className="w-4 h-4 text-muted-foreground" />}
        </div>
      </div>

      {expanded && parsed && (
        <CardContent className="pt-0 pb-6 border-t border-border">
          <div className="space-y-5 mt-4">
            {/* Projects */}
            {parsed.projects.map((project, i) => (
              <ProjectSection key={i} project={project} />
            ))}

            {/* General tasks */}
            {parsed.general.length > 0 && (
              <div>
                <h4 className="text-sm font-semibold text-muted-foreground mb-2 flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/50" />
                  General
                </h4>
                <TaskList tasks={parsed.general} />
              </div>
            )}

            {/* Tomorrow */}
            {parsed.tomorrow.length > 0 && (
              <div className="bg-brand/5 rounded-lg p-4">
                <h4 className="text-sm font-semibold mb-2 flex items-center gap-2">
                  📅 Para mañana
                </h4>
                <ul className="space-y-1">
                  {parsed.tomorrow.map((item, i) => (
                    <li key={i} className="text-sm text-muted-foreground flex gap-2">
                      <span className="text-brand">•</span>
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </CardContent>
      )}
    </Card>
  )
}

function ProjectSection({ project }: { project: ParsedProject }) {
  return (
    <div>
      <h4 className="text-sm font-semibold mb-2 flex items-center gap-2">
        <span className="w-1.5 h-1.5 rounded-full bg-brand" />
        {project.name}
        {project.client && (
          <span className="text-xs font-normal text-muted-foreground">({project.client})</span>
        )}
        <span className="text-xs font-normal text-muted-foreground ml-auto">
          {project.tasks.length} tarea{project.tasks.length !== 1 ? "s" : ""}
        </span>
      </h4>
      <TaskList tasks={project.tasks} />
    </div>
  )
}

function TaskList({ tasks }: { tasks: ParsedTask[] }) {
  return (
    <ul className="space-y-1.5 ml-4">
      {tasks.map((task, i) => (
        <li key={i} className="text-sm">
          <span className="text-foreground">{task.description}</span>
          {task.details && (
            <span className="text-muted-foreground ml-1">— {task.details}</span>
          )}
        </li>
      ))}
    </ul>
  )
}
