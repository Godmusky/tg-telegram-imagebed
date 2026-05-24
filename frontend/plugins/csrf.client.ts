/**
 * CSRF 保护插件（Double-Submit Cookie 模式）
 *
 * 对所有管理后台 API 的 state-changing 请求自动添加 X-CSRF-Token 请求头。
 * 使用 globalThis.$fetch 包装以拦截所有 fetch 调用。
 */
export default defineNuxtPlugin(async () => {
  const config = useRuntimeConfig()

  /**
   * 判断请求是否为管理后台的 state-changing 请求
   */
  function isAdminMutatingRequest(url: string, method?: string): boolean {
    const m = (method || 'GET').toUpperCase()
    if (!['POST', 'PUT', 'DELETE', 'PATCH'].includes(m)) return false
    return url.includes('/api/admin/') || url.includes('/api/setup')
  }

  /**
   * 从 document.cookie 读取 csrf_token
   */
  function getCsrfToken(): string {
    if (typeof document === 'undefined') return ''
    for (const c of document.cookie.split(';')) {
      const [k, ...v] = c.trim().split('=')
      if (k === 'csrf_token') return decodeURIComponent(v.join('='))
    }
    return ''
  }

  // 获取 CSRF token（非关键路径 —— 失败时静默忽略）
  try {
    await $fetch(`${config.public.apiBase}/api/admin/csrf-token`, {
      credentials: 'include',
    })
  } catch { /* 静默 */ }

  // ---- 包装 globalThis.$fetch ----
  const orig = globalThis.$fetch as typeof $fetch

  if (orig) {
    const wrapped: typeof $fetch = (request: any, options?: any) => {
      let url = ''
      if (typeof request === 'string') {
        url = request
      } else if (request instanceof Request) {
        url = request.url
      } else if (request && typeof request === 'object') {
        url = String((request as any).url || request)
      }

      // 不对 csrf-token 端点本身添加 header（避免循环）
      if (!url.includes('/api/admin/csrf-token') && isAdminMutatingRequest(url, options?.method)) {
        const token = getCsrfToken()
        if (token) {
          options = {
            ...(options || {}),
            headers: {
              ...((options && options.headers) || {}),
              'X-CSRF-Token': token,
            },
          }
        }
      }

      // 管理后台请求强制带上 cookie
      if (url.includes('/api/admin/') || url.includes('/api/setup')) {
        options = {
          ...(options || {}),
          credentials: (options && options.credentials) || 'include',
        }
      }

      return orig(request, options)
    }

    // @ts-expect-error 覆盖全局 fetch
    globalThis.$fetch = wrapped
  }
})
