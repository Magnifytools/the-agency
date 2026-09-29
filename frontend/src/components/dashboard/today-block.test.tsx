import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, expect, it, vi } from "vitest"
import { TodayBlock } from "./today-block"

const today = vi.hoisted(() => vi.fn())
vi.mock("@/lib/api", () => ({ dashboardApi: { today } }))

beforeEach(() => {
  today.mockResolvedValue({
    date: "2026-09-22",
    total_tasks: 1,
    by_user: { David: [{ id: 42, title: "Revisar propuesta", status: "pending", priority: "high", client_name: "Acme", estimated_minutes: 30 }] },
  })
})

it("opens the exact task from the today dashboard block", async () => {
  render(<MemoryRouter><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><TodayBlock /></QueryClientProvider></MemoryRouter>)

  expect((await screen.findByRole("link", { name: /Revisar propuesta/ })).getAttribute("href")).toBe("/tasks?task=42")
})
