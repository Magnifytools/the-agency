import { lazy, Suspense } from "react"
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { Toaster } from "sonner"
import { AuthProvider } from "@/context/auth-context"
import { ProtectedRoute } from "@/components/layout/protected-route"
import { PermissionRoute } from "@/components/layout/permission-route"
import { AppLayout } from "@/components/layout/app-layout"
import { ErrorBoundary } from "@/components/ui/error-boundary"

// Eagerly loaded (always needed)
import LoginPage from "@/pages/login"

// Lazy loaded pages (code-split per route)
const DashboardPage = lazy(() => import("@/pages/dashboard-page"))
const ClientsPage = lazy(() => import("@/pages/clients-page"))
const ClientDetailPage = lazy(() => import("@/pages/client-detail-page"))
const TasksPage = lazy(() => import("@/pages/tasks-page"))
const UsersPage = lazy(() => import("@/pages/users-page"))
const TimesheetPage = lazy(() => import("@/pages/timesheet-page"))
const BillingPage = lazy(() => import("@/pages/billing-page"))
const ProjectsPage = lazy(() => import("@/pages/projects-page"))
const ProjectDetailPage = lazy(() => import("@/pages/project-detail-page"))
const ReportsPage = lazy(() => import("@/pages/reports-page"))
const ProposalsPage = lazy(() => import("@/pages/proposals-page"))
const LeadsPage = lazy(() => import("@/pages/leads-page"))
const LeadDetailPage = lazy(() => import("@/pages/lead-detail-page"))
const DigestsPage = lazy(() => import("@/pages/digests-page"))
const DigestEditPage = lazy(() => import("@/pages/digest-edit-page"))
const GrowthPage = lazy(() => import("@/pages/growth-page"))
const FinanceDashboardPage = lazy(() => import("@/pages/finance-dashboard-page"))
const IncomePage = lazy(() => import("@/pages/income-page"))
const ExpensesPage = lazy(() => import("@/pages/expenses-page"))
const TaxesPage = lazy(() => import("@/pages/taxes-page"))
const ForecastsPage = lazy(() => import("@/pages/forecasts-page"))
const AdvisorPage = lazy(() => import("@/pages/advisor-page"))
const ImportPage = lazy(() => import("@/pages/import-page"))
const HoldedFinancePage = lazy(() => import("@/pages/holded-finance-page"))
const DiscordSettingsPage = lazy(() => import("@/pages/discord-settings-page"))
const DailysPage = lazy(() => import("@/pages/dailys-page"))
const CapacityPage = lazy(() => import("@/pages/capacity-page"))
const ExecutiveDashboardPage = lazy(() => import("@/pages/executive-dashboard-page"))
const AgencyVaultPage = lazy(() => import("@/pages/agency-vault-page"))
const IndustryNewsPage = lazy(() => import("@/pages/industry-news-page"))
const InboxPage = lazy(() => import("@/pages/inbox-page"))
const MyWeekPage = lazy(() => import("@/pages/my-week-page"))
const SettingsPage = lazy(() => import("@/pages/settings-page"))
const AutomationsPage = lazy(() => import("@/pages/automations-page"))

function PageLoader() {
  return (
    <div className="space-y-4 p-6 animate-pulse">
      <div className="h-7 w-48 rounded bg-muted" />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-24 rounded-lg bg-muted" />
        ))}
      </div>
      <div className="h-64 rounded-lg bg-muted" />
    </div>
  )
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (failureCount, error) => {
        // No reintentar en errores de permisos o not found
        const status = (error as { response?: { status?: number } })?.response?.status
        if (status === 403 || status === 404 || status === 401) return false
        return failureCount < 1
      },
    },
  },
})

