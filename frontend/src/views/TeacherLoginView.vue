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
  <main class="teacher-login-page">
    <section class="teacher-login-card">
      <div class="teacher-login-hero">
        <div class="teacher-login-brand"><Monitor /><span>芯鉴知微</span><b>教师端</b></div>
        <div class="teacher-login-copy">
          <p class="eyebrow">TEACHER OPERATIONS</p>
          <h1>把异常、证据与教学介入，放在同一视野。</h1>
          <p>快速识别班级设备风险，查看诊断依据，并完成审核与学生协助。</p>
        </div>
        <p class="teacher-login-lede">
          工作台持续汇总设备状态、错误趋势和待处理请求，让每一次介入都有来源、过程和结果。
        </p>
      </div>

      <div class="teacher-login-access">
        <p class="eyebrow">SECURE ACCOUNT</p>
        <h2>登录教师工作台</h2>
        <p>使用已分配教师或管理员角色的正式账号登录，数据范围按班级权限隔离。</p>
        <el-alert v-if="store.errorMessage" :title="store.errorMessage" type="error" show-icon />
        <el-form @submit.prevent="submit">
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
        <router-link to="/login">返回学生端登录</router-link>
      </div>
    </section>
  </main>
</template>
