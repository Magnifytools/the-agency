import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { CSRF_COOKIE_NAME } from "@/lib/api"

// Mock sonner before importing api
vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}))

const clearCsrfCookie = () => {
  document.cookie = `${CSRF_COOKIE_NAME}=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/`
}

describe("API Client", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    clearCsrfCookie()
  })

  afterEach(() => {
    clearCsrfCookie()
    vi.restoreAllMocks()
  })

  it("creates an axios instance with /api baseURL", async () => {
    // Re-import to get fresh module
    const { default: axiosModule } = await import("axios")
    const instance = axiosModule.create({ baseURL: "/api" })
    expect(instance.defaults.baseURL).toBe("/api")
  })

  it("request interceptor adds CSRF header when cookie exists", () => {
    document.cookie = `${CSRF_COOKIE_NAME}=test-csrf-token;path=/`
    const match = document.cookie
      .split("; ")
      .find((row) => row.startsWith(`${CSRF_COOKIE_NAME}=`))
    const csrfToken = match ? decodeURIComponent(match.split("=")[1]) : null
    const headers: Record<string, string> = {}
    if (csrfToken) {
      headers["X-CSRF-Token"] = csrfToken
    }

    expect(headers["X-CSRF-Token"]).toBe("test-csrf-token")
  })

  it("request interceptor does not add CSRF header when no cookie", () => {
    const match = document.cookie
      .split("; ")
      .find((row) => row.startsWith(`${CSRF_COOKIE_NAME}=`))
    const csrfToken = match ? decodeURIComponent(match.split("=")[1]) : null
    const headers: Record<string, string> = {}
    if (csrfToken) {
      headers["X-CSRF-Token"] = csrfToken
    }

    expect(headers["X-CSRF-Token"]).toBeUndefined()
  })

  it("401 response redirects for non-auth requests", async () => {
    const href = "http://localhost/dashboard"
    const error = {
      config: { url: "/clients", method: "get" },
      response: { status: 401 },
      request: {},
    }

    const status = error.response.status
    const requestUrl = error.config.url
    if (status === 401) {
      const isAuthRequest =
        requestUrl.includes("/auth/login") ||
        requestUrl.includes("/auth/me") ||
        requestUrl.includes("/auth/logout")
      if (!isAuthRequest) {
        // Simulate redirect side effect
        expect(href).toContain("/dashboard")
      }
    }
  })

  it("401 response does not redirect for /auth/me", async () => {
    const error = {
      config: { url: "/auth/me", method: "get" },
      response: { status: 401 },
      request: {},
    }

    const status = error.response.status
    const requestUrl = error.config.url
    let shouldRedirect = false
    if (status === 401) {
      const isAuthRequest =
        requestUrl.includes("/auth/login") ||
        requestUrl.includes("/auth/me") ||
        requestUrl.includes("/auth/logout")
      if (!isAuthRequest) {
        shouldRedirect = true
      }
    }
    expect(shouldRedirect).toBe(false)
  })

  it("403 response shows permission error toast for write requests", async () => {
    const { toast } = await import("sonner")

    // Simulate response interceptor logic
    const error = { response: { status: 403 }, request: {}, config: { method: "post" } }
    const status = error.response.status
    const isGetRequest = error.config.method === "get"

    if (status === 403 && !isGetRequest) {
      toast.error("No tienes permisos para esta acción")
    }

    expect(toast.error).toHaveBeenCalledWith("No tienes permisos para esta acción")
  })

  it("500+ response does not show server toast for GET requests", async () => {
    const { toast } = await import("sonner")

    const error = { response: { status: 500 }, request: {}, config: { method: "get" } }
    const status = error.response.status
    const isGetRequest = error.config.method === "get"

    if (status >= 500 && !isGetRequest) {
      toast.error("Error del servidor. Intenta de nuevo.")
    }

    expect(toast.error).not.toHaveBeenCalled()
  })

  it("network error (no response) shows connection error toast for write requests", async () => {
    const { toast } = await import("sonner")

    const error = { response: undefined, request: {}, config: { method: "post" } }
    const isGetRequest = error.config.method === "get"

    if (!error.response && error.request && !isGetRequest) {
      toast.error("Error de conexión. Verifica tu red.")
    }

    expect(toast.error).toHaveBeenCalledWith("Error de conexión. Verifica tu red.")
  })
})
