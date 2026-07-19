<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { computed, onMounted } from 'vue'

import StatusBadge from '@/components/StatusBadge.vue'
import { useHealthStore } from '@/stores/health'

const store = useHealthStore()
const { state, health, errorMessage } = storeToRefs(store)
const isReady = computed(() => state.value === 'ready' && health.value?.status === 'ok')

onMounted(() => {
  void store.loadHealth()
})
</script>

<template>
  <main class="page-shell">
    <section class="hero-panel">
      <div class="eyebrow">嵌入式实验智能分析平台</div>
      <h1>芯鉴知微</h1>
      <p class="hero-copy">
        连接设备日志、规则诊断与教学反馈，让实验中的异常有证据、可解释、能沉淀。
      </p>

      <el-card class="health-card" shadow="never">
        <template #header>
          <div class="card-header">
            <div>
              <span class="card-kicker">SYSTEM CHECK</span>
              <h2>运行环境</h2>
            </div>
            <StatusBadge v-if="state !== 'loading' && state !== 'idle'" :online="isReady" />
          </div>
        </template>

        <div v-if="state === 'loading' || state === 'idle'" class="loading-state">
          <el-skeleton :rows="3" animated />
        </div>

        <div v-else-if="isReady && health" class="health-details">
          <div>
            <span>后端服务</span>
            <strong>{{ health.service }}</strong>
          </div>
          <div>
            <span>API 版本</span>
            <strong>{{ health.version }}</strong>
          </div>
          <div>
            <span>运行环境</span>
            <strong>{{ health.environment }}</strong>
          </div>
        </div>

        <el-alert v-else :title="errorMessage" type="error" show-icon :closable="false">
          <template #default>
            <el-button type="danger" plain @click="store.loadHealth">重新检测</el-button>
          </template>
        </el-alert>
      </el-card>

      <p class="phase-note">Phase 2 · 设备数据接入链路</p>
    </section>
  </main>
</template>
