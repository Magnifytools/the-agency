import { ReportArchive } from "@/components/reports/report-archive"

interface Props {
  clientId: number
  clientName: string
  engineProjectId?: number | null
}

export function ClientReportsTab({ clientId, clientName }: Props) {
  return <ReportArchive clientId={clientId} clientName={clientName} />
}
