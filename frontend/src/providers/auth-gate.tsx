import type { ReactNode } from 'react'
import { useEffect } from 'react'
import {
  ClerkLoaded,
  ClerkLoading,
  RedirectToSignIn,
  SignedIn,
  SignedOut,
  useAuth,
} from '@clerk/react'
import { Loader2 } from 'lucide-react'
import {
  getClerkJwtTemplate,
  isClerkEnabled,
  setApiTokenProvider,
} from '@/lib/auth'

interface AuthGateProps {
  children: ReactNode
}

function ClerkTokenBridge() {
  const { getToken } = useAuth()

  useEffect(() => {
    setApiTokenProvider(async () => {
      const template = getClerkJwtTemplate()
      return getToken(template ? { template } : undefined)
    })

    return () => {
      setApiTokenProvider(null)
    }
  }, [getToken])

  return null
}

function AuthLoadingState() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <Loader2 className="h-6 w-6 animate-spin text-slate-400" aria-hidden="true" />
    </div>
  )
}

export function AuthGate({ children }: AuthGateProps) {
  if (!isClerkEnabled()) {
    return <>{children}</>
  }

  return (
    <>
      <ClerkLoading>
        <AuthLoadingState />
      </ClerkLoading>
      <ClerkLoaded>
        <SignedIn>
          <ClerkTokenBridge />
          {children}
        </SignedIn>
        <SignedOut>
          <RedirectToSignIn />
        </SignedOut>
      </ClerkLoaded>
    </>
  )
}
