import type {
  AdminImageItem,
  AdminImagesQuery,
  AdminImageSortBy,
  AdminImageSortOrder,
  ApiResponse,
} from '~/types/api'
import type { AdminLegacyFilter } from '~/composables/useAdminImages'

export interface AdminImagesAdvancedFilters {
  source: string
  cacheStatus: 'all' | 'cached' | 'uncached'
  dateFrom: string
  dateTo: string
  sizeMinMb: string
  sizeMaxMb: string
  accessMin: string
  accessMax: string
}

export const createDefaultAdvancedFilters = (): AdminImagesAdvancedFilters => ({
  source: 'all',
  cacheStatus: 'all',
  dateFrom: '',
  dateTo: '',
  sizeMinMb: '',
  sizeMaxMb: '',
  accessMin: '',
  accessMax: '',
})

const parsePositiveNumber = (value: string): number | undefined => {
  const trimmed = String(value || '').trim()
  if (!trimmed) return undefined
  const parsed = Number(trimmed)
  if (!Number.isFinite(parsed) || parsed < 0) return undefined
  return parsed
}

const asBytesFromMb = (valueMb: string): number | undefined => {
  const parsed = parsePositiveNumber(valueMb)
  if (parsed === undefined) return undefined
  return Math.round(parsed * 1024 * 1024)
}

export const useAdminImagesData = () => {
  const { getImages } = useImageApi()
  const runtimeConfig = useRuntimeConfig()

  // ── 数据状态 ──
  const images = ref<AdminImageItem[]>([])
  const totalPages = ref(1)
  const totalCount = ref(0)
  const loading = ref(false)
  const refreshing = ref(false)

  // ── 查询/筛选状态 ──
  const currentPage = ref(1)
  const pageSize = ref(50)
  const searchQuery = ref('')
  const primaryFilter = ref<AdminLegacyFilter>('all')
  const sortBy = ref<AdminImageSortBy>('created_at')
  const sortOrder = ref<AdminImageSortOrder>('desc')
  const advancedFilters = ref<AdminImagesAdvancedFilters>(createDefaultAdvancedFilters())
  const tgSyncDeleteEnabled = ref(false)

  // ── 衍生计算 ──
  const hasActiveAdvancedFilters = computed(() => {
    const af = advancedFilters.value
    return af.source !== 'all'
      || af.cacheStatus !== 'all'
      || !!af.dateFrom
      || !!af.dateTo
      || !!String(af.sizeMinMb || '').trim()
      || !!String(af.sizeMaxMb || '').trim()
      || !!String(af.accessMin || '').trim()
      || !!String(af.accessMax || '').trim()
  })

  // ── 选项常量 ──
  const pageSizeOptions = [
    { label: '20 / 页', value: 20 },
    { label: '50 / 页', value: 50 },
    { label: '100 / 页', value: 100 },
    { label: '200 / 页', value: 200 },
  ]

  const primaryFilterOptions = [
    { label: '全部图片', value: 'all' },
    { label: '已缓存', value: 'cached' },
    { label: '未缓存', value: 'uncached' },
    { label: '群组上传', value: 'group' },
  ]

  const sortByOptions = [
    { label: '按上传时间', value: 'created_at' },
    { label: '按文件大小', value: 'file_size' },
    { label: '按总访问量', value: 'access_count' },
    { label: '按 CDN 访问量', value: 'cdn_hit_count' },
    { label: '按直连访问量', value: 'direct_hit_count' },
  ]

  const sortOrderOptions = [
    { label: '降序', value: 'desc' },
    { label: '升序', value: 'asc' },
  ]

  const sourceOptions = [
    { label: '全部来源', value: 'all' },
    { label: 'Token 上传', value: 'token' },
    { label: '群组上传', value: 'group' },
    { label: '机器人上传', value: 'telegram_bot' },
    { label: '管理员上传', value: 'admin_upload' },
    { label: '匿名上传', value: 'guest' },
  ]

  // ── 查询参数构建 ──
  const buildQueryParams = (): AdminImagesQuery => {
    const query: AdminImagesQuery = {
      page: currentPage.value,
      limit: Number(pageSize.value),
      search: searchQuery.value.trim(),
      filter: primaryFilter.value,
      sort_by: sortBy.value,
      sort_order: sortOrder.value,
    }

    const af = advancedFilters.value

    if (af.source !== 'all') {
      query.source = af.source
    }

    if (af.cacheStatus === 'cached' || af.cacheStatus === 'uncached') {
      query.filter = af.cacheStatus
    }

    if (af.dateFrom) query.date_from = af.dateFrom
    if (af.dateTo) query.date_to = af.dateTo

    const sizeMin = asBytesFromMb(af.sizeMinMb)
    const sizeMax = asBytesFromMb(af.sizeMaxMb)
    const accessMin = parsePositiveNumber(af.accessMin)
    const accessMax = parsePositiveNumber(af.accessMax)

    if (sizeMin !== undefined) query.size_min = sizeMin
    if (sizeMax !== undefined) query.size_max = sizeMax
    if (accessMin !== undefined) query.access_min = Math.floor(accessMin)
    if (accessMax !== undefined) query.access_max = Math.floor(accessMax)

    return query
  }

  // ── 数据获取（纯数据层，不含 UI 副作用） ──
  const fetchData = async (opts: { silent?: boolean; fromRefresh?: boolean } = {}): Promise<void> => {
    if (opts.fromRefresh) {
      refreshing.value = true
    } else {
      loading.value = true
    }
    try {
      const data = await getImages(buildQueryParams())
      images.value = data.images || []
      totalPages.value = data.totalPages || 1
      totalCount.value = data.total ?? images.value.length
    } catch (error) {
      if (!opts.silent) {
        console.error('加载图片列表失败:', error)
      }
      throw error
    } finally {
      loading.value = false
      refreshing.value = false
    }
  }

  // ── 系统设置加载 ──
  const loadSyncDeleteSetting = async () => {
    try {
      const resp = await $fetch<ApiResponse<{ tg_sync_delete_enabled?: boolean | string | number }>>(`${runtimeConfig.public.apiBase}/api/admin/system/settings`, {
        credentials: 'include',
      })
      if (resp?.success) {
        tgSyncDeleteEnabled.value = resp.data?.tg_sync_delete_enabled === true
          || String(resp.data?.tg_sync_delete_enabled) === '1'
      }
    } catch {
      // 静默失败
    }
  }

  return {
    // 数据状态
    images,
    totalPages,
    totalCount,
    loading,
    refreshing,
    tgSyncDeleteEnabled,
    // 查询状态
    currentPage,
    pageSize,
    searchQuery,
    primaryFilter,
    sortBy,
    sortOrder,
    advancedFilters,
    // 衍生
    hasActiveAdvancedFilters,
    // 选项
    pageSizeOptions,
    primaryFilterOptions,
    sortByOptions,
    sortOrderOptions,
    sourceOptions,
    // 数据动作
    fetchData,
    loadSyncDeleteSetting,
  }
}
