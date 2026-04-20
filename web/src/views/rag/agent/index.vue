<script setup>
import { h, onMounted, ref, resolveDirective, withDirectives } from 'vue'
import {
  NButton,
  NDrawer,
  NDrawerContent,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NPopconfirm,
  NSelect,
  NSpace,
  NSpin,
  NSwitch,
  NTag,
} from 'naive-ui'
import MarkdownIt from 'markdown-it'

import CommonPage from '@/components/page/CommonPage.vue'
import QueryBarItem from '@/components/query-bar/QueryBarItem.vue'
import CrudModal from '@/components/table/CrudModal.vue'
import CrudTable from '@/components/table/CrudTable.vue'

import { formatDate, renderIcon } from '@/utils'
import { useCRUD } from '@/composables'
import { getToken } from '@/utils/auth'
import api from '@/api'

// 初始化 Markdown 解析器
const md = new MarkdownIt({
  html: true,
  linkify: true,
  typographer: true,
  breaks: true,
})

defineOptions({ name: 'Agent管理' })

const $table = ref(null)
const queryItems = ref({})
const vPermission = resolveDirective('permission')

const chatModelOptions = ref([])
const kbOptions = ref([])

const {
  modalVisible,
  modalAction,
  modalTitle,
  modalLoading,
  handleAdd,
  handleDelete,
  handleEdit,
  handleSave,
  modalForm,
  modalFormRef,
} = useCRUD({
  name: 'Agent',
  initForm: { max_history_turns: 10, is_active: true, knowledge_base_ids: [] },
  doCreate: api.createAgent,
  doDelete: api.deleteAgent,
  doUpdate: api.updateAgent,
  refresh: () => $table.value?.handleSearch(),
})

// Chat drawer state
const chatDrawerVisible = ref(false)
const chatAgentId = ref(null)
const chatAgentName = ref('')
const chatQuestion = ref('')
const chatMessages = ref([])
const chatLoading = ref(false)
const chatStreaming = ref(false) // 流式输出中
const currentStreamContent = ref('') // 当前流式内容

async function loadOptions() {
  const [modelRes, kbRes] = await Promise.all([
    api.getAiConfigList({ is_embedding: false, page: 1, page_size: 9999 }),
    api.getKnowledgeBaseList({ page: 1, page_size: 9999 }),
  ])
  chatModelOptions.value = (modelRes.data || []).map((item) => ({
    label: item.name,
    value: item.id,
  }))
  kbOptions.value = (kbRes.data || []).map((item) => ({ label: item.name, value: item.id }))
}

function getChatModelName(id) {
  return chatModelOptions.value.find((o) => o.value === id)?.label || id
}

function openChatDrawer(row) {
  chatAgentId.value = row.id
  chatAgentName.value = row.name
  chatMessages.value = []
  chatQuestion.value = ''
  chatDrawerVisible.value = true
}

async function sendMessage() {
  if (!chatQuestion.value.trim() || chatStreaming.value) return
  const question = chatQuestion.value.trim()
  chatMessages.value.push({ role: 'user', content: question })
  chatQuestion.value = ''
  chatStreaming.value = true
  chatLoading.value = true
  currentStreamContent.value = ''

  // 添加一个空的助手消息，用于流式填充
  const assistantMsgIndex = chatMessages.value.length
  chatMessages.value.push({ role: 'assistant', content: '', isStreaming: true })

  try {
    // 使用 fetch 直接调用 SSE 接口
    const token = getToken()
    const headers = {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    }
    if (token) {
      headers.token = token
    }
    const response = await fetch('/api/v1/agent/chat/stream', {
      method: 'POST',
      headers,
      body: JSON.stringify({ agent_id: chatAgentId.value, question }),
    })

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let sources = []

    // eslint-disable-next-line no-constant-condition
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      const chunk = decoder.decode(value, { stream: true })
      const lines = chunk.split('\n')

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6))

            if (data.type === 'delta') {
              currentStreamContent.value += data.content
              chatMessages.value[assistantMsgIndex].content = currentStreamContent.value
            } else if (data.type === 'sources') {
              sources = data.content
            } else if (data.type === 'error') {
              chatMessages.value[assistantMsgIndex].content = `错误: ${data.content}`
              chatMessages.value[assistantMsgIndex].isStreaming = false
              chatStreaming.value = false
              chatLoading.value = false
              return
            } else if (data.type === 'done') {
              chatMessages.value[assistantMsgIndex].isStreaming = false
              chatMessages.value[assistantMsgIndex].sources = sources
              chatStreaming.value = false
              chatLoading.value = false
              return
            }
          } catch (e) {
            console.error('Parse SSE data error:', e)
          }
        }
      }
    }
  } catch (error) {
    console.error('Chat stream error:', error)
    chatMessages.value[assistantMsgIndex].content = `请求失败: ${error.message}`
    chatMessages.value[assistantMsgIndex].isStreaming = false
  } finally {
    chatStreaming.value = false
    chatLoading.value = false
  }
}

