import { BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer } from "recharts"
import type { ClientProfitability } from "@/lib/types"
import { formatCurrency } from "@/lib/format"

interface ProfitabilityChartProps {
  data: ClientProfitability[]
}

export function ProfitabilityChart({ data }: ProfitabilityChartProps) {
  const chartData = data.map((c) => ({
    name: c.client_name.length > 15 ? c.client_name.slice(0, 15) + "..." : c.client_name,
    Presupuesto: c.budget,
    Coste: c.cost,
  }))

  return (
    <ResponsiveContainer width="100%" height={300}>
      <BarChart data={chartData}>
        <XAxis dataKey="name" fontSize={11} tick={{ fill: "#8a8a80" }} />
        <YAxis fontSize={11} tickFormatter={(v) => formatCurrency(v)} tick={{ fill: "#8a8a80" }} />
        <Tooltip
          formatter={(value) => formatCurrency(Number(value))}
          contentStyle={{
            backgroundColor: "#2a2a28",
            border: "1px solid rgba(254, 230, 48, 0.3)",
            color: "#f5f5f0",
            fontSize: 12,
          }}
          labelStyle={{ color: "#FEE630" }}
        />
        <Legend wrapperStyle={{ fontSize: 11, color: "#8a8a80" }} />
        <Bar dataKey="Presupuesto" fill="#FEE630" radius={[2, 2, 0, 0]} />
        <Bar dataKey="Coste" fill="#ef4444" radius={[2, 2, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  )
}
