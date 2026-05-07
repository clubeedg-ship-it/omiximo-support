import type { ReactNode } from 'react'
import { Header } from './header'

interface MainLayoutProps {
  children: ReactNode
}

export function MainLayout({ children }: MainLayoutProps) {
  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      <Header />
      <main
        className="mx-auto max-w-screen-xl px-4 py-6 sm:px-6"
        role="main"
        id="main-content"
      >
        {children}
      </main>
    </div>
  )
}
