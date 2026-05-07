import { Link, useNavigate } from 'react-router-dom'
import { LayoutDashboard, Headset } from 'lucide-react'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useMarketplaces } from '@/hooks/use-threads'

export function Header() {
  const navigate = useNavigate()
  const { data: marketplaces = [] } = useMarketplaces()

  const handleMarketplaceFilter = (value: string) => {
    if (value === 'ALL') {
      void navigate('/')
    } else {
      void navigate(`/?marketplace=${value}`)
    }
  }

  return (
    <header
      className="sticky top-0 z-40 border-b border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-950"
      role="banner"
    >
      <div className="mx-auto flex h-14 max-w-screen-xl items-center justify-between px-4 sm:px-6">
        <Link
          to="/"
          className="flex items-center gap-2.5 font-semibold text-slate-900 hover:text-slate-700 dark:text-slate-100 dark:hover:text-slate-200 transition-colors"
          aria-label="Omiximo Support — go to dashboard"
        >
          <Headset className="h-5 w-5 text-slate-600 dark:text-slate-400" aria-hidden="true" />
          <span className="text-base">Omiximo Support</span>
        </Link>

        <nav className="flex items-center gap-4" role="navigation" aria-label="Main navigation">
          {marketplaces.length > 0 && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500 dark:text-slate-400 hidden sm:inline">
                Marketplace:
              </span>
              <Select defaultValue="ALL" onValueChange={handleMarketplaceFilter}>
                <SelectTrigger
                  className="h-8 w-[150px] text-xs"
                  aria-label="Filter by marketplace"
                >
                  <SelectValue placeholder="All marketplaces" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ALL">All marketplaces</SelectItem>
                  {marketplaces.map((mp) => (
                    <SelectItem key={mp.id} value={String(mp.id)}>
                      {mp.marketplace}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          <Link
            to="/"
            className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100 hover:text-slate-900 transition-colors dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
            aria-label="Go to dashboard"
          >
            <LayoutDashboard className="h-4 w-4" aria-hidden="true" />
            <span className="hidden sm:inline">Dashboard</span>
          </Link>
        </nav>
      </div>
    </header>
  )
}
