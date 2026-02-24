import axios from "axios"
import { toast } from "sonner"
import type {
  PaginatedResponse,
  Client,
  ClientCreate,
  ClientSummary,
  Task,
  TaskCreate,
  TaskCategory,
  TokenResponse,
  User,
  UserCreate,
  UserPermission,
  TimeEntry,
  TimeEntryCreate,
  ActiveTimer,
  WeeklyTimesheet,
  DashboardOverview,
  ProfitabilityResponse,
  TeamMemberSummary,
  MonthlyClose,
  FinancialSettings,
  Project,
  ProjectListItem,
  ProjectCreate,
  ProjectTemplate,
  ProjectPhase,
  Communication,
  CommunicationCreate,
  Insight,
  InsightCount,
  DailyBriefing,
  AlertSettings,
  AlertSettingsUpdate,
  Report,
  ReportRequest,
  Proposal,
  ProposalCreate,
  ProposalUpdate,
  GrowthIdea,
  GrowthIdeaCreate,
  GrowthIdeaUpdate,
  Invitation,
  InvitationCreate,
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
} from "./types"

const api = axios.create({
  baseURL: "/api",
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token")
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(
  (res) => res,
  (error) => {
    if (error.response) {
      const status = error.response.status
      if (status === 401) {
        localStorage.removeItem("token")
        window.location.href = "/login"
      } else if (status === 403) {
        toast.error("No tienes permisos para esta acción")
      } else if (status >= 500) {
        toast.error("Error del servidor. Intenta de nuevo.")
      }
    } else if (error.request) {
      toast.error("Error de conexión. Verifica tu red.")
    }
    return Promise.reject(error)
  }
)

// Auth
export const authApi = {
  login: (email: string, password: string) =>
    api.post<TokenResponse>("/auth/login", { email, password }).then((r) => r.data),
  me: () => api.get<User>("/auth/me").then((r) => r.data),
}

// Clients
export const clientsApi = {
  list: (params?: { status?: string; page?: number; page_size?: number }) =>
    api.get<PaginatedResponse<Client>>("/clients", { params }).then((r) => r.data),
  listAll: (status?: string) =>
    api.get<PaginatedResponse<Client>>("/clients", { params: { status, page_size: 999 } }).then((r) => r.data.items),
  get: (id: number) => api.get<Client>(`/clients/${id}`).then((r) => r.data),
  create: (data: ClientCreate) => api.post<Client>("/clients", data).then((r) => r.data),
  update: (id: number, data: Partial<ClientCreate>) =>
    api.put<Client>(`/clients/${id}`, data).then((r) => r.data),
  delete: (id: number) => api.delete<Client>(`/clients/${id}`).then((r) => r.data),
  summary: (id: number) => api.get<ClientSummary>(`/clients/${id}/summary`).then((r) => r.data),
}

// Tasks
export const tasksApi = {
  list: (params?: { client_id?: number; status?: string; category_id?: number; project_id?: number; assigned_to?: number; priority?: string; overdue?: boolean; page?: number; page_size?: number }) =>
    api.get<PaginatedResponse<Task>>("/tasks", { params }).then((r) => r.data),
  listAll: (params?: { client_id?: number; status?: string; category_id?: number; project_id?: number; assigned_to?: number; priority?: string; overdue?: boolean }) =>
    api.get<PaginatedResponse<Task>>("/tasks", { params: { ...params, page_size: 999 } }).then((r) => r.data.items),
  get: (id: number) => api.get<Task>(`/tasks/${id}`).then((r) => r.data),
  create: (data: TaskCreate) => api.post<Task>("/tasks", data).then((r) => r.data),
  update: (id: number, data: Partial<TaskCreate>) =>
    api.put<Task>(`/tasks/${id}`, data).then((r) => r.data),
  delete: (id: number) => api.delete(`/tasks/${id}`).then((r) => r.data),
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
}

// Timer
export const timerApi = {
  start: (data: { task_id?: number | null; notes?: string }) =>
    api.post<ActiveTimer>("/timer/start", data).then((r) => r.data),
  stop: (notes?: string) => api.post<TimeEntry>("/timer/stop", { notes }).then((r) => r.data),
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
    api.get<PaginatedResponse<User>>("/users", { params: { page_size: 999 } }).then((r) => r.data.items),
  create: (data: UserCreate) => api.post<User>("/users", data).then((r) => r.data),
  get: (id: number) => api.get<User>(`/users/${id}`).then((r) => r.data),
  update: (id: number, data: Partial<User>) => api.put<User>(`/users/${id}`, data).then((r) => r.data),
}

// Dashboard
export const dashboardApi = {
  overview: (params?: { year?: number; month?: number }) =>
    api.get<DashboardOverview>("/dashboard/overview", { params }).then((r) => r.data),
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
}

// Billing
export const billingApi = {
  preview: (params: { year: number; month: number }) =>
    api.get("/billing/export", { params: { ...params, format: "json" } }).then((r) => r.data),
}

// Discord
export const discordApi = {
  preview: (date?: string) =>
    api.get<{ summary: string; date: string }>("/discord/preview", { params: date ? { date } : {} }).then((r) => r.data),
  send: (date?: string) =>
    api.post<{ ok: boolean; date: string }>("/discord/send", null, { params: date ? { date } : {} }).then((r) => r.data),
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
  list: (params?: { client_id?: number; status?: string; project_type?: string; page?: number; page_size?: number }) =>
    api.get<PaginatedResponse<ProjectListItem>>("/projects", { params }).then((r) => r.data),
  listAll: (params?: { client_id?: number; status?: string; project_type?: string }) =>
    api.get<PaginatedResponse<ProjectListItem>>("/projects", { params: { ...params, page_size: 999 } }).then((r) => r.data.items),
  get: (id: number) => api.get<Project>(`/projects/${id}`).then((r) => r.data),
  create: (data: ProjectCreate) => api.post<Project>("/projects", data).then((r) => r.data),
  update: (id: number, data: Partial<ProjectCreate> & { status?: string; progress_percent?: number }) =>
    api.put<Project>(`/projects/${id}`, data).then((r) => r.data),
  delete: (id: number) => api.delete(`/projects/${id}`).then((r) => r.data),
  templates: () => api.get<Record<string, ProjectTemplate>>("/projects/templates").then((r) => r.data),
  createFromTemplate: (client_id: number, template_key: string, start_date?: string) =>
    api.post<Project>("/projects/from-template", null, { params: { client_id, template_key, start_date } }).then((r) => r.data),
  tasks: (id: number) => api.get(`/projects/${id}/tasks`).then((r) => r.data),
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
}

// PM Assistant
export const pmApi = {
  insights: (params?: { status?: string; priority?: string }) =>
    api.get<Insight[]>("/pm/insights", { params }).then((r) => r.data),
  generateInsights: () =>
    api.post<Insight[]>("/pm/generate-insights").then((r) => r.data),
  dismissInsight: (id: number) =>
    api.put<Insight>(`/pm/insights/${id}/dismiss`).then((r) => r.data),
  actOnInsight: (id: number) =>
    api.put<Insight>(`/pm/insights/${id}/act`).then((r) => r.data),
  insightCount: () =>
    api.get<InsightCount>("/pm/insights/count").then((r) => r.data),
  dailyBriefing: () =>
    api.get<DailyBriefing>("/pm/daily-briefing").then((r) => r.data),
  alertSettings: () =>
    api.get<AlertSettings>("/pm/settings/alerts").then((r) => r.data),
  updateAlertSettings: (data: AlertSettingsUpdate) =>
    api.put<AlertSettings>("/pm/settings/alerts", data).then((r) => r.data),
  shareBriefingToDiscord: () =>
    api.post<{ status: string, message: string }>("/pm/briefing/discord").then((r) => r.data),
}

// Reports
export const reportsApi = {
  list: (limit?: number) =>
    api.get<Report[]>("/reports", { params: limit ? { limit } : {} }).then((r) => r.data),
  get: (id: number) =>
    api.get<Report>(`/reports/${id}`).then((r) => r.data),
  generate: (data: ReportRequest) =>
    api.post<Report>("/reports/generate", data).then((r) => r.data),
  delete: (id: number) =>
    api.delete(`/reports/${id}`).then((r) => r.data),
}

// Proposals
export const proposalsApi = {
  list: (params?: { client_id?: number; status_filter?: string }) =>
    api.get<Proposal[]>("/proposals", { params }).then((r) => r.data),
  get: (id: number) => api.get<Proposal>(`/proposals/${id}`).then((r) => r.data),
  create: (data: ProposalCreate) => api.post<Proposal>("/proposals", data).then((r) => r.data),
  update: (id: number, data: ProposalUpdate) =>
    api.put<Proposal>(`/proposals/${id}`, data).then((r) => r.data),
  delete: (id: number) => api.delete(`/proposals/${id}`).then((r) => r.data),
  downloadPdf: (id: number) =>
    api.get(`/proposals/${id}/pdf`, { responseType: "blob" }).then((r) => r.data),
}

// Invitations & Permissions
export const invitationsApi = {
  list: () => api.get<Invitation[]>("/invitations").then((r) => r.data),
  create: (data: InvitationCreate) =>
    api.post<Invitation>("/invitations", data).then((r) => r.data),
  revoke: (id: number) => api.delete(`/invitations/${id}`).then((r) => r.data),
  accept: (data: { token: string; full_name: string; password: string }) =>
    api.post<User>("/invitations/accept", data).then((r) => r.data),
  getPermissions: (userId: number) =>
    api.get<UserPermission[]>(`/users/${userId}/permissions`).then((r) => r.data),
  updatePermissions: (userId: number, permissions: UserPermission[]) =>
    api.put<UserPermission[]>(`/users/${userId}/permissions`, { permissions }).then((r) => r.data),
}

// Growth Operations
export const growthApi = {
  list: (params?: { status?: string; funnel_stage?: string }) =>
    api.get<GrowthIdea[]>("/growth", { params }).then((r) => r.data),
  create: (data: GrowthIdeaCreate) =>
    api.post<GrowthIdea>("/growth", data).then((r) => r.data),
  update: (id: number, data: GrowthIdeaUpdate) =>
    api.put<GrowthIdea>(`/growth/${id}`, data).then((r) => r.data),
  delete: (id: number) =>
    api.delete(`/growth/${id}`).then((r) => r.data),
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

// --- Weekly Digests ---
export const digestsApi = {
  list: (params?: { client_id?: number; status?: string; limit?: number; offset?: number }) =>
    api.get<Digest[]>("/digests", { params }).then((r) => r.data),
  get: (id: number) => api.get<Digest>(`/digests/${id}`).then((r) => r.data),
  generate: (data: DigestGenerateRequest) =>
    api.post<Digest>("/digests/generate", data).then((r) => r.data),
  generateBatch: (params?: { period_start?: string; period_end?: string; tone?: string }) =>
    api.post<Digest[]>("/digests/generate-batch", null, { params }).then((r) => r.data),
  update: (id: number, data: DigestUpdateRequest) =>
    api.put<Digest>(`/digests/${id}`, data).then((r) => r.data),
  updateStatus: (id: number, status: string) =>
    api.patch<Digest>(`/digests/${id}/status`, { status }).then((r) => r.data),
  render: (id: number, format: "slack" | "email") =>
    api.get<DigestRenderResponse>(`/digests/${id}/render`, { params: { format } }).then((r) => r.data),
}

export const financeExportApi = {
  income: (params?: { year?: number; month?: number }) =>
    api.get("/finance/export/income", { params, responseType: "blob" }).then((r) => r.data),
  expenses: (params?: { year?: number; month?: number }) =>
    api.get("/finance/export/expenses", { params, responseType: "blob" }).then((r) => r.data),
  taxes: (params?: { year?: number }) =>
    api.get("/finance/export/taxes", { params, responseType: "blob" }).then((r) => r.data),
}
