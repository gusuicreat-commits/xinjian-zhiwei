<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { getReadiness } from '@/api/readiness'
import type { ReadinessStatus } from '@/types/readiness'

const data = ref<ReadinessStatus | null>(null)
const error = ref('')

onMounted(async () => {
  try {
    data.value = await getReadiness()
  } catch {
    error.value = '无法读取就绪状态，请检查后端服务。'
  }
})

const labels = {
  ready: '已就绪',
  blocked: '受阻',
  not_required: '当前非必需',
  test_only: '仅测试',
}

const readinessDimensions = [
  ['software_ready', '软件就绪'],
  ['demo_ready', '演示就绪'],
  ['hardware_ready', '硬件就绪'],
  ['knowledge_ready', '知识就绪'],
  ['organization_ready', '组织就绪'],
  ['production_ready', '生产就绪'],
] as const
</script>

<template>
  <main class="readiness-page">
    <h1>芯鉴知微 · 就绪门禁</h1>
    <p>此页面只展示后端实际证据；缺少外部输入时保持“受阻”，不会自动伪造就绪。</p>
    <el-alert v-if="error" type="error" :title="error" :closable="false" />
    <el-skeleton v-else-if="!data" :rows="8" animated />
    <template v-else>
      <el-alert
        :type="data.overall === 'ready' ? 'success' : 'warning'"
        :title="`版本 ${data.version} · 总体状态：${labels[data.overall]}`"
        :closable="false"
        show-icon
      />
      <section class="readiness-summary" aria-label="六维就绪结论">
        <dl>
          <div v-for="[key, label] in readinessDimensions" :key="key">
            <dt>{{ label }}</dt>
            <dd>
              <el-tag :type="data[key] ? 'success' : 'danger'">
                {{ data[key] ? 'true' : 'false' }}
              </el-tag>
            </dd>
          </div>
        </dl>
      </section>
      <section class="readiness-grid" aria-label="就绪检查项">
        <article v-for="item in data.items" :key="item.key" class="panel-card">
          <h2>{{ item.label }}</h2>
          <el-tag :type="item.status === 'ready' ? 'success' : item.status === 'blocked' ? 'danger' : 'warning'">
            {{ labels[item.status] }}
          </el-tag>
          <p>{{ item.evidence }}</p>
          <p v-if="item.required_input"><strong>仍需提供：</strong>{{ item.required_input }}</p>
        </article>
      </section>
    </template>
  </main>
</template>
