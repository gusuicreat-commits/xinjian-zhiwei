<script setup lang="ts">
import { REVIEW_MODE } from '@/review/fixtures'
import { Connection, Lock, Monitor, User } from '@element-plus/icons-vue'
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { useStudentSessionStore } from '@/stores/studentSession'

const router = useRouter()
const sessionStore = useStudentSessionStore()
const form = reactive({ deviceId: '', deviceToken: '' })
const mode = ref<'account' | 'demo'>('account')
const account = reactive({ username: '', password: '' })
const selectedSession = ref('')
const selectedAssignment = ref('')
const selectedDevice = ref('')
const availableDevices = computed(
  () => sessionStore.assignments.find((a) => a.id === selectedAssignment.value)?.devices ?? [],
)

async function beginExperiment(): Promise<void> {
  try {
    await sessionStore.beginExperiment(selectedAssignment.value, selectedDevice.value)
    if (sessionStore.isAuthenticated) await router.replace('/student')
  } catch {
    // A retry preserves the original request, including after a lost response.
  }
}

async function authenticate(): Promise<void> {
  selectedSession.value = ''
  selectedAssignment.value = ''
  selectedDevice.value = ''
  try {
    await sessionStore.authenticateAccount(account.username.trim(), account.password)
    account.password = ''
    if (REVIEW_MODE && sessionStore.isAuthenticated) await router.replace('/student')
    if (sessionStore.availableSessions.length === 1) {
      selectedSession.value = sessionStore.availableSessions[0]!.id
    }
  } catch {
    // Store presents the failure; do not fall back to device credentials.
  }
}

async function enterExperiment(): Promise<void> {
  try {
    await sessionStore.selectExperiment(selectedSession.value)
    if (sessionStore.isAuthenticated) await router.replace('/student')
  } catch {
    // Keep the explicit selection for a safe retry.
  }
}

async function submit(): Promise<void> {
  if (!form.deviceId.trim() || !form.deviceToken) return
  try {
    await sessionStore.login({ deviceId: form.deviceId.trim(), deviceToken: form.deviceToken })
    if (sessionStore.isAuthenticated) await router.replace('/student')
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
        <p class="auth-kicker">STUDENT SESSION</p>
        <h1 id="student-login-title">进入学生实验</h1>
        <p class="auth-panel-copy">
          {{
            REVIEW_MODE
              ? '离线演示无需真实账号，请勿填写真实密码。'
              : '验证本人账号，再选择已获授权的实验。'
          }}
        </p>
        <el-radio-group v-model="mode" aria-label="登录方式">
          <el-radio-button value="account">学生账号</el-radio-button>
          <el-radio-button value="demo">测试设备演示</el-radio-button>
        </el-radio-group>

        <el-button v-if="REVIEW_MODE" type="primary" @click="authenticate"
          >以演示学生身份进入</el-button
        >
        <el-form v-else-if="mode === 'account'" class="login-form" @submit.prevent="authenticate">
          <el-form-item required>
            <el-input v-model="account.username" placeholder="学生账号" autocomplete="username" />
          </el-form-item>
          <el-form-item required>
            <el-input
              v-model="account.password"
              placeholder="学生密码"
              type="password"
              autocomplete="current-password"
              show-password
            />
          </el-form-item>
          <el-button
            native-type="submit"
            type="primary"
            :loading="sessionStore.loading"
            :disabled="!account.username.trim() || !account.password"
            >验证学生账号</el-button
          >
          <el-form-item v-if="sessionStore.availableSessions.length" label="当前实验">
            <el-select v-model="selectedSession" placeholder="选择实验会话">
              <el-option
                v-for="item in sessionStore.availableSessions"
                :key="item.id"
                :value="item.id"
                :label="`${item.assignment_title} · ${item.display_name ?? item.device_id}${item.is_test_data ? '（测试）' : ''}`"
              />
            </el-select>
          </el-form-item>
          <el-button
            v-if="sessionStore.availableSessions.length"
            :disabled="!selectedSession"
            :loading="sessionStore.loading"
            type="primary"
            @click="enterExperiment"
            >进入所选实验</el-button
          >
          <template v-if="sessionStore.assignments.length">
            <el-form-item label="开始新实验">
              <el-select
                v-model="selectedAssignment"
                placeholder="选择实验任务"
                @change="selectedDevice = ''"
              >
                <el-option
                  v-for="item in sessionStore.assignments"
                  :key="item.id"
                  :value="item.id"
                  :label="`${item.title}${item.is_test_data ? '（测试）' : ''}`"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="已分配设备">
              <el-select v-model="selectedDevice" placeholder="选择设备">
                <el-option
                  v-for="item in availableDevices"
                  :key="item.id"
                  :value="item.id"
                  :label="item.name ?? item.id"
                />
              </el-select>
            </el-form-item>
            <el-button
              :disabled="!selectedAssignment || !selectedDevice"
              :loading="sessionStore.loading"
              @click="beginExperiment"
              >开始所选实验</el-button
            >
          </template>
          <el-alert
            v-if="sessionStore.errorMessage"
            :title="sessionStore.errorMessage"
            type="error"
            :closable="false"
          />
        </el-form>

        <el-form v-else class="login-form" @submit.prevent="submit">
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
            <span>设备令牌仅供测试演示；正式实验使用本人账号。</span>
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
