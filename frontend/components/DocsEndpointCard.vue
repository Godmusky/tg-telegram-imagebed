<template>
  <div class="rounded-xl border border-stone-200 bg-stone-50/60 p-4 dark:border-stone-700 dark:bg-stone-800/40">
    <div class="mb-3 flex flex-wrap items-center gap-2">
      <UBadge :color="methodColor" variant="subtle">{{ endpoint.method }}</UBadge>
      <code class="rounded-md bg-stone-200 px-2 py-0.5 font-mono text-sm text-stone-800 dark:bg-stone-700 dark:text-stone-200">{{ endpoint.path }}</code>
    </div>

    <h4 class="mb-1 font-semibold text-stone-900 dark:text-white">{{ endpoint.summary }}</h4>
    <p v-if="endpoint.description" class="mb-3 text-sm text-stone-600 dark:text-stone-400">{{ endpoint.description }}</p>

    <div v-if="endpoint.requestBody" class="mb-3">
      <p class="mb-1 text-xs font-medium uppercase tracking-wide text-stone-500">Request Body</p>
      <p class="text-xs text-stone-600 dark:text-stone-400">{{ endpoint.requestBody.contentType }}</p>
      <pre class="mt-1 overflow-x-auto rounded-md bg-stone-200 p-2 font-mono text-xs dark:bg-stone-700">{{ endpoint.requestBody.schema }}</pre>
    </div>

    <div v-if="endpoint.responses?.length" class="mb-3">
      <p class="mb-1 text-xs font-medium uppercase tracking-wide text-stone-500">Responses</p>
      <div class="space-y-1.5">
        <div v-for="resp in endpoint.responses" :key="resp.status" class="flex items-start gap-2 text-xs">
          <UBadge :color="statusColor(resp.status)" variant="subtle" size="xs">{{ resp.status }}</UBadge>
          <span class="text-stone-600 dark:text-stone-400">{{ resp.description }}</span>
        </div>
      </div>
    </div>

    <div v-if="endpoint.curlExample">
      <p class="mb-1 text-xs font-medium uppercase tracking-wide text-stone-500">cURL 示例</p>
      <pre class="overflow-x-auto rounded-md bg-stone-900 p-3 font-mono text-xs text-green-300">{{ endpoint.curlExample }}</pre>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { ApiEndpoint } from '~/data/apiDocs'

const props = defineProps<{
  endpoint: ApiEndpoint
  baseUrl: string
}>()

const methodColor = computed(() => {
  switch (props.endpoint.method) {
    case 'GET': return 'blue'
    case 'POST': return 'green'
    case 'PUT': return 'amber'
    case 'DELETE': return 'red'
    case 'PATCH': return 'gray'
    default: return 'gray'
  }
})

const statusColor = (status: number) => {
  if (status >= 200 && status < 300) return 'green'
  if (status >= 300 && status < 400) return 'blue'
  if (status >= 400 && status < 500) return 'amber'
  return 'red'
}
</script>
