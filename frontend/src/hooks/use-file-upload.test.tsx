import type { ReactNode } from "react"
import { act, render, renderHook, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { AxiosError, AxiosHeaders, type AxiosProgressEvent } from "axios"
import { beforeEach, expect, it, vi } from "vitest"
import { useFileUpload, uploadErrorMessage, type UploadProgressHandler } from "./use-file-upload"
import { UploadProgress } from "@/components/ui/upload-progress"

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
vi.mock("sonner", () => ({ toast }))

beforeEach(() => {
  toast.success.mockReset()
  toast.error.mockReset()
})

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

function serverError(status: number, detail?: string) {
  const config = { headers: new AxiosHeaders() }
  return new AxiosError("Request failed", "ERR_BAD_REQUEST", config, {}, {
    status, statusText: "", headers: {}, config, data: detail ? { detail } : "",
  })
}

it("shows progress while uploading and confirms when it is done", async () => {
  let report: UploadProgressHandler = () => {}
  let finish: (value: { id: number }) => void = () => {}
  const onUploaded = vi.fn()
  const { result } = renderHook(() => useFileUpload({
    upload: (_file, onProgress) => {
      report = onProgress
      return new Promise((resolve) => { finish = resolve })
    },
    onUploaded,
  }), { wrapper })

  act(() => result.current.upload(new File(["<html></html>"], "informe.html", { type: "text/html" })))
  await waitFor(() => expect(result.current.uploading).toEqual({ name: "informe.html", percent: 0 }))

  act(() => report({ loaded: 40, total: 100 } as AxiosProgressEvent))
  expect(result.current.uploading?.percent).toBe(40)
  render(<UploadProgress state={result.current.uploading} />)
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "40")
  expect(screen.getByRole("status")).toHaveTextContent("Subiendo informe.html…")

  await act(async () => finish({ id: 7 }))
  await waitFor(() => expect(result.current.uploading).toBeNull())
  expect(toast.success).toHaveBeenCalledWith("«informe.html» subido")
  expect(onUploaded).toHaveBeenCalledWith({ id: 7 }, expect.any(File))
  expect(toast.error).not.toHaveBeenCalled()
})

it("says why the server rejected the file", async () => {
  const { result } = renderHook(() => useFileUpload({
    upload: () => Promise.reject(serverError(415, "No se admiten archivos .exe. Sube PDF…")),
  }), { wrapper })

  act(() => result.current.upload(new File(["x"], "setup.exe")))
  await waitFor(() => expect(toast.error).toHaveBeenCalledWith(
    "No se pudo subir «setup.exe»: No se admiten archivos .exe. Sube PDF…",
  ))
  expect(result.current.uploading).toBeNull()
  expect(result.current.isUploading).toBe(false)
})

it("explains a size limit or a dropped connection without a server message", () => {
  expect(uploadErrorMessage(serverError(413))).toBe("El archivo es demasiado grande")
  const config = { headers: new AxiosHeaders() }
  expect(uploadErrorMessage(new AxiosError("Network Error", "ERR_NETWORK", config, {}))).toBe(
    "Se cortó la conexión durante la subida",
  )
})

it("shows an indeterminate bar when the total size is unknown", () => {
  render(<UploadProgress state={{ name: "datos.zip", percent: null }} />)
  expect(screen.getByRole("progressbar")).not.toHaveAttribute("aria-valuenow")
  expect(screen.queryByText(/%/)).not.toBeInTheDocument()
})
