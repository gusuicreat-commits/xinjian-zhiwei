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
  <main class="login-page">
    <section class="login-shell">
      <div class="login-hero">
        <header class="login-brand">
          <Monitor aria-hidden="true" />
          <div>
            <h1>芯鉴知微</h1>
            <p>嵌入式实验智能分析平台</p>
          </div>
          <b>学生端</b>
        </header>

        <div class="login-hero-copy">
          <p class="auth-kicker">STUDENT LAB ACCESS</p>
          <h2>
            <span class="auth-title-line">让每一次设备异常，</span>
            <span class="auth-title-line auth-title-accent">都有清晰下一步。</span>
          </h2>
          <p>连接设备日志、传感数据与诊断建议，在同一工作台完成实验排查与反馈。</p>
        </div>

        <img
          class="login-illustration"
          src="/assets/login-chip-platform.png"
          alt="铜色微芯片与传感模块三维插画"
        />

        <p class="login-hero-lede">
          系统持续整理设备状态和实验记录，帮助你更快定位异常、验证排查结果，并在需要时请求教师协助。
        </p>
      </div>

      <div class="login-access">
        <p class="auth-kicker">DEVICE SESSION</p>
        <h2>连接实验设备</h2>
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
        <router-link class="auth-switch" to="/teacher/login">切换到教师账号登录</router-link>
        <footer>安全 · 稳定 · 可追溯</footer>
      </div>
    </section>
  </main>
</template>
