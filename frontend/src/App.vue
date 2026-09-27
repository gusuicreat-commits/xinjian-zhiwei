<script setup lang="ts">
import { REVIEW_MODE } from '@/review/fixtures'
import { RouterView } from 'vue-router'
</script>

<template>
  <aside v-if="REVIEW_MODE" role="status" class="review-mode-notice">
    离线演示 · 全部为合成数据，操作仅保存在本浏览器标签页，不连接真实业务。
  </aside>
  <RouterView />
</template>

<style>
.review-mode-notice {
  padding: 10px 20px;
  background: #fff2ca;
  color: #493900;
  text-align: center;
  font-size: 14px;
}
</style>
