import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts"
import type { ForecastVsActual } from "@/lib/types"

const MONTH_LABELS = [
  "Ene", "Feb", "Mar", "Abr", "May", "Jun",
  "Jul", "Ago", "Sep", "Oct", "Nov", "Dic",
]

interface RevenueTrendChartProps {
  data: ForecastVsActual[]
}

export function RevenueTrendChart({ data }: RevenueTrendChartProps) {
  const chartData = data.map((d) => {
    const monthNum = parseInt(d.month.split("-")[1], 10)
    return {
      name: MONTH_LABELS[monthNum - 1] || d.month,
      "Ingresos": d.actual_income,
      "Gastos": d.actual_expenses,
      "Beneficio": d.actual_profit,
      "Ingresos prev.": d.projected_income,
      "Gastos prev.": d.projected_expenses,
    }
  })

  const fmt = (v: number) => `${(v / 1000).toFixed(1)}k`

  return (
    <ResponsiveContainer width="100%" height={320}>
      <LineChart data={chartData}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
        <XAxis
          dataKey="name"
          fontSize={11}
          tick={{ fill: "#8a8a80" }}
        />
        <YAxis
          fontSize={11}
          tickFormatter={fmt}
          tick={{ fill: "#8a8a80" }}
        />
        <Tooltip
          formatter={(value) => `${Number(value).toLocaleString("es-ES", { style: "currency", currency: "EUR" })}`}
          contentStyle={{
            backgroundColor: "#2a2a28",
            border: "1px solid rgba(254, 230, 48, 0.3)",
            color: "#f5f5f0",
            fontSize: 12,
            borderRadius: 8,
          }}
          labelStyle={{ color: "#FEE630" }}
        />
        <Legend wrapperStyle={{ fontSize: 11, color: "#8a8a80" }} />
        <Line
          type="monotone"
          dataKey="Ingresos"
          stroke="#22c55e"
          strokeWidth={2}
          dot={{ r: 3 }}
          activeDot={{ r: 5 }}
        />
        <Line
          type="monotone"
          dataKey="Gastos"
          stroke="#ef4444"
          strokeWidth={2}
          dot={{ r: 3 }}
          activeDot={{ r: 5 }}
        />
        <Line
          type="monotone"
          dataKey="Beneficio"
          stroke="#FEE630"
          strokeWidth={2.5}
          dot={{ r: 3 }}
          activeDot={{ r: 5 }}
        />
        <Line
          type="monotone"
          dataKey="Ingresos prev."
          stroke="#22c55e"
          strokeWidth={1}
          strokeDasharray="5 5"
          dot={false}
        />
        <Line
          type="monotone"
          dataKey="Gastos prev."
          stroke="#ef4444"
          strokeWidth={1}
          strokeDasharray="5 5"
          dot={false}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}
