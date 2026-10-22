import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { DownloadPdfButton } from "./download-pdf-button"
import { filenameFromDisposition } from "@/lib/pdf-download"

const toast = vi.hoisted(() => ({ error: vi.fn() }))
vi.mock("sonner", () => ({ toast }))

describe("DownloadPdfButton", () => {
  const createObjectURL = vi.fn(() => "blob:pdf")
  let clicked: HTMLAnchorElement[] = []

  beforeEach(() => {
    clicked = []
    URL.createObjectURL = createObjectURL
    URL.revokeObjectURL = vi.fn()
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this)
    })
  })
  afterEach(() => vi.restoreAllMocks())

  it("downloads the blob with the server's file name", async () => {
    const blob = new Blob(["%PDF-1.3"], { type: "application/pdf" })
    const download = vi.fn().mockResolvedValue({ blob, filename: "informe-fit-2026-09.pdf" })
    render(<DownloadPdfButton download={download} />)

    await userEvent.click(screen.getByRole("button", { name: "Descargar PDF" }))

    await waitFor(() => expect(clicked).toHaveLength(1))
    expect(download).toHaveBeenCalledTimes(1)
    expect(createObjectURL).toHaveBeenCalledWith(blob)
    expect(clicked[0].download).toBe("informe-fit-2026-09.pdf")
    expect(clicked[0].href).toBe("blob:pdf")
    expect(screen.getByRole("button", { name: "Descargar PDF" })).toBeEnabled()
  })

  it("shows the server's message even though the error body is a blob", async () => {
    const body = new Blob([JSON.stringify({ detail: "Demasiados PDF seguidos. Espera un minuto." })])
    const download = vi.fn().mockRejectedValue({ response: { status: 429, data: body } })
    render(<DownloadPdfButton iconOnly ariaLabel="Descargar PDF del resumen de Fit" download={download} />)

    await userEvent.click(screen.getByRole("button", { name: "Descargar PDF del resumen de Fit" }))

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Demasiados PDF seguidos. Espera un minuto."))
    expect(clicked).toHaveLength(0)
  })

  it("does nothing when the caller cancels (null)", async () => {
    render(<DownloadPdfButton download={vi.fn().mockResolvedValue(null)} />)
    await userEvent.click(screen.getByRole("button", { name: "Descargar PDF" }))
    await waitFor(() => expect(screen.getByRole("button", { name: "Descargar PDF" })).toBeEnabled())
    expect(clicked).toHaveLength(0)
  })
})

describe("filenameFromDisposition", () => {
  it("reads the attachment name and falls back otherwise", () => {
    expect(filenameFromDisposition('attachment; filename="informe-a-2026-09.pdf"', "x.pdf")).toBe("informe-a-2026-09.pdf")
    expect(filenameFromDisposition(undefined, "x.pdf")).toBe("x.pdf")
  })
})
