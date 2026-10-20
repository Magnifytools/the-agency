import type { ProjectTasksResponse } from "@/lib/project-work"
import axios, { type GenericAbortSignal, type InternalAxiosRequestConfig } from "axios"
import { toast } from "sonner"
import type {
  VigilClients,
  TaskAgendaSection,
  SearchResults,
  PaginatedResponse,
  Client,
  ClientCreate,
  ClientOnboardingCreate,
  ClientOnboardingResult,
  ClientExtract,
  ClientDocument,
  ClientSummary,
  Task,
  TaskCreate,
  RecurrenceSummary,
  TaskCategory,
  ChecklistItem,
  TaskComment,
  TaskAttachment,
  TokenResponse,
  User,
  UserCreate,
  UserPermission,
  DeactivationImpact,
  TimeEntry,
  TimeEntryCreate,
  ActiveTimer,
  WeeklyTimesheet,
  AdminActiveTimer,
  ProjectTimeReport,
  ClientTimeReport,
  BalanceSnapshot,
  BalanceSnapshotCreate,
  DashboardOverview,
  DashboardOperations,
  DashboardFinancialOverview,
  ProfitabilityResponse,
  TeamMemberSummary,
  MonthlyClose,
  FinancialSettings,
  Project,
  ProjectMonthlyCycle,
  ProjectListItem,
  ProjectCreate,
  ProjectDraft,
  ProjectTemplate,
  ProjectTemplateDetail,
  ProjectPhase,
  Communication,
  CommunicationCreate,
  Insight,
  InsightCount,
  DailyBriefing,
  AlertSettings,
  AlertSettingsUpdate,
  Proposal,
  ProposalCreate,
  ProposalUpdate,
  ProposalStatusUpdate,
  ServiceTemplate,
  GrowthIdea,
  GrowthIdeaCreate,
  ChangeEntry,
  UndoResult,
  CommandContext,
  CommandReceipt,
  GrowthIdeaUpdate,
  Income,
  IncomeCreate,
  Expense,
  ExpenseCreate,
  ExpenseCategory,
  ExpenseCategoryCreate,
  Tax,
  TaxCreate,
  Forecast,
  ForecastCreate,
  ForecastVsActual,
  RunwayResponse,
  FinancialInsight,
  AdvisorTask,
  AdvisorAiBrief,
  AdvisorOverview,
  CsvPreviewResponse,
  CsvImportRequest,
  CsvImportResponse,
  CsvMapping,
  SyncLog,
  Digest,
  DigestGenerateRequest,
  DigestUpdateRequest,
  DigestRenderResponse,
  Lead,
  LeadCreate,
  LeadDetail,
  LeadActivity,
  PipelineSummary,
  LeadReminder,
  HoldedSyncResult,
  HoldedSyncStatus,
  HoldedSyncLog,
  HoldedInvoice,
  HoldedExpense,
  HoldedDashboard,
  HoldedConfig,
  HoldedTestConnection,
  DailyUpdate,
  DailySubmitRequest,
  DailyPrefill,
  DailyDiscordResponse,
  EmailDraftRequest,
  EmailDraftResponse,
  ClientContact,
  ClientContactCreate,
  ClientDashboard,
  ClientStatusRow,
  ClientCohort,
  CapacityMember,
  CapacityMemberDetail,
  ActivityEvent,
  NotificationItem,
  InvestmentCalculateRequest,
  InvestmentCalculateResponse,
  InboxNote,
  InboxNoteCreate,
  InboxNoteUpdate,
  JobRuntimeResponse,
  OperationalUsage,
} from "./types"

export const CSRF_COOKIE_NAME = "agency_csrf_token"

export const api = axios.create({
  baseURL: "/api",
  timeout: 30_000,
  withCredentials: true,
})

type SessionRequestConfig = InternalAxiosRequestConfig & {
  agencySessionEpoch?: number
}

let sessionEpoch = 0
let sessionAbortController = new AbortController()

/**
 * Starts a new authenticated browser session. Requests from the old session
 * are aborted and their responses can no longer expire the new session.
 */
export function beginApiSessionTransition() {
  sessionEpoch += 1
  sessionAbortController.abort()
  sessionAbortController = new AbortController()
  return sessionEpoch
}

function isLogoutRequest(url: string) {
  return url.includes("/auth/logout")
}

function withSessionAbortSignal(requestSignal?: GenericAbortSignal) {
  if (!requestSignal) return sessionAbortController.signal

  if (typeof AbortSignal.any === "function") {
    return AbortSignal.any([sessionAbortController.signal, requestSignal as AbortSignal])
  }

  const combined = new AbortController()
  const abort = () => combined.abort()
  if (requestSignal.aborted || sessionAbortController.signal.aborted) {
    abort()
    return combined.signal
  }
  sessionAbortController.signal.addEventListener("abort", abort, { once: true })
  requestSignal.addEventListener?.("abort", abort, { once: true })
  return combined.signal
}

