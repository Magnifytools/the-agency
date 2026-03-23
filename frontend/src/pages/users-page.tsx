import { useState, useEffect } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { usersApi } from "@/lib/api"
import type { User, UserPermission } from "@/lib/types"
import { useAuth } from "@/context/auth-context"
import { usePagination } from "@/hooks/use-pagination"
import { Pagination } from "@/components/ui/pagination"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { Pencil, Plus, Shield } from "lucide-react"
import { toast } from "sonner"
import type { UserCreate, UserRole } from "@/lib/types"

const REGIONES = [
  "MAD", "CAT", "AND", "VAL", "GAL", "PV", "CYL", "CLM",
  "ARA", "EXT", "MUR", "NAV", "AST", "CAN", "BAL", "RIO", "CANT", "CEU", "MEL",
] as const
import { getErrorMessage } from "@/lib/utils"
import { formatCurrency } from "@/lib/format"
import { SkeletonTableRow } from "@/components/ui/skeleton"

const ALL_MODULES: { key: string; label: string; group: string }[] = [
  { key: "dashboard", label: "Dashboard", group: "General" },
  { key: "clients", label: "Clientes", group: "General" },
  { key: "projects", label: "Proyectos", group: "General" },
  { key: "tasks", label: "Tareas", group: "General" },
  { key: "timesheet", label: "Timesheet", group: "General" },
  { key: "pm", label: "PM", group: "General" },
  { key: "digests", label: "Digests", group: "General" },
  { key: "billing", label: "Facturación", group: "General" },
  { key: "communications", label: "Comunicaciones", group: "General" },
  { key: "leads", label: "Leads", group: "Crecimiento" },
  { key: "proposals", label: "Propuestas", group: "Crecimiento" },
  { key: "growth", label: "Pipeline", group: "Crecimiento" },
  { key: "reports", label: "Informes", group: "Crecimiento" },
  { key: "finance_dashboard", label: "Dashboard Financiero", group: "Finanzas" },
  { key: "finance_income", label: "Ingresos", group: "Finanzas" },
  { key: "finance_expenses", label: "Gastos", group: "Finanzas" },
  { key: "finance_taxes", label: "Impuestos", group: "Finanzas" },
  { key: "finance_forecasts", label: "Previsiones", group: "Finanzas" },
  { key: "finance_advisor", label: "Advisor", group: "Finanzas" },
  { key: "finance_import", label: "Importar", group: "Finanzas" },
]

const MODULE_GROUPS = [...new Set(ALL_MODULES.map((m) => m.group))]

