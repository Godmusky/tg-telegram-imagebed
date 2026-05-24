import { defineStore } from 'pinia'
import type { TokenInfo, TokenVaultItem, TokenVaultPersistedV1 } from '~/types/tokenVault'
import type { ApiResponse, TokenGenerateResult, TokenVerifyData, TokenUploadsData } from '~/types/api'

const VAULT_STORAGE_KEY = 'token_vault_v1'
const LEGACY_TOKEN_KEY = 'guest_token'
const LEGACY_IS_GUEST_KEY = 'is_guest'

const nowIso = () => new Date().toISOString()

// ── Token AES-GCM 加密存储 ──────────────────────────────────────────────
const ENC_KEY_STORAGE = 'token_enc_key'
const ENC_PREFIX = 'ae:'
const LEGACY_PREFIX = 'ob:'

let _encKey: CryptoKey | null = null
let _encKeyPromise: Promise<CryptoKey> | null = null

/** 获取或创建 AES-GCM 加密密钥（存 sessionStorage，会话级别） */
const getEncKey = async (): Promise<CryptoKey> => {
  if (_encKey) return _encKey
  if (_encKeyPromise) return _encKeyPromise
  _encKeyPromise = (async () => {
    const stored = sessionStorage.getItem(ENC_KEY_STORAGE)
    if (stored) {
      try {
        const rawKey = Uint8Array.from(atob(stored), c => c.charCodeAt(0))
        _encKey = await crypto.subtle.importKey('raw', rawKey, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt'])
        return _encKey
      } catch {
        sessionStorage.removeItem(ENC_KEY_STORAGE)
      }
    }
    _encKey = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, true, ['encrypt', 'decrypt'])
    const rawKey = new Uint8Array(await crypto.subtle.exportKey('raw', _encKey))
    sessionStorage.setItem(ENC_KEY_STORAGE, btoa(String.fromCharCode(...rawKey)))
    return _encKey
  })()
  return _encKeyPromise
}

/** 旧格式解码（base64 + 字符位移 SHIFT=3），仅用于迁移 */
const deobfuscateLegacy = (stored: string): string => {
  if (!stored || !stored.startsWith(LEGACY_PREFIX)) return stored
  const SHIFT = 3
  try {
    const shifted = stored.slice(3)
    const b64 = shifted.split('').map(c => {
      const code = c.charCodeAt(0)
      if (code >= 33 && code <= 126) {
        return String.fromCharCode(((code - 33 - SHIFT + 94) % 94) + 33)
      }
      return c
    }).join('')
    return decodeURIComponent(escape(atob(b64)))
  } catch {
    return stored
  }
}

/**
 * 加密：AES-GCM 加密 token，格式 'ae:<base64-iv>:<base64-ciphertext>'
 * 已是 ae: 前缀则跳过，ob: 前缀先解码再加密（自动迁移）
 */
const encryptToken = async (token: string): Promise<string> => {
  if (!token) return token
  if (token.startsWith(ENC_PREFIX)) return token
  let plaintext = token
  if (token.startsWith(LEGACY_PREFIX)) {
    plaintext = deobfuscateLegacy(token)
  }
  try {
    const key = await getEncKey()
    const iv = crypto.getRandomValues(new Uint8Array(12))
    const encoded = new TextEncoder().encode(plaintext)
    const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, encoded)
    const ctArray = new Uint8Array(ciphertext)
    return `${ENC_PREFIX}${btoa(String.fromCharCode(...iv))}:${btoa(String.fromCharCode(...ctArray))}`
  } catch {
    return token
  }
}

/**
 * 解密：AES-GCM 解密，兼容旧格式 ob: 前缀和明文（自动迁移）
 * 新会话无密钥时，ae: 加密项解密失败 → 返回空串（该项视为无效）
 */
