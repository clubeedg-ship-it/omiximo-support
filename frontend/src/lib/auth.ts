type TokenProvider = () => Promise<string | null>

const clerkPublishableKey =
  (import.meta.env['VITE_CLERK_PUBLISHABLE_KEY'] as string | undefined)?.trim() ?? ''
const clerkJwtTemplate =
  (import.meta.env['VITE_CLERK_JWT_TEMPLATE'] as string | undefined)?.trim() ?? ''
const allowDevAuthBypass =
  (import.meta.env['VITE_ALLOW_INSECURE_DEV_AUTH_BYPASS'] as string | undefined) === 'true'

let apiTokenProvider: TokenProvider | null = null

export function isClerkEnabled(): boolean {
  return clerkPublishableKey.length > 0
}

export function isDevAuthBypassEnabled(): boolean {
  return allowDevAuthBypass
}

export function getClerkPublishableKey(): string | null {
  return clerkPublishableKey || null
}

export function getClerkJwtTemplate(): string | null {
  return clerkJwtTemplate || null
}

export function setApiTokenProvider(provider: TokenProvider | null): void {
  apiTokenProvider = provider
}

export async function getApiToken(): Promise<string | null> {
  if (!apiTokenProvider) {
    return null
  }

  return apiTokenProvider()
}
