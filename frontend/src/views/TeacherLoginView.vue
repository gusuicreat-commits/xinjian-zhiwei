<script setup lang="ts">
import { Key, Lock, Monitor, User } from '@element-plus/icons-vue'
import { reactive } from 'vue'
import { useRouter } from 'vue-router'

import { useTeacherSessionStore } from '@/stores/teacherSession'

const router = useRouter()
const store = useTeacherSessionStore()
const form = reactive({ username: '', password: '' })

async function submit(): Promise<void> {
  if (!form.username || !form.password) return
  try {
    await store.login(form.username, form.password)
    await router.replace('/teacher')
  } catch {
    // Store exposes the user-facing error.
  }
}
</script>

<template>
  <main class="auth-page auth-page--teacher">
    <header class="auth-topbar">
      <div class="auth-topbar-inner">
        <div class="auth-brand">
          <Monitor aria-hidden="true" />
          <div class="auth-brand-copy">
            <strong>芯鉴知微</strong>
            <small>嵌入式实验智能分析平台</small>
          </div>
          <span class="auth-portal-badge">教师端</span>
        </div>
        <router-link class="auth-topbar-switch" to="/login">学生端登录</router-link>
      </div>
    </header>

    <section class="auth-stage" aria-labelledby="teacher-login-title">
      <div class="auth-card auth-card--teacher">
        <p class="auth-kicker">SECURE ACCOUNT</p>
        <h1 id="teacher-login-title">登录教师工作台</h1>
        <p class="auth-panel-copy">使用已分配教师或管理员角色的正式账号登录，数据范围按班级权限隔离。</p>
        <el-alert v-if="store.errorMessage" :title="store.errorMessage" type="error" show-icon />
        <el-form class="login-form" @submit.prevent="submit">
          <el-form-item>
            <el-input v-model="form.username" autocomplete="username" placeholder="教师用户名"
              ><template #prefix><User /></template
            ></el-input>
          </el-form-item>
          <el-form-item>
            <el-input
              v-model="form.password"
              type="password"
              show-password
              autocomplete="current-password"
              placeholder="密码"
              @keyup.enter="submit"
              ><template #prefix><Lock /></template
            ></el-input>
          </el-form-item>
          <el-button
            type="primary"
            :loading="store.loading"
            :disabled="!form.username || !form.password"
            @click="submit"
          >
            <Key />进入教师端
          </el-button>
        </el-form>
      </div>
    </section>
    <footer class="auth-footer">权限隔离 · 操作留痕 · 数据可追溯</footer>
  </main>
</template>