const decryptToken = async (stored: string): Promise<string> => {
  if (!stored) return stored
  // AES-GCM 加密格式
  if (stored.startsWith(ENC_PREFIX)) {
    try {
      const key = await getEncKey()
      const payload = stored.slice(3)
      const sepIdx = payload.indexOf(':')
      if (sepIdx < 0) return ''
      const ivB64 = payload.slice(0, sepIdx)
      const ctB64 = payload.slice(sepIdx + 1)
      const iv = Uint8Array.from(atob(ivB64), c => c.charCodeAt(0))
      const ct = Uint8Array.from(atob(ctB64), c => c.charCodeAt(0))
      const decrypted = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, ct)
      return new TextDecoder().decode(decrypted)
    } catch {
      return '' // 新会话无密钥，解密失败视为无效
    }
  }
  // 旧格式迁移：ob: 前缀 → 解码为明文
  if (stored.startsWith(LEGACY_PREFIX)) {
    return deobfuscateLegacy(stored)
  }
  // 明文直接返回
  return stored
}

export const maskToken = (token: string) => {
  const t = (token || '').trim()
  if (t.length <= 12) return t
  return `${t.slice(0, 8)}…${t.slice(-4)}`
}

const safeParse = <T,>(raw: string | null, fallback: T): T => {
  try {
    if (!raw) return fallback
    return JSON.parse(raw) as T
  } catch {
    return fallback
  }
}

const newId = () => {
  const c = globalThis.crypto as any
  if (c?.randomUUID) return c.randomUUID()
  return `id_${Math.random().toString(16).slice(2)}_${Date.now()}`
}

