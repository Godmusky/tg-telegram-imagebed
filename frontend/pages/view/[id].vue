<template>
  <div class="fixed inset-0 z-50 flex flex-col bg-black">
    <!-- 顶部栏 -->
    <header class="flex shrink-0 items-center justify-between px-2 py-2 sm:px-4 sm:py-3">
      <div class="flex min-w-0 items-center gap-2">
        <UButton
          color="white"
          variant="ghost"
          icon="heroicons:arrow-left-20-solid"
          size="sm"
          class="-ml-1 text-white/70 hover:text-white"
          @click="goBack"
        />
        <div class="min-w-0">
          <p class="truncate text-xs font-medium text-white/90">
            {{ filename || '图片查看' }}
          </p>
          <p v-if="fileSize" class="text-[11px] text-white/50">
            {{ fileSize }}
          </p>
        </div>
      </div>
      <div class="flex items-center gap-1">
        <UButton
          color="white"
          variant="ghost"
          icon="heroicons:arrow-down-tray"
          size="sm"
          class="text-white/70 hover:text-white"
          :to="imageUrl"
          :download="filename || 'image'"
          aria-label="下载"
        />
        <UButton
          color="white"
          variant="ghost"
          icon="heroicons:clipboard"
          size="sm"
          class="text-white/70 hover:text-white"
          aria-label="复制链接"
          @click="copyLink"
        />
      </div>
    </header>

    <!-- 图片区域 -->
    <div class="flex min-h-0 flex-1 items-center justify-center p-2 sm:p-4">
      <img
        v-if="imageUrl"
        :src="imageUrl"
        :alt="filename"
        class="max-h-full max-w-full rounded-lg object-contain shadow-2xl"
        @error="onError"
      >
      <div v-else class="flex flex-col items-center gap-2 text-white/50">
        <UIcon name="heroicons:photo" class="h-12 w-12" />
        <p class="text-sm">加载中...</p>
      </div>
    </div>

    <!-- 错误提示 -->
    <div
      v-if="error"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/90 px-6"
    >
      <div class="max-w-sm text-center">
        <div class="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-white/10">
          <UIcon name="heroicons:exclamation-triangle" class="h-7 w-7 text-white/60" />
        </div>
        <p class="mb-1 text-base font-medium text-white/90">图片加载失败</p>
        <p class="mb-6 text-sm text-white/50">{{ error }}</p>
        <UButton color="white" variant="soft" @click="goBack">
          返回
        </UButton>
      </div>
    </div>

    <!-- 键盘快捷键提示（桌面端） -->
    <footer class="hidden shrink-0 items-center justify-center gap-4 border-t border-white/10 px-4 py-2 sm:flex">
      <kbd class="rounded bg-white/10 px-2 py-0.5 text-[11px] text-white/50">Esc</kbd>
      <span class="text-[11px] text-white/40">关闭</span>
      <kbd class="rounded bg-white/10 px-2 py-0.5 text-[11px] text-white/50">← →</kbd>
      <span class="text-[11px] text-white/40">浏览器前进/后退</span>
    </footer>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ layout: false })

const route = useRoute()
const router = useRouter()
const { copy: clipboardCopy } = useClipboardCopy()

const imgId = computed(() => String(route.params.id || ''))
const imageUrl = computed(() => `/image/${imgId.value}`)

const filename = ref('')
const fileSize = ref('')
const error = ref('')

// 尝试从响应头获取文件名和大小
onMounted(async () => {
  try {
    const resp = await fetch(imageUrl.value, { method: 'HEAD' })
    if (!resp.ok) {
      error.value = `服务器返回 ${resp.status}`
      return
    }
    const disposition = resp.headers.get('Content-Disposition')
    if (disposition) {
      const match = disposition.match(/filename\*?=(?:UTF-8'')?([^;\s]+)/i)
      if (match) {
        filename.value = decodeURIComponent(match[1].replace(/["']/g, ''))
      }
    }
    const size = resp.headers.get('Content-Length')
    if (size) {
      const bytes = parseInt(size, 10)
      if (!Number.isNaN(bytes)) {
        fileSize.value = bytes > 1024 * 1024
          ? `${(bytes / (1024 * 1024)).toFixed(2)} MB`
          : `${(bytes / 1024).toFixed(1)} KB`
      }
    }
    if (!filename.value) {
      filename.value = imgId.value
    }
  } catch {
    // HEAD 请求失败不影响图片显示
    filename.value = imgId.value
  }
})

const onError = () => {
  error.value = '图片无法获取，链接可能已失效'
}

const goBack = () => {
  if (window.history.length > 1) {
    router.back()
  } else {
    router.push('/')
  }
}

const copyLink = async () => {
  try {
    await clipboardCopy(window.location.href)
    const toast = useToast()
    toast.add({ title: '链接已复制', icon: 'heroicons:check-circle', color: 'green' })
  } catch {
    // 静默失败
  }
}

// 键盘 Esc 关闭
onMounted(() => {
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape') goBack()
  }
  window.addEventListener('keydown', onKey)
  onUnmounted(() => window.removeEventListener('keydown', onKey))
})
</script>
