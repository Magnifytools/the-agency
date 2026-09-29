import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { expect, it, vi } from "vitest"
import { OnboardingModal } from "./onboarding-modal"

const mocks = vi.hoisted(() => ({
  update: vi.fn().mockResolvedValue({}),
  refreshUser: vi.fn().mockResolvedValue(undefined),
  user: {
    id: 7,
    full_name: "Persona de prueba",
    short_name: "Nombre existente",
    job_title: "Estrategia",
    birthday: "1990-01-02",
    locality: "Barcelona",
    region: "CAT",
    morning_reminder_time: "08:30",
    evening_reminder_time: "19:15",
    onboarding_completed: false,
  },
}))

vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ user: mocks.user, refreshUser: mocks.refreshUser }),
}))
vi.mock("@/lib/api", () => ({ usersApi: { update: mocks.update } }))

it("keeps existing profile values when onboarding is saved", async () => {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  render(<QueryClientProvider client={client}><OnboardingModal /></QueryClientProvider>)

  expect(screen.getByLabelText("Nombre corto")).toHaveValue("Nombre existente")
  expect(screen.getByLabelText("Comunidad autónoma")).toHaveValue("CAT")
  expect(screen.getByLabelText("Hora preferida para el aviso de la mañana")).toHaveValue("08:30")
  expect(screen.getByLabelText("Hora preferida para el aviso de cierre")).toHaveValue("19:15")

  await userEvent.click(screen.getByRole("button", { name: "Guardar y continuar" }))
  await waitFor(() => expect(mocks.update).toHaveBeenCalledWith(7, expect.objectContaining({
    short_name: "Nombre existente",
    region: "CAT",
    morning_reminder_time: "08:30",
    evening_reminder_time: "19:15",
    onboarding_completed: true,
  })))
})
