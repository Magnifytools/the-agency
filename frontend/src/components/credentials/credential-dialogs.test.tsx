import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, expect, it, vi } from "vitest"
import { CredentialFormDialog } from "./credential-dialogs"
import { CredentialImportDialog } from "./credential-import-dialog"
import type { Credential } from "@/lib/credentials-api"

const api = vi.hoisted(() => ({
  list: vi.fn(), create: vi.fn(), update: vi.fn(), importMany: vi.fn(), shareableUsers: vi.fn(), notes: vi.fn(),
}))
vi.mock("@/lib/credentials-api", () => ({ credentialsApi: api }))
vi.mock("@/lib/api", () => ({ clientsApi: { listAll: vi.fn().mockResolvedValue([]) } }))
vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ user: { id: 1 }, hasPermission: (module: string) => module === "credentials" }),
}))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

function wrap(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>)
}

const existing: Credential = {
  id: 7, name: "WordPress Fit", url: null, username: "magnify", has_notes: false, client_id: null, client_name: null,
  created_by: 1, created_by_name: "David", updated_at: "2026-10-20T08:00:00+00:00", can_manage: true, has_totp: true, shared_with: [],
}

beforeEach(() => {
  vi.resetAllMocks()
  api.list.mockResolvedValue([existing])
  api.shareableUsers.mockResolvedValue([{ id: 1, full_name: "David" }, { id: 2, full_name: "Nacho" }])
  api.create.mockResolvedValue(existing)
  api.update.mockResolvedValue(existing)
})

it("generates a password in the browser and sends it with the 2FA key", async () => {
  wrap(<CredentialFormDialog open onOpenChange={vi.fn()} />)
  fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "Google Ads" } })
  fireEvent.click(screen.getByRole("button", { name: /Generar/ }))
  const field = screen.getByLabelText("Contraseña") as HTMLInputElement
  expect(field.type).toBe("text")
  expect(field.value).toHaveLength(20)
  fireEvent.change(screen.getByLabelText("Longitud de la contraseña generada"), { target: { value: "32" } })
  expect(field.value).toHaveLength(32)
  const generated = field.value
  fireEvent.change(screen.getByLabelText("Código 2FA (opcional)"), { target: { value: "JBSW Y3DP EHPK 3PXP" } })
  fireEvent.click(screen.getByRole("button", { name: "Guardar" }))
  await waitFor(() => expect(api.create).toHaveBeenCalled())
  expect(api.create.mock.calls[0][0]).toMatchObject({ name: "Google Ads", secret: generated, totp: "JBSW Y3DP EHPK 3PXP" })
})

it("editing keeps the stored 2FA key unless it is changed or removed", async () => {
  wrap(<CredentialFormDialog open onOpenChange={vi.fn()} credential={existing} />)
  expect(screen.getByText("Tiene la clave del autenticador guardada.")).toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "Guardar" }))
  await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1))
  expect(api.update.mock.calls[0][1]).not.toHaveProperty("totp")

  fireEvent.click(screen.getByRole("button", { name: "Quitar" }))
  fireEvent.click(screen.getByRole("button", { name: "Guardar" }))
  await waitFor(() => expect(api.update).toHaveBeenCalledTimes(2))
  expect(api.update.mock.calls[1][1]).toMatchObject({ totp: "" })
})

it("imports the marked rows of a 1Password CSV, skipping what already exists", async () => {
  api.importMany.mockResolvedValue({ created: 1 })
  wrap(<CredentialImportDialog onOpenChange={vi.fn()} />)
  await waitFor(() => expect(screen.getByLabelText("Fichero CSV de contraseñas")).toBeEnabled())
  const csv = [
    "Title,Url,Username,Password,OTPAuth,Favorite,Archived,Tags,Notes",
    "Google Ads,https://ads.google.com,ads@magnify.ing,pw-1,otpauth://totp/G?secret=JBSWY3DPEHPK3PXP,false,false,,",
    "WordPress Fit,https://fit.example,magnify,pw-2,,false,false,,",
  ].join("\n")
  const file = new File([csv], "1password.csv", { type: "text/csv" })
  fireEvent.change(screen.getByLabelText("Fichero CSV de contraseñas"), { target: { files: [file] } })
  expect(await screen.findByText("Ya existe")).toBeInTheDocument()
  expect(screen.getByLabelText("Importar WordPress Fit")).not.toBeChecked()
  fireEvent.click(screen.getByLabelText("Nacho"))
  fireEvent.click(screen.getByRole("button", { name: "Importar 1" }))
  await waitFor(() => expect(api.importMany).toHaveBeenCalled())
  expect(api.importMany).toHaveBeenCalledWith("1password", [{
    name: "Google Ads", url: "https://ads.google.com", username: "ads@magnify.ing", secret: "pw-1",
    totp: "otpauth://totp/G?secret=JBSWY3DPEHPK3PXP", notes: null, client_id: null,
  }], [2])
})


it("editing does not send the stored notes unless they are opened", async () => {
  api.notes.mockResolvedValue("PIN 1234")
  wrap(<CredentialFormDialog open onOpenChange={vi.fn()} credential={{ ...existing, has_notes: true }} />)
  expect(screen.getByText("Tiene notas guardadas.")).toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "Guardar" }))
  await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1))
  expect(api.update.mock.calls[0][1]).not.toHaveProperty("notes")

  fireEvent.click(screen.getByRole("button", { name: "Ver y editar" }))
  const notes = await screen.findByLabelText("Notas")
  expect(notes).toHaveValue("PIN 1234")
  fireEvent.change(notes, { target: { value: "PIN 5678" } })
  fireEvent.click(screen.getByRole("button", { name: "Guardar" }))
  await waitFor(() => expect(api.update).toHaveBeenCalledTimes(2))
  expect(api.update.mock.calls[1][1]).toMatchObject({ notes: "PIN 5678" })
})
