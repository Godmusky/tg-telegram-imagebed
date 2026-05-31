import type {
  AdminImageItem,
} from '~/types/api'
import { useAdminImagesData, createDefaultAdvancedFilters } from '~/composables/useAdminImagesData'
import type {
  AdminImageSortBy,
  AdminImageSortOrder,
} from '~/types/api'

export type AdminImagesViewMode = 'list' | 'grid' | 'masonry'
export type AdminLegacyFilter = 'all' | 'cached' | 'uncached' | 'group'

// Re-export types that consumers import from this module
export type { AdminImagesAdvancedFilters } from '~/composables/useAdminImagesData'

const VIEW_MODE_STORAGE_KEY = 'admin_images_view_mode'

export const useAdminImages = () => {
  const notification = useNotification()

  // ── 组合数据层 ──
  const data = useAdminImagesData()

  // ── UI 状态 ──
  const deleting = ref(false)
  const selectedIds = ref<string[]>([])

  const detailModalOpen = ref(false)
  const detailIndex = ref(-1)
  const selectedImage = ref<AdminImageItem | null>(null)
  const deleteModalOpen = ref(false)
  const deleteMessage = ref('')
  const deleteWithStorage = ref(true)

  const advancedPanelOpen = ref(false)

  const viewMode = ref<AdminImagesViewMode>('list')

  if (import.meta.client) {
    const saved = localStorage.getItem(VIEW_MODE_STORAGE_KEY)
    if (saved === 'list' || saved === 'grid' || saved === 'masonry') {
      viewMode.value = saved
    }
  }

  watch(viewMode, (value) => {
    if (import.meta.client) {
      localStorage.setItem(VIEW_MODE_STORAGE_KEY, value)
    }
  })

  // ── 选择相关 ──
  const selectedCount = computed(() => selectedIds.value.length)

  const isAllOnPageSelected = computed(() => {
    if (!data.images.value.length) return false
    return data.images.value.every(item => selectedIds.value.includes(item.id))
  })

  const isPagePartiallySelected = computed(() => {
    if (!data.images.value.length) return false
    const selectedOnPage = data.images.value.filter(item => selectedIds.value.includes(item.id)).length
    return selectedOnPage > 0 && selectedOnPage < data.images.value.length
  })

  const clearSelection = () => {
    selectedIds.value = []
  }

  const toggleSelect = (id: string) => {
    const idx = selectedIds.value.indexOf(id)
    if (idx >= 0) {
      selectedIds.value.splice(idx, 1)
    } else {
      selectedIds.value.push(id)
    }
  }

  const toggleSelectAllOnPage = () => {
    if (isAllOnPageSelected.value) {
      const currentIds = new Set(data.images.value.map(item => item.id))
      selectedIds.value = selectedIds.value.filter(id => !currentIds.has(id))
      return
    }

    const merged = new Set(selectedIds.value)
    for (const item of data.images.value) {
      merged.add(item.id)
    }
    selectedIds.value = [...merged]
  }

  // ── 数据获取（组合 UI 层处理：选择清除 + 通知） ──
  const fetchImages = async (opts: { silent?: boolean; keepSelection?: boolean } = {}) => {
    const silent = opts.silent ?? false
    const keepSelection = opts.keepSelection ?? false
    try {
      await data.fetchData({ silent })
      if (!keepSelection) {
        clearSelection()
      }
    } catch (error) {
      if (!silent) {
        notification.error('错误', '加载图片列表失败')
      }
    }
  }

  const refresh = async () => {
    data.refreshing.value = true
    await fetchImages({ silent: true, keepSelection: true })
    data.refreshing.value = false
    notification.success('已刷新', '图片数据已更新')
  }

  // ── 查询动作（调用 fetchImages 以正确处理选择清除） ──
  const applySearchDebounced = useDebounceFn(() => {
    data.currentPage.value = 1
    fetchImages()
  }, 400)

  const setSearchQuery = (value: string) => {
    data.searchQuery.value = value
    applySearchDebounced()
  }

  const changePage = (page: number) => {
    data.currentPage.value = Math.max(1, Number(page || 1))
    fetchImages()
  }

  const applyPrimaryFilter = (value: AdminLegacyFilter) => {
    data.primaryFilter.value = value
    data.currentPage.value = 1
    fetchImages()
  }

  const applyPageSize = (value: number) => {
    data.pageSize.value = Number(value || 50)
    data.currentPage.value = 1
    fetchImages()
  }

  const applySorting = (nextSortBy: AdminImageSortBy, nextOrder: AdminImageSortOrder) => {
    data.sortBy.value = nextSortBy
    data.sortOrder.value = nextOrder
    data.currentPage.value = 1
    fetchImages()
  }

  const applyAdvancedFilters = (next: AdminImagesAdvancedFilters) => {
    data.advancedFilters.value = { ...next }
    data.currentPage.value = 1
    advancedPanelOpen.value = false
    fetchImages()
  }

  const resetAdvancedFilters = () => {
    data.advancedFilters.value = createDefaultAdvancedFilters()
    data.currentPage.value = 1
    fetchImages()
  }

  // ── 详情面板 ──
  const hasPrevDetail = computed(() => detailIndex.value > 0)
  const hasNextDetail = computed(() => detailIndex.value >= 0 && detailIndex.value < data.images.value.length - 1)

  const setDetailByIndex = (index: number) => {
    if (index < 0 || index >= data.images.value.length) return false
    detailIndex.value = index
    selectedImage.value = data.images.value[index]
    return true
  }

  const openDetailById = (id: string) => {
    const targetId = String(id || '').trim()
    if (!targetId) return
    const index = data.images.value.findIndex(item => item.id === targetId)
    if (index < 0) return
    setDetailByIndex(index)
    detailModalOpen.value = true
  }

  const openDetail = (image: AdminImageItem) => {
    if (image?.id) {
      openDetailById(image.id)
      return
    }
    detailIndex.value = -1
    selectedImage.value = image
    detailModalOpen.value = true
  }

  const goPrevDetail = () => {
    if (!hasPrevDetail.value) return
    setDetailByIndex(detailIndex.value - 1)
  }

  const goNextDetail = () => {
    if (!hasNextDetail.value) return
    setDetailByIndex(detailIndex.value + 1)
  }

  const closeDetail = () => {
    detailModalOpen.value = false
  }

  const downloadImage = (image?: AdminImageItem | null) => {
    if (!import.meta.client) return
    const target = image || selectedImage.value
    if (!target?.url) {
      notification.error('下载失败', '当前图片链接无效')
      return
    }

    const fallbackName = `${target.id || 'image'}.jpg`
    const filename = String(target.filename || '').trim() || fallbackName

    try {
      const link = document.createElement('a')
      link.href = target.url
      link.download = filename
      link.rel = 'noopener'
      link.target = '_blank'
      document.body.appendChild(link)
      link.click()
      link.remove()
      notification.success('开始下载', filename)
    } catch (error) {
      console.error('下载图片失败:', error)
      notification.error('下载失败', '无法触发浏览器下载，请稍后重试')
    }
  }

  const deleteCurrentDetailImage = () => {
    const target = selectedImage.value
    if (!target?.id) return
    openDeleteForSingle(target.id)
  }

  const handleDetailKeydown = (event: KeyboardEvent) => {
    if (!detailModalOpen.value) return
    if (event.key === 'ArrowLeft') {
      event.preventDefault()
      goPrevDetail()
      return
    }
    if (event.key === 'ArrowRight') {
      event.preventDefault()
      goNextDetail()
      return
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      closeDetail()
    }
  }

  watch(detailModalOpen, (open) => {
    if (!import.meta.client) return
    if (open) {
      window.addEventListener('keydown', handleDetailKeydown)
      return
    }
    window.removeEventListener('keydown', handleDetailKeydown)
  })

  onBeforeUnmount(() => {
    if (!import.meta.client) return
    window.removeEventListener('keydown', handleDetailKeydown)
  })

  watch(data.images, () => {
    if (!detailModalOpen.value) return
    const currentId = selectedImage.value?.id
    if (!currentId) return
    const idx = data.images.value.findIndex(item => item.id === currentId)
    if (idx >= 0) {
      setDetailByIndex(idx)
      return
    }
    detailIndex.value = -1
    selectedImage.value = null
    closeDetail()
  })

  // ── 剪贴板 ──
  const copyImageUrl = async (url?: string | null) => {
    const val = String(url || '').trim()
    if (!val) return
    try {
      await navigator.clipboard.writeText(val)
      notification.success('已复制', '链接已复制到剪贴板')
    } catch {
      notification.error('复制失败', '请检查浏览器剪贴板权限')
    }
  }

  const copySelectedUrls = async () => {
    if (!selectedIds.value.length) return
    const selectedSet = new Set(selectedIds.value)
    const urls = data.images.value
      .filter(item => selectedSet.has(item.id))
      .map(item => String(item.share_url || item.url || '').trim())
      .filter(Boolean)

    if (!urls.length) {
      notification.error('复制失败', '当前选中项没有可用链接')
      return
    }

    try {
      await navigator.clipboard.writeText(urls.join('\n'))
      notification.success('已复制', `已复制 ${urls.length} 条链接`)
    } catch {
      notification.error('复制失败', '请检查浏览器剪贴板权限')
    }
  }

  // ── 删除对话框 ──
  const openDeleteForSingle = (id: string) => {
    selectedIds.value = [id]
    deleteWithStorage.value = true
    deleteMessage.value = '确定要删除这张图片吗？此操作不可恢复。'
    deleteModalOpen.value = true
  }

  const openDeleteForSelection = () => {
    if (!selectedIds.value.length) return
    deleteWithStorage.value = true
    deleteMessage.value = `确定要删除选中的 ${selectedIds.value.length} 张图片吗？此操作不可恢复。`
    deleteModalOpen.value = true
  }

  const closeDeleteModal = () => {
    deleteModalOpen.value = false
  }

  const confirmDelete = async () => {
    if (!selectedIds.value.length) return
    deleting.value = true
    try {
      const deletingCount = selectedIds.value.length
      const deletingFromDetail = Boolean(
        detailModalOpen.value
        && selectedImage.value
        && selectedIds.value.includes(selectedImage.value.id)
      )
      const previousDetailIndex = detailIndex.value

      const deletingCurrentPageAll = data.images.value.length > 0 && selectedIds.value.length >= data.images.value.length

      const { deleteImages } = useImageApi()
      await deleteImages(selectedIds.value, {
        deleteStorage: data.tgSyncDeleteEnabled.value && deleteWithStorage.value,
      })

      notification.success('删除成功', `已删除 ${deletingCount} 张图片`)
      deleteModalOpen.value = false
      clearSelection()

      if (deletingCurrentPageAll && data.currentPage.value > 1) {
        data.currentPage.value -= 1
      }
      await fetchImages({ silent: true })

      if (deletingFromDetail) {
        if (!data.images.value.length) {
          detailIndex.value = -1
          selectedImage.value = null
          closeDetail()
        } else {
          const fallbackIndex = Math.max(0, Math.min(previousDetailIndex, data.images.value.length - 1))
          setDetailByIndex(fallbackIndex)
          detailModalOpen.value = true
        }
      }
    } catch (error) {
      notification.error('删除失败', '删除图片时出错')
      console.error('删除图片失败:', error)
    } finally {
      deleting.value = false
    }
  }

  const clearCacheAction = async () => {
    try {
      const { clearCache } = useImageApi()
      await clearCache()
      notification.success('成功', '缓存已清理')
    } catch (error) {
      notification.error('错误', '清理缓存失败')
      console.error('清理缓存失败:', error)
    }
  }

  // ── 高级面板 ──
  const openAdvancedPanel = () => {
    advancedPanelOpen.value = true
  }

  const closeAdvancedPanel = () => {
    advancedPanelOpen.value = false
  }

  // ── 初始化 ──
  const initialize = async () => {
    await Promise.all([
      data.loadSyncDeleteSetting(),
      fetchImages({ silent: true }),
    ])
  }

  return {
    // 数据状态
    loading: data.loading,
    refreshing: data.refreshing,
    deleting,
    images: data.images,
    selectedIds,
    selectedCount,
    isAllOnPageSelected,
    isPagePartiallySelected,

    // 查询/筛选
    searchQuery: data.searchQuery,
    primaryFilter: data.primaryFilter,
    sortBy: data.sortBy,
    sortOrder: data.sortOrder,
    advancedFilters: data.advancedFilters,
    hasActiveAdvancedFilters: data.hasActiveAdvancedFilters,
    currentPage: data.currentPage,
    totalPages: data.totalPages,
    totalCount: data.totalCount,
    pageSize: data.pageSize,
    viewMode,
    advancedPanelOpen,
    tgSyncDeleteEnabled: data.tgSyncDeleteEnabled,

    // 详情 & 删除面板
    detailModalOpen,
    detailIndex,
    selectedImage,
    hasPrevDetail,
    hasNextDetail,
    deleteModalOpen,
    deleteMessage,
    deleteWithStorage,

    // 选项常量
    pageSizeOptions: data.pageSizeOptions,
    primaryFilterOptions: data.primaryFilterOptions,
    sortByOptions: data.sortByOptions,
    sortOrderOptions: data.sortOrderOptions,
    sourceOptions: data.sourceOptions,

    // 初始化
    initialize,
    fetchImages,
    refresh,
    setSearchQuery,
    applyPrimaryFilter,
    applyPageSize,
    applySorting,
    applyAdvancedFilters,
    resetAdvancedFilters,
    openAdvancedPanel,
    closeAdvancedPanel,
    changePage,

    // 选择
    toggleSelect,
    toggleSelectAllOnPage,
    clearSelection,

    // 详情
    openDetail,
    openDetailById,
    goPrevDetail,
    goNextDetail,
    closeDetail,
    downloadImage,
    deleteCurrentDetailImage,
    copyImageUrl,
    copySelectedUrls,

    // 删除
    openDeleteForSingle,
    openDeleteForSelection,
    closeDeleteModal,
    confirmDelete,
    clearCacheAction,
  }
}
