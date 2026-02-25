import { useState } from "react"
import { Link } from "react-router-dom"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { clientsApi } from "@/lib/api"
import type { Client, ClientCreate, ClientStatus } from "@/lib/types"
import { usePagination } from "@/hooks/use-pagination"
import { Pagination } from "@/components/ui/pagination"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Select } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { Plus, Pencil, Trash2, Users } from "lucide-react"
import { EmptyTableState } from "@/components/ui/empty-state"
import { toast } from "sonner"
import { getErrorMessage } from "@/lib/utils"

const STATUS_TABS: { label: string; value: ClientStatus | "all" }[] = [
  { label: "Todos", value: "all" },
  { label: "Activos", value: "active" },
  { label: "Pausados", value: "paused" },
  { label: "Finalizados", value: "finished" },
]

const statusBadge = (status: ClientStatus) => {
  const map: Record<ClientStatus, { label: string; variant: "success" | "warning" | "secondary" }> = {
    active: { label: "Activo", variant: "success" },
    paused: { label: "Pausado", variant: "warning" },
    finished: { label: "Finalizado", variant: "secondary" },
  }
  const { label, variant } = map[status]
  return <Badge variant={variant}>{label}</Badge>
}

export default function ClientsPage() {
  const queryClient = useQueryClient()
  const { page, pageSize, setPage, reset } = usePagination(25)
  const [tab, setTab] = useState<ClientStatus | "all">("all")
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<Client | null>(null)
  const [deleteId, setDeleteId] = useState<number | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ["clients", tab, page, pageSize],
    queryFn: () => clientsApi.list({ status: tab === "all" ? undefined : tab, page, page_size: pageSize }),
  })
  const clients = data?.items ?? []

  const createMutation = useMutation({
    mutationFn: (data: ClientCreate) => clientsApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["clients"] })
      closeDialog()
      toast.success("Cliente creado")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al crear cliente")),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<ClientCreate> }) => clientsApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["clients"] })
      closeDialog()
      toast.success("Cliente actualizado")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar cliente")),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => clientsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["clients"] })
      toast.success("Cliente archivado")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al archivar cliente")),
  })

  const closeDialog = () => {
    setDialogOpen(false)
    setEditing(null)
  }

  const openCreate = () => {
    setEditing(null)
    setDialogOpen(true)
  }

  const openEdit = (client: Client) => {
    setEditing(client)
    setDialogOpen(true)
  }

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const fd = new FormData(e.currentTarget)
    const data: ClientCreate = {
      name: fd.get("name") as string,
      email: (fd.get("email") as string) || null,
      phone: (fd.get("phone") as string) || null,
      company: (fd.get("company") as string) || null,
      website: (fd.get("website") as string) || null,
      contract_type: (fd.get("contract_type") as ClientCreate["contract_type"]) || "monthly",
      monthly_budget: fd.get("monthly_budget") ? Number(fd.get("monthly_budget")) : null,
      status: (fd.get("status") as ClientStatus) || "active",
      notes: (fd.get("notes") as string) || null,
    }
    if (editing) {
      updateMutation.mutate({ id: editing.id, data })
    } else {
      createMutation.mutate(data)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold uppercase tracking-wide">Clientes</h2>
          {data && <p className="text-sm text-muted-foreground mt-1">{data.total} clientes · {clients.length} en vista</p>}
        </div>
        <Button onClick={openCreate}>
          <Plus className="h-4 w-4 mr-2" /> Nuevo cliente
        </Button>
      </div>

      {/* Tabs */}
      <div className="flex gap-2">
        {STATUS_TABS.map((t) => (
          <Button
            key={t.value}
            variant={tab === t.value ? "default" : "outline"}
            size="sm"
            onClick={() => { setTab(t.value); reset() }}
          >
            {t.label}
          </Button>
        ))}
      </div>

      {/* Table */}
      {isLoading ? (
        <p className="text-muted-foreground">Cargando...</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nombre</TableHead>
              <TableHead>Empresa</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Contrato</TableHead>
              <TableHead>Presupuesto</TableHead>
              <TableHead>Estado</TableHead>
              <TableHead className="w-24">Acciones</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {clients.map((c) => (
              <TableRow key={c.id}>
                <TableCell className="font-medium">
                  <Link to={`/clients/${c.id}`} className="hover:underline text-brand">
                    {c.name}
                  </Link>
                </TableCell>
                <TableCell>{c.company || "-"}</TableCell>
                <TableCell>{c.email || "-"}</TableCell>
                <TableCell>{c.contract_type === "monthly" ? "Mensual" : "Puntual"}</TableCell>
                <TableCell className="mono">{c.monthly_budget != null ? `${c.monthly_budget}€` : "-"}</TableCell>
                <TableCell>{statusBadge(c.status)}</TableCell>
                <TableCell>
                  <div className="flex gap-1">
                    <Button variant="ghost" size="icon" onClick={() => openEdit(c)}>
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button variant="ghost" size="icon" onClick={() => setDeleteId(c.id)}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
            {clients.length === 0 && (
              <EmptyTableState colSpan={7} icon={Users} title="Sin clientes todavía" description="Aquí verás tus clientes con estado, presupuesto y contacto." />
            )}
          </TableBody>
        </Table>
      )}

      <Pagination page={page} pageSize={pageSize} total={data?.total ?? 0} onPageChange={setPage} />

      {/* Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogHeader>
          <DialogTitle>{editing ? "Editar cliente" : "Nuevo cliente"}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="name">Nombre *</Label>
              <Input id="name" name="name" defaultValue={editing?.name ?? ""} required />
            </div>
            <div className="space-y-2">
              <Label htmlFor="company">Empresa</Label>
              <Input id="company" name="company" defaultValue={editing?.company ?? ""} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" name="email" type="email" defaultValue={editing?.email ?? ""} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="phone">Teléfono</Label>
              <Input id="phone" name="phone" defaultValue={editing?.phone ?? ""} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="website">Web</Label>
              <Input id="website" name="website" defaultValue={editing?.website ?? ""} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="contract_type">Tipo de contrato</Label>
              <Select id="contract_type" name="contract_type" defaultValue={editing?.contract_type ?? "monthly"}>
                <option value="monthly">Mensual</option>
                <option value="one_time">Puntual</option>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="monthly_budget">Presupuesto mensual (€)</Label>
              <Input
                id="monthly_budget"
                name="monthly_budget"
                type="number"
                step="0.01"
                defaultValue={editing?.monthly_budget ?? ""}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="status">Estado</Label>
              <Select id="status" name="status" defaultValue={editing?.status ?? "active"}>
                <option value="active">Activo</option>
                <option value="paused">Pausado</option>
                <option value="finished">Finalizado</option>
              </Select>
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="notes">Notas</Label>
            <Textarea id="notes" name="notes" defaultValue={editing?.notes ?? ""} />
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={closeDialog}>
              Cancelar
            </Button>
            <Button type="submit">{editing ? "Guardar" : "Crear"}</Button>
          </div>
        </form>
      </Dialog>

      {/* Delete Confirm */}
      <ConfirmDialog
        open={deleteId !== null}
        onOpenChange={(open) => !open && setDeleteId(null)}
        title="Archivar cliente"
        description="El cliente se marcara como finalizado. Sus tareas no se eliminaran."
        confirmLabel="Archivar"
        onConfirm={() => {
          if (deleteId !== null) {
            deleteMutation.mutate(deleteId)
            setDeleteId(null)
          }
        }}
      />
    </div>
  )
}