export const useTokenStore = defineStore('token', {
  state: () => ({
    vault: {
      version: 1 as const,
      activeId: null as string | null,
      items: [] as TokenVaultItem[]
    } satisfies TokenVaultPersistedV1,

    // 向后兼容：保留这些字段作为"当前激活Token"视图
    token: '',
    tokenInfo: null as TokenInfo | null,
    isGuest: true
  }),

  getters: {
    vaultItems: (state) => state.vault.items,
    activeVaultId: (state) => state.vault.activeId,
    activeVaultItem: (state) => state.vault.items.find(i => i.id === state.vault.activeId) || null,

    hasToken: (state) => !!state.token,
    activeAlbumLabel: (state) => {
      const item = state.vault.items.find(i => i.id === state.vault.activeId)
      if (!item) return ''
      const name = (item.albumName || '').trim()
      return name || '未命名相册'
    },
    activeAlbumLabelWithToken: (state) => {
      const item = state.vault.items.find(i => i.id === state.vault.activeId)
      if (!item) return ''
      const name = (item.albumName || '').trim()
      return `${name || '未命名相册'} (${maskToken(item.token)})`
    },

    remainingUploads: (state) => state.tokenInfo?.remaining_uploads || 0,
    uploadLimit: (state) => state.tokenInfo?.upload_limit || 0,
    uploadCount: (state) => state.tokenInfo?.upload_count || 0,
    expiresAt: (state) => state.tokenInfo?.expires_at || '',
    isExpired: (state) => {
      if (!state.tokenInfo?.expires_at) return false
      return new Date(state.tokenInfo.expires_at) < new Date()
    }
  },

  actions: {
    async persistVault() {
      if (!import.meta.client) return
      // 存储前对每个 token 做 AES-GCM 加密
      const encryptedItems = await Promise.all(
        this.vault.items.map(async i => ({
          ...i,
          token: await encryptToken(i.token)
        }))
      )
      const vaultToStore = {
        ...this.vault,
        items: encryptedItems
      }
      localStorage.setItem(VAULT_STORAGE_KEY, JSON.stringify(vaultToStore))
    },

    async loadVault() {
      if (!import.meta.client) return
      const raw = localStorage.getItem(VAULT_STORAGE_KEY)
      const parsed = safeParse<TokenVaultPersistedV1 | null>(raw, null)
      if (parsed?.version === 1 && Array.isArray(parsed.items)) {
        const decryptedItems = await Promise.all(
          parsed.items
            .filter(i => i && typeof i.id === 'string' && typeof i.token === 'string')
            .map(async i => ({
              id: i.id,
              // 读取时解密（兼容 ob: 旧格式和明文，ae: 加密项新会话无密钥时返回空串）
              token: await decryptToken((i.token || '').trim()),
              albumName: typeof i.albumName === 'string' ? i.albumName : '',
              addedAt: i.addedAt || nowIso(),
              lastSelectedAt: i.lastSelectedAt,
              lastVerifiedAt: i.lastVerifiedAt,
              tokenInfo: i.tokenInfo
            }))
        )
        // 过滤掉解密失败的项（新会话无密钥时 ae: 加密项会返回空串）
        const validItems = decryptedItems.filter(i => i.token)

        // 验证 activeId 是否有效，无效则自动选择第一个
        let activeId = parsed.activeId || null
        if (activeId && !validItems.some(i => i.id === activeId)) {
          activeId = validItems[0]?.id || null
        }

        this.vault = {
          version: 1,
          activeId,
          items: validItems
        }
      }
    },

    async importLegacySingleTokenIfNeeded() {
      if (!import.meta.client) return
      const legacyToken = (localStorage.getItem(LEGACY_TOKEN_KEY) || '').trim()
      const legacyIsGuest = localStorage.getItem(LEGACY_IS_GUEST_KEY) === 'true'
      if (!legacyToken || !legacyIsGuest) return

      const exists = this.vault.items.some(i => i.token === legacyToken)
      if (!exists) {
        const item: TokenVaultItem = {
          id: newId(),
          token: legacyToken,
          albumName: '',
          addedAt: nowIso()
        }
        this.vault.items.unshift(item)
        this.vault.activeId = item.id
        await this.persistVault()
      }

      localStorage.removeItem(LEGACY_TOKEN_KEY)
      localStorage.removeItem(LEGACY_IS_GUEST_KEY)
    },

    syncActiveFromVault() {
      const active = this.vault.items.find(i => i.id === this.vault.activeId) || null
      this.token = active?.token || ''
      this.tokenInfo = active?.tokenInfo || null
      this.isGuest = true
    },

    async setActiveTokenById(id: string, opts?: { verify?: boolean }) {
      const item = this.vault.items.find(i => i.id === id)
      if (!item) throw new Error('Token不存在')
      this.vault.activeId = item.id
      item.lastSelectedAt = nowIso()
      this.persistVault()
      this.syncActiveFromVault()
      if (opts?.verify) return this.verifyToken()
    },

    updateAlbumName(id: string, albumName: string) {
      const item = this.vault.items.find(i => i.id === id)
      if (!item) throw new Error('Token不存在')
      item.albumName = (albumName || '').slice(0, 50)
      this.persistVault()
    },

    removeTokenFromVault(id: string) {
      const idx = this.vault.items.findIndex(i => i.id === id)
      if (idx < 0) return
      const removingActive = this.vault.activeId === id
      this.vault.items.splice(idx, 1)

      if (removingActive) {
        this.vault.activeId = this.vault.items[0]?.id || null
      }
      this.persistVault()
      this.syncActiveFromVault()
    },

    removeBoundTokens() {
      const retained = this.vault.items.filter(item => !item.tokenInfo?.tg_user_id)
      const removed = this.vault.items.length - retained.length
      if (removed <= 0) return 0

      const activeRemoved = !!this.vault.activeId && !retained.some(item => item.id === this.vault.activeId)
      this.vault.items = retained
      if (activeRemoved) {
        this.vault.activeId = retained[0]?.id || null
      }
      this.persistVault()
      this.syncActiveFromVault()
      return removed
    },

    async addTokenToVault(token: string, opts?: { albumName?: string; makeActive?: boolean; verify?: boolean }) {
      const t = (token || '').trim()
      if (!t) throw new Error('Token不能为空')

      // 先验证 Token 有效性，无效则不添加；复用验证结果避免后续重复请求
      let verifiedTokenInfo: any = null
      if (opts?.verify) {
        const config = useRuntimeConfig()
        const response = await $fetch<any>(`${config.public.apiBase}/api/auth/token/verify`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${t}` },
          credentials: 'include'
        })
        if (!response?.success || !response?.valid) {
          const err: any = new Error(response?.reason || 'Token无效或不存在')
          err.tokenInvalid = true
          throw err
        }
        // 保存验证结果，后续直接写入缓存，无需再次请求
        verifiedTokenInfo = response.data
      }

      const existing = this.vault.items.find(i => i.token === t)
      if (existing) {
        if (typeof opts?.albumName === 'string') existing.albumName = opts.albumName.slice(0, 50)
        if (opts?.makeActive) {
          this.vault.activeId = existing.id
          existing.lastSelectedAt = nowIso()
        }
        // 复用验证结果写入缓存，避免第二次 API 调用
        if (verifiedTokenInfo) {
          existing.tokenInfo = verifiedTokenInfo
          existing.lastVerifiedAt = nowIso()
          this.tokenInfo = verifiedTokenInfo
        }
        this.persistVault()
        this.syncActiveFromVault()
        return existing.id
      }

      const item: TokenVaultItem = {
        id: newId(),
        token: t,
        albumName: typeof opts?.albumName === 'string' ? opts.albumName.slice(0, 50) : '',
        addedAt: nowIso()
      }
      // 复用验证结果写入缓存，避免第二次 API 调用
      if (verifiedTokenInfo) {
        item.tokenInfo = verifiedTokenInfo
        item.lastVerifiedAt = nowIso()
      }
      this.vault.items.unshift(item)
      if (opts?.makeActive !== false) {
        this.vault.activeId = item.id
        item.lastSelectedAt = nowIso()
      }
      this.persistVault()
      this.syncActiveFromVault()
      if (verifiedTokenInfo) {
        this.tokenInfo = verifiedTokenInfo
      }
      return item.id
    },

    // 生成新的游客token
    async generateToken(options?: { upload_limit?: number; expires_days?: number; albumName?: string }) {
      const config = useRuntimeConfig()

      try {
        // 只传递用户明确指定的参数，否则让后端使用默认值
        const body: Record<string, any> = {}
        if (options?.upload_limit != null) body.upload_limit = options.upload_limit
        if (options?.expires_days != null) body.expires_days = options.expires_days
        if (options?.albumName) body.description = options.albumName

        const response = await $fetch<ApiResponse<TokenGenerateResult>>(`${config.public.apiBase}/api/auth/token/generate`, {
          method: 'POST',
          body,
          credentials: 'include',
        })

        if (response.success && response.data) {
          await this.addTokenToVault(response.data.token, {
            albumName: options?.albumName || '',
            makeActive: true,
            verify: true
          })
          return response.data
        } else {
          throw new Error(response.error || '生成Token失败')
        }
      } catch (error: any) {
        throw new Error(error.data?.error || error.message || '生成Token失败')
      }
    },

    // 验证token
    async verifyToken() {
      if (!this.token) {
        throw new Error('未提供Token')
      }

      // 5 分钟缓存：如果最近验证过且有 tokenInfo，跳过 API 调用
      const active = this.vault.items.find(i => i.id === this.vault.activeId)
      if (active?.lastVerifiedAt && active.tokenInfo) {
        const elapsed = Date.now() - new Date(active.lastVerifiedAt).getTime()
        if (elapsed < 5 * 60 * 1000) {
          this.tokenInfo = active.tokenInfo
          return active.tokenInfo
        }
      }

      const config = useRuntimeConfig()

      try {
        const response = await $fetch<ApiResponse<TokenVerifyData> & { valid?: boolean; reason?: string }>(`${config.public.apiBase}/api/auth/token/verify`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${this.token}`
          },
          credentials: 'include'
        })

        if (response.success && response.valid) {
          this.tokenInfo = response.data ?? null
          const active = this.vault.items.find(i => i.id === this.vault.activeId)
          if (active && response.data) {
            active.tokenInfo = response.data
            active.lastVerifiedAt = nowIso()
            this.persistVault()
          }
          return response.data
        } else {
          // Token 确实无效（后端明确返回 valid=false）
          const err: any = new Error(response.reason || 'Token无效')
          err.tokenInvalid = true
          throw err
        }
      } catch (error: any) {
        // 保留 tokenInvalid 标记
        if (error.tokenInvalid) throw error
        // 网络/服务器错误，不标记为 tokenInvalid
        throw new Error(error.data?.reason || error.message || 'Token验证失败')
      }
    },

    // 刷新token(重新生成)
    async refreshToken(options?: { upload_limit?: number; expires_days?: number }) {
      this.clearToken()
      return await this.generateToken(options)
    },

    // 清除当前激活的token（不删除vault中的记录）
    clearToken() {
      this.vault.activeId = null
      this.persistVault()
      this.syncActiveFromVault()
    },

    // 清空整个 vault（退出登录时使用，仅清本地）
    clearVault() {
      this.vault.items = []
      this.vault.activeId = null
      this.persistVault()
      this.syncActiveFromVault()
    },

    // 从 localStorage 恢复token
    async restoreToken() {
      if (import.meta.client) {
        this.loadVault()
        this.importLegacySingleTokenIfNeeded()
        this.syncActiveFromVault()
        if (this.token) {
          try {
            await this.verifyToken()
          } catch (e: any) {
            // 仅在 Token 确实无效时自动移除（网络错误不移除）
            if (e?.tokenInvalid) {
              const failedId = this.vault.activeId
              if (failedId) {
                this.removeTokenFromVault(failedId)
              }
            }
          }
        }
      }
    },

    // 获取上传历史
    async getUploads(page: number = 1, limit: number = 50) {
      if (!this.token) {
        throw new Error('未提供Token')
      }

      const config = useRuntimeConfig()

      try {
        const response = await $fetch<ApiResponse<TokenUploadsData>>(`${config.public.apiBase}/api/auth/uploads`, {
          method: 'GET',
          headers: {
            'Authorization': `Bearer ${this.token}`
          },
          credentials: 'include',
          params: { page, limit, _t: Date.now() }
        })

        if (response.success && response.data) {
          if (response.data.total_uploads !== undefined) {
            // 更新当前 tokenInfo
            if (this.tokenInfo) {
              this.tokenInfo.upload_count = response.data.total_uploads
              this.tokenInfo.remaining_uploads = response.data.remaining_uploads
              this.tokenInfo.can_upload = response.data.can_upload
            }
            // 同步更新 vault 中的 tokenInfo
            const active = this.vault.items.find(i => i.id === this.vault.activeId)
            if (active && active.tokenInfo) {
              active.tokenInfo.upload_count = response.data.total_uploads
              active.tokenInfo.remaining_uploads = response.data.remaining_uploads
              active.tokenInfo.can_upload = response.data.can_upload
              this.persistVault()
            }
          }
          return response.data
        } else {
          throw new Error(response.error || '获取上传历史失败')
        }
      } catch (error: any) {
        throw new Error(error.data?.error || error.message || '获取上传历史失败')
      }
    },

    // 从服务器删除所有 vault 中的 Token（退出登录时使用）
    async deleteAllTokensFromServer(opts?: { deleteImages?: boolean }) {
      const config = useRuntimeConfig()
      const items = [...this.vault.items]
      const qs = opts?.deleteImages ? '?delete_images=true' : ''
      for (const item of items) {
        try {
          await $fetch(`${config.public.apiBase}/api/auth/token${qs}`, {
            method: 'DELETE',
            headers: { Authorization: `Bearer ${item.token}` },
            credentials: 'include'
          })
        } catch {
          // 静默忽略单个删除失败（Token 可能已失效）
        }
      }
      // 清空本地 vault
      this.vault.items = []
      this.vault.activeId = null
      this.persistVault()
      this.syncActiveFromVault()
    },

    // 从服务器删除 Token（级联删除，可选同时删除图片）
    async deleteTokenFromServer(vaultId: string, opts?: { deleteImages?: boolean }) {
      const item = this.vault.items.find(i => i.id === vaultId)
      if (!item) return

      const config = useRuntimeConfig()
      const qs = opts?.deleteImages ? '?delete_images=true' : ''
      await $fetch(`${config.public.apiBase}/api/auth/token${qs}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${item.token}` },
        credentials: 'include'
      })

      // 后端删除成功后，从本地 vault 移除
      this.removeTokenFromVault(vaultId)
    },

    // 更新相册描述（同步到服务器）
    async updateDescription(description: string) {
      if (!this.token) throw new Error('未提供Token')
      const config = useRuntimeConfig()
      const response = await $fetch<ApiResponse<{ token: string; description: string }>>(`${config.public.apiBase}/api/auth/token`, {
        method: 'PATCH',
        headers: { Authorization: `Bearer ${this.token}` },
        credentials: 'include',
        body: { description }
      })
      if (!response?.success) throw new Error(response?.error || '更新失败')

      // 同步到本地vault
      const active = this.vault.items.find(i => i.id === this.vault.activeId)
      if (active) {
        active.albumName = description
        if (active.tokenInfo) active.tokenInfo.description = description
        this.persistVault()
      }
      if (this.tokenInfo) this.tokenInfo.description = description
      return response.data
    }
  }
})