onMounted(() => {
  loadOptions()
  $table.value?.handleSearch()
})

const columns = [
  {
    title: '名称',
    key: 'name',
    width: 150,
    align: 'center',
    ellipsis: { tooltip: true },
  },
  {
    title: '描述',
    key: 'description',
    width: 200,
    align: 'center',
    ellipsis: { tooltip: true },
  },
  {
    title: '对话模型',
    key: 'chat_model_id',
    width: 120,
    align: 'center',
    render(row) {
      return h('span', getChatModelName(row.chat_model_id))
    },
  },
  {
    title: '历史轮数',
    key: 'max_history_turns',
    width: 80,
    align: 'center',
  },
  {
    title: '状态',
    key: 'is_active',
    width: 80,
    align: 'center',
    render(row) {
      return h(
        NTag,
        { type: row.is_active ? 'success' : 'default', size: 'small' },
        { default: () => (row.is_active ? '启用' : '停用') }
      )
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
    width: 240,
    align: 'center',
    fixed: 'right',
    render(row) {
      return [
        withDirectives(
          h(
            NButton,
            {
              size: 'small',
              type: 'primary',
              style: 'margin-right: 8px;',
              onClick: () => handleEdit(row),
            },
            {
              default: () => '编辑',
              icon: renderIcon('material-symbols:edit-outline', { size: 16 }),
            }
          ),
          [[vPermission, 'post/api/v1/agent/update']]
        ),
        h(
          NPopconfirm,
          {
            onPositiveClick: () => handleDelete({ agent_id: row.id }, false),
            onNegativeClick: () => {},
          },
          {
            trigger: () =>
              withDirectives(
                h(
                  NButton,
                  { size: 'small', type: 'error', style: 'margin-right: 8px;' },
                  {
                    default: () => '删除',
                    icon: renderIcon('material-symbols:delete-outline', { size: 16 }),
                  }
                ),
                [[vPermission, 'delete/api/v1/agent/delete']]
              ),
            default: () => h('div', {}, '确定删除该Agent吗?'),
          }
        ),
        withDirectives(
          h(
            NButton,
            { size: 'small', type: 'info', onClick: () => openChatDrawer(row) },
            { default: () => '对话', icon: renderIcon('carbon:chat', { size: 16 }) }
          ),
          [[vPermission, 'post/api/v1/agent/chat']]
        ),
      ]
    },
  },
]
</script>

<template>
  <CommonPage show-footer title="Agent管理">
    <template #action>
      <NButton v-permission="'post/api/v1/agent/create'" type="primary" @click="handleAdd">
        <TheIcon icon="material-symbols:add" :size="18" class="mr-5" />新建Agent
      </NButton>
    </template>

    <CrudTable
      ref="$table"
      v-model:query-items="queryItems"
      :columns="columns"
      :get-data="api.getAgentList"
    >
      <template #queryBar>
        <QueryBarItem label="名称" :label-width="40">
          <NInput
            v-model:value="queryItems.name"
            clearable
            type="text"
            placeholder="请输入名称"
            @keypress.enter="$table?.handleSearch()"
          />
        </QueryBarItem>
      </template>
    </CrudTable>

    <CrudModal
      v-model:visible="modalVisible"
      :title="modalTitle"
      :loading="modalLoading"
      @save="handleSave"
    >
      <NForm
        ref="modalFormRef"
        label-placement="left"
        label-align="left"
        :label-width="100"
        :model="modalForm"
        :disabled="modalAction === 'view'"
      >
        <NFormItem
          label="名称"
          path="name"
          :rule="{ required: true, message: '请输入名称', trigger: ['input', 'blur'] }"
        >
          <NInput v-model:value="modalForm.name" placeholder="请输入Agent名称" />
        </NFormItem>
        <NFormItem label="描述" path="description">
          <NInput v-model:value="modalForm.description" type="textarea" placeholder="请输入描述" />
        </NFormItem>
        <NFormItem
          label="对话模型"
          path="chat_model_id"
          :rule="{
            required: true,
            type: 'number',
            message: '请选择对话模型',
            trigger: ['change', 'blur'],
          }"
        >
          <NSelect
            v-model:value="modalForm.chat_model_id"
            :options="chatModelOptions"
            placeholder="请选择对话模型"
          />
        </NFormItem>
        <NFormItem label="系统提示词" path="system_prompt">
          <NInput
            v-model:value="modalForm.system_prompt"
            type="textarea"
            placeholder="请输入系统提示词"
            :rows="4"
          />
        </NFormItem>
        <NFormItem label="历史轮数" path="max_history_turns">
          <NInputNumber
            v-model:value="modalForm.max_history_turns"
            :min="0"
            :max="50"
            style="width: 100%"
          />
        </NFormItem>
        <NFormItem label="关联知识库" path="knowledge_base_ids">
          <NSelect
            v-model:value="modalForm.knowledge_base_ids"
            multiple
            :options="kbOptions"
            placeholder="请选择关联知识库"
          />
        </NFormItem>
        <NFormItem label="启用" path="is_active">
          <NSwitch v-model:value="modalForm.is_active" />
        </NFormItem>
      </NForm>
    </CrudModal>

    <!-- Chat Test Drawer -->
    <NDrawer v-model:show="chatDrawerVisible" placement="right" :width="500">
      <NDrawerContent :title="`对话测试 - ${chatAgentName}`">
        <div style="display: flex; flex-direction: column; height: 100%">
          <div style="flex: 1; overflow-y: auto; padding-bottom: 16px">
            <div v-for="(msg, idx) in chatMessages" :key="idx" style="margin-bottom: 12px">
              <div :style="{ textAlign: msg.role === 'user' ? 'right' : 'left' }">
                <NTag
                  :type="msg.role === 'user' ? 'info' : 'success'"
                  size="small"
                  style="margin-bottom: 4px"
                >
                  {{ msg.role === 'user' ? '我' : 'Agent' }}
                </NTag>
                <div
                  v-if="msg.role === 'user'"
                  :style="{
                    background: '#e8f4fd',
                    padding: '8px 12px',
                    borderRadius: '8px',
                    display: 'inline-block',
                    maxWidth: '80%',
                    textAlign: 'left',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                  }"
                >
                  {{ msg.content }}
                </div>
                <div
                  v-else
                  class="markdown-body"
                  :style="{
                    background: '#f0f9eb',
                    padding: '8px 12px',
                    borderRadius: '8px',
                    display: 'inline-block',
                    maxWidth: '80%',
                    textAlign: 'left',
                    wordBreak: 'break-word',
                  }"
                  v-html="md.render(msg.content)"
                />
              </div>
            </div>
            <div v-if="chatLoading" style="text-align: left">
              <NSpin size="small" />
            </div>
          </div>
          <NSpace style="padding-top: 8px">
            <NInput
              v-model:value="chatQuestion"
              placeholder="输入问题..."
              style="flex: 1"
              @keypress.enter="sendMessage"
            />
            <NButton type="primary" :loading="chatLoading" @click="sendMessage"> 发送 </NButton>
          </NSpace>
        </div>
      </NDrawerContent>
    </NDrawer>
  </CommonPage>
</template>
