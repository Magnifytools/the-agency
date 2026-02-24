import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { usersApi } from "@/lib/api"
import type { User } from "@/lib/types"
import { useAuth } from "@/context/auth-context"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table"
import { Pencil, Plus } from "lucide-react"
import { toast } from "sonner"
import type { UserCreate, UserRole } from "@/lib/types"

export default function UsersPage() {
  const queryClient = useQueryClient()
  const { user: currentUser } = useAuth()
  const [editing, setEditing] = useState<User | null>(null)

  const [isInviteOpen, setIsInviteOpen] = useState(false)
  const [inviteData, setInviteData] = useState<UserCreate>({
    email: "",
    password: "",
    full_name: "",
    role: "member",
    hourly_rate: null,
  })

  const { data: users = [], isLoading } = useQuery({
    queryKey: ["users"],
    queryFn: () => usersApi.list(),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<User> }) =>
      usersApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] })
      setEditing(null)
      toast.success("Usuario actualizado")
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Error al actualizar"),
  })

  const createMutation = useMutation({
    mutationFn: (data: UserCreate) => usersApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] })
      toast.success("Miembro invitado correctamente")
      setIsInviteOpen(false)
      setInviteData({ email: "", password: "", full_name: "", role: "member", hourly_rate: null })
    },
    onError: (err: any) => toast.error(err.response?.data?.detail || "Error al invitar"),
  })

  const handleSubmitEdit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!editing) return
    const fd = new FormData(e.currentTarget)
    const data: Partial<User> = {
      full_name: fd.get("full_name") as string,
      hourly_rate: fd.get("hourly_rate") ? Number(fd.get("hourly_rate")) : null,
    }
    if (currentUser?.role === "admin") {
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
      <div className="flex justify-between items-center">
        <h2 className="text-2xl font-bold uppercase tracking-wide">Equipo</h2>
        {currentUser?.role === "admin" && (
          <Button onClick={() => setIsInviteOpen(true)}>
            <Plus className="h-4 w-4 mr-2" /> Invitar Miembro
          </Button>
        )}
      </div>

      {isLoading ? (
        <p className="text-muted-foreground">Cargando...</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nombre</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Rol</TableHead>
              <TableHead>Tarifa/h</TableHead>
              <TableHead className="w-12"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {users.map((u) => (
              <TableRow key={u.id}>
                <TableCell className="font-medium">{u.full_name}</TableCell>
                <TableCell>{u.email}</TableCell>
                <TableCell>
                  <Badge variant={u.role === "admin" ? "default" : "secondary"}>
                    {u.role === "admin" ? "Admin" : "Miembro"}
                  </Badge>
                </TableCell>
                <TableCell className="mono">{u.hourly_rate != null ? `${u.hourly_rate}€/h` : "-"}</TableCell>
                <TableCell>
                  <Button variant="ghost" size="icon" onClick={() => setEditing(u)}>
                    <Pencil className="h-4 w-4" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {/* Edit Dialog */}
      <Dialog open={!!editing} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogHeader>
          <DialogTitle>Editar usuario</DialogTitle>
        </DialogHeader>
        {editing && (
          <form onSubmit={handleSubmitEdit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="full_name">Nombre completo</Label>
              <Input id="full_name" name="full_name" defaultValue={editing?.full_name} required />
            </div>
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
            {currentUser?.role === "admin" && (
              <div className="space-y-2">
                <Label htmlFor="role">Rol</Label>
                <Select id="role" name="role" defaultValue={editing?.role}>
                  <option value="admin">Admin</option>
                  <option value="member">Miembro</option>
                </Select>
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
