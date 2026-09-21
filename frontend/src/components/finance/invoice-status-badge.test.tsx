import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { InvoiceStatusBadge } from "./invoice-status-badge"

describe("Holded invoice status", () => {
  it.each([
    ["paid", "Pagada"],
    ["pending", "Pendiente"],
    ["overdue", "Vencida"],
    ["unknown", "Sin confirmar"],
    [null, "Sin confirmar"],
  ])("renders %s as %s", (status, label) => {
    render(<InvoiceStatusBadge status={status} />)
    expect(screen.getByText(label)).toBeInTheDocument()
  })
})
