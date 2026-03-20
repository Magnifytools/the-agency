import { useEffect, useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { timerApi, tasksApi, clientsApi, timeEntriesApi } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select } from "@/components/ui/select"
import { Dialog, DialogHeader, DialogTitle, DialogContent, DialogFooter } from "@/components/ui/dialog"
import { Square, Clock, Play, Plus } from "lucide-react"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"
import type { Task, Client, TimeEntry } from "@/lib/types"

function formatElapsed(startedAt: string): string {
  const elapsed = Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000)
  const h = Math.floor(elapsed / 3600)
  const m = Math.floor((elapsed % 3600) / 60)
  const s = elapsed % 60
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
}

export function ActiveTimerBar() {
  const queryClient = useQueryClient()
  const [elapsed, setElapsed] = useState("")
  const [omniInput, setOmniInput] = useState("")
  const [selectedTaskId, setSelectedTaskId] = useState<string>("")
  const [reminderShown, setReminderShown] = useState(false)

  // Post-stop assignment dialog
  const [showAssignDialog, setShowAssignDialog] = useState(false)
  const [stoppedEntryId, setStoppedEntryId] = useState<number | null>(null)
  const [assignTaskId, setAssignTaskId] = useState<string>("")

  // Quick create task
  const [showQuickCreate, setShowQuickCreate] = useState(false)
  const [qcTitle, setQcTitle] = useState("")
  const [qcClientId, setQcClientId] = useState<string>("")

  const { data: timer } = useQuery({
    queryKey: ["active-timer"],
    queryFn: () => timerApi.active(),
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
  })

  // Fetch user's tasks for selector
  const { data: tasks = [] } = useQuery({
    queryKey: ["my-tasks-timer"],
    queryFn: () => tasksApi.listAll({ assigned_to: "me", status: "in_progress" }),
  })

  // Fetch clients for quick create
  const { data: clients = [] } = useQuery<Client[]>({
    queryKey: ["clients-active"],
    queryFn: () => clientsApi.listAll("active"),
    staleTime: 60_000,
  })

  // eslint-disable-next-line react-hooks/set-state-in-effect -- Timer tick requires setInterval in effect
  useEffect(() => {
    if (!timer?.started_at) return
    setElapsed(formatElapsed(timer.started_at))
    const interval = setInterval(() => {
      setElapsed(formatElapsed(timer.started_at))
    }, 1000)
    return () => clearInterval(interval)
  }, [timer?.started_at])

  // eslint-disable-next-line react-hooks/set-state-in-effect -- Reminder state tracks async 4h threshold
  useEffect(() => {
    if (!timer?.started_at) {
      setReminderShown(false)
      return
    }
    const check = () => {
      const secs = Math.floor((Date.now() - new Date(timer.started_at).getTime()) / 1000)
      if (secs > 14400 && !reminderShown) {
        toast.warning("¡Llevas más de 4 horas con el timer activo! ¿Sigue corriendo?")
        setReminderShown(true)
      }
    }
    check()
    const interval = setInterval(check, 60_000)
    return () => clearInterval(interval)
  }, [timer?.started_at, reminderShown])

  const startMutation = useMutation({
    mutationFn: (data: { task_id?: number; notes?: string }) => timerApi.start(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["active-timer"] })
      setOmniInput("")
      setSelectedTaskId("")
      toast.success("Timer iniciado")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al iniciar timer")),
  })

  const stopMutation = useMutation({
    mutationFn: () => timerApi.stop(),
    onSuccess: (entry: TimeEntry) => {
      queryClient.invalidateQueries({ queryKey: ["active-timer"] })
      queryClient.invalidateQueries({ queryKey: ["time-entries"] })
      // If stopped entry had no task assigned, prompt to assign
      if (!entry.task_id) {
        setStoppedEntryId(entry.id)
        setAssignTaskId("")
        setShowAssignDialog(true)
        toast.success("Timer detenido — asigna una tarea al registro")
      } else {
        toast.success("Timer detenido")
      }
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al detener timer")),
  })

  // Assign task to stopped entry
  const assignMutation = useMutation({
    mutationFn: (data: { entryId: number; taskId: number }) =>
      timeEntriesApi.update(data.entryId, { task_id: data.taskId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["time-entries"] })
      setShowAssignDialog(false)
      setStoppedEntryId(null)
      toast.success("Tarea asignada al registro")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al asignar")),
  })

  // Quick create task
  const createTaskMutation = useMutation({
    mutationFn: (data: { title: string; client_id: number }) =>
      tasksApi.create({ title: data.title, client_id: data.client_id, status: "in_progress" }),
    onSuccess: (task: Task) => {
      queryClient.invalidateQueries({ queryKey: ["my-tasks-timer"] })
      setSelectedTaskId(String(task.id))
      setShowQuickCreate(false)
      setQcTitle("")
      setQcClientId("")
      toast.success("Tarea creada")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al crear tarea")),
  })

  const handleOmniSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const notes = omniInput.trim() || undefined
    const task_id = selectedTaskId ? parseInt(selectedTaskId, 10) : undefined
    if (!notes && !task_id) return
    startMutation.mutate({ task_id, notes })
  }

  // Si no hay timer activo, mostramos el Omni-Input de captura rápida
  if (!timer) {
    return (
      <>
        <div className="bg-card border-b px-4 py-2 flex justify-center items-center">
          <form onSubmit={handleOmniSubmit} className="flex items-center gap-2 w-full max-w-2xl">
            <Select
              value={selectedTaskId}
              onChange={(e) => setSelectedTaskId(e.target.value)}
              className="w-48 shrink-0 h-9 text-xs"
            >
              <option value="">Sin tarea</option>
              {tasks.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.title.length > 35 ? t.title.slice(0, 35) + "..." : t.title}
                </option>
              ))}
            </Select>
            <button
              type="button"
              onClick={() => setShowQuickCreate(true)}
              className="shrink-0 p-1.5 text-muted-foreground hover:text-brand transition-colors rounded"
              title="Crear tarea rápida"
            >
              <Plus className="h-4 w-4" />
            </button>
            <div className="relative flex-1">
              <Input
                value={omniInput}
                onChange={(e) => setOmniInput(e.target.value)}
                placeholder="¿En qué estás trabajando?"
                className="w-full bg-background border-muted pr-10 h-9 text-sm"
              />
              <Button
                type="submit"
                size="sm"
                variant="ghost"
                disabled={(!omniInput.trim() && !selectedTaskId) || startMutation.isPending}
                className="absolute right-0 top-0 h-full px-3 text-muted-foreground hover:text-brand"
              >
                <Play className="h-4 w-4" />
              </Button>
            </div>
          </form>
        </div>

        {/* Quick Create Task Dialog */}
        <Dialog open={showQuickCreate} onOpenChange={setShowQuickCreate}>
          <DialogHeader>
            <DialogTitle>Crear tarea rápida</DialogTitle>
          </DialogHeader>
          <DialogContent>
            <div>
              <label className="text-sm text-muted-foreground mb-1 block">Título *</label>
              <Input
                value={qcTitle}
                onChange={(e) => setQcTitle(e.target.value)}
                placeholder="Nombre de la tarea"
                autoFocus
              />
            </div>
            <div>
              <label className="text-sm text-muted-foreground mb-1 block">Cliente *</label>
              <Select value={qcClientId} onChange={(e) => setQcClientId(e.target.value)}>
                <option value="">Selecciona cliente</option>
                {clients.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </div>
          </DialogContent>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setShowQuickCreate(false)}>
              Cancelar
            </Button>
            <Button
              onClick={() => {
                if (!qcTitle.trim() || !qcClientId) {
                  toast.error("Título y cliente son obligatorios")
                  return
                }
                createTaskMutation.mutate({ title: qcTitle.trim(), client_id: parseInt(qcClientId, 10) })
              }}
              disabled={createTaskMutation.isPending}
            >
              {createTaskMutation.isPending ? "Creando..." : "Crear"}
            </Button>
          </DialogFooter>
        </Dialog>
      </>
    )
  }

  // Si hay timer activo, mostramos la barra superior
  return (
    <>
      <div className="bg-brand text-primary-foreground px-4 py-2 flex items-center justify-between text-sm">
        <div className="flex items-center gap-3">
          <Clock className="h-4 w-4 animate-pulse" />
          <span className="font-bold uppercase tracking-wide">{timer.task_title || "Tarea sin nombre"}</span>
          {timer.client_name && (
            <span className="opacity-75">— {timer.client_name}</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className="font-mono font-bold">{elapsed}</span>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => stopMutation.mutate()}
            disabled={stopMutation.isPending}
            className="bg-white text-brand hover:bg-white/90 font-semibold"
          >
            <Square className="h-3 w-3 mr-1" /> Detener
          </Button>
        </div>
      </div>

      {/* Post-stop Assignment Dialog */}
      <Dialog open={showAssignDialog} onOpenChange={(open) => {
        if (!open) {
          setShowAssignDialog(false)
          setStoppedEntryId(null)
        }
      }}>
        <DialogHeader>
          <DialogTitle>Asignar registro a tarea</DialogTitle>
        </DialogHeader>
        <DialogContent>
          <p className="text-sm text-muted-foreground">
            El tiempo registrado no tiene tarea asignada. Selecciona una tarea para asociarlo:
          </p>
          <Select value={assignTaskId} onChange={(e) => setAssignTaskId(e.target.value)}>
            <option value="">Selecciona tarea</option>
            {tasks.map((t) => (
              <option key={t.id} value={t.id}>
                {t.title.length > 50 ? t.title.slice(0, 50) + "..." : t.title}
              </option>
            ))}
          </Select>
        </DialogContent>
        <DialogFooter>
          <Button variant="ghost" onClick={() => { setShowAssignDialog(false); setStoppedEntryId(null) }}>
            Omitir
          </Button>
          <Button
            onClick={() => {
              if (assignTaskId && stoppedEntryId) {
                assignMutation.mutate({ entryId: stoppedEntryId, taskId: parseInt(assignTaskId, 10) })
              }
            }}
            disabled={!assignTaskId || assignMutation.isPending}
          >
            {assignMutation.isPending ? "Asignando..." : "Asignar"}
          </Button>
        </DialogFooter>
      </Dialog>
    </>
  )
}
