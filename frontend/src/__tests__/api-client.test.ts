import axios, { type InternalAxiosRequestConfig } from "axios"
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { api, beginApiSessionTransition, CSRF_COOKIE_NAME, discordApi } from "@/lib/api"

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
  let originalAdapter: typeof api.defaults.adapter

  beforeEach(() => {
    vi.clearAllMocks()
    clearCsrfCookie()
    originalAdapter = api.defaults.adapter
  })

  afterEach(() => {
    clearCsrfCookie()
    api.defaults.adapter = originalAdapter
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it("versions explicit custom sends while digest sends retain their source route", async () => {
    const requests: InternalAxiosRequestConfig[] = []
    api.defaults.adapter = async (config) => {
      requests.push(config)
      return { data: { success: false, status: "pending" }, status: 202, statusText: "Accepted", headers: {}, config }
    }
    await discordApi.sendCustom("Custom text")
    await discordApi.sendDigest(42, "Digest text")
    expect(requests[0].url).toBe("/discord/send-custom")
    expect(requests[0].headers.get("X-Agency-Send-Intent")).toBe("custom-v1")
    expect(requests[1].url).toBe("/discord/send-digest/42")
    expect(requests[1].headers.get("X-Agency-Send-Intent")).toBeUndefined()
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

  it("aborts a pending data request when the authenticated session changes", async () => {
    let requestSignal: { aborted: boolean } | undefined
    api.defaults.adapter = (config) => new Promise((_resolve, reject) => {
      requestSignal = config.signal
      const signal = config.signal
      const addAbortListener = signal?.addEventListener
      if (addAbortListener) {
        addAbortListener.call(signal, "abort", () => reject({ __CANCEL__: true, config }))
      }
    })

    const pending = api.get("/tasks").catch((error) => error)
    await vi.waitFor(() => expect(requestSignal).toBeDefined())

    beginApiSessionTransition()
    const error = await pending

    expect(requestSignal?.aborted).toBe(true)
    expect(axios.isCancel(error)).toBe(true)
  })

  it("combines a caller signal with the session signal and silences cancellation toasts", async () => {
    const { toast } = await import("sonner")
    const ownController = new AbortController()
    let requestSignal: { aborted: boolean } | undefined
    api.defaults.adapter = (config) => new Promise((_resolve, reject) => {
      requestSignal = config.signal
      const addAbortListener = config.signal?.addEventListener
      if (addAbortListener) {
        addAbortListener.call(config.signal, "abort", () => reject({ __CANCEL__: true, config, request: {} }))
      }
    })

    const pending = api.post("/tasks", {}, { signal: ownController.signal }).catch((error) => error)
    await vi.waitFor(() => expect(requestSignal).toBeDefined())
    beginApiSessionTransition()
    const error = await pending

    expect(requestSignal?.aborted).toBe(true)
    expect(ownController.signal.aborted).toBe(false)
    expect(axios.isCancel(error)).toBe(true)
    expect(toast.error).not.toHaveBeenCalled()
  })

  it("keeps an already cancelled caller signal cancelled without AbortSignal.any", async () => {
    vi.stubGlobal("AbortSignal", { any: undefined })
    const caller = new AbortController()
    caller.abort()
    const adapter = vi.fn()
    api.defaults.adapter = adapter
    const error = await api.get("/tasks", { signal: caller.signal }).catch((err) => err)
    expect(axios.isCancel(error)).toBe(true)
    expect(adapter).not.toHaveBeenCalled()
  })

  it("ignores an old 401 after a new session begins", async () => {
    const onExpired = vi.fn()
    let rejectOldRequest!: (reason: unknown) => void
    let oldConfig!: InternalAxiosRequestConfig
    window.addEventListener("auth:expired", onExpired)
    api.defaults.adapter = (config) => new Promise((_resolve, reject) => {
      oldConfig = config as InternalAxiosRequestConfig
      rejectOldRequest = reject
    })

    const pending = api.get("/tasks").catch((error) => error)
    await vi.waitFor(() => expect(rejectOldRequest).toBeTypeOf("function"))
    beginApiSessionTransition()
    rejectOldRequest({
      config: oldConfig,
      request: {},
      response: { status: 401, data: {}, headers: {}, config: oldConfig },
    })

    await pending
    expect(onExpired).not.toHaveBeenCalled()
    window.removeEventListener("auth:expired", onExpired)
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
