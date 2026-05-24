<template>
  <div>
    <aside
      class="fixed bottom-4 right-4 z-30 hidden rounded-2xl border border-stone-200 bg-white/90 p-2 shadow-lg backdrop-blur-sm dark:border-stone-700 dark:bg-stone-900/90 lg:block"
    >
      <nav class="flex flex-col gap-1">
        <button
          v-for="section in sections"
          :key="section.id"
          class="rounded-lg px-3 py-1.5 text-left text-xs font-medium text-stone-600 transition-colors hover:bg-amber-50 hover:text-amber-700 dark:text-stone-400 dark:hover:bg-amber-900/20 dark:hover:text-amber-400"
          @click="scrollTo(section.id)"
        >
          {{ section.title }}
        </button>
      </nav>
    </aside>
    <slot />
  </div>
</template>

<script setup lang="ts">
import type { ApiSection } from '~/data/apiDocs'

defineProps<{
  sections: ApiSection[]
}>()

const scrollTo = (id: string) => {
  if (typeof document === 'undefined') return
  const el = document.getElementById(id)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
</script>