export default function App() {
  return (
    <ErrorBoundary section="App">
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route
              element={
                <ProtectedRoute>
                  <ErrorBoundary section="Layout">
                    <AppLayout />
                  </ErrorBoundary>
                </ProtectedRoute>
              }
            >
              <Route path="/dashboard" element={<ErrorBoundary section="Dashboard"><Suspense fallback={<PageLoader />}><DashboardPage /></Suspense></ErrorBoundary>} />
              <Route path="/executive" element={<PermissionRoute adminOnly><ErrorBoundary section="Executive"><Suspense fallback={<PageLoader />}><ExecutiveDashboardPage /></Suspense></ErrorBoundary></PermissionRoute>} />
              <Route path="/pipeline" element={<Navigate to="/leads" replace />} />
              <Route path="/leads" element={<PermissionRoute module="growth"><ErrorBoundary section="Leads"><Suspense fallback={<PageLoader />}><LeadsPage /></Suspense></ErrorBoundary></PermissionRoute>} />
              <Route path="/leads/:id" element={<PermissionRoute module="growth"><ErrorBoundary section="LeadDetail"><Suspense fallback={<PageLoader />}><LeadDetailPage /></Suspense></ErrorBoundary></PermissionRoute>} />
              <Route path="/clients" element={<ErrorBoundary section="Clients"><Suspense fallback={<PageLoader />}><ClientsPage /></Suspense></ErrorBoundary>} />
              <Route path="/clients/:id" element={<ErrorBoundary section="ClientDetail"><Suspense fallback={<PageLoader />}><ClientDetailPage /></Suspense></ErrorBoundary>} />
              <Route path="/tasks" element={<ErrorBoundary section="Tasks"><Suspense fallback={<PageLoader />}><TasksPage /></Suspense></ErrorBoundary>} />
              <Route path="/projects" element={<ErrorBoundary section="Projects"><Suspense fallback={<PageLoader />}><ProjectsPage /></Suspense></ErrorBoundary>} />
              <Route path="/projects/:id" element={<ErrorBoundary section="ProjectDetail"><Suspense fallback={<PageLoader />}><ProjectDetailPage /></Suspense></ErrorBoundary>} />
              <Route path="/growth" element={<ErrorBoundary section="Growth"><Suspense fallback={<PageLoader />}><GrowthPage /></Suspense></ErrorBoundary>} />
              <Route path="/capacity" element={<PermissionRoute adminOnly><ErrorBoundary section="Capacity"><Suspense fallback={<PageLoader />}><CapacityPage /></Suspense></ErrorBoundary></PermissionRoute>} />
              <Route path="/users" element={<PermissionRoute adminOnly><ErrorBoundary section="Users"><Suspense fallback={<PageLoader />}><UsersPage /></Suspense></ErrorBoundary></PermissionRoute>} />
              <Route path="/timesheet" element={<ErrorBoundary section="Timesheet"><Suspense fallback={<PageLoader />}><TimesheetPage /></Suspense></ErrorBoundary>} />
              <Route path="/billing" element={<PermissionRoute adminOnly><ErrorBoundary section="Billing"><Suspense fallback={<PageLoader />}><BillingPage /></Suspense></ErrorBoundary></PermissionRoute>} />
              <Route path="/proposals" element={<PermissionRoute module="proposals"><ErrorBoundary section="Proposals"><Suspense fallback={<PageLoader />}><ProposalsPage /></Suspense></ErrorBoundary></PermissionRoute>} />
              <Route path="/digests" element={<PermissionRoute module="digests"><ErrorBoundary section="Digests"><Suspense fallback={<PageLoader />}><DigestsPage /></Suspense></ErrorBoundary></PermissionRoute>} />
              <Route path="/digests/:id/edit" element={<PermissionRoute module="digests"><ErrorBoundary section="DigestEdit"><Suspense fallback={<PageLoader />}><DigestEditPage /></Suspense></ErrorBoundary></PermissionRoute>} />
              <Route path="/dailys" element={<ErrorBoundary section="Dailys"><Suspense fallback={<PageLoader />}><DailysPage /></Suspense></ErrorBoundary>} />
              <Route path="/reports" element={<PermissionRoute module="reports"><ErrorBoundary section="Reports"><Suspense fallback={<PageLoader />}><ReportsPage /></Suspense></ErrorBoundary></PermissionRoute>} />
              {/* Finance — admin only */}
              <Route path="/finance" element={<PermissionRoute adminOnly><ErrorBoundary section="Finance"><Suspense fallback={<PageLoader />}><FinanceDashboardPage /></Suspense></ErrorBoundary></PermissionRoute>} />
              <Route path="/finance/income" element={<PermissionRoute adminOnly><ErrorBoundary section="Income"><Suspense fallback={<PageLoader />}><IncomePage /></Suspense></ErrorBoundary></PermissionRoute>} />
              <Route path="/finance/expenses" element={<PermissionRoute adminOnly><ErrorBoundary section="Expenses"><Suspense fallback={<PageLoader />}><ExpensesPage /></Suspense></ErrorBoundary></PermissionRoute>} />
              <Route path="/finance/taxes" element={<PermissionRoute adminOnly><ErrorBoundary section="Taxes"><Suspense fallback={<PageLoader />}><TaxesPage /></Suspense></ErrorBoundary></PermissionRoute>} />
              <Route path="/finance/forecasts" element={<PermissionRoute adminOnly><ErrorBoundary section="Forecasts"><Suspense fallback={<PageLoader />}><ForecastsPage /></Suspense></ErrorBoundary></PermissionRoute>} />
              <Route path="/finance/advisor" element={<PermissionRoute adminOnly><ErrorBoundary section="Advisor"><Suspense fallback={<PageLoader />}><AdvisorPage /></Suspense></ErrorBoundary></PermissionRoute>} />
              <Route path="/finance/import" element={<PermissionRoute adminOnly><ErrorBoundary section="Import"><Suspense fallback={<PageLoader />}><ImportPage /></Suspense></ErrorBoundary></PermissionRoute>} />
              {/* Holded Finance — admin only */}
              <Route path="/finance-holded" element={<PermissionRoute adminOnly><ErrorBoundary section="HoldedFinance"><Suspense fallback={<PageLoader />}><HoldedFinancePage /></Suspense></ErrorBoundary></PermissionRoute>} />
              {/* Agency */}
              <Route path="/news" element={<ErrorBoundary section="News"><Suspense fallback={<PageLoader />}><IndustryNewsPage /></Suspense></ErrorBoundary>} />
              <Route path="/vault" element={<PermissionRoute adminOnly><ErrorBoundary section="Vault"><Suspense fallback={<PageLoader />}><AgencyVaultPage /></Suspense></ErrorBoundary></PermissionRoute>} />
              <Route path="/inbox" element={<ErrorBoundary section="Inbox"><Suspense fallback={<PageLoader />}><InboxPage /></Suspense></ErrorBoundary>} />
              <Route path="/my-week" element={<ErrorBoundary section="MyWeek"><Suspense fallback={<PageLoader />}><MyWeekPage /></Suspense></ErrorBoundary>} />
              {/* Discord */}
              <Route path="/discord" element={<PermissionRoute adminOnly><ErrorBoundary section="Discord"><Suspense fallback={<PageLoader />}><DiscordSettingsPage /></Suspense></ErrorBoundary></PermissionRoute>} />
              {/* Automations */}
              <Route path="/automations" element={<PermissionRoute adminOnly><ErrorBoundary section="Automations"><Suspense fallback={<PageLoader />}><AutomationsPage /></Suspense></ErrorBoundary></PermissionRoute>} />
              {/* Settings */}
              <Route path="/settings" element={<ErrorBoundary section="Settings"><Suspense fallback={<PageLoader />}><SettingsPage /></Suspense></ErrorBoundary>} />
            </Route>
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
      <Toaster position="top-right" richColors />
    </QueryClientProvider>
    </ErrorBoundary>
  )
}
