<script setup lang="ts">
import { Connection, Lock, User } from '@element-plus/icons-vue'
import { reactive } from 'vue'
import { useRouter } from 'vue-router'

import { useStudentSessionStore } from '@/stores/studentSession'

const router = useRouter()
const sessionStore = useStudentSessionStore()
const form = reactive({ deviceId: '', deviceToken: '' })

async function submit(): Promise<void> {
  if (!form.deviceId.trim() || !form.deviceToken) return
  try {
    await sessionStore.login({ deviceId: form.deviceId.trim(), deviceToken: form.deviceToken })
    await router.replace('/student')
  } catch {
    // Store exposes a user-safe error message.
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-shell">
      <header class="login-brand">
        <img src="/assets/xinjian-brand-mark.png" alt="芯鉴知微品牌标志" />
        <h1>芯鉴知微</h1>
        <p>面向嵌入式实时数据的智能分析平台</p>
      </header>

      <img
        class="login-illustration"
        src="/assets/login-chip-platform.png"
        alt="铜色微芯片与传感模块三维插画"
      />

      <el-form class="login-form" @submit.prevent="submit">
        <el-form-item required>
          <el-input
            v-model="form.deviceId"
            size="large"
            autocomplete="username"
            placeholder="设备 ID"
          >
            <template #prefix><User /></template>
          </el-input>
        </el-form-item>
        <el-form-item required>
          <el-input
            v-model="form.deviceToken"
            size="large"
            type="password"
            show-password
            autocomplete="current-password"
            placeholder="设备令牌"
          >
            <template #prefix><Lock /></template>
          </el-input>
        </el-form-item>
        <el-alert
          v-if="sessionStore.errorMessage"
          :title="sessionStore.errorMessage"
          type="error"
          :closable="false"
        />
        <el-button
          native-type="submit"
          type="primary"
          size="large"
          :loading="sessionStore.loading"
          :disabled="!form.deviceId.trim() || !form.deviceToken"
        >
          登录
        </el-button>
      </el-form>

      <div class="session-notice">
        <Connection />
        <span>当前使用设备凭据，仅保留本次浏览器会话</span>
      </div>
      <footer>安全 · 稳定 · 可追溯</footer>
    </section>
  </main>
</template>
