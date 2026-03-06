import { Link } from "react-router-dom"
import { ShieldOff } from "lucide-react"
import { Button } from "@/components/ui/button"

export function AccessDenied() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 text-center px-4">
      <div className="rounded-full bg-muted p-4">
        <ShieldOff className="h-8 w-8 text-muted-foreground" />
      </div>
      <div>
        <h2 className="text-xl font-semibold">Acceso restringido</h2>
        <p className="text-sm text-muted-foreground mt-1">
          No tienes permisos para ver esta sección.
        </p>
      </div>
      <Link to="/dashboard">
        <Button variant="outline" size="sm">
          Volver al dashboard
        </Button>
      </Link>
    </div>
  )
}
