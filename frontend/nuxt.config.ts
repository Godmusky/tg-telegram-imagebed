// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  compatibilityDate: '2024-11-01',
  devtools: { enabled: true },
  ssr: false,  // 禁用SSR，生成纯静态SPA

  modules: [
    '@nuxt/ui',
    '@pinia/nuxt',
    '@vueuse/nuxt'
  ],

  // 应用配置
  app: {
    baseURL: '/',
    buildAssetsDir: '/_nuxt/',
    head: {
      title: '\u56fe\u5e8a Pro \u2014 \u5feb\u901f\u5b89\u5168\u7684\u56fe\u7247\u6258\u7ba1',
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        { 'http-equiv': 'Content-Security-Policy', content: "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; connect-src 'self'" },
        { name: 'description', content: '\u4e13\u4e1a\u7684\u56fe\u7247\u6258\u7ba1\u670d\u52a1\uff0c\u57fa\u4e8e Telegram \u4e91\u5b58\u50a8\uff0c\u652f\u6301 Cloudflare CDN \u5168\u7403\u52a0\u901f\u3002\u5feb\u901f\u4e0a\u4f20\u3001\u5b89\u5168\u5b58\u50a8\u3001\u4fbf\u6377\u5206\u4eab\u3002' },
        { name: 'keywords', content: '\u56fe\u5e8a,\u514d\u8d39\u56fe\u5e8a,Telegram,\u4e91\u5b58\u50a8,CDN\u52a0\u901f,\u56fe\u7247\u6258\u7ba1' },
        { name: 'robots', content: 'index, follow' },
        { property: 'og:title', content: '\u56fe\u5e8a Pro \u2014 \u5feb\u901f\u5b89\u5168\u7684\u56fe\u7247\u6258\u7ba1' },
        { property: 'og:description', content: '\u4e13\u4e1a\u7684\u56fe\u7247\u6258\u7ba1\u670d\u52a1\uff0c\u57fa\u4e8e Telegram \u4e91\u5b58\u50a8\uff0c\u652f\u6301 Cloudflare CDN \u5168\u7403\u52a0\u901f\u3002' },
        { property: 'og:type', content: 'website' },
        { property: 'og:locale', content: 'zh_CN' },
        { name: 'twitter:card', content: 'summary_large_image' },
        { name: 'twitter:title', content: '\u56fe\u5e8a Pro \u2014 \u5feb\u901f\u5b89\u5168\u7684\u56fe\u7247\u6258\u7ba1' },
        { name: 'twitter:description', content: '\u4e13\u4e1a\u7684\u56fe\u7247\u6258\u7ba1\u670d\u52a1\uff0c\u57fa\u4e8e Telegram \u4e91\u5b58\u50a8\uff0c\u652f\u6301 Cloudflare CDN \u5168\u7403\u52a0\u901f\u3002' },
      ],
      link: [
        { rel: 'icon', type: 'image/x-icon', href: '/favicon.ico' }
      ]
    }
  },

  // CSS 配置
  css: [
    '~/assets/css/main.scss'
  ],

  // 运行时配置
  runtimeConfig: {
    public: {
      apiBase: '',  // 空字符串，使用相对路径
      cdnDomain: process.env.NUXT_PUBLIC_CDN_DOMAIN || '',
      cdnEnabled: process.env.NUXT_PUBLIC_CDN_ENABLED === 'true'
    }
  },

  // Nitro 配置（静态生成）
  nitro: {
    preset: 'static',
    prerender: {
      crawlLinks: true,
      routes: [
        '/',
        '/gallery-site/',
        '/gallery-site/galleries',
        '/docs',
      ]
    }
  },

  // UI 配置
  ui: {
    global: true,
    icons: ['heroicons'],
    notifications: {
      // 小屏幕优化配置
      position: 'bottom-right',
      timeout: 3000  // 3秒后自动消失，避免长时间遮挡
    }
  },

  // Icon 配置
  icon: {
    serverBundle: {
      collections: ['heroicons']
    }
  },

  // 开发服务器配置
  devServer: {
    port: 3000,
    host: '0.0.0.0'
  }
})
