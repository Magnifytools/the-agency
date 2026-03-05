import { lazy, Suspense } from "react"
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { Toaster } from "sonner"
import { AuthProvider } from "@/context/auth-context"
import { ProtectedRoute } from "@/components/layout/protected-route"
import { PermissionRoute } from "@/components/layout/permission-route"
import { AppLayout } from "@/components/layout/app-layout"
import { ErrorBoundary } from "@/components/ui/error-boundary"
import { Loader2 } from "lucide-react"

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
const SettingsPage = lazy(() => import("@/pages/settings-page"))

function PageLoader() {
  return (
    <div className="flex items-center justify-center h-64">
      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
    </div>
  )
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1 },
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
              <Route path="/dashboard" element={<Suspense fallback={<PageLoader />}><DashboardPage /></Suspense>} />
              <Route path="/executive" element={<PermissionRoute adminOnly><Suspense fallback={<PageLoader />}><ExecutiveDashboardPage /></Suspense></PermissionRoute>} />
              <Route path="/pipeline" element={<Navigate to="/leads" replace />} />
              <Route path="/leads" element={<PermissionRoute module="growth"><Suspense fallback={<PageLoader />}><LeadsPage /></Suspense></PermissionRoute>} />
              <Route path="/leads/:id" element={<PermissionRoute module="growth"><Suspense fallback={<PageLoader />}><LeadDetailPage /></Suspense></PermissionRoute>} />
              <Route path="/clients" element={<Suspense fallback={<PageLoader />}><ClientsPage /></Suspense>} />
              <Route path="/clients/:id" element={<Suspense fallback={<PageLoader />}><ClientDetailPage /></Suspense>} />
              <Route path="/tasks" element={<Suspense fallback={<PageLoader />}><TasksPage /></Suspense>} />
              <Route path="/projects" element={<Suspense fallback={<PageLoader />}><ProjectsPage /></Suspense>} />
              <Route path="/projects/:id" element={<Suspense fallback={<PageLoader />}><ProjectDetailPage /></Suspense>} />
              <Route path="/growth" element={<Suspense fallback={<PageLoader />}><GrowthPage /></Suspense>} />
              <Route path="/capacity" element={<PermissionRoute adminOnly><Suspense fallback={<PageLoader />}><CapacityPage /></Suspense></PermissionRoute>} />
              <Route path="/users" element={<PermissionRoute adminOnly><Suspense fallback={<PageLoader />}><UsersPage /></Suspense></PermissionRoute>} />
              <Route path="/timesheet" element={<Suspense fallback={<PageLoader />}><TimesheetPage /></Suspense>} />
              <Route path="/billing" element={<PermissionRoute module="billing"><Suspense fallback={<PageLoader />}><BillingPage /></Suspense></PermissionRoute>} />
              <Route path="/proposals" element={<PermissionRoute module="proposals"><Suspense fallback={<PageLoader />}><ProposalsPage /></Suspense></PermissionRoute>} />
              <Route path="/digests" element={<Suspense fallback={<PageLoader />}><DigestsPage /></Suspense>} />
              <Route path="/digests/:id/edit" element={<Suspense fallback={<PageLoader />}><DigestEditPage /></Suspense>} />
              <Route path="/dailys" element={<Suspense fallback={<PageLoader />}><DailysPage /></Suspense>} />
              <Route path="/reports" element={<PermissionRoute module="reports"><Suspense fallback={<PageLoader />}><ReportsPage /></Suspense></PermissionRoute>} />
              {/* Finance */}
              <Route path="/finance" element={<PermissionRoute module="finance_dashboard"><Suspense fallback={<PageLoader />}><FinanceDashboardPage /></Suspense></PermissionRoute>} />
              <Route path="/finance/income" element={<PermissionRoute module="finance_income"><Suspense fallback={<PageLoader />}><IncomePage /></Suspense></PermissionRoute>} />
              <Route path="/finance/expenses" element={<PermissionRoute module="finance_expenses"><Suspense fallback={<PageLoader />}><ExpensesPage /></Suspense></PermissionRoute>} />
              <Route path="/finance/taxes" element={<PermissionRoute module="finance_taxes"><Suspense fallback={<PageLoader />}><TaxesPage /></Suspense></PermissionRoute>} />
              <Route path="/finance/forecasts" element={<PermissionRoute module="finance_forecasts"><Suspense fallback={<PageLoader />}><ForecastsPage /></Suspense></PermissionRoute>} />
              <Route path="/finance/advisor" element={<PermissionRoute module="finance_advisor"><Suspense fallback={<PageLoader />}><AdvisorPage /></Suspense></PermissionRoute>} />
              <Route path="/finance/import" element={<PermissionRoute module="finance_import"><Suspense fallback={<PageLoader />}><ImportPage /></Suspense></PermissionRoute>} />
              {/* Holded Finance */}
              <Route path="/finance-holded" element={<PermissionRoute module="finance_dashboard"><Suspense fallback={<PageLoader />}><HoldedFinancePage /></Suspense></PermissionRoute>} />
              {/* Agency */}
              <Route path="/news" element={<Suspense fallback={<PageLoader />}><IndustryNewsPage /></Suspense>} />
              <Route path="/vault" element={<PermissionRoute adminOnly><Suspense fallback={<PageLoader />}><AgencyVaultPage /></Suspense></PermissionRoute>} />
              <Route path="/inbox" element={<Suspense fallback={<PageLoader />}><InboxPage /></Suspense>} />
              {/* Discord */}
              <Route path="/discord" element={<PermissionRoute adminOnly><Suspense fallback={<PageLoader />}><DiscordSettingsPage /></Suspense></PermissionRoute>} />
              {/* Settings */}
              <Route path="/settings" element={<Suspense fallback={<PageLoader />}><SettingsPage /></Suspense>} />
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
