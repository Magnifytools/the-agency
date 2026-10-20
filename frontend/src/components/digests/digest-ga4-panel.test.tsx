import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { DigestGa4Panel } from "./digest-ga4-panel"

const month = { start: "2026-09-01", end: "2026-09-30", days: 30, sessions: 1234, key_events: 25, ai_sessions: 50, ai_key_events: 3 }

describe("DigestGa4Panel", () => {
  it("shows the month's figures and lets you leave the block out", async () => {
    const onIncludeChange = vi.fn()
    render(<DigestGa4Panel ga4={{ status: "ok", month, previous: { ...month, sessions: 1000 },
      vs_previous: { sessions_pct: 23.4, key_events_pct: null, ai_sessions_pct: 100 } }}
      include canWrite onIncludeChange={onIncludeChange} />)
    expect(screen.getByText("1.234")).toBeInTheDocument()
    expect(screen.getByText("+23,4 %")).toBeInTheDocument()
    await userEvent.click(screen.getByRole("checkbox", { name: "Incluir en el resumen" }))
    expect(onIncludeChange).toHaveBeenCalledWith(false)
  })

  it("explains why there is no block yet", () => {
    render(<DigestGa4Panel ga4={{ status: "incomplete" }} include canWrite onIncludeChange={vi.fn()} />)
    expect(screen.getByText(/aún no tiene el mes cerrado/)).toBeInTheDocument()
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument()
  })
})
