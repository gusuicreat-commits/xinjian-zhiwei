<script setup lang="ts">
import { Connection, Lock, Monitor, User } from '@element-plus/icons-vue'
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
  <main class="auth-page auth-page--student">
    <header class="auth-topbar">
      <div class="auth-topbar-inner">
        <div class="auth-brand">
          <Monitor aria-hidden="true" />
          <div class="auth-brand-copy">
            <strong>芯鉴知微</strong>
            <small>嵌入式实验智能分析平台</small>
          </div>
          <span class="auth-portal-badge">学生端</span>
        </div>
        <router-link class="auth-topbar-switch" to="/teacher/login">教师端登录</router-link>
      </div>
    </header>

    <section class="auth-stage" aria-labelledby="student-login-title">
      <div class="auth-card">
        <p class="auth-kicker">DEVICE SESSION</p>
        <h1 id="student-login-title">连接实验设备</h1>
        <p class="auth-panel-copy">输入设备 ID 与一次性令牌，进入当前实验会话。</p>

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
            登录学生工作台
          </el-button>
        </el-form>

        <div class="auth-notices">
          <div class="session-notice">
            <Connection />
            <span>设备令牌只在创建时显示一次，数据库仅保存哈希，无法反查原令牌。</span>
          </div>
          <div class="session-notice">
            <Lock />
            <span>测试凭据请由后端 demo 数据脚本生成；页面仅保存本次浏览器会话。</span>
          </div>
        </div>
      </div>
    </section>
    <footer class="auth-footer">安全 · 稳定 · 可追溯</footer>
  </main>
</template>
