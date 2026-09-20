import { useAuth } from "@/context/auth-context"
import { IncidentInbox } from "@/components/incidents/incident-inbox"

/** Dashboard uses the same recipient, decisions and cache as Hoy and the bell. */
export function InsightsPanel() {
  const { user } = useAuth()
  return user ? <IncidentInbox key={user.id} userId={user.id} compact /> : null
}
