import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { timeEntriesApi } from "@/lib/api";
import type { TimeEntry } from "@/lib/types";
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { Trash2, Pencil, Check, X } from "lucide-react";
import { toast } from "sonner";
import { getErrorMessage } from "@/lib/utils";
import { invalidateTimeChange, timeKeys } from "@/lib/query-keys";
import { formatCivilDate, timeEntryBusinessDate } from "@/lib/dates";
import { useBusinessDate } from "@/hooks/use-business-date";
import { useAuth } from "@/context/auth-context";

interface TimeLogDialogProps {
  taskId: number;
  taskTitle: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  taskRetired?: boolean;
}

function formatMinutes(m: number): string {
  const h = Math.floor(m / 60);
  const mins = m % 60;
  if (h && mins) return `${h}h ${mins}m`;
  if (h) return `${h}h`;
  return `${mins}m`;
}

export function TimeLogDialog({
  taskId,
  taskTitle,
  open,
  onOpenChange,
  taskRetired = false,
}: TimeLogDialogProps) {
  const queryClient = useQueryClient();
  const businessToday = useBusinessDate();
  const { user, isAdmin, hasPermission } = useAuth();
  const canRead = hasPermission("timesheet");
  const canWrite = hasPermission("timesheet", true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editHours, setEditHours] = useState(0);
  const [editMins, setEditMins] = useState(0);
  const [editNotes, setEditNotes] = useState("");

  const entriesQuery = useQuery({
    queryKey: timeKeys.task(taskId),
    queryFn: () => timeEntriesApi.list({ task_id: taskId }),
    enabled: open && canRead,
    retry: false,
  });
  const entries = entriesQuery.data ?? [];

  const invalidateEntries = () => invalidateTimeChange(queryClient);

  const createMutation = useMutation({
    mutationFn: (data: {
      minutes: number;
      task_id: number;
      notes?: string;
      date: string;
    }) => timeEntriesApi.create(data),
    onSuccess: () => {
      invalidateEntries();
      setShowForm(false);
      toast.success("Entrada de tiempo creada");
    },
    onError: (err) =>
      toast.error(getErrorMessage(err, "Error al crear entrada")),
  });

  const updateMutation = useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: number;
      data: { minutes?: number; notes?: string };
    }) => timeEntriesApi.update(id, data),
    onSuccess: () => {
      invalidateEntries();
      setEditingId(null);
      toast.success("Entrada actualizada");
    },
    onError: (err) =>
      toast.error(getErrorMessage(err, "Error al actualizar entrada")),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => timeEntriesApi.delete(id),
    onSuccess: () => {
      invalidateEntries();
      toast.success("Entrada eliminada");
    },
    onError: (err) =>
      toast.error(getErrorMessage(err, "Error al eliminar entrada")),
  });

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (taskRetired) return;
    const fd = new FormData(e.currentTarget);
    const hours = Number(fd.get("hours") || 0);
    const mins = Number(fd.get("mins") || 0);
    const totalMinutes = hours * 60 + mins;
    if (totalMinutes <= 0) {
      toast.error("Introduce al menos 1 minuto");
      return;
    }
    createMutation.mutate({
      minutes: totalMinutes,
      task_id: taskId,
      notes: (fd.get("notes") as string) || undefined,
      date: String(fd.get("date")),
    });
  };

  const startEdit = (entry: TimeEntry) => {
    const m = entry.minutes || 0;
    setEditingId(entry.id);
    setEditHours(Math.floor(m / 60));
    setEditMins(m % 60);
    setEditNotes(entry.notes || "");
  };

  const saveEdit = () => {
    if (editingId === null) return;
    const totalMinutes = editHours * 60 + editMins;
    if (totalMinutes <= 0) {
      toast.error("Introduce al menos 1 minuto");
      return;
    }
    updateMutation.mutate({
      id: editingId,
      data: { minutes: totalMinutes, notes: editNotes || undefined },
    });
  };

  const cancelEdit = () => {
    setEditingId(null);
  };

  const totalMinutes = entries.reduce(
    (sum: number, e: TimeEntry) => sum + (e.minutes || 0),
    0,
  );
  const canChangeEntry = (entry: TimeEntry) =>
    canWrite && (isAdmin || entry.user_id === user?.id);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogHeader>
        <DialogTitle>Registro de tiempo — {taskTitle}</DialogTitle>
      </DialogHeader>
      {!canRead ? (
        <p role="status" className="text-sm text-muted-foreground">
          No tienes permiso para consultar registros de tiempo.
        </p>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              Total:{" "}
              <span className="font-bold text-brand mono">
                {formatMinutes(totalMinutes)}
              </span>
            </p>
            {canWrite && !taskRetired && (
              <Button
                type="button"
                size="sm"
                onClick={() => setShowForm(!showForm)}
              >
                {showForm ? "Cancelar" : "Añadir manual"}
              </Button>
            )}
          </div>

          {taskRetired && <p className="text-sm text-muted-foreground">La tarea está retirada. Puedes consultar y corregir sus horas existentes, pero no añadir nuevas entradas.</p>}
          {showForm && !taskRetired && (
            <form
              onSubmit={handleSubmit}
              className="border border-brand/20 p-3 space-y-3"
            >
              <div className="flex gap-3">
                <div className="space-y-1">
                  <Label htmlFor="time-entry-date">Fecha</Label>
                  <Input
                    id="time-entry-date"
                    name="date"
                    type="date"
                    defaultValue={businessToday}
                    required
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="hours">Horas</Label>
                  <Input
                    id="hours"
                    name="hours"
                    type="number"
                    min="0"
                    placeholder="0"
                    className="w-20"
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="mins">Minutos</Label>
                  <Input
                    id="mins"
                    name="mins"
                    type="number"
                    min="0"
                    max="59"
                    placeholder="0"
                    className="w-20"
                  />
                </div>
              </div>
              <div className="space-y-1">
                <Label htmlFor="notes">Notas</Label>
                <Textarea id="notes" name="notes" rows={2} />
              </div>
              <Button
                type="submit"
                size="sm"
                disabled={createMutation.isPending}
              >
                {createMutation.isPending ? "Guardando…" : "Guardar"}
              </Button>
            </form>
          )}

          {entriesQuery.isLoading ? (
            <p
              role="status"
              className="text-sm text-muted-foreground text-center py-4"
            >
              Cargando registros…
            </p>
          ) : entriesQuery.isError ? (
            <div
              role="alert"
              className="flex items-center justify-between gap-3 text-sm text-destructive"
            >
              <span>
                {getErrorMessage(
                  entriesQuery.error,
                  "No se pudieron cargar los registros",
                )}
              </span>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => entriesQuery.refetch()}
              >
                Reintentar
              </Button>
            </div>
          ) : entries.length > 0 ? (
            <Table className="block w-full sm:table">
              <TableHeader className="hidden sm:table-header-group">
                <TableRow>
                  <TableHead>Fecha</TableHead>
                  <TableHead>Duración</TableHead>
                  <TableHead>Notas</TableHead>
                  <TableHead className="w-20"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody className="block sm:table-row-group">
                {entries.map((e: TimeEntry) => (
                  <TableRow key={e.id} className="mb-3 block rounded-md border p-3 sm:mb-0 sm:table-row sm:rounded-none sm:border-0 sm:p-0">
                    {editingId === e.id && canChangeEntry(e) ? (
                      <>
                        <TableCell className="flex items-center justify-between gap-3 px-0 py-1 mono sm:table-cell sm:px-4 sm:py-3">
                          <span className="text-xs font-medium text-muted-foreground sm:hidden">Fecha</span>
                          {formatCivilDate(timeEntryBusinessDate(e))}
                        </TableCell>
                        <TableCell className="flex items-center justify-between gap-3 px-0 py-1 sm:table-cell sm:px-4 sm:py-3">
                          <span className="text-xs font-medium text-muted-foreground sm:hidden">Duración</span>
                          <div className="flex items-center gap-1">
                            <Input
                              type="number"
                              min="0"
                              aria-label="Horas"
                              value={editHours}
                              onChange={(ev) =>
                                setEditHours(Number(ev.target.value))
                              }
                              className="w-14 h-7 text-xs"
                              placeholder="h"
                            />
                            <span className="text-xs text-muted-foreground">
                              h
                            </span>
                            <Input
                              type="number"
                              min="0"
                              max="59"
                              aria-label="Minutos"
                              value={editMins}
                              onChange={(ev) =>
                                setEditMins(Number(ev.target.value))
                              }
                              className="w-14 h-7 text-xs"
                              placeholder="m"
                            />
                            <span className="text-xs text-muted-foreground">
                              m
                            </span>
                          </div>
                        </TableCell>
                        <TableCell className="flex items-center justify-between gap-3 px-0 py-1 sm:table-cell sm:px-4 sm:py-3">
                          <span className="text-xs font-medium text-muted-foreground sm:hidden">Notas</span>
                          <Input
                            aria-label="Notas"
                            value={editNotes}
                            onChange={(ev) => setEditNotes(ev.target.value)}
                            className="h-7 text-xs"
                            placeholder="Notas..."
                          />
                        </TableCell>
                        <TableCell className="flex items-center justify-end gap-3 px-0 py-1 sm:table-cell sm:px-4 sm:py-3">
                          <span className="text-xs font-medium text-muted-foreground sm:hidden">Acciones</span>
                          <div className="flex items-center gap-1">
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7"
                              onClick={saveEdit}
                              disabled={updateMutation.isPending}
                              aria-label="Guardar cambios"
                            >
                              <Check className="h-3.5 w-3.5 text-green-600" />
                            </Button>
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7"
                              onClick={cancelEdit}
                              disabled={updateMutation.isPending}
                              aria-label="Cancelar edición"
                            >
                              <X className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        </TableCell>
                      </>
                    ) : (
                      <>
                        <TableCell className="flex items-center justify-between gap-3 px-0 py-1 mono sm:table-cell sm:px-4 sm:py-3">
                          <span className="text-xs font-medium text-muted-foreground sm:hidden">Fecha</span>
                          {formatCivilDate(timeEntryBusinessDate(e))}
                        </TableCell>
                        <TableCell className="flex items-center justify-between gap-3 px-0 py-1 mono sm:table-cell sm:px-4 sm:py-3">
                          <span className="text-xs font-medium text-muted-foreground sm:hidden">Duración</span>
                          {e.minutes ? formatMinutes(e.minutes) : "-"}
                        </TableCell>
                        <TableCell className="flex items-center justify-between gap-3 px-0 py-1 sm:table-cell sm:max-w-[200px] sm:px-4 sm:py-3">
                          <span className="text-xs font-medium text-muted-foreground sm:hidden">Notas</span>
                          <span className="min-w-0 truncate">{e.notes || "-"}</span>
                        </TableCell>
                        <TableCell className="flex items-center justify-end gap-3 px-0 py-1 sm:table-cell sm:px-4 sm:py-3">
                          <span className="text-xs font-medium text-muted-foreground sm:hidden">Acciones</span>
                          {canChangeEntry(e) && (
                            <div className="flex items-center gap-1">
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7"
                                onClick={() => startEdit(e)}
                                aria-label={`Editar registro del ${formatCivilDate(timeEntryBusinessDate(e))}`}
                              >
                                <Pencil className="h-3.5 w-3.5" />
                              </Button>
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7"
                                disabled={deleteMutation.isPending}
                                aria-label={`Eliminar registro del ${formatCivilDate(timeEntryBusinessDate(e))}`}
                                onClick={() => {
                                  if (
                                    window.confirm(
                                      "¿Eliminar esta entrada de tiempo?",
                                    )
                                  ) {
                                    deleteMutation.mutate(e.id);
                                  }
                                }}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                            </div>
                          )}
                        </TableCell>
                      </>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <p className="text-sm text-muted-foreground text-center py-4">
              No hay entradas de tiempo
            </p>
          )}
        </div>
      )}
    </Dialog>
  );
}
