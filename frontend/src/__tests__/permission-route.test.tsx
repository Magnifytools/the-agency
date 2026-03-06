import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { PermissionRoute } from "@/components/layout/permission-route"

// ── Mock useAuth ──────────────────────────────────────────────────────────────

const mockUseAuth = vi.fn()

vi.mock("@/context/auth-context", () => ({
  useAuth: () => mockUseAuth(),
}))

// ── Helpers ───────────────────────────────────────────────────────────────────

function renderRoute(props: Omit<Parameters<typeof PermissionRoute>[0], "children">) {
  return render(
    <MemoryRouter>
      <PermissionRoute {...props}>
        <div data-testid="protected-content">Contenido protegido</div>
      </PermissionRoute>
    </MemoryRouter>,
  )
}

function authAs(overrides: Partial<ReturnType<typeof mockUseAuth>>) {
  mockUseAuth.mockReturnValue({
    isLoading: false,
    isAdmin: false,
    hasPermission: () => false,
    ...overrides,
  })
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("PermissionRoute", () => {
  describe("loading state", () => {
    it("renders nothing while auth is loading", () => {
      authAs({ isLoading: true })
      const { container } = renderRoute({})
      expect(container).toBeEmptyDOMElement()
    })
  })

  describe("adminOnly guard", () => {
    it("renders children when user is admin", () => {
      authAs({ isAdmin: true })
      renderRoute({ adminOnly: true })
      expect(screen.getByTestId("protected-content")).toBeInTheDocument()
    })

    it("renders AccessDenied when member hits admin-only route", () => {
      authAs({ isAdmin: false })
      renderRoute({ adminOnly: true })
      expect(screen.queryByTestId("protected-content")).not.toBeInTheDocument()
      expect(screen.getByText("Acceso restringido")).toBeInTheDocument()
    })

    it("shows back-to-dashboard link in AccessDenied", () => {
      authAs({ isAdmin: false })
      renderRoute({ adminOnly: true })
      const link = screen.getByRole("link", { name: /volver al dashboard/i })
      expect(link).toHaveAttribute("href", "/dashboard")
    })
  })

  describe("module permission guard", () => {
    it("renders children when user has read permission", () => {
      authAs({ hasPermission: (mod: string) => mod === "clients" })
      renderRoute({ module: "clients" })
      expect(screen.getByTestId("protected-content")).toBeInTheDocument()
    })

    it("renders AccessDenied when user lacks read permission", () => {
      authAs({ hasPermission: () => false })
      renderRoute({ module: "billing" })
      expect(screen.queryByTestId("protected-content")).not.toBeInTheDocument()
      expect(screen.getByText("Acceso restringido")).toBeInTheDocument()
    })

    it("renders children when user has write permission and write=true", () => {
      authAs({ hasPermission: (_mod: string, write?: boolean) => !!write })
      renderRoute({ module: "clients", write: true })
      expect(screen.getByTestId("protected-content")).toBeInTheDocument()
    })

    it("renders AccessDenied when user only has read but write=true required", () => {
      authAs({
        // can read but not write
        hasPermission: (_mod: string, write?: boolean) => !write,
      })
      renderRoute({ module: "clients", write: true })
      expect(screen.queryByTestId("protected-content")).not.toBeInTheDocument()
      expect(screen.getByText("Acceso restringido")).toBeInTheDocument()
    })
  })

  describe("no guard", () => {
    it("renders children when no adminOnly/module props set", () => {
      authAs({ isAdmin: false, hasPermission: () => false })
      renderRoute({})
      expect(screen.getByTestId("protected-content")).toBeInTheDocument()
    })

    it("admin bypasses module check even without hasPermission returning true", () => {
      // adminOnly=false, no module prop → always passes through
      authAs({ isAdmin: true, hasPermission: () => false })
      renderRoute({ adminOnly: false })
      expect(screen.getByTestId("protected-content")).toBeInTheDocument()
    })
  })
})
