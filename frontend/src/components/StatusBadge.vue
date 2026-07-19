<script setup lang="ts">
defineProps<{
  online: boolean
}>()
</script>

<template>
  <span class="status-badge" :class="online ? 'is-online' : 'is-offline'">
    <span class="status-dot" aria-hidden="true"></span>
    {{ online ? '服务正常' : '连接异常' }}
  </span>
</template>

<style scoped>
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 999px;
  font-size: 14px;
  font-weight: 650;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
}

.is-online {
  color: #087f5b;
  background: #dff8ed;
}

.is-offline {
  color: #b42318;
  background: #fee4e2;
}
</style>
