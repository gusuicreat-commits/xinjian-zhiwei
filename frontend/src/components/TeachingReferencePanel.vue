<script setup lang="ts">
import type { TeachingReference } from '@/types/student'

defineProps<{ material?: TeachingReference | null }>()
</script>

<template>
  <details v-if="material?.status === 'available'" class="teaching-reference">
    <summary>为什么这样检查 · 实验参考</summary>
    <p class="material-status">
      {{
        material.is_test_data
          ? '测试资料，待硬件与教师确认'
          : '实验包参考资料，实际结果仍需观察确认'
      }}
      · 版本 {{ material.package_version }}
    </p>
    <div v-if="material.concepts.length">
      <strong>相关知识</strong>
      <p v-for="concept in material.concepts" :key="concept.concept_id">
        {{ concept.description }}
      </p>
    </div>
    <div v-if="material.steps.length">
      <strong>相关实验环节</strong>
      <p>以下是实验参考，不代表已经执行；当前排查动作以上方提示为准。</p>
      <div v-for="step in material.steps" :key="step.step_id" class="reference-step">
        <strong>{{ step.title }}</strong>
        <p>预期观察（不是实测结果）：{{ step.expected_state }}</p>
      </div>
    </div>
  </details>
  <p v-else class="teaching-missing">
    {{
      material?.status === 'unavailable'
        ? '本次教学资料不可用，基础诊断仍可查看。'
        : material
          ? '本条提示暂无明确关联的教学资料。'
          : '此历史指导未记录教学资料关联。'
    }}
  </p>
</template>

<style scoped>
.teaching-reference {
  margin-top: 0.75rem;
  font-size: 0.9rem;
  line-height: 1.65;
}
.teaching-reference summary {
  cursor: pointer;
  color: var(--el-color-primary, #2563eb);
}
.teaching-reference p {
  margin: 0.4rem 0;
  font-size: 14px;
  line-height: 1.65;
  overflow-wrap: anywhere;
}
.reference-step {
  margin: 0.65rem 0;
  padding-left: 0.8rem;
  border-left: 2px solid #b9c5d5;
}
.material-status,
.teaching-missing {
  color: #58677a;
  font-size: 0.85rem;
}
</style>
