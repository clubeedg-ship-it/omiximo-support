import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchThreads } from '@/lib/api'
import { setApiTokenProvider } from '@/lib/auth'

const okResponse = {
  ok: true,
  status: 200,
  json: async () => ({
    items: [],
    total: 0,
    page: 1,
    page_size: 50,
  }),
} as Response

describe('API client', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    setApiTokenProvider(null)
  })

  it('includes the search query when fetching threads', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okResponse)
    vi.stubGlobal('fetch', fetchMock)

    await fetchThreads({ search: 'abc-123' })

    const [url] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/api/v1/threads')
    expect(url).toContain('search=abc-123')
  })

  it('attaches the Clerk bearer token when configured', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okResponse)
    vi.stubGlobal('fetch', fetchMock)
    setApiTokenProvider(async () => 'clerk-token-123')

    await fetchThreads()

    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit]
    const headers = new Headers(options.headers)
    expect(headers.get('Authorization')).toBe('Bearer clerk-token-123')
  })
})
