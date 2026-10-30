import { fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, expect, it, vi } from "vitest"
import type { Client } from "@/lib/types"
import { BrandTermsNotice } from "./brand-terms-notice"

const perms = vi.hoisted(() => ({ write: true }))
vi.mock("@/context/auth-context", () => ({
  useAuth: () => ({ hasPermission: (module: string, write = false) => module === "clients" && (!write || perms.write) }),
}))

const client = (over: Partial<Client> = {}) =>
  ({ id: 1, name: "Fit Generation", status: "active", gsc_url: "sc-domain:fitgeneration.es", brand_terms: [], ...over }) as Client

beforeEach(() => {
  perms.write = true
})

it("asks for brand terms and takes you to them", () => {
  const onConfigure = vi.fn()
  render(<BrandTermsNotice client={client()} onConfigure={onConfigure} />)
  expect(screen.getByRole("status")).toHaveTextContent("Faltan los términos de marca de Fit Generation")
  fireEvent.click(screen.getByRole("button", { name: "Poner términos de marca" }))
  expect(onConfigure).toHaveBeenCalled()
})

it("stays quiet with terms, without Search Console or for a former client", () => {
  const { rerender } = render(<BrandTermsNotice client={client({ brand_terms: ["fit generation"] })} onConfigure={vi.fn()} />)
  expect(screen.queryByRole("status")).not.toBeInTheDocument()
  rerender(<BrandTermsNotice client={client({ gsc_url: null })} onConfigure={vi.fn()} />)
  expect(screen.queryByRole("status")).not.toBeInTheDocument()
  rerender(<BrandTermsNotice client={client({ status: "finished" })} onConfigure={vi.fn()} />)
  expect(screen.queryByRole("status")).not.toBeInTheDocument()
})

it("readers see the notice without the button", () => {
  perms.write = false
  render(<BrandTermsNotice client={client()} onConfigure={vi.fn()} />)
  expect(screen.getByRole("status")).toBeInTheDocument()
  expect(screen.queryByRole("button")).not.toBeInTheDocument()
})
