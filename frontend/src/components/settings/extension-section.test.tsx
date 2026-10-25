import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ExtensionSection } from "./extension-section"

const info = vi.hoisted(() => vi.fn())
vi.mock("@/lib/api", () => ({ extensionApi: { info } }))

const base = { version: "2.2.8", filename: "the-agency-extension-v2.2.8.zip", download_url: "/api/extension/download" }

function show() {
  render(<QueryClientProvider client={new QueryClient()}><ExtensionSection /></QueryClientProvider>)
}

describe("ExtensionSection", () => {
  beforeEach(() => info.mockReset())

  it("offers the deployed version with install and update steps", async () => {
    info.mockResolvedValue({ ...base, released_on: null, releases: [] })
    show()
    const link = await screen.findByRole("link", { name: /Descargar extensión/ })
    expect(link).toHaveAttribute("href", "/api/extension/download")
    expect(link).toHaveAttribute("download", "the-agency-extension-v2.2.8.zip")
    expect(screen.getByText("2.2.8")).toBeInTheDocument()
    expect(screen.queryByText(/actualizada el/)).not.toBeInTheDocument()
    expect(screen.queryByText("Novedades")).not.toBeInTheDocument()
    expect(screen.getByText(/Cargar descomprimida/)).toBeInTheDocument()
    expect(screen.getByText(/Sustituye el contenido/)).toBeInTheDocument()
  })

  it("says when it was updated and what changed, newest first", async () => {
    info.mockResolvedValue({
      ...base,
      released_on: "2026-10-24",
      releases: [
        { version: "2.2.8", date: "2026-10-24", changes: ["Sin tareas a meses vista en el timer."] },
        { version: "2.2.7", date: "2026-10-20", changes: ["Se descarga desde Ajustes."] },
      ],
    })
    show()
    expect(await screen.findByText(/actualizada el 24 de octubre de 2026/)).toBeInTheDocument()
    expect(screen.getByText("Novedades")).toBeInTheDocument()
    expect(screen.getByText(/la que se descarga ahora/)).toBeInTheDocument()
    const changes = screen.getAllByRole("listitem").map((li) => li.textContent)
    expect(changes.indexOf("Sin tareas a meses vista en el timer.")).toBeLessThan(changes.indexOf("Se descarga desde Ajustes."))
  })
})
