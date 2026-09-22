import { Component, type ErrorInfo, type ReactNode } from "react"
import { AlertTriangle, RefreshCw } from "lucide-react"

interface Props {
  children: ReactNode
  fallback?: ReactNode
  /** Optional label for logging (e.g. "Dashboard", "Pipeline") */
  section?: string
}

interface State {
  hasError: boolean
  error: Error | null
}

const lazyModuleLoadError = /(?:failed to fetch dynamically imported module|error loading dynamically imported module|importing a module script failed|chunkloaderror|loading chunk [^\n]+ failed)/i

export function isLazyModuleLoadError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error ?? "")
  return lazyModuleLoadError.test(message)
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(_error: Error, _info: ErrorInfo) {
    // Error logged internally by React; no console.error in production
  }

  handleRetry = () => {
    if (isLazyModuleLoadError(this.state.error)) {
      window.location.reload()
      return
    }
    this.setState({ hasError: false, error: null })
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback
      const needsReload = isLazyModuleLoadError(this.state.error)

      return (
        <div className="flex flex-col items-center justify-center gap-3 p-8 text-center">
          <AlertTriangle className="h-10 w-10 text-amber-500" />
          <h3 className="text-lg font-semibold">Algo salió mal</h3>
          <p className="text-sm text-muted-foreground max-w-md">
            {needsReload ? "No se pudo cargar esta parte de la aplicación. Recarga la página para continuar." : "Ha ocurrido un error inesperado. Intenta de nuevo."}
          </p>
          <button
            onClick={this.handleRetry}
            className="mt-2 inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm text-primary-foreground hover:bg-primary/90"
          >
            <RefreshCw className="h-4 w-4" />
            {needsReload ? "Recargar página" : "Reintentar"}
          </button>
        </div>
      )
    }

    return this.props.children
  }
}
