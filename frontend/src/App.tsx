import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Toaster } from 'sonner'
import { QueryProvider } from '@/providers/query-provider'
import { AuthGate } from '@/providers/auth-gate'
import { MainLayout } from '@/components/layout/main-layout'
import { DashboardPage } from '@/pages/dashboard'
import { ReviewPage } from '@/pages/review'
import { ReportsPage } from '@/pages/reports'
import { ClassificationPage } from '@/pages/classification'

function App() {
  return (
    <QueryProvider>
      <AuthGate>
        <BrowserRouter>
          <MainLayout>
            <Routes>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/review/:id" element={<ReviewPage />} />
              <Route path="/reports" element={<ReportsPage />} />
              <Route path="/classification" element={<ClassificationPage />} />
            </Routes>
          </MainLayout>
        </BrowserRouter>
      </AuthGate>
      <Toaster
        position="bottom-right"
        richColors
        closeButton
        toastOptions={{
          duration: 5000,
        }}
      />
    </QueryProvider>
  )
}

export default App
