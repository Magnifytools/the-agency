import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { Toaster } from "sonner"
import { AuthProvider } from "@/context/auth-context"
import { ProtectedRoute } from "@/components/layout/protected-route"
import { AppLayout } from "@/components/layout/app-layout"
import { ErrorBoundary } from "@/components/ui/error-boundary"
import LoginPage from "@/pages/login"
import DashboardPage from "@/pages/dashboard-page"
import ClientsPage from "@/pages/clients-page"
import ClientDetailPage from "@/pages/client-detail-page"
import TasksPage from "@/pages/tasks-page"
import UsersPage from "@/pages/users-page"
import TimesheetPage from "@/pages/timesheet-page"
import BillingPage from "@/pages/billing-page"
import ProjectsPage from "@/pages/projects-page"
import ProjectDetailPage from "@/pages/project-detail-page"
import ReportsPage from "@/pages/reports-page"
import ProposalsPage from "@/pages/proposals-page"

import LeadsPage from "@/pages/leads-page"
import LeadDetailPage from "@/pages/lead-detail-page"
import DigestsPage from "@/pages/digests-page"
import DigestEditPage from "@/pages/digest-edit-page"
import GrowthPage from "@/pages/growth-page"
import FinanceDashboardPage from "@/pages/finance-dashboard-page"
import IncomePage from "@/pages/income-page"
import ExpensesPage from "@/pages/expenses-page"
import TaxesPage from "@/pages/taxes-page"
import ForecastsPage from "@/pages/forecasts-page"
import AdvisorPage from "@/pages/advisor-page"
import ImportPage from "@/pages/import-page"
import HoldedFinancePage from "@/pages/holded-finance-page"
import DiscordSettingsPage from "@/pages/discord-settings-page"
import DailysPage from "@/pages/dailys-page"

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
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/leads" element={<LeadsPage />} />
              <Route path="/leads/:id" element={<LeadDetailPage />} />
              <Route path="/clients" element={<ClientsPage />} />
              <Route path="/clients/:id" element={<ClientDetailPage />} />
              <Route path="/tasks" element={<TasksPage />} />
              <Route path="/projects" element={<ProjectsPage />} />
              <Route path="/projects/:id" element={<ProjectDetailPage />} />
              <Route path="/growth" element={<GrowthPage />} />
              <Route path="/users" element={<UsersPage />} />
              <Route path="/timesheet" element={<TimesheetPage />} />
              <Route path="/billing" element={<BillingPage />} />
              <Route path="/proposals" element={<ProposalsPage />} />
              <Route path="/digests" element={<DigestsPage />} />
              <Route path="/digests/:id/edit" element={<DigestEditPage />} />
              <Route path="/dailys" element={<DailysPage />} />
              <Route path="/reports" element={<ReportsPage />} />
              {/* Finance */}
              <Route path="/finance" element={<FinanceDashboardPage />} />
              <Route path="/finance/income" element={<IncomePage />} />
              <Route path="/finance/expenses" element={<ExpensesPage />} />
              <Route path="/finance/taxes" element={<TaxesPage />} />
              <Route path="/finance/forecasts" element={<ForecastsPage />} />
              <Route path="/finance/advisor" element={<AdvisorPage />} />
              <Route path="/finance/import" element={<ImportPage />} />
              {/* Holded Finance */}
              <Route path="/finance-holded" element={<HoldedFinancePage />} />
              {/* Discord */}
              <Route path="/discord" element={<DiscordSettingsPage />} />
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
