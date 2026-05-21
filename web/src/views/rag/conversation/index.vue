<script setup>
import { computed, h, onMounted, ref } from 'vue'
import { NButton, NDrawer, NDrawerContent, NSelect, NTag } from 'naive-ui'

import CommonPage from '@/components/page/CommonPage.vue'
import QueryBarItem from '@/components/query-bar/QueryBarItem.vue'
import CrudTable from '@/components/table/CrudTable.vue'

import { formatDate, renderIcon } from '@/utils'
import api from '@/api'

defineOptions({ name: '会话管理' })

const $table = ref(null)
const queryItems = ref({})
const agentOptions = ref([])

// Message drawer
const drawerVisible = ref(false)
const messages = ref([])
const messageLoading = ref(false)
// 只展示 user 和 assistant 消息
const displayMessages = computed(() => messages.value.filter((m) => m.type === 'user' || m.type === 'assistant'))

async function loadAgents() {
  const res = await api.getAgentList({ page: 1, page_size: 9999 })
  agentOptions.value = (res.data || []).map((item) => ({ label: item.name, value: item.id }))
}

function getAgentName(id) {
  return agentOptions.value.find((o) => o.value === id)?.label || id
}

async function openMessageDrawer(row) {
  drawerVisible.value = true
  messageLoading.value = true
  try {
    const res = await api.getMessageList({ conversation_id: row.id, limit: 50 })
    messages.value = res.data || []
  } catch {
    messages.value = []
  } finally {
    messageLoading.value = false
  }
}

onMounted(() => {
  loadAgents()
  $table.value?.handleSearch()
})

const columns = [
  {
    title: 'Agent',
    key: 'agent_id',
    width: 150,
    align: 'center',
    render(row) {
      return h('span', getAgentName(row.agent_id))
    },
  },
  {
    title: '消息数',
    key: 'message_count',
    width: 80,
    align: 'center',
  },
  {
    title: '最后活跃',
    key: 'last_active_at',
    width: 150,
    align: 'center',
    render(row) {
      return h('span', row.last_active_at ? formatDate(row.last_active_at) : '-')
    },
  },
  {
    title: '创建日期',
    key: 'created_at',
    width: 120,
    align: 'center',
    render(row) {
      return h('span', formatDate(row.created_at))
    },
  },
  {
    title: '操作',
    key: 'actions',
    width: 100,
    align: 'center',
    fixed: 'right',
    render(row) {
      return h(
        NButton,
        { size: 'small', type: 'info', onClick: () => openMessageDrawer(row) },
        { default: () => '查看消息', icon: renderIcon('carbon:chat', { size: 16 }) }
      )
    },
  },
]
</script>

<template>
  <CommonPage show-footer title="会话管理">
    <CrudTable
      ref="$table"
      v-model:query-items="queryItems"
      :columns="columns"
      :get-data="api.getConversationList"
    >
      <template #queryBar>
        <QueryBarItem label="Agent" :label-width="50">
          <NSelect
            v-model:value="queryItems.agent_id"
            clearable
            :options="agentOptions"
            placeholder="请选择Agent"
          />
        </QueryBarItem>
      </template>
    </CrudTable>

    <!-- Message Drawer -->
    <NDrawer v-model:show="drawerVisible" placement="right" :width="500">
      <NDrawerContent title="消息记录" :native-scrollbar="false">
        <div v-if="messageLoading" style="text-align: center; padding: 20px">加载中...</div>
        <div
          v-else-if="messages.length === 0"
          style="text-align: center; padding: 20px; color: #999"
        >
          暂无消息
        </div>
        <div v-else>
          <div v-for="(msg, idx) in displayMessages" :key="idx" style="margin-bottom: 16px">
            <div :style="{ textAlign: msg.type === 'user' ? 'right' : 'left' }">
              <NTag
                :type="msg.type === 'user' ? 'info' : 'success'"
                size="small"
                style="margin-bottom: 4px"
              >
                {{ msg.type === 'user' ? '用户' : 'Agent' }}
              </NTag>
              <div style="font-size: 12px; color: #999; margin-bottom: 2px">
                {{ formatDate(msg.created_at) }}
              </div>
              <div
                :style="{
                  background: msg.type === 'user' ? '#e8f4fd' : '#f0f9eb',
                  padding: '8px 12px',
                  borderRadius: '8px',
                  display: 'inline-block',
                  maxWidth: '85%',
                  textAlign: 'left',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                }"
              >
                {{ msg.content }}
              </div>
            </div>
          </div>
        </div>
      </NDrawerContent>
    </NDrawer>
  </CommonPage>
</template>
