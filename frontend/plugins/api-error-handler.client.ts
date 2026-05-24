/**
 * 全局 API 错误处理插件
 * 通过 $fetch 的 onResponseError 钩子拦截 401，自动登出并跳转到登录页
 * 不覆盖 globalThis.fetch，避免污染全局环境
 */
export default defineNuxtPlugin((nuxtApp) => {
  const authStore = useAuthStore()

  // 通过 $fetch.create() 创建带拦截器的实例，处理管理后台 API 的 401 和超时
  const apiFetch = $fetch.create({
    timeout: 15000,
    onResponseError({ request, response }) {
      if (response.status === 401) {
        // 仅拦截管理后台 API 的 401
        const url = typeof request === 'string' ? request : (request as Request).url
        if (url.includes('/api/admin/')) {
          authStore.handleUnauthorized()
        }
      }
    },
    onRequestError({ request, error }) {
      // 超时或网络错误：给用户可见的错误提示
      const isTimeout = error?.message?.includes('timeout') || error?.message?.includes('timed out')
      const msg = isTimeout ? '请求超时，请检查网络连接后重试' : '网络请求失败，请检查连接'
      try {
        useNotificationStore().error(msg)
      } catch {
        console.error('[API Error]', error?.message || 'Request failed')
      }
    }
  })

  // 拦截 Vue 组件内未捕获的错误
  nuxtApp.hook('vue:error', (error: any) => {
    if (error?.statusCode === 401 || error?.status === 401) {
      authStore.handleUnauthorized()
    }
  })

  // 提供一个全局的 API 请求包装器（向后兼容）
  return {
    provide: {
      apiFetch,
      apiRequest: async <T>(url: string, options: any = {}): Promise<T> => {
        const config = useRuntimeConfig()
        const fullUrl = url.startsWith('http') ? url : `${config.public.apiBase}${url}`
        return await apiFetch<T>(fullUrl, {
          ...options,
          credentials: 'include',
        })
      }
    }
  }
})
