import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { SeoPageGroup } from "@/lib/types"
import { pageGroupsProblem } from "@/lib/seo-control"
import { SeoPageGroupsEditor } from "./seo-page-groups-editor"

const mocks = vi.hoisted(() => ({ update: vi.fn(), preview: vi.fn() }))

vi.mock("@/lib/api", () => ({
  clientsApi: { update: mocks.update },
  clientSeoApi: { previewGroups: mocks.preview },
}))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const blog: SeoPageGroup = { name: "Blog", rules: [{ type: "prefix", value: "/blog/" }] }

function show(groups: SeoPageGroup[] = [blog], canWrite = true) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <SeoPageGroupsEditor client={{ id: 5, gsc_url: "sc-domain:acme.com", seo_page_groups: groups }} canWrite={canWrite} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.update.mockImplementation((_id: number, data: { seo_page_groups: SeoPageGroup[] }) =>
    Promise.resolve({ id: 5, seo_page_groups: data.seo_page_groups }))
})

describe("SeoPageGroupsEditor", () => {
  it("adds a group with a regex rule and saves the whole ordered list", async () => {
    show()
    const save = screen.getByRole("button", { name: "Guardar grupos" })
    expect(save).toBeDisabled()

    await userEvent.click(screen.getByRole("button", { name: "Añadir grupo" }))
    // Sin nombre ni valor: no se puede guardar y se dice por qué.
    expect(screen.getByText("El grupo 2 necesita un nombre.")).toBeInTheDocument()
    expect(save).toBeDisabled()

    await userEvent.type(screen.getByLabelText("Nombre del grupo 2"), "Fichas")
    await userEvent.selectOptions(screen.getByLabelText("Tipo de regla 1 del grupo 2"), "regex")
    await userEvent.type(screen.getByLabelText("Valor de la regla 1 del grupo 2"), "^/p/\\d+$")
    // El orden importa: sube Fichas por encima de Blog.
    await userEvent.click(screen.getAllByRole("button", { name: "Subir grupo" })[1])
    await userEvent.click(save)

    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith(5, {
      seo_page_groups: [{ name: "Fichas", rules: [{ type: "regex", value: "^/p/\\d+$" }] }, blog],
    }))
  })

  it("tests the rules without saving and shows how many pages each group gets", async () => {
    mocks.preview.mockResolvedValue({
      status: "ok", site_url: "sc-domain:acme.com", error_code: null, last_synced_at: null, configured: 1,
      window: { start: "2026-09-21", end: "2026-10-18", previous_start: "2026-08-24", previous_end: "2026-09-20", days: 28 },
      groups: [
        { key: "Blog", label: "Blog", clicks: 120, previous_clicks: 0, clicks_pct: null, clicks_share: 0.6,
          impressions: 9000, position: 4, position_delta: null, pages: 12 },
        { key: "Sin grupo", label: "Sin grupo", clicks: 800, previous_clicks: 0, clicks_pct: null, clicks_share: 0.4,
          impressions: 6000, position: 6, position_delta: null, pages: 30 },
      ],
    })
    show()
    await userEvent.click(screen.getByRole("button", { name: "Probar" }))
    expect(await screen.findByText(/12 páginas · 120 clics/)).toBeInTheDocument()
    expect(screen.getByText(/Sin grupo: 30 páginas · 800 clics/)).toBeInTheDocument()
    expect(mocks.preview).toHaveBeenCalledWith(5, [blog])
    expect(mocks.update).not.toHaveBeenCalled()
  })

  it("is read-only without write permission on clients", () => {
    show([blog], false)
    expect(screen.getByLabelText("Nombre del grupo 1")).toBeDisabled()
    expect(screen.queryByRole("button", { name: "Guardar grupos" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Añadir grupo" })).not.toBeInTheDocument()
  })
})

describe("pageGroupsProblem", () => {
  it("mirrors the server limits", () => {
    expect(pageGroupsProblem([blog])).toBeNull()
    expect(pageGroupsProblem([{ ...blog, name: "sin GRUPO" }])).toMatch(/reservado/)
    expect(pageGroupsProblem([blog, { ...blog, name: " blog " }])).toMatch(/dos grupos/)
    expect(pageGroupsProblem([{ ...blog, rules: [] }])).toMatch(/al menos una regla/)
    expect(pageGroupsProblem([{ ...blog, rules: [{ type: "contains", value: "  " }] }])).toMatch(/regla vacía/)
    expect(pageGroupsProblem(Array.from({ length: 31 }, (_, i) => ({ ...blog, name: `G${i}` })))).toMatch(/30 grupos/)
  })
})
