import createClient from 'openapi-fetch'
import type { paths } from './schema'

export const client = createClient<paths>({
  baseUrl: import.meta.env.VITE_API_URL || window.location.origin,
  fetch: (...args) => globalThis.fetch(...args),
})

client.use({
  onRequest({ request }) {
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method)) {
      const csrfCookie = document.cookie
        .split(';')
        .map((cookie) => cookie.trim())
        .find((cookie) => cookie.startsWith('__Host-platform-csrf='))
      if (csrfCookie) {
        request.headers.set(
          'X-Platform-CSRF-Token',
          decodeURIComponent(csrfCookie.slice('__Host-platform-csrf='.length)),
        )
      }
    }
    if (import.meta.env.DEV) {
      const groupNames = localStorage.getItem('bot-social-group-names')?.trim()
      if (groupNames) request.headers.set('X-Platform-Principal-Group-Names', groupNames)
    }
    return request
  },
})

export function explain(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'detail' in error) {
    const detail = (error as { detail: unknown }).detail
    return typeof detail === 'string' ? detail : JSON.stringify(detail)
  }
  return 'The request failed.'
}
