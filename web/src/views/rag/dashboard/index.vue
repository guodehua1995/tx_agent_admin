<script setup>
import { onMounted, ref } from 'vue'
import { NCard, NDataTable, NGrid, NGi, NStatistic, NNumberAnimation } from 'naive-ui'

import CommonPage from '@/components/page/CommonPage.vue'
import api from '@/api'

defineOptions({ name: '数据看板' })

const stats = ref({})
const trends = ref([])
const loading = ref(true)

const trendColumns = [
  { title: '日期', key: 'date', width: 120, align: 'center' },
  { title: '新增文档', key: 'new_documents', width: 100, align: 'center' },
  { title: '新增消息', key: 'new_messages', width: 100, align: 'center' },
]

const statCards = [
  { key: 'total_documents', label: '文档总数', color: '#2080f0' },
  { key: 'pending_review', label: '待审核', color: '#f0a020' },
  { key: 'completed_documents', label: '已完成', color: '#18a058' },
  { key: 'processing_documents', label: '处理中', color: '#2080f0' },
  { key: 'failed_documents', label: '失败', color: '#d03050' },
  { key: 'rejected_documents', label: '已拒绝', color: '#d03050' },
  { key: 'total_knowledge_bases', label: '知识库', color: '#2080f0' },
  { key: 'total_agents', label: 'Agent', color: '#2080f0' },
  { key: 'total_conversations', label: '会话数', color: '#2080f0' },
  { key: 'total_messages', label: '消息数', color: '#2080f0' },
]

onMounted(async () => {
  try {
    const [statsRes, trendsRes] = await Promise.all([
      api.getDashboardStats(),
      api.getDashboardTrends(),
    ])
    stats.value = statsRes.data || {}
    trends.value = trendsRes.data || []
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <CommonPage title="数据看板">
    <NGrid :x-gap="16" :y-gap="16" cols="2 s:3 m:4 l:5" responsive="screen">
      <NGi v-for="card in statCards" :key="card.key">
        <NCard size="small" hoverable>
          <NStatistic :label="card.label">
            <NNumberAnimation :from="0" :to="stats[card.key] || 0" />
          </NStatistic>
        </NCard>
      </NGi>
    </NGrid>

    <NCard title="近7天趋势" size="small" style="margin-top: 16px">
      <NDataTable
        :columns="trendColumns"
        :data="trends"
        :loading="loading"
        :bordered="false"
        size="small"
      />
    </NCard>
  </CommonPage>
</template>