function getCookie(name: string): string | null {
  if (typeof document === "undefined") return null
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${name}=`))
  if (!match) return null
  return decodeURIComponent(match.substring(name.length + 1))
}

api.interceptors.request.use((config) => {
  const sessionConfig = config as SessionRequestConfig
  config.headers["X-Agency-Client"] = "web"
  sessionConfig.agencySessionEpoch = sessionEpoch
  // Logout must keep its own request alive: it clears the cookie that belongs
  // to the session being ended, even while a later login is queued.
  if (!isLogoutRequest(String(config.url || ""))) {
    config.signal = withSessionAbortSignal(config.signal)
  }
  const csrfToken = getCookie(CSRF_COOKIE_NAME)
  if (csrfToken) {
    config.headers["X-CSRF-Token"] = csrfToken
  }
  return config
})

api.interceptors.response.use(
  (res) => res,
  (error) => {
    if (axios.isCancel(error) || error.code === "ERR_CANCELED") {
      return Promise.reject(error)
    }
    const method = String(error.config?.method || "").toLowerCase()
    const isGetRequest = method === "get"
    const requestUrl = String(error.config?.url || "")
    if (error.response) {
      const status = error.response.status
      if (status === 401) {
        const isAuthRequest =
          requestUrl.includes("/auth/login") ||
          requestUrl.includes("/auth/me") ||
          requestUrl.includes("/auth/logout")
        const responseEpoch = (error.config as SessionRequestConfig | undefined)?.agencySessionEpoch
        if (!isAuthRequest && responseEpoch === sessionEpoch) {
          // Signal AuthContext to clear user — ProtectedRoute handles redirect
          localStorage.removeItem("token")
          window.dispatchEvent(new Event("auth:expired"))
        }
      } else if (status === 403) {
        // GET 403: silencioso — PermissionRoute ya redirige antes de que llegue aquí
        // Mutation 403: aviso al usuario
        if (!isGetRequest) {
          toast.error("No tienes permisos para esta acción")
        }
      } else if (status >= 500) {
        // Silenciar errores de shell global (inbox, badges) para no contaminar la UI
        const isShellRequest =
          requestUrl.includes("/inbox/count") ||
          requestUrl.includes("/holded/config")
        // La página de dailys ya muestra el detalle del 502 ("El texto sigue guardado...")
        const isDailyEnrichment = /\/dailys\/\d+\/reparse$/.test(requestUrl)
        if (!isShellRequest && !isDailyEnrichment) {
          toast.error("Error del servidor. Intenta de nuevo.")
        }
      }
    } else if (error.request) {
      if (!isGetRequest) {
        toast.error("Error de conexión. Verifica tu red.")
      }
    }
    return Promise.reject(error)
  }
)

// Auth
export const authApi = {
  login: (email: string, password: string) =>
    api.post<TokenResponse>("/auth/login", { email, password }).then((r) => r.data),
  logout: () => api.post<void>("/auth/logout").then((r) => r.data),
  me: () => api.get<User>("/auth/me").then((r) => r.data),
}

// Clients
export type ClientSort = "created" | "seo_change_asc" | "seo_change_desc"

export const clientsApi = {
  list: (params?: { status?: string; cohort?: ClientCohort; page?: number; page_size?: number; sort?: ClientSort }) =>
    api.get<PaginatedResponse<Client>>("/clients", { params }).then((r) => r.data),
  listAll: (status?: string, cohort?: ClientCohort) =>
    api.get<PaginatedResponse<Client>>("/clients", { params: { ...(status && { status }), ...(cohort && { cohort }), page_size: 1000 } }).then((r) => r.data.items),
  get: (id: number) => api.get<Client>(`/clients/${id}`).then((r) => r.data),
  create: (data: ClientCreate) => api.post<Client>("/clients", data).then((r) => r.data),
  onboard: (data: ClientOnboardingCreate, requestKey: string) =>
    api.post<ClientOnboardingResult>("/clients/onboarding", data, { headers: { "X-Agency-Request-Key": requestKey } }).then((r) => r.data),
  recoverOnboarding: (requestKey: string) =>
    api.post<ClientOnboardingResult>(`/clients/onboarding-attempts/${encodeURIComponent(requestKey)}/recover`).then((r) => r.data),
  update: (id: number, data: Partial<ClientCreate>) =>
    api.put<Client>(`/clients/${id}`, data).then((r) => r.data),
  delete: (id: number) => api.delete<Client>(`/clients/${id}`).then((r) => r.data),
  hardDelete: (id: number) => api.delete(`/clients/${id}/hard`).then((r) => r.data),
  summary: (id: number) => api.get<ClientSummary>(`/clients/${id}/summary`).then((r) => r.data),
  aiAdvice: (id: number) =>
    api.post<{ recommendations: Array<{ priority: "high" | "medium" | "low"; category: string; title: string; description: string; action: string }> }>(`/clients/${id}/ai-advice`).then((r) => r.data),
  recentTimeEntries: (id: number, limit = 10) =>
    api.get<Array<{ id: number; date: string; started_at: string | null; minutes: number; notes: string | null; task_title: string | null; user_name: string | null }>>(`/clients/${id}/recent-time-entries`, { params: { limit } }).then((r) => r.data),
  whatIf: (clientId: number) => api.get(`/clients/${clientId}/what-if`).then((r) => r.data),
  extractContext: (params: { file?: File; rawText?: string }) => {
    const form = new FormData()
    if (params.file) form.append("file", params.file)
    if (params.rawText) form.append("raw_text", params.rawText)
    return api.post<ClientExtract>("/clients/extract-context", form).then((r) => r.data)
  },
  documents: {
    list: (clientId: number) =>
      api.get<ClientDocument[]>(`/clients/${clientId}/documents`).then((r) => r.data),
    upload: (clientId: number, file: File, description?: string) => {
      const form = new FormData()
      form.append("file", file)
      if (description) form.append("description", description)
      return api.post<ClientDocument>(`/clients/${clientId}/documents`, form).then((r) => r.data)
    },
    downloadUrl: (clientId: number, docId: number) =>
      `/api/clients/${clientId}/documents/${docId}/download`,
    delete: (clientId: number, docId: number) =>
      api.delete(`/clients/${clientId}/documents/${docId}`),
  },
}

// Tasks
export const tasksApi = {
  list: (params?: { client_id?: number; status?: string; category_id?: number; project_id?: number; assigned_to?: number | string; priority?: string; overdue?: boolean; no_date?: boolean; no_estimate?: boolean; no_project?: boolean; scheduled_date?: string; due_date_from?: string; due_date_to?: string; scheduled_date_from?: string; scheduled_date_to?: string; is_recurring?: boolean; timer_eligible?: boolean; timer_scope?: "assigned" | "assigned_or_created"; retirement?: "active" | "retired"; search?: string; page?: number; page_size?: number }) =>
    api.get<PaginatedResponse<Task>>("/tasks", { params }).then((r) => r.data),
  agenda: (params: { date: string; section: TaskAgendaSection; assigned_to?: number | "me" | "unassigned" | "all"; timezone_offset_minutes?: number; page?: number; page_size?: number }) =>
    api.get<PaginatedResponse<Task>>("/tasks/agenda", { params }).then((r) => r.data),
  listAll: async (params?: { client_id?: number; status?: string; category_id?: number; project_id?: number; assigned_to?: number | string; priority?: string; overdue?: boolean; scheduled_date?: string; due_date_from?: string; due_date_to?: string; scheduled_date_from?: string; scheduled_date_to?: string; is_recurring?: boolean; timer_eligible?: boolean; timer_scope?: "assigned" | "assigned_or_created" }) => {
    const items: Task[] = []
    let page = 1
    let total = Infinity
    while (items.length < total) {
      const response = await api.get<PaginatedResponse<Task>>("/tasks", { params: { ...params, page, page_size: 1000 } })
      const batch = response.data.items
      items.push(...batch)
      total = response.data.total
      if (batch.length === 0) break
      page += 1
    }
    return items
  },
  get: (id: number) => api.get<Task>(`/tasks/${id}`).then((r) => r.data),
  create: (data: TaskCreate) => api.post<Task>("/tasks", data).then((r) => r.data),
  update: (id: number, data: Partial<TaskCreate>) =>
    api.put<Task>(`/tasks/${id}`, data).then((r) => r.data),
  carryoverDecision: (id: number, data: {
    action: "reschedule" | "wait" | "complete" | "retire"
    expected_updated_at: string
    scheduled_date?: string
    waiting_for?: string
    follow_up_date?: string
    reason?: string
  }) => api.post<Task>(`/tasks/${id}/carryover-decision`, data).then((r) => r.data),
  restore: (id: number, expected_updated_at: string) =>
    api.post<Task>(`/tasks/${id}/restore`, { expected_updated_at }).then((r) => r.data),
  recurrencePreview: (data: Pick<TaskCreate, "is_recurring" | "recurrence_pattern" | "recurrence_day" | "recurrence_anchor_date" | "recurrence_end_date" | "client_id" | "project_id" | "phase_id" | "recurrence_paused">) =>
    api.post<RecurrenceSummary>("/tasks/recurrence-preview", data).then((r) => r.data),
  delete: (id: number) => api.delete(`/tasks/${id}`).then((r) => r.data),
  bulkUpdate: (ids: number[], updates: Record<string, unknown>) =>
    api.patch<{ updated: number; failed: number; requested: number; results: Array<{ id: number; updated: boolean; detail?: string }> }>("/tasks/bulk/update", { ids, updates }).then((r) => r.data),
  bulkDelete: (ids: number[]) =>
    api.post<{ deleted: number; errors: number; requested: number }>("/tasks/bulk/delete", { ids }).then((r) => r.data),
  checklist: {
    list: (taskId: number) => api.get<ChecklistItem[]>(`/tasks/${taskId}/checklist`).then((r) => r.data),
    create: (taskId: number, text: string, assigned_to?: number | null, due_date?: string | null, description?: string | null) =>
      api.post<ChecklistItem>(`/tasks/${taskId}/checklist`, { text, assigned_to, due_date, description }).then((r) => r.data),
    update: (taskId: number, itemId: number, data: Partial<{ text: string; description: string | null; is_done: boolean; assigned_to: number | null; due_date: string | null }>) =>
      api.put<ChecklistItem>(`/tasks/${taskId}/checklist/${itemId}`, data).then((r) => r.data),
    delete: (taskId: number, itemId: number) =>
      api.delete(`/tasks/${taskId}/checklist/${itemId}`).then((r) => r.data),
  },
  comments: {
    list: (taskId: number) =>
      api.get<TaskComment[]>(`/tasks/${taskId}/comments`).then((r) => r.data),
    create: (taskId: number, text: string) =>
      api.post<TaskComment>(`/tasks/${taskId}/comments`, { text }).then((r) => r.data),
    delete: (taskId: number, commentId: number) =>
      api.delete(`/tasks/${taskId}/comments/${commentId}`).then((r) => r.data),
  },
  attachments: {
    list: (taskId: number) =>
      api.get<TaskAttachment[]>(`/tasks/${taskId}/attachments`).then((r) => r.data),
    upload: (taskId: number, file: File, description?: string) => {
      const fd = new FormData()
      fd.append("file", file)
      if (description) fd.append("description", description)
      return api.post<TaskAttachment>(`/tasks/${taskId}/attachments`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      }).then((r) => r.data)
    },
    download: (taskId: number, attachmentId: number) =>
      api.get(`/tasks/${taskId}/attachments/${attachmentId}/download`, { responseType: "blob" }).then((r) => r.data),
    delete: (taskId: number, attachmentId: number) =>
      api.delete(`/tasks/${taskId}/attachments/${attachmentId}`).then((r) => r.data),
  },
}

// Time Entries
export const timeEntriesApi = {
  list: (params?: { task_id?: number; user_id?: number; date_from?: string; date_to?: string }) =>
    api.get<TimeEntry[]>("/time-entries", { params }).then((r) => r.data),
  weekly: (week_start?: string) =>
    api.get<WeeklyTimesheet>("/time-entries/weekly", { params: week_start ? { week_start } : {} }).then((r) => r.data),
  create: (data: TimeEntryCreate) => api.post<TimeEntry>("/time-entries", data).then((r) => r.data),
  update: (id: number, data: { minutes?: number; notes?: string; task_id?: number }) =>
    api.put<TimeEntry>(`/time-entries/${id}`, data).then((r) => r.data),
  delete: (id: number) => api.delete(`/time-entries/${id}`).then((r) => r.data),
  exportCsv: (params?: { date_from?: string; date_to?: string; user_id?: number; client_id?: number; project_id?: number }) =>
    api.get("/time-entries/export", { params, responseType: "blob" }).then((r) => r.data),
  byProject: (params?: { date_from?: string; date_to?: string; client_id?: number }) =>
    api.get<ProjectTimeReport[]>("/time-entries/by-project", { params }).then((r) => r.data),
  byClient: (params?: { date_from?: string; date_to?: string }) =>
    api.get<ClientTimeReport[]>("/time-entries/by-client", { params }).then((r) => r.data),
  adminTimers: () =>
    api.get<AdminActiveTimer[]>("/admin/timers/active").then((r) => r.data),
}

// Timer
export const timerApi = {
  start: (data: { task_id?: number | null; notes?: string }) =>
    api.post<ActiveTimer>("/timer/start", data).then((r) => r.data),
  stop: (timerId: number, notes?: string) => api.post<TimeEntry>("/timer/stop", { timer_id: timerId, notes }).then((r) => r.data),
  pause: () => api.post<ActiveTimer>("/timer/pause").then((r) => r.data),
  resume: () => api.post<ActiveTimer>("/timer/resume").then((r) => r.data),
  active: () =>
    api.get<ActiveTimer>("/timer/active").then((r) => r.data).catch((err) => {
      if (err.response?.status === 204) return null
      throw err
    }),
}

// Users
export const usersApi = {
  list: (params?: { page?: number; page_size?: number }) =>
    api.get<PaginatedResponse<User>>("/users", { params }).then((r) => r.data),
  listAll: () =>
    api.get<PaginatedResponse<User>>("/users", { params: { page_size: 1000 } }).then((r) => r.data.items),
  create: (data: UserCreate) => api.post<User>("/users", data).then((r) => r.data),
  get: (id: number) => api.get<User>(`/users/${id}`).then((r) => r.data),
  update: (id: number, data: Partial<User>) => api.put<User>(`/users/${id}`, data).then((r) => r.data),
  deactivationImpact: (id: number) =>
    api.get<DeactivationImpact>(`/users/${id}/deactivation-impact`).then((r) => r.data),
  getPermissions: (id: number) => api.get<UserPermission[]>(`/users/${id}/permissions`).then((r) => r.data),
  updatePermissions: (id: number, permissions: UserPermission[]) =>
    api.put<UserPermission[]>(`/users/${id}/permissions`, { permissions }).then((r) => r.data),
}

// Dashboard
export const dashboardApi = {
  overview: (params?: { year?: number; month?: number }) =>
    api.get<DashboardOverview>("/dashboard/overview", { params }).then((r) => r.data),
  operations: () => api.get<DashboardOperations>("/dashboard/operations").then((r) => r.data),
  financialOverview: (params?: { year?: number; month?: number }) =>
    api.get<DashboardFinancialOverview>("/dashboard/overview/financial", { params }).then((r) => r.data),
  profitability: (params?: { year?: number; month?: number }) =>
    api.get<ProfitabilityResponse>("/dashboard/profitability", { params }).then((r) => r.data),
  team: (params?: { year?: number; month?: number }) =>
    api.get<TeamMemberSummary[]>("/dashboard/team", { params }).then((r) => r.data),
  monthlyClose: (params?: { year?: number; month?: number }) =>
    api.get<MonthlyClose>("/dashboard/monthly-close", { params }).then((r) => r.data),
  updateMonthlyClose: (data: Partial<MonthlyClose>, params?: { year?: number; month?: number }) =>
    api.put<MonthlyClose>("/dashboard/monthly-close", data, { params }).then((r) => r.data),
  financialSettings: () =>
    api.get<FinancialSettings>("/dashboard/financial-settings").then((r) => r.data),
  updateFinancialSettings: (data: Partial<FinancialSettings>) =>
    api.put<FinancialSettings>("/dashboard/financial-settings", data).then((r) => r.data),
  exportMonthlyClose: (params?: { year?: number; month?: number }) =>
    api.get("/dashboard/monthly-close/export", { params, responseType: "blob" }).then((r) => r.data),
  today: () => api.get("/dashboard/today").then((r) => r.data),
  alertsSummary: () => api.get("/dashboard/alerts-summary").then((r) => r.data),
  utilization: (params?: { year?: number; month?: number }) =>
    api.get("/dashboard/utilization", { params }).then((r) => r.data),
}

// Balance Snapshots
export const balanceApi = {
  latest: () => api.get<BalanceSnapshot | null>("/finance/balance/latest").then((r) => r.data),
  create: (data: BalanceSnapshotCreate) => api.post<BalanceSnapshot>("/finance/balance", data).then((r) => r.data),
  list: () => api.get<BalanceSnapshot[]>("/finance/balance").then((r) => r.data),
}

// Discord
export const discordApi = {
  preview: (date?: string) =>
    api.get<import("./types").DiscordPreview>("/discord/preview", { params: date ? { date } : {} }).then((r) => r.data),
  send: (params: { date: string; expected_revision: string }) =>
    api.post<import("./types").DeliveryReceipt>("/discord/send", null, { params }).then((r) => r.data),
  settings: () =>
    api.get<import("./types").DiscordSettings>("/discord/settings").then((r) => r.data),
  updateSettings: (data: Partial<import("./types").DiscordSettings>) =>
    api.put<import("./types").DiscordSettings>("/discord/settings", data).then((r) => r.data),
  testWebhook: (requestKey: string) =>
    api.post<import("./types").DeliveryReceipt>("/discord/test-webhook", null, {
      headers: { "X-Agency-Request-Key": requestKey },
    }).then((r) => r.data),
  sendDailySummary: (date?: string) =>
    api.post<import("./types").DeliveryReceipt>("/discord/send-daily-summary", null, { params: date ? { date } : {} }).then((r) => r.data),
  sendDigest: (digestId: number, content?: string) =>
    api.post<import("./types").DeliveryReceipt>(`/discord/send-digest/${digestId}`, { content }).then((r) => r.data),
  sendCustom: (content: string) =>
    api.post<import("./types").DeliveryReceipt>("/discord/send-custom", { content }, { headers: { "X-Agency-Send-Intent": "custom-v1" } }).then((r) => r.data),
  sendWeeklyReport: (weekStart?: string) =>
    api.post<import("./types").DeliveryReceipt>("/discord/send-weekly-report", null, { params: weekStart ? { week_start: weekStart } : {} }).then((r) => r.data),
}

// Task Categories
export const categoriesApi = {
  list: () => api.get<TaskCategory[]>("/task-categories").then((r) => r.data),
  create: (data: { name: string; default_minutes: number }) =>
    api.post<TaskCategory>("/task-categories", data).then((r) => r.data),
  update: (id: number, data: { name?: string; default_minutes?: number }) =>
    api.put<TaskCategory>(`/task-categories/${id}`, data).then((r) => r.data),
  delete: (id: number) => api.delete(`/task-categories/${id}`).then((r) => r.data),
}

// Projects
export const projectsApi = {
  list: (params?: { client_id?: number; status?: string; owner?: string; lifecycle?: "portfolio" | "archive"; project_type?: string; is_recurring?: boolean; period_from?: string; period_to?: string; page?: number; page_size?: number }) =>
    api.get<PaginatedResponse<ProjectListItem>>("/projects", { params }).then((r) => r.data),
  unassignedCount: () =>
    api.get<PaginatedResponse<ProjectListItem>>("/projects", { params: { lifecycle: "portfolio", owner: "unassigned", page_size: 1 } }).then((r) => r.data.total),
  listAll: (params?: { client_id?: number; status?: string; project_type?: string }) =>
    api.get<PaginatedResponse<ProjectListItem>>("/projects", { params: { ...params, page_size: 1000 } }).then((r) => r.data.items),
  get: (id: number) => api.get<Project>(`/projects/${id}`).then((r) => r.data),
  closePreview: (id: number, target: "completed" | "cancelled") =>
    api.get<import("./types").ProjectClosePreview>(`/projects/${id}/close-preview`, { params: { target } }).then((r) => r.data),
  close: (id: number, data: { target: "completed" | "cancelled"; expected_updated_at: string; preview_revision: string }) =>
    api.post<Project>(`/projects/${id}/close`, data).then((r) => r.data),
  reopenPreview: (id: number) =>
    api.get<import("./types").ProjectReopenPreview>(`/projects/${id}/reopen-preview`).then((r) => r.data),
  reopen: (id: number, data: { expected_updated_at: string; preview_revision: string }) =>
    api.post<Project>(`/projects/${id}/reopen`, data).then((r) => r.data),
  create: (data: ProjectCreate) => api.post<Project>("/projects", data).then((r) => r.data),
  update: (id: number, data: Partial<ProjectCreate> & { status?: string; progress_percent?: number }) =>
    api.put<Project>(`/projects/${id}`, data).then((r) => r.data),
  delete: (id: number) => api.delete(`/projects/${id}`).then((r) => r.data),
  templates: () => api.get<Record<string, ProjectTemplate>>("/projects/templates").then((r) => r.data),
  templateDetail: (id: number) => api.get<ProjectTemplateDetail>(`/projects/templates/${id}`).then((r) => r.data),
  createTemplate: (data: Record<string, unknown>) => api.post("/projects/templates", data).then((r) => r.data),
  updateTemplate: (id: number, data: Record<string, unknown>) => api.put(`/projects/templates/${id}`, data).then((r) => r.data),
  deleteTemplate: (id: number) => api.delete(`/projects/templates/${id}`).then((r) => r.data),
  saveAsTemplate: (projectId: number, data: { name: string; key?: string; description?: string }) =>
    api.post(`/projects/${projectId}/save-as-template`, data).then((r) => r.data),
  createFromTemplate: (client_id: number, template_key: string, start_date?: string, owner_id?: number) =>
    api.post<Project>("/projects/from-template", null, { params: { client_id, template_key, start_date, owner_id } }).then((r) => r.data),
  extractFromPdf: (file: File) => {
    const form = new FormData()
    form.append("file", file)
    return api.post<ProjectDraft>("/projects/extract-from-pdf", form).then((r) => r.data)
  },
  extractFromText: (file: File) => {
    const form = new FormData()
    form.append("file", file)
    return api.post<ProjectDraft>("/projects/extract-from-text", form).then((r) => r.data)
  },
  tasks: (id: number) => api.get<ProjectTasksResponse>(`/projects/${id}/tasks`).then((r) => r.data),
  monthlyCycle: (id: number, month?: string) =>
    api.get<ProjectMonthlyCycle>(`/projects/${id}/monthly-cycle`, { params: { month } }).then((r) => r.data),
  burndown: (id: number) => api.get(`/projects/${id}/burndown`).then((r) => r.data),
  createPhase: (project_id: number, data: { name: string; order_index: number; start_date?: string; due_date?: string }) =>
    api.post<ProjectPhase>(`/projects/${project_id}/phases`, data).then((r) => r.data),
  updatePhase: (phase_id: number, data: { name?: string; status?: string }) =>
    api.put<ProjectPhase>(`/projects/phases/${phase_id}`, data).then((r) => r.data),
  deletePhase: (phase_id: number) => api.delete(`/projects/phases/${phase_id}`).then((r) => r.data),
}

// Communications
export const communicationsApi = {
  list: (client_id: number) =>
    api.get<Communication[]>(`/clients/${client_id}/communications`).then((r) => r.data),
  create: (client_id: number, data: CommunicationCreate) =>
    api.post<Communication>(`/clients/${client_id}/communications`, data).then((r) => r.data),
  get: (id: number) => api.get<Communication>(`/communications/${id}`).then((r) => r.data),
  update: (id: number, data: Partial<CommunicationCreate>) =>
    api.put<Communication>(`/communications/${id}`, data).then((r) => r.data),
  delete: (id: number) => api.delete(`/communications/${id}`).then((r) => r.data),
  pendingFollowups: () =>
    api.get<Communication[]>("/communications/pending-followups").then((r) => r.data),
  draftEmail: (data: EmailDraftRequest) =>
    api.post<EmailDraftResponse>("/communications/draft-email", data).then((r) => r.data),
}

// PM Assistant
export const pmApi = {
  insights: (params?: { status?: string; priority?: string }) =>
    api.get<Insight[]>("/pm/insights", { params }).then((r) => r.data),
  generateInsights: () =>
    api.post<Insight[]>("/pm/generate-insights", {}, { timeout: 90_000 }).then((r) => r.data),
  dismissInsight: (id: number) =>
    api.put<Insight>(`/pm/insights/${id}/dismiss`).then((r) => r.data),
  actOnInsight: (id: number) =>
    api.put<Insight>(`/pm/insights/${id}/act`).then((r) => r.data),
  insightCount: () =>
    api.get<InsightCount>("/pm/insights/count").then((r) => r.data),
  dailyBriefing: (scope: "mine" | "team" = "mine") =>
    api.get<DailyBriefing>("/pm/daily-briefing", { params: { scope } }).then((r) => r.data),
  alertSettings: () =>
    api.get<AlertSettings>("/pm/settings/alerts").then((r) => r.data),
  updateAlertSettings: (data: AlertSettingsUpdate) =>
    api.put<AlertSettings>("/pm/settings/alerts", data).then((r) => r.data),
  shareBriefingToDiscord: (scope: "mine" | "team" = "mine", content?: string, date?: string) =>
    api.post<import("./types").DeliveryReceipt>("/pm/briefing/discord", content || date ? { content, date } : null, { params: { scope } }).then((r) => r.data),
}

// Service Templates
export const serviceTemplatesApi = {
  list: () => api.get<ServiceTemplate[]>("/service-templates").then((r) => r.data),
  get: (serviceType: string) =>
    api.get<ServiceTemplate>(`/service-templates/${serviceType}`).then((r) => r.data),
}

// Proposals
export const proposalsApi = {
  list: (params?: { client_id?: number; status?: string; lead_id?: number; service_type?: string }) =>
    api.get<Proposal[]>("/proposals", { params }).then((r) => r.data),
  get: (id: number) => api.get<Proposal>(`/proposals/${id}`).then((r) => r.data),
  create: (data: ProposalCreate) => api.post<Proposal>("/proposals", data).then((r) => r.data),
  update: (id: number, data: ProposalUpdate) =>
    api.put<Proposal>(`/proposals/${id}`, data).then((r) => r.data),
  delete: (id: number) => api.delete(`/proposals/${id}`).then((r) => r.data),
  changeStatus: (id: number, data: ProposalStatusUpdate) =>
    api.put<Proposal>(`/proposals/${id}/status`, data).then((r) => r.data),
  duplicate: (id: number) => api.post<Proposal>(`/proposals/${id}/duplicate`).then((r) => r.data),
  convert: (id: number) => api.post<Proposal>(`/proposals/${id}/convert`).then((r) => r.data),
  generate: (id: number) => api.post<Proposal>(`/proposals/${id}/generate`, {}, { timeout: 90_000 }).then((r) => r.data),
  pdf: (id: number) => api.get(`/proposals/${id}/pdf`, { responseType: "blob" }).then((r) => r.data),
  pdfUrl: (id: number) => `/api/proposals/${id}/pdf`,
  draftEmail: (id: number) =>
    api.post<{ subject: string; body: string; tone: string; suggested_followup: string | null }>(`/proposals/${id}/draft-email`).then((r) => r.data),
  saveInvestment: (id: number, data: Record<string, unknown>) =>
    api.post<Proposal>(`/proposals/${id}/save-investment`, data).then((r) => r.data),
}

// Investments
export const investmentsApi = {
  calculate: (data: InvestmentCalculateRequest) =>
    api.post<InvestmentCalculateResponse>("/investments/calculate", data).then((r) => r.data),
}

// Growth Operations
export const growthApi = {
  list: (params?: { status?: string; funnel_stage?: string; project_id?: number }) =>
    api.get<GrowthIdea[]>("/growth", { params }).then((r) => r.data),
  create: (data: GrowthIdeaCreate) =>
    api.post<GrowthIdea>("/growth", data).then((r) => r.data),
  update: (id: number, data: GrowthIdeaUpdate) =>
    api.put<GrowthIdea>(`/growth/${id}`, data).then((r) => r.data),
  delete: (id: number) =>
    api.delete(`/growth/${id}`).then((r) => r.data),
  convertToProject: (id: number, clientId: number) =>
    api.post<{ project_id: number; message: string }>(`/growth/${id}/convert-to-project`, null, { params: { client_id: clientId } }).then((r) => r.data),
  createTask: (id: number, clientId: number) =>
    api.post<{ task_id: number; message: string }>(`/growth/${id}/create-task`, null, { params: { client_id: clientId } }).then((r) => r.data),
}

// --- Finance APIs ---

export const financeIncomeApi = {
  list: (params?: { date_from?: string; date_to?: string; client_id?: number; type?: string; status?: string }) =>
    api.get<Income[]>("/finance/income", { params }).then((r) => r.data),
  get: (id: number) => api.get<Income>(`/finance/income/${id}`).then((r) => r.data),
  create: (data: IncomeCreate) => api.post<Income>("/finance/income", data).then((r) => r.data),
  update: (id: number, data: Partial<IncomeCreate>) =>
    api.put<Income>(`/finance/income/${id}`, data).then((r) => r.data),
  delete: (id: number) => api.delete(`/finance/income/${id}`).then((r) => r.data),
}

export const financeExpensesApi = {
  list: (params?: { date_from?: string; date_to?: string; category_id?: number; is_recurring?: boolean }) =>
    api.get<Expense[]>("/finance/expenses", { params }).then((r) => r.data),
  get: (id: number) => api.get<Expense>(`/finance/expenses/${id}`).then((r) => r.data),
  create: (data: ExpenseCreate) => api.post<Expense>("/finance/expenses", data).then((r) => r.data),
  update: (id: number, data: Partial<ExpenseCreate>) =>
    api.put<Expense>(`/finance/expenses/${id}`, data).then((r) => r.data),
  delete: (id: number) => api.delete(`/finance/expenses/${id}`).then((r) => r.data),
  generateRecurring: (year?: number, month?: number) =>
    api.post<{ created: number; skipped: number; month: string }>(
      "/finance/expenses/generate-recurring",
      null,
      { params: { year, month } }
    ).then((r) => r.data),
}

export const financeExpenseCategoriesApi = {
  list: () => api.get<ExpenseCategory[]>("/finance/expense-categories").then((r) => r.data),
  create: (data: ExpenseCategoryCreate) =>
    api.post<ExpenseCategory>("/finance/expense-categories", data).then((r) => r.data),
  update: (id: number, data: ExpenseCategoryCreate) =>
    api.put<ExpenseCategory>(`/finance/expense-categories/${id}`, data).then((r) => r.data),
  delete: (id: number) => api.delete(`/finance/expense-categories/${id}`).then((r) => r.data),
}

export const financeTaxesApi = {
  list: (params?: { year?: number; model?: string; period?: string; status?: string }) =>
    api.get<Tax[]>("/finance/taxes", { params }).then((r) => r.data),
  get: (id: number) => api.get<Tax>(`/finance/taxes/${id}`).then((r) => r.data),
  create: (data: TaxCreate) => api.post<Tax>("/finance/taxes", data).then((r) => r.data),
  update: (id: number, data: Partial<TaxCreate>) =>
    api.put<Tax>(`/finance/taxes/${id}`, data).then((r) => r.data),
  delete: (id: number) => api.delete(`/finance/taxes/${id}`).then((r) => r.data),
  calendar: (year: number) =>
    api.get("/finance/taxes/calendar", { params: { year } }).then((r) => r.data),
  summary: (year: number) =>
    api.get("/finance/taxes/summary/" + year).then((r) => r.data),
  calculate: (year: number) =>
    api.post(`/finance/taxes/calculate/${year}`).then((r) => r.data),
}

export const financeForecastsApi = {
  list: (params?: { year?: number }) =>
    api.get<Forecast[]>("/finance/forecasts", { params }).then((r) => r.data),
  get: (id: number) => api.get<Forecast>(`/finance/forecasts/${id}`).then((r) => r.data),
  create: (data: ForecastCreate) => api.post<Forecast>("/finance/forecasts", data).then((r) => r.data),
  update: (id: number, data: Partial<ForecastCreate>) =>
    api.put<Forecast>(`/finance/forecasts/${id}`, data).then((r) => r.data),
  delete: (id: number) => api.delete(`/finance/forecasts/${id}`).then((r) => r.data),
  generate: (months?: number) =>
    api.post("/finance/forecasts/generate", null, { params: months ? { months } : {} }).then((r) => r.data),
  runway: () => api.get<RunwayResponse>("/finance/forecasts/runway").then((r) => r.data),
  vsActual: (year: number) =>
    api.get<ForecastVsActual[]>("/finance/forecasts/vs-actual", { params: { year } }).then((r) => r.data),
}

export const financeAdvisorApi = {
  overview: () => api.get<AdvisorOverview>("/finance/advisor/overview").then((r) => r.data),
  insights: () => api.get<FinancialInsight[]>("/finance/advisor/insights").then((r) => r.data),
  markInsightRead: (id: number) => api.put(`/finance/advisor/insights/${id}/read`).then((r) => r.data),
  dismissInsight: (id: number) => api.put(`/finance/advisor/insights/${id}/dismiss`).then((r) => r.data),
  tasks: (params?: { status?: string }) =>
    api.get<AdvisorTask[]>("/finance/advisor/tasks", { params }).then((r) => r.data),
  createTask: (data: { source_key: string; title: string; description?: string; priority?: string; due_date?: string }) =>
    api.post<AdvisorTask>("/finance/advisor/tasks", data).then((r) => r.data),
  updateTask: (id: number, data: { status: string }) =>
    api.put(`/finance/advisor/tasks/${id}`, data).then((r) => r.data),
  deleteTask: (id: number) => api.delete(`/finance/advisor/tasks/${id}`).then((r) => r.data),
  aiBriefs: (limit?: number) =>
    api.get<AdvisorAiBrief[]>("/finance/advisor/ai-briefs", { params: limit ? { limit } : {} }).then((r) => r.data),
  generateBrief: (year: number, quarter: string) =>
    api.post<{ id: number; content: Record<string, unknown> }>("/finance/advisor/generate-brief", null, { params: { year, quarter }, timeout: 90_000 }).then((r) => r.data),
  generateInsights: () =>
    api.post<{ ok: boolean; insights_created: number; insights: { title: string; description: string; severity: string }[] }>("/finance/advisor/generate-insights", null, { timeout: 90_000 }).then((r) => r.data),
  monthlyClose: (params?: { year?: number; month?: number }) =>
    api.get<MonthlyClose>("/finance/advisor/monthly-close", { params }).then((r) => r.data),
  updateMonthlyClose: (data: Partial<MonthlyClose>, params?: { year?: number; month?: number }) =>
    api.put("/finance/advisor/monthly-close", data, { params }).then((r) => r.data),
}

export const financeSyncApi = {
  preview: (content: string, delimiter?: string) =>
    api.post<CsvPreviewResponse>("/finance/sync/preview", { content, delimiter }).then((r) => r.data),
  import: (data: CsvImportRequest) =>
    api.post<CsvImportResponse>("/finance/sync/import", data).then((r) => r.data),
  mappings: () => api.get<CsvMapping[]>("/finance/sync/mappings").then((r) => r.data),
  createMapping: (data: { name: string; target: string; mapping: Record<string, string>; delimiter?: string }) =>
    api.post<CsvMapping>("/finance/sync/mappings", data).then((r) => r.data),
  deleteMapping: (id: number) => api.delete(`/finance/sync/mappings/${id}`).then((r) => r.data),
  logs: () => api.get<SyncLog[]>("/finance/sync/logs").then((r) => r.data),
}

export const bankImportApi = {
  preview: (content: string) =>
    api.post<{ transactions: { row: number; date: string; description: string; amount: number; is_income: boolean }[]; total: number }>("/finance/bank-import/preview", { content }).then((r) => r.data),
  match: (content: string) =>
    api.post<{ transactions: { row: number; date: string; description: string; amount: number; is_income: boolean; match: { income_id: number; invoice_number: string | null; client_name: string | null; amount: number } | null; confidence: number }[]; total: number; matched: number }>("/finance/bank-import/match", { content }).then((r) => r.data),
  apply: (matches: { income_id: number }[]) =>
    api.post<{ ok: boolean; applied: number }>("/finance/bank-import/apply", { matches }).then((r) => r.data),
}

// --- Weekly Digests ---
export const digestsApi = {
  list: (params?: { client_id?: number; status?: string; period_from?: string; period_to?: string; limit?: number; offset?: number }) =>
    api.get<Digest[]>("/digests", { params }).then((r) => r.data),
  get: (id: number) => api.get<Digest>(`/digests/${id}`).then((r) => r.data),
  recoverGeneration: (generationKey: string) => api.get<Digest>(`/digests/generation/${generationKey}`).then((r) => r.data),
  generate: (data: DigestGenerateRequest) =>
    api.post<Digest>("/digests/generate", data, { timeout: 90_000 }).then((r) => r.data),
  generateBatch: (params?: { period_start?: string; period_end?: string; tone?: string }) =>
    api.post<Digest[]>("/digests/generate-batch", null, { params, timeout: 90_000 }).then((r) => r.data),
  update: (id: number, data: DigestUpdateRequest) =>
    api.put<Digest>(`/digests/${id}`, data).then((r) => r.data),
  updateStatus: (id: number, status: string) =>
    api.patch<Digest>(`/digests/${id}/status`, { status }).then((r) => r.data),
  render: (id: number, format: "slack" | "email" | "email_plain" | "discord") =>
    api.get<DigestRenderResponse>(`/digests/${id}/render`, { params: { format } }).then((r) => r.data),
  delete: (id: number) => api.delete(`/digests/${id}`).then((r) => r.data),
}

// --- CRM Leads ---
export const leadsApi = {
  list: (params?: { status?: string; source?: string; assigned_to?: number; service_interest?: string }) =>
    api.get<Lead[]>("/leads", { params }).then((r) => r.data),
  get: (id: number) => api.get<LeadDetail>(`/leads/${id}`).then((r) => r.data),
  create: (data: LeadCreate) => api.post<Lead>("/leads", data).then((r) => r.data),
  update: (id: number, data: Partial<LeadCreate> & { status?: string; lost_reason?: string; last_contacted_at?: string }) =>
    api.put<Lead>(`/leads/${id}`, data).then((r) => r.data),
  delete: (id: number) => api.delete(`/leads/${id}`).then((r) => r.data),
  addActivity: (leadId: number, data: { activity_type: string; title: string; description?: string }) =>
    api.post<LeadActivity>(`/leads/${leadId}/activities`, data).then((r) => r.data),
  convert: (leadId: number) =>
    api.post<{ message: string; client_id: number; client_name: string }>(`/leads/${leadId}/convert`).then((r) => r.data),
  pipelineSummary: () =>
    api.get<PipelineSummary>("/leads/pipeline-summary").then((r) => r.data),
  reminders: () =>
    api.get<LeadReminder[]>("/leads/reminders").then((r) => r.data),
}

// --- Holded Integration ---
export const holdedApi = {
  // Sync
  syncContacts: () => api.post<HoldedSyncResult>("/holded/sync/contacts").then((r) => r.data),
  syncInvoices: () => api.post<HoldedSyncResult>("/holded/sync/invoices").then((r) => r.data),
  syncExpenses: () => api.post<HoldedSyncResult>("/holded/sync/expenses").then((r) => r.data),
  syncAll: () => api.post<HoldedSyncResult[]>("/holded/sync/all").then((r) => r.data),
  syncStatus: () => api.get<HoldedSyncStatus>("/holded/sync/status").then((r) => r.data),
  syncLogs: (limit = 20) => api.get<HoldedSyncLog[]>("/holded/sync/logs", { params: { limit } }).then((r) => r.data),
  // Data
  invoices: (params?: { client_id?: number; status?: string; date_from?: string; date_to?: string; page?: number; page_size?: number }) =>
    api.get<PaginatedResponse<HoldedInvoice>>("/holded/invoices", { params }).then((r) => r.data),
  invoicePdf: (holdedId: string) =>
    api.get(`/holded/invoices/${holdedId}/pdf`, { responseType: "blob" }).then((r) => r.data),
  expenses: (params?: { category?: string; date_from?: string; date_to?: string; page?: number; page_size?: number }) =>
    api.get<PaginatedResponse<HoldedExpense>>("/holded/expenses", { params }).then((r) => r.data),
  dashboard: () => api.get<HoldedDashboard>("/holded/dashboard").then((r) => r.data),
  // Config
  config: () => api.get<HoldedConfig>("/holded/config").then((r) => r.data),
  testConnection: () => api.post<HoldedTestConnection>("/holded/test-connection").then((r) => r.data),
  // Client invoices
  clientInvoices: (clientId: number) =>
    api.get<HoldedInvoice[]>(`/holded/clients/${clientId}/invoices`).then((r) => r.data),
}

// --- Daily Updates ---
export const dailysApi = {
  list: (params?: { user_id?: number; date_from?: string; date_to?: string; limit?: number }) =>
    api.get<DailyUpdate[]>("/dailys", { params }).then((r) => r.data),
  get: (id: number) => api.get<DailyUpdate>(`/dailys/${id}`).then((r) => r.data),
  submit: (data: DailySubmitRequest) =>
    api.post<DailyUpdate>("/dailys", data).then((r) => r.data),
  forDate: (date: string) => api.get<DailyUpdate | null>("/dailys/for-date", { params: { date } }).then((r) => r.data),
  reparse: (id: number, revision: number) =>
    api.post<DailyUpdate>(`/dailys/${id}/reparse`, { revision }, { timeout: 90_000 }).then((r) => r.data),
  previewDiscord: (id: number) =>
    api.get<{ revision: number; content: string }>(`/dailys/${id}/preview`).then((r) => r.data),
  sendDiscord: (id: number, data?: { revision: number; content: string }) =>
    api.post<DailyDiscordResponse>(`/dailys/${id}/send-discord`, data).then((r) => r.data),
  edit: (id: number, data: { raw_text?: string; parsed_data?: DailyUpdate["parsed_data"]; revision: number; source_fact_keys?: string[] }) =>
    api.put<DailyUpdate>(`/dailys/${id}`, data).then((r) => r.data),
  delete: (id: number, revision: number) => api.delete(`/dailys/${id}`, { params: { revision } }).then((r) => r.data),
  prefill: (date: string) => api.get<DailyPrefill>("/dailys/prefill", { params: { date } }).then((r) => r.data),
}

export const deliveriesApi = {
  get: (id: string) => api.get<import("./types").DeliveryReceipt>(`/deliveries/${encodeURIComponent(id)}`).then((r) => r.data),
  list: (source_kind: "daily" | "digest" | "communication", source_id: number) =>
    api.get<import("./types").DeliveryReceipt[]>("/deliveries", { params: { source_kind, source_id } }).then((r) => r.data),
  retry: (id: string) => api.post<import("./types").DeliveryReceipt>(`/deliveries/${id}/retry`).then((r) => r.data),
  cancel: (id: string) => api.post<import("./types").DeliveryReceipt>(`/deliveries/${id}/cancel`).then((r) => r.data),
  resend: (id: string, reviewKey: string) =>
    api.post<import("./types").DeliveryReceipt>(`/deliveries/${id}/resend`, { reviewed: true, review_key: reviewKey }).then((r) => r.data),
  listManual: (kind: "pm_briefing" | "weekly_report" | "daily_summary" | "custom" | "connection_test", scope?: "mine" | "team") =>
    api.get<import("./types").DeliveryReceipt[]>("/deliveries/manual", { params: { kind, ...(scope ? { scope } : {}) } }).then((r) => r.data),
}

export const financeExportApi = {
  income: (params?: { year?: number; month?: number }) =>
    api.get("/finance/export/income", { params, responseType: "blob" }).then((r) => r.data),
  expenses: (params?: { year?: number; month?: number }) =>
    api.get("/finance/export/expenses", { params, responseType: "blob" }).then((r) => r.data),
  taxes: (params?: { year?: number }) =>
    api.get("/finance/export/taxes", { params, responseType: "blob" }).then((r) => r.data),
}

// --- Client Contacts ---
export const contactsApi = {
  list: (clientId: number) =>
    api.get<ClientContact[]>(`/clients/${clientId}/contacts`).then((r) => r.data),
  create: (clientId: number, data: ClientContactCreate) =>
    api.post<ClientContact>(`/clients/${clientId}/contacts`, data).then((r) => r.data),
  update: (clientId: number, contactId: number, data: Partial<ClientContactCreate>) =>
    api.put<ClientContact>(`/clients/${clientId}/contacts/${contactId}`, data).then((r) => r.data),
  delete: (clientId: number, contactId: number) =>
    api.delete(`/clients/${clientId}/contacts/${contactId}`).then((r) => r.data),
}

// --- Client Dashboard ---
export const clientDashboardApi = {
  get: (clientId: number) =>
    api.get<ClientDashboard>(`/clients/${clientId}/dashboard`).then((r) => r.data),
}

// --- Estado del cliente (cartera) ---
export const clientStatusApi = {
  get: (clientId: number) =>
    api.get<ClientStatusRow>(`/clients/${clientId}/status`).then((r) => r.data),
  portfolio: (cohort: ClientCohort = "external") =>
    api.get<ClientStatusRow[]>("/clients/portfolio", { params: { cohort } }).then((r) => r.data),
}

// --- Capacity Planning ---
export const capacityApi = {
  get: () =>
    api.get<CapacityMember[]>("/dashboard/capacity").then((r) => r.data),
  detail: () =>
    api.get<CapacityMemberDetail[]>("/dashboard/capacity/detail").then((r) => r.data),
}

// --- Client Activity Timeline ---
export const clientActivityApi = {
  list: (clientId: number, limit = 50) =>
    api.get<ActivityEvent[]>(`/clients/${clientId}/activity`, { params: { limit } }).then((r) => r.data),
}

export const notificationsApi = {
  list: (params?: { limit?: number; offset?: number; unread_only?: boolean }) =>
    api.get<NotificationItem[]>("/notifications", { params }).then((r) => r.data),
  unreadCount: () =>
    api.get<{ count: number }>("/notifications/unread-count").then((r) => r.data),
  markRead: (id: number) =>
    api.put(`/notifications/${id}/read`).then((r) => r.data),
  markAllRead: () =>
    api.put("/notifications/read-all").then((r) => r.data),
  generateChecks: () =>
    api.post<{ created: number }>("/notifications/generate-checks").then((r) => r.data),
}

// --- Undo (journal de cambios) ---
export const changesApi = {
  recent: (limit = 5) =>
    api.get<ChangeEntry[]>("/changes/recent", { params: { limit } }).then((r) => r.data),
  undo: (id: number) =>
    api.post<UndoResult>(`/changes/${id}/undo`).then((r) => r.data),
}

export const commandsApi = {
  get: (id: string) =>
    api.get<CommandReceipt>(`/commands/${id}`).then((r) => r.data),
  create: (data: { request_key: string; text: string; channel: "app" | "extension"; context?: CommandContext }) =>
    api.post<CommandReceipt>("/commands", data).then((r) => r.data),
  resolve: (id: string, data: { request_key: string; revision: number; answers: Array<{ field: string; choice_id?: string; value?: string | number }> }) =>
    api.post<CommandReceipt>(`/commands/${id}/resolve`, data).then((r) => r.data),
  execute: (id: string, data: { request_key: string; revision: number }) =>
    api.post<CommandReceipt>(`/commands/${id}/execute`, data).then((r) => r.data),
  query: (id: string, page: number, pageSize = 25) =>
    api.get<NonNullable<NonNullable<CommandReceipt["result"]>["query"]>>(`/commands/${id}/query`, { params: { page, page_size: pageSize } }).then((r) => r.data),
  list: (page = 1, pageSize = 5) =>
    api.get<{ items: CommandReceipt[]; total: number; page: number; page_size: number; has_more: boolean }>("/commands", { params: { page, page_size: pageSize } }).then((r) => r.data),
}

export const operationalUsageApi = {
  get: (days = 30) =>
    api.get<OperationalUsage>("/admin/usage/operational", { params: { days } }).then((response) => response.data),
  origins: (days = 30) =>
    api.get<Array<{ origin: "web" | "extension" | "unknown"; hits: number }>>("/admin/usage/origins", { params: { days } }).then((response) => response.data),
}

// --- Global Search ---
export const searchApi = {
  search: (q: string) =>
    api.get<SearchResults>("/search", { params: { q } }).then((r) => r.data),
}

// --- Engine Integration ---
export interface EngineProject {
  id: number
  name: string
  domain: string
  logo_url: string | null
  agency_client_id: number | null
  agency_project_id: number | null
  agency_synced_at: string | null
}

export interface EngineMetrics {
  project_id: number
  project_name: string
  domain: string
  content_count: number
  keyword_count: number
  avg_position: number | null
  clicks_30d: number
  impressions_30d: number
}

export const engineApi = {
  listProjects: () =>
    api.get<EngineProject[]>("/engine/projects").then((r) => r.data),
  getMetrics: (projectId: number) =>
    api.get<EngineMetrics>(`/engine/projects/${projectId}/metrics`).then((r) => r.data),
  getReportData: (projectId: number, from?: string, to?: string) =>
    api.get(`/engine/projects/${projectId}/report-data`, { params: { from_date: from, to_date: to } }).then((r) => r.data),
  getConfig: () =>
    api.get<{ engine_frontend_url: string | null }>("/engine/config").then((r) => r.data),
  triggerSync: () =>
    api.post<{ synced: number; failed: number; detail?: string }>("/engine/sync").then((r) => r.data),
}

// ── Inbox Quick Capture ────────────────────────────────────

export const inboxApi = {
  list: (params?: { status?: string; limit?: number; offset?: number }) =>
    api.get<InboxNote[]>("/inbox", { params }).then((r) => r.data),
  count: () =>
    api.get<{ count: number }>("/inbox/count").then((r) => r.data),
  create: (data: InboxNoteCreate) =>
    api.post<InboxNote>("/inbox", data).then((r) => r.data),
  update: (id: number, data: InboxNoteUpdate) =>
    api.put<InboxNote>(`/inbox/${id}`, data).then((r) => r.data),
  delete: (id: number) =>
    api.delete(`/inbox/${id}`).then((r) => r.data),
  classify: (id: number) =>
    api.post<InboxNote>(`/inbox/${id}/classify`).then((r) => r.data),
  convertToTask: (id: number, data?: { title?: string; project_id?: number; client_id?: number; priority?: string; assigned_to?: number }) =>
    api.post<{ ok: boolean; task_id: number; note: InboxNote }>(`/inbox/${id}/convert-to-task`, data).then((r) => r.data),
  dismiss: (id: number) =>
    api.post<InboxNote>(`/inbox/${id}/dismiss`).then((r) => r.data),
  suggest: (id: number) =>
    api.post<InboxNote>(`/inbox/${id}/suggest`).then((r) => r.data),
  uploadAttachment: (noteId: number, file: File) => {
    const fd = new FormData()
    fd.append("file", file)
    return api.post<{ id: number; name: string; mime_type: string; size_bytes: number }>(`/inbox/${noteId}/attachments`, fd, {
      headers: { "Content-Type": "multipart/form-data" },
    }).then((r) => r.data)
  },
  deleteAttachment: (noteId: number, attachmentId: number) =>
    api.delete(`/inbox/${noteId}/attachments/${attachmentId}`).then((r) => r.data),
}

// ── Google Calendar ───────────────────────────────────────
export interface NextMeetingResponse {
  meeting: { id: number; title: string; date: string; time: string; source: "manual" | "google" } | null
  timezone: string
  connection_status: "connected" | "disconnected" | "reconnect_required"
  last_synced_at: string | null
}

export const calendarApi = {
  nextMeeting: () => api.get<NextMeetingResponse>("/calendar/next-meeting").then((r) => r.data),
  getAuthUrl: () =>
    api.get<{ url: string }>("/calendar/auth-url").then((r) => r.data),
  getStatus: () =>
    api.get<{ connected: boolean; connection_status: "connected" | "disconnected" | "reconnect_required"; calendar_id: string | null; last_synced_at: string | null; meeting_alerts: { minutes_before: number; discord_dm: boolean; extension: boolean } | null }>("/calendar/status").then((r) => r.data),
  disconnect: () =>
    api.post("/calendar/disconnect").then((r) => r.data),
  updateAlerts: (data: { minutes_before: number; discord_dm: boolean; extension: boolean }) =>
    api.put("/calendar/alerts", data).then((r) => r.data),
  sync: () =>
    api.post<{ ok: boolean; events_synced: number }>("/calendar/sync").then((r) => r.data),
  upcoming: (minutes: number = 60) =>
    api.get<{ id: number; title: string; start_time: string; minutes_until: number }[]>(`/calendar/upcoming?minutes=${minutes}`).then((r) => r.data),
}

// ── Search Console ──────────────────────────────────────────

export interface GscSiteStatus {
  site_url: string
  clients: { id: number; name: string }[]
  backfilled: boolean
  last_data_date: string | null
  last_synced_at: string | null
  error_code: string | null
  /** Cuenta de Google con la que se importa (la que ve la propiedad). */
  google_email: string | null
}

export interface GscConnectionStatus {
  id: number
  status: "connected" | "reconnect_required"
  google_email: string | null
  connected_by: string | null
  connected_at: string
}

export interface GscStatus {
  configured: boolean
  connections: GscConnectionStatus[]
  sites: GscSiteStatus[]
}

export const vigilApi = {
  clients: () => api.get<VigilClients>("/vigil/clients").then((r) => r.data),
}

export const gscApi = {
  getStatus: () => api.get<GscStatus>("/gsc/status").then((r) => r.data),
  getAuthUrl: () => api.get<{ url: string }>("/gsc/auth-url").then((r) => r.data),
  disconnect: (connectionId: number) => api.post(`/gsc/connections/${connectionId}/disconnect`).then((r) => r.data),
  listSites: () => api.get<{ sites: { site_url: string; permission: string | null; google_email: string | null }[] }>("/gsc/sites").then((r) => r.data),
  sync: () => api.post<{ status: string; synced: number; failed: number }>("/gsc/sync").then((r) => r.data),
}

// ── Festivos ─────────────────────────────────────────────

export interface CompanyHolidayResponse {
  id: number
  date: string
  name: string
  country: string
  region: string | null
  locality: string | null
}

export const holidaysApi = {
  list: (year?: number, region?: string) =>
    api.get<CompanyHolidayResponse[]>("/holidays", {
      params: { ...(year ? { year } : {}), ...(region ? { region } : {}) },
    }).then((r) => r.data),
  create: (data: { date: string; name: string; country?: string; region?: string | null; locality?: string | null }) =>
    api.post<CompanyHolidayResponse>("/holidays", data).then((r) => r.data),
  delete: (id: number) =>
    api.delete(`/holidays/${id}`).then((r) => r.data),
}

export const jobRuntimeApi = {
  list: () => api.get<JobRuntimeResponse>("/admin/job-runtime").then((r) => r.data),
}
