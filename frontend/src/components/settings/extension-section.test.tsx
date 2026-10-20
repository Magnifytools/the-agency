import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { ExtensionSection } from "./extension-section"

vi.mock("@/lib/api", () => ({ extensionApi: {
  info: vi.fn().mockResolvedValue({ version: "2.2.7", filename: "the-agency-extension-v2.2.7.zip", download_url: "/api/extension/download" }),
} }))

describe("ExtensionSection", () => {
  it("offers the deployed version with install and update steps", async () => {
    render(<QueryClientProvider client={new QueryClient()}><ExtensionSection /></QueryClientProvider>)
    const link = await screen.findByRole("link", { name: /Descargar extensión/ })
    expect(link).toHaveAttribute("href", "/api/extension/download")
    expect(link).toHaveAttribute("download", "the-agency-extension-v2.2.7.zip")
    expect(screen.getByText("2.2.7")).toBeInTheDocument()
    expect(screen.getByText(/Cargar descomprimida/)).toBeInTheDocument()
    expect(screen.getByText(/Sustituye el contenido/)).toBeInTheDocument()
  })
})
