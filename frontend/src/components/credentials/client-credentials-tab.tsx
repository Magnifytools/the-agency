import { useState } from "react"
import { Plus } from "lucide-react"
import { useAuth } from "@/context/auth-context"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { CredentialList } from "./credential-list"
import { CredentialFormDialog } from "./credential-dialogs"

/** Pestaña Accesos de la ficha: los del cliente que puede ver quien mira. */
export function ClientCredentialsTab({ clientId }: { clientId: number }) {
  const { hasPermission } = useAuth()
  const [creating, setCreating] = useState(false)
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="text-base">Accesos</CardTitle>
        {hasPermission("credentials", true) && (
          <Button size="sm" onClick={() => setCreating(true)}><Plus className="h-4 w-4 mr-1" /> Nuevo acceso</Button>
        )}
      </CardHeader>
      <CardContent>
        <CredentialList clientId={clientId} showClient={false} />
      </CardContent>
      {creating && <CredentialFormDialog open fixedClientId={clientId} onOpenChange={setCreating} />}
    </Card>
  )
}
