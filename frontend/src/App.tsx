import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Toaster } from 'sonner'
import { QueryProvider } from '@/providers/query-provider'
import { MainLayout } from '@/components/layout/main-layout'
import { DashboardPage } from '@/pages/dashboard'
import { ReviewPage } from '@/pages/review'
import { ReportsPage } from '@/pages/reports'

function App() {
  return (
    <QueryProvider>
      <BrowserRouter>
        <MainLayout>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/review/:id" element={<ReviewPage />} />
            <Route path="/reports" element={<ReportsPage />} />
          </Routes>
        </MainLayout>
      </BrowserRouter>
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
