/**
 * 全局 $fetch 默认超时与重试配置
 *
 * 为所有通过 Nuxt $fetch 发出的 API 请求设置默认超时（15s）和重试（1 次）。
 * 调用方可通过显式传入 timeout / retry 选项覆盖默认值。
 * XHR 上传不走 $fetch，超时在 composables/useUpload.ts 中单独配置（120s）。
 */
export default defineNuxtPlugin(() => {
  const orig = globalThis.$fetch as typeof $fetch

  if (!orig) return

  const DEFAULTS = {
    timeout: 15000,
    retry: 1,
    retryDelay: 1000,
  }

  const wrapped: typeof $fetch = (request: any, options?: any) => {
    return orig(request, {
      ...DEFAULTS,
      ...options,
      // 让调用方显式传入的 timeout/retry 覆盖默认值
      // （ofetch 的 $fetch.create() 实例自带 options，不会被覆盖）
    })
  }

  // @ts-expect-error 覆盖全局 fetch
  globalThis.$fetch = wrapped
})
