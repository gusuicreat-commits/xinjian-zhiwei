<script setup lang="ts">
import type { MemoryContext } from '@/types/memory'
defineProps<{ memory: MemoryContext }>()
</script>
<template>
  <details class="memory-summary">
    <summary>本次任务记住了什么</summary>
    <p v-if="!memory.available" role="alert">
      相关资料已停用或无法核验，请联系教师。旧建议不能继续使用。
    </p>
    <p v-if="memory.working.is_test_data">本次包含测试数据，不代表真实实验结论。</p>
    <dl>
      <dt>事实记忆</dt>
      <dd>
        {{
          memory.facts.length
            ? '已保留固定版本的实验配置；配置不等于实际接线或实测结果。'
            : '暂无可用的固定版本事实资料。'
        }}
      </dd>
      <dt>经验记忆</dt>
      <dd>
        摘要列出
        {{ memory.experiences.length }} 条本次关联的已审核经验；参考案例不代表本次根因已确认。
      </dd>
      <dt>工作记忆</dt>
      <dd>
        {{ memory.working.active ? '当前任务仍在处理' : '当前任务上下文已停止活动' }}，保留
        {{ memory.working.evidence_ids.length }} 条证据引用和
        {{ memory.working.feedback.length }} 条学生反馈。
      </dd>
    </dl>
    <p v-if="memory.working.evidence_truncated || memory.working.feedback_truncated">
      此处为有限摘要，完整记录仍保留在对应任务中。
    </p>
  </details>
</template>
<style scoped>
.memory-summary {
  margin: 12px 0;
  padding: 14px;
  border: 1px solid #dce5eb;
  border-radius: 10px;
}
summary {
  cursor: pointer;
  font-weight: 600;
}
dt {
  font-weight: 600;
  margin-top: 10px;
}
dd {
  margin: 4px 0 0;
  line-height: 1.6;
}
p {
  line-height: 1.6;
}
</style>