export default function UsersPage() {
  const queryClient = useQueryClient()
  const { page, pageSize, setPage } = usePagination(25)
  const { user: currentUser } = useAuth()
  const [editing, setEditing] = useState<User | null>(null)
  const [permissionsUser, setPermissionsUser] = useState<User | null>(null)
  const [permissionsState, setPermissionsState] = useState<Record<string, { read: boolean; write: boolean }>>({})

  const [isInviteOpen, setIsInviteOpen] = useState(false)
  const [inviteData, setInviteData] = useState<UserCreate>({
    email: "",
    password: "",
    full_name: "",
    role: "member",
    hourly_rate: null,
  })

  const { data, isLoading } = useQuery({
    queryKey: ["users", page, pageSize],
    queryFn: () => usersApi.list({ page, page_size: pageSize }),
  })
  const users = data?.items ?? []

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<User> }) =>
      usersApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] })
      setEditing(null)
      toast.success("Usuario actualizado")
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar")),
  })

  const createMutation = useMutation({
    mutationFn: (data: UserCreate) => usersApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] })
      toast.success("Miembro invitado correctamente")
      setIsInviteOpen(false)
      setInviteData({ email: "", password: "", full_name: "", role: "member", hourly_rate: null })
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al invitar")),
  })

  // Permissions
  const permissionsQuery = useQuery({
    queryKey: ["user-permissions", permissionsUser?.id],
    queryFn: () => usersApi.getPermissions(permissionsUser!.id),
    enabled: !!permissionsUser,
  })

  useEffect(() => {
    if (permissionsQuery.data) {
      const state: Record<string, { read: boolean; write: boolean }> = {}
      for (const p of permissionsQuery.data) {
        state[p.module] = { read: p.can_read, write: p.can_write }
      }
      setPermissionsState(state)
    }
  }, [permissionsQuery.data])

  const permissionsMutation = useMutation({
    mutationFn: (perms: UserPermission[]) =>
      usersApi.updatePermissions(permissionsUser!.id, perms),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["user-permissions", permissionsUser?.id] })
      queryClient.invalidateQueries({ queryKey: ["users"] })
      toast.success("Permisos actualizados")
      setPermissionsUser(null)
    },
    onError: (err) => toast.error(getErrorMessage(err, "Error al actualizar permisos")),
  })

  const handleSavePermissions = () => {
    const perms: UserPermission[] = Object.entries(permissionsState)
      .filter(([, v]) => v.read || v.write)
      .map(([module, v]) => ({ module, can_read: v.read, can_write: v.write }))
    permissionsMutation.mutate(perms)
  }

  const toggleModule = (mod: string, field: "read" | "write") => {
    setPermissionsState((prev) => {
      const cur = prev[mod] || { read: false, write: false }
      const next = { ...cur, [field]: !cur[field] }
      // If enabling write, also enable read
      if (field === "write" && next.write) next.read = true
      // If disabling read, also disable write
      if (field === "read" && !next.read) next.write = false
      return { ...prev, [mod]: next }
    })
  }

  const handleSubmitEdit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!editing) return
    const fd = new FormData(e.currentTarget)
    const data: Partial<User> = {
      full_name: fd.get("full_name") as string,
      short_name: (fd.get("short_name") as string) || null,
      job_title: (fd.get("job_title") as string) || null,
      birthday: (fd.get("birthday") as string) || null,
      locality: (fd.get("locality") as string) || null,
      region: (fd.get("region") as string) || null,
      morning_reminder_time: (fd.get("morning_reminder_time") as string) || null,
      evening_reminder_time: (fd.get("evening_reminder_time") as string) || null,
    }
    if (currentUser?.role === "admin") {
      data.hourly_rate = fd.get("hourly_rate") ? Number(fd.get("hourly_rate")) : null
      data.role = fd.get("role") as UserRole
    }
    updateMutation.mutate({ id: editing.id, data })
  }

  const handleSubmitInvite = (e: React.FormEvent) => {
    e.preventDefault()
    createMutation.mutate(inviteData)
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:justify-between sm:items-center">
        <h2 className="text-2xl font-bold uppercase tracking-wide">Equipo</h2>
        {currentUser?.role === "admin" && (
          <Button onClick={() => setIsInviteOpen(true)} className="w-full sm:w-auto">
            <Plus className="h-4 w-4 mr-2" /> Invitar Miembro
          </Button>
        )}
      </div>

      {isLoading ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nombre</TableHead>
              <TableHead>Nombre corto</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Puesto</TableHead>
              <TableHead>Ciudad</TableHead>
              <TableHead>Rol</TableHead>
              <TableHead>Tarifa/h</TableHead>
              <TableHead>Acciones</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {Array.from({ length: 3 }).map((_, i) => <SkeletonTableRow key={i} cols={8} />)}
          </TableBody>
        </Table>
      ) : (
        <>
          <div className="hidden md:block">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Nombre</TableHead>
                  <TableHead>Nombre corto</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead>Puesto</TableHead>
                  <TableHead>Ciudad</TableHead>
                  <TableHead>Rol</TableHead>
                  <TableHead>Tarifa/h</TableHead>
                  <TableHead className="w-12"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {users.map((u) => (
                  <TableRow key={u.id}>
                    <TableCell className="font-medium">{u.full_name}</TableCell>
                    <TableCell>{u.short_name ?? "-"}</TableCell>
                    <TableCell>{u.email}</TableCell>
                    <TableCell>{u.job_title ?? "-"}</TableCell>
                    <TableCell>{u.locality ?? "-"}</TableCell>
                    <TableCell>
                      <Badge variant={u.role === "admin" ? "default" : "secondary"}>
                        {u.role === "admin" ? "Admin" : "Miembro"}
                      </Badge>
                    </TableCell>
                    <TableCell className="mono">{u.hourly_rate != null ? `${formatCurrency(u.hourly_rate)}/h` : "-"}</TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        <Button variant="ghost" size="icon" aria-label="Editar usuario" onClick={() => setEditing(u)}>
                          <Pencil className="h-4 w-4" />
                        </Button>
                        {currentUser?.role === "admin" && u.role !== "admin" && (
                          <Button variant="ghost" size="icon" aria-label="Permisos" onClick={() => setPermissionsUser(u)}>
                            <Shield className="h-4 w-4" />
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="md:hidden space-y-3">
            {users.map((u) => (
              <div key={u.id} className="rounded-lg border border-border p-3 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <p className="font-medium">{u.full_name}</p>
                    {u.job_title && <p className="text-xs text-muted-foreground">{u.job_title}</p>}
                  </div>
                  <Badge variant={u.role === "admin" ? "default" : "secondary"}>
                    {u.role === "admin" ? "Admin" : "Miembro"}
                  </Badge>
                </div>
                <p className="text-sm text-muted-foreground break-all">{u.email}</p>
                {u.locality && <p className="text-xs text-muted-foreground">{u.locality}</p>}
                <div className="flex items-center justify-between">
                  <p className="text-sm mono">{u.hourly_rate != null ? `${formatCurrency(u.hourly_rate)}/h` : "-"}</p>
                  <div className="flex gap-2">
                    {currentUser?.role === "admin" && u.role !== "admin" && (
                      <Button variant="outline" size="sm" onClick={() => setPermissionsUser(u)}>
                        <Shield className="h-4 w-4 mr-2" />
                        Permisos
                      </Button>
                    )}
                    <Button variant="outline" size="sm" onClick={() => setEditing(u)}>
                      <Pencil className="h-4 w-4 mr-2" />
                      Editar
                    </Button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      <Pagination page={page} pageSize={pageSize} total={data?.total ?? 0} onPageChange={setPage} />

      {/* Edit Dialog */}
      <Dialog open={!!editing} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogHeader>
          <DialogTitle>Editar usuario</DialogTitle>
        </DialogHeader>
        {editing && (
          <form onSubmit={handleSubmitEdit} className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="short_name">Nombre corto</Label>
                <Input id="short_name" name="short_name" defaultValue={editing?.short_name ?? ""} placeholder="David" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="full_name">Nombre completo</Label>
                <Input id="full_name" name="full_name" defaultValue={editing?.full_name} required />
              </div>
              <div className="space-y-2">
                <Label htmlFor="job_title">Puesto</Label>
                <Input id="job_title" name="job_title" defaultValue={editing?.job_title ?? ""} placeholder="SEO Strategist" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="birthday">Cumpleanos</Label>
                <Input id="birthday" name="birthday" type="date" defaultValue={editing?.birthday ?? ""} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="locality">Ciudad</Label>
                <Input id="locality" name="locality" defaultValue={editing?.locality ?? ""} placeholder="Madrid" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="region">Comunidad Autonoma</Label>
                <Select id="region" name="region" defaultValue={editing?.region ?? ""}>
                  <option value="">Seleccionar...</option>
                  {REGIONES.map((r) => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="morning_reminder_time">Reminder manana</Label>
                <Input id="morning_reminder_time" name="morning_reminder_time" type="time" defaultValue={editing?.morning_reminder_time ?? "09:00"} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="evening_reminder_time">Recap noche</Label>
                <Input id="evening_reminder_time" name="evening_reminder_time" type="time" defaultValue={editing?.evening_reminder_time ?? "18:00"} />
              </div>
            </div>
            {currentUser?.role === "admin" && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2 border-t border-border">
                <div className="space-y-2">
                  <Label htmlFor="hourly_rate">Tarifa por hora (€)</Label>
                  <Input
                    id="hourly_rate"
                    name="hourly_rate"
                    type="number"
                    step="0.01"
                    defaultValue={editing?.hourly_rate ?? ""}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="role">Rol</Label>
                  <Select id="role" name="role" defaultValue={editing?.role}>
                    <option value="admin">Admin</option>
                    <option value="member">Miembro</option>
                  </Select>
                </div>
              </div>
            )}
            <div className="flex justify-end gap-2 pt-4">
              <Button type="button" variant="outline" onClick={() => setEditing(null)}>
                Cancelar
              </Button>
              <Button type="submit">Guardar</Button>
            </div>
          </form>
        )}
      </Dialog>

      {/* Permissions Dialog */}
      <Dialog open={!!permissionsUser} onOpenChange={(open) => !open && setPermissionsUser(null)}>
        <DialogHeader>
          <DialogTitle>Permisos — {permissionsUser?.full_name}</DialogTitle>
        </DialogHeader>
        {permissionsQuery.isLoading ? (
          <p className="text-sm text-muted-foreground py-4">Cargando permisos...</p>
        ) : (
          <div className="space-y-5 pt-4">
            {MODULE_GROUPS.map((group) => (
              <div key={group}>
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">{group}</p>
                <div className="space-y-1">
                  {ALL_MODULES.filter((m) => m.group === group).map((mod) => {
                    const state = permissionsState[mod.key] || { read: false, write: false }
                    return (
                      <div key={mod.key} className="flex items-center justify-between py-1.5 px-2 rounded hover:bg-muted/50">
                        <span className="text-sm">{mod.label}</span>
                        <div className="flex gap-3">
                          <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer">
                            <input
                              type="checkbox"
                              checked={state.read}
                              onChange={() => toggleModule(mod.key, "read")}
                              className="rounded border-border"
                            />
                            Leer
                          </label>
                          <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer">
                            <input
                              type="checkbox"
                              checked={state.write}
                              onChange={() => toggleModule(mod.key, "write")}
                              className="rounded border-border"
                            />
                            Escribir
                          </label>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            ))}
            <div className="flex justify-end gap-2 pt-4 border-t border-border">
              <Button variant="outline" onClick={() => setPermissionsUser(null)}>Cancelar</Button>
              <Button onClick={handleSavePermissions} disabled={permissionsMutation.isPending}>
                {permissionsMutation.isPending ? "Guardando..." : "Guardar permisos"}
              </Button>
            </div>
          </div>
        )}
      </Dialog>

      {/* Invite Dialog */}
      <Dialog open={isInviteOpen} onOpenChange={setIsInviteOpen}>
        <DialogHeader>
          <DialogTitle>Invitar al Equipo</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmitInvite} className="space-y-4 pt-4">
          <div className="space-y-2">
            <Label htmlFor="new_full_name">Nombre completo</Label>
            <Input
              id="new_full_name"
              required
              value={inviteData.full_name}
              onChange={(e) => setInviteData({ ...inviteData, full_name: e.target.value })}
              placeholder="Ej. Juan Pérez"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="new_email">Email</Label>
            <Input
              id="new_email"
              type="email"
              required
              value={inviteData.email}
              onChange={(e) => setInviteData({ ...inviteData, email: e.target.value })}
              placeholder="juan@agencia.com"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="new_password">Contraseña inicial</Label>
            <Input
              id="new_password"
              type="password"
              required
              value={inviteData.password}
              onChange={(e) => setInviteData({ ...inviteData, password: e.target.value })}
              placeholder="••••••••"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="new_role">Rol</Label>
            <Select
              id="new_role"
              value={inviteData.role}
              onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setInviteData({ ...inviteData, role: e.target.value as UserRole })}
            >
              <option value="member">Miembro</option>
              <option value="admin">Administrador</option>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="new_hourly">Tarifa por hora (€)</Label>
            <Input
              id="new_hourly"
              type="number"
              step="0.01"
              min="0"
              value={inviteData.hourly_rate || ""}
              onChange={(e) =>
                setInviteData({
                  ...inviteData,
                  hourly_rate: e.target.value ? parseFloat(e.target.value) : null,
                })
              }
            />
          </div>
          <div className="flex justify-end gap-2 pt-4">
            <Button type="button" variant="outline" onClick={() => setIsInviteOpen(false)}>
              Cancelar
            </Button>
            <Button type="submit" disabled={createMutation.isPending}>
              Invitar
            </Button>
          </div>
        </form>
      </Dialog>
    </div>
  )
}
