<template>
  <div class="relative">
    <button
      class="absolute right-2 top-2 rounded-md bg-stone-700 px-2 py-1 text-xs text-stone-300 transition-colors hover:bg-stone-600 hover:text-white"
      @click="copyCode"
    >
      {{ copied ? '已复制' : '复制' }}
    </button>
    <pre
      class="overflow-x-auto rounded-xl bg-stone-900 p-4 font-mono text-sm leading-relaxed"
      :class="languageClass"
    ><code>{{ code }}</code></pre>
  </div>
</template>

<script setup lang="ts">
const props = defineProps<{
  code: string
  language?: string
}>()

const copied = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined

const languageClass = computed(() => {
  switch (props.language) {
    case 'bash': return 'text-green-300'
    case 'json': return 'text-amber-300'
    default: return 'text-stone-200'
  }
})

const copyCode = async () => {
  if (typeof navigator === 'undefined') return
  try {
    await navigator.clipboard.writeText(props.code)
  } catch {
    const el = document.createElement('textarea')
    el.value = props.code
    el.style.cssText = 'position:fixed;left:-9999px'
    document.body.appendChild(el)
    el.select()
    document.execCommand('copy')
    document.body.removeChild(el)
  }
  copied.value = true
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => { copied.value = false }, 2000)
}
</script>
