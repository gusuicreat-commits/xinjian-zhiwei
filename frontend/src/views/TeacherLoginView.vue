<script setup lang="ts">
import { Key, Lock, Monitor, UserFilled } from '@element-plus/icons-vue'
import { reactive } from 'vue'
import { useRouter } from 'vue-router'

import { useTeacherSessionStore } from '@/stores/teacherSession'

const router = useRouter()
const store = useTeacherSessionStore()
const form = reactive({ reviewToken: '' })

async function submit(): Promise<void> {
  if (!form.reviewToken) return
  try {
    await store.login({ reviewToken: form.reviewToken })
    await router.replace('/teacher')
  } catch {
    // Store exposes the user-facing error.
  }
}
</script>

<template>
  <main class="teacher-login-page">
    <section class="teacher-login-card">
      <div class="teacher-login-brand"><Monitor /><span>芯鉴知微</span><b>教师端</b></div>
      <div class="teacher-login-visual"><UserFilled /></div>
      <p class="eyebrow">嵌入式实验智能分析平台</p>
      <h1>教师审阅工作台</h1>
      <p>当前阶段使用默认关闭的临时审阅令牌；正式教师账号与角色仍待建设。</p>
      <el-alert v-if="store.errorMessage" :title="store.errorMessage" type="error" show-icon />
      <el-form @submit.prevent="submit">
        <el-form-item>
          <el-input
            v-model="form.reviewToken"
            type="password"
            show-password
            autocomplete="current-password"
            placeholder="审阅访问令牌"
            @keyup.enter="submit"
            ><template #prefix><Lock /></template
          ></el-input>
        </el-form-item>
        <el-button
          type="primary"
          :loading="store.loading"
          :disabled="!form.reviewToken"
          @click="submit"
        >
          <Key />进入教师端
        </el-button>
      </el-form>
      <router-link to="/login">返回学生端登录</router-link>
    </section>
  </main>
</template>
