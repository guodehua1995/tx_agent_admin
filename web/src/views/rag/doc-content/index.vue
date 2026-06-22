<script setup>
import { h, onMounted, ref } from 'vue'
import { NButton, NDataTable, NInput, NModal, NPopconfirm, NSpin, NTag, NEmpty } from 'naive-ui'
import { useRoute, useRouter } from 'vue-router'

import CommonPage from '@/components/page/CommonPage.vue'
import { renderIcon } from '@/utils'
import api from '@/api'

defineOptions({ name: '文档分片' })

const route = useRoute()
const router = useRouter()

const docId = ref(Number(route.query.doc_id) || 0)
const kbId = ref(Number(route.query.kb_id) || 0)
const docTitle = ref('')
const loading = ref(false)
const chunks = ref([])

// Modal state
const modalVisible = ref(false)
const modalTitle = ref('')
const modalLoading = ref(false)
const modalText = ref('')
const editingNodeId = ref(null)

async function loadDocInfo() {
  if (!docId.value) return
  try {
    const res = await api.getDocument({ document_id: docId.value })
    docTitle.value = res.data?.title || ''
  } catch {
    docTitle.value = ''
  }
}

async function loadChunks() {
  if (!docId.value) return
  loading.value = true
  try {
    const res = await api.getDocChunkList({ doc_id: docId.value })
    chunks.value = res.data || []
  } catch {
    $message?.error('加载切片列表失败')
    chunks.value = []
  } finally {
    loading.value = false
  }
}

function goBack() {
  if (kbId.value) {
    router.push({ path: '/rag-knowledge/kb-content', query: { kb_id: kbId.value } })
  } else {
    router.back()
  }
}

function handleAdd() {
  editingNodeId.value = null
  modalText.value = ''
  modalTitle.value = '新增切片'
  modalVisible.value = true
}

function handleEdit(row) {
  editingNodeId.value = row.node_id
  modalText.value = row.text || ''
  modalTitle.value = '编辑切片'
  modalVisible.value = true
}

async function handleSave() {
  if (!modalText.value.trim()) {
    $message?.warning('切片文本不能为空')
    return
  }
  modalLoading.value = true
  try {
    if (editingNodeId.value) {
      // 编辑模式
      const res = await api.updateDocChunk({
        node_id: editingNodeId.value,
        doc_id: docId.value,
        text: modalText.value,
      })
      if (res.code === 200) {
        $message?.success('切片更新成功')
        modalVisible.value = false
        await loadChunks()
      } else {
        $message?.error(res.msg || '更新失败')
      }
    } else {
      // 新增模式
      const res = await api.createDocChunk({
        doc_id: docId.value,
        text: modalText.value,
      })
      if (res.code === 200) {
        $message?.success('切片创建成功')
        modalVisible.value = false
        await loadChunks()
      } else {
        $message?.error(res.msg || '创建失败')
      }
    }
  } catch {
    $message?.error('操作失败')
  } finally {
    modalLoading.value = false
  }
}

async function handleDelete(row) {
  try {
    const res = await api.deleteDocChunk({ node_id: row.node_id })
    if (res.code === 200) {
      $message?.success('删除成功')
      await loadChunks()
    } else {
      $message?.error(res.msg || '删除失败')
    }
  } catch {
    $message?.error('删除失败')
  }
}

const columns = [
  {
    title: '序号',
    key: 'index',
    width: 60,
    align: 'center',
    render(_, index) {
      return h('span', index + 1)
    },
  },
  {
    title: 'Node ID',
    key: 'node_id',
    width: 120,
    align: 'center',
    ellipsis: { tooltip: true },
    render(row) {
      const short = row.node_id ? row.node_id.substring(0, 8) + '...' : '-'
      return h(NTag, { size: 'small', type: 'default' }, { default: () => short })
    },
  },
  {
    title: '文本内容',
    key: 'text',
    ellipsis: { tooltip: true, lineClamp: 3 },
    render(row) {
      const preview = row.text
        ? row.text.length > 200
          ? row.text.substring(0, 200) + '...'
          : row.text
        : '-'
      return h('span', { style: 'white-space: pre-wrap; font-size: 13px;' }, preview)
    },
  },
  {
    title: '操作',
    key: 'actions',
    width: 150,
    align: 'center',
    fixed: 'right',
    render(row) {
      return [
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
        h(
          NPopconfirm,
          {
            onPositiveClick: () => handleDelete(row),
            onNegativeClick: () => {},
          },
          {
            trigger: () =>
              h(
                NButton,
                { size: 'small', type: 'error' },
                {
                  default: () => '删除',
                  icon: renderIcon('material-symbols:delete-outline', { size: 16 }),
                }
              ),
            default: () => h('div', {}, '确定删除该切片吗？向量数据也将被移除。'),
          }
        ),
      ]
    },
  },
]

onMounted(() => {
  if (!docId.value) {
    $message?.error('缺少文档ID参数')
    goBack()
    return
  }
  loadDocInfo()
  loadChunks()
})
</script>

<template>
  <CommonPage :title="`文档分片 - ${docTitle || '加载中...'}`">
    <template #action>
      <NButton quaternary style="margin-right: 12px" @click="goBack">
        <TheIcon icon="material-symbols:arrow-back" :size="18" class="mr-5" />返回
      </NButton>
      <NButton type="primary" @click="handleAdd">
        <TheIcon icon="material-symbols:add" :size="18" class="mr-5" />新增切片
      </NButton>
    </template>

    <NSpin :show="loading">
      <NDataTable
        v-if="chunks.length > 0"
        :columns="columns"
        :data="chunks"
        :bordered="true"
        :single-line="false"
        :max-height="600"
        virtual-scroll
      />
      <NEmpty v-else description="暂无切片数据" style="margin-top: 60px" />
    </NSpin>

    <!-- Add/Edit Modal -->
    <NModal v-model:show="modalVisible" preset="card" :title="modalTitle" style="width: 700px">
      <NInput
        v-model:value="modalText"
        type="textarea"
        :rows="12"
        placeholder="请输入切片文本内容"
        style="font-family: monospace"
      />
      <template #footer>
        <div style="display: flex; justify-content: flex-end; gap: 8px">
          <NButton @click="modalVisible = false">取消</NButton>
          <NButton type="primary" :loading="modalLoading" @click="handleSave"> 确定 </NButton>
        </div>
      </template>
    </NModal>
  </CommonPage>
</template>
