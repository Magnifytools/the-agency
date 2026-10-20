import { useState } from "react"
import { KeyRound, Plus, Search } from "lucide-react"
import { useAuth } from "@/context/auth-context"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"
import { CredentialList } from "@/components/credentials/credential-list"
import { CredentialFormDialog } from "@/components/credentials/credential-dialogs"

/** Accesos: las contraseñas compartidas del equipo (WordPress, GA, herramientas…). */
export default function CredentialsPage() {
  const { hasPermission, isAdmin } = useAuth()
  const [q, setQ] = useState("")
  const [creating, setCreating] = useState(false)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2"><KeyRound className="h-6 w-6" /> Accesos</h1>
          <p className="text-sm text-muted-foreground">
            {isAdmin
              ? "Ves todos los accesos. Cada vez que alguien ve o copia una contraseña queda apuntado."
              : "Los accesos que has creado o te han compartido. Ver o copiar una contraseña queda apuntado."}
          </p>
        </div>
        {hasPermission("credentials", true) && (
          <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4 mr-1" /> Nuevo acceso</Button>
        )}
      </div>
      <div className="relative max-w-md">
        <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar por nombre, cliente, URL o usuario" aria-label="Buscar accesos" className="pl-9" />
      </div>
      <Card>
        <CardContent className="p-4 sm:p-6">
          <CredentialList q={q} />
        </CardContent>
      </Card>
      {creating && <CredentialFormDialog open onOpenChange={setCreating} />}
    </div>
  )
}
