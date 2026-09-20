import { IncidentInbox } from "@/components/incidents/incident-inbox"
import { useAuth } from "@/context/auth-context"

export default function IncidentsPage() {
  const { user } = useAuth()
  if (!user) return null
  return <IncidentInbox key={user.id} userId={user.id} />
}
