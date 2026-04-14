<script setup>
import { h, onMounted, ref, resolveDirective, withDirectives } from 'vue'
import {
  NButton,
  NForm,
  NFormItem,
  NInput,
  NPopconfirm,
  NSelect,
  NTag,
} from 'naive-ui'

import CommonPage from '@/components/page/CommonPage.vue'
import QueryBarItem from '@/components/query-bar/QueryBarItem.vue'
import CrudModal from '@/components/table/CrudModal.vue'
import CrudTable from '@/components/table/CrudTable.vue'

import { formatDate, renderIcon } from '@/utils'
import { useCRUD } from '@/composables'
import api from '@/api'

defineOptions({ name: '文档管理' })

const $table = ref(null)
const queryItems = ref({})
const vPermission = resolveDirective('permission')

const docTypeOptions = ref([])
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
  name: '文档',
  initForm: {},
  doCreate: api.createDocument,
  doDelete: api.deleteDocument,
  doUpdate: api.updateDocument,
  refresh: () => $table.value?.handleSearch(),
})

const sourceTypeOptions = [
  { label: '飞书文档', value: 'feishu_doc' },
  { label: '文件上传', value: 'file_upload' },
  { label: '网页链接', value: 'web_url' },
]

const statusOptions = [
  { label: '待抓取', value: 'pending_fetch' },
  { label: '已抓取', value: 'fetched' },
  { label: '结构化中', value: 'structuring' },
  { label: '待审核', value: 'pending_review' },
  { label: '已通过', value: 'approved' },
  { label: '向量化中', value: 'vectorizing' },
  { label: '已完成', value: 'completed' },
  { label: '已拒绝', value: 'rejected' },
  { label: '失败', value: 'failed' },
]

const statusColorMap = {
  pending_fetch: 'default',
  fetched: 'info',
  structuring: 'warning',
  pending_review: 'warning',
  approved: 'success',
  vectorizing: 'info',
  completed: 'success',
  rejected: 'error',
  failed: 'error',
}

async function loadOptions() {
  const [typeRes, kbRes] = await Promise.all([
    api.getDocumentTypeList({ page: 1, page_size: 9999 }),
    api.getKnowledgeBaseList({ page: 1, page_size: 9999 }),
  ])
  docTypeOptions.value = (typeRes.data || []).map((item) => ({ label: item.name, value: item.id }))
  kbOptions.value = (kbRes.data || []).map((item) => ({ label: item.name, value: item.id }))
}

function getDocTypeName(id) {
  return docTypeOptions.value.find((o) => o.value === id)?.label || id
}

function getKbName(id) {
  return kbOptions.value.find((o) => o.value === id)?.label || id
}

async function handleRetry(row) {
  try {
    const res = await api.retryDocument({ document_id: row.id })
    if (res.code === 0) {
      $message?.success('已重新提交处理')
      $table.value?.handleSearch()
    } else {
      $message?.error(res.msg || '重试失败')
    }
  } catch {
    $message?.error('重试失败')
  }
}

onMounted(() => {
  loadOptions()
  $table.value?.handleSearch()
})

const columns = [
  {
    title: '标题',
    key: 'title',
    width: 200,
    align: 'center',
    ellipsis: { tooltip: true },
  },
  {
    title: '来源类型',
    key: 'source_type',
    width: 100,
    align: 'center',
    render(row) {
      const label = sourceTypeOptions.find((o) => o.value === row.source_type)?.label || row.source_type
      return h(NTag, { size: 'small' }, { default: () => label })
    },
  },
  {
    title: '文档类型',
    key: 'doc_type_id',
    width: 100,
    align: 'center',
    render(row) {
      return h('span', getDocTypeName(row.doc_type_id))
    },
  },
  {
    title: '知识库',
    key: 'knowledge_base_id',
    width: 120,
    align: 'center',
    render(row) {
      return h('span', getKbName(row.knowledge_base_id))
    },
  },
  {
    title: '状态',
    key: 'status',
    width: 100,
    align: 'center',
    render(row) {
      const label = statusOptions.find((o) => o.value === row.status)?.label || row.status
      return h(NTag, { type: statusColorMap[row.status] || 'default', size: 'small' }, { default: () => label })
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
    width: 220,
    align: 'center',
    fixed: 'right',
    render(row) {
      const buttons = [
        withDirectives(
          h(
            NButton,
            { size: 'small', type: 'primary', style: 'margin-right: 8px;', onClick: () => handleEdit(row) },
            { default: () => '编辑', icon: renderIcon('material-symbols:edit-outline', { size: 16 }) }
          ),
          [[vPermission, 'post/api/v1/document/update']]
        ),
        h(
          NPopconfirm,
          { onPositiveClick: () => handleDelete({ document_id: row.id }, false), onNegativeClick: () => {} },
          {
            trigger: () =>
              withDirectives(
                h(
                  NButton,
                  { size: 'small', type: 'error', style: 'margin-right: 8px;' },
                  { default: () => '删除', icon: renderIcon('material-symbols:delete-outline', { size: 16 }) }
                ),
                [[vPermission, 'delete/api/v1/document/delete']]
              ),
            default: () => h('div', {}, '确定删除该文档吗?'),
          }
        ),
      ]
      if (row.status === 'failed') {
        buttons.push(
          withDirectives(
            h(
              NButton,
              { size: 'small', type: 'warning', onClick: () => handleRetry(row) },
              { default: () => '重试', icon: renderIcon('material-symbols:refresh', { size: 16 }) }
            ),
            [[vPermission, 'post/api/v1/document/retry']]
          )
        )
      }
      return buttons
    },
  },
]
</script>

<template>
  <CommonPage show-footer title="文档管理">
    <template #action>
      <NButton v-permission="'post/api/v1/document/create'" type="primary" @click="handleAdd">
        <TheIcon icon="material-symbols:add" :size="18" class="mr-5" />新建文档
      </NButton>
    </template>

    <CrudTable
      ref="$table"
      v-model:query-items="queryItems"
      :columns="columns"
      :get-data="api.getDocumentList"
    >
      <template #queryBar>
        <QueryBarItem label="标题" :label-width="40">
          <NInput
            v-model:value="queryItems.title"
            clearable
            type="text"
            placeholder="请输入标题"
            @keypress.enter="$table?.handleSearch()"
          />
        </QueryBarItem>
        <QueryBarItem label="状态" :label-width="40">
          <NSelect
            v-model:value="queryItems.status"
            clearable
            :options="statusOptions"
            placeholder="请选择状态"
          />
        </QueryBarItem>
        <QueryBarItem label="知识库" :label-width="50">
          <NSelect
            v-model:value="queryItems.knowledge_base_id"
            clearable
            :options="kbOptions"
            placeholder="请选择知识库"
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
        <NFormItem label="标题" path="title" :rule="{ required: true, message: '请输入标题', trigger: ['input', 'blur'] }">
          <NInput v-model:value="modalForm.title" placeholder="请输入文档标题" />
        </NFormItem>
        <NFormItem label="来源类型" path="source_type" :rule="{ required: true, message: '请选择来源类型', trigger: ['change', 'blur'] }">
          <NSelect v-model:value="modalForm.source_type" :options="sourceTypeOptions" placeholder="请选择来源类型" />
        </NFormItem>
        <NFormItem label="文档类型" path="doc_type_id" :rule="{ required: true, type: 'number', message: '请选择文档类型', trigger: ['change', 'blur'] }">
          <NSelect v-model:value="modalForm.doc_type_id" :options="docTypeOptions" placeholder="请选择文档类型" />
        </NFormItem>
        <NFormItem label="知识库" path="knowledge_base_id" :rule="{ required: true, type: 'number', message: '请选择知识库', trigger: ['change', 'blur'] }">
          <NSelect v-model:value="modalForm.knowledge_base_id" :options="kbOptions" placeholder="请选择知识库" />
        </NFormItem>
        <NFormItem label="来源元数据" path="source_meta">
          <NInput v-model:value="modalForm.source_meta" type="textarea" placeholder="JSON格式的来源元数据 (可选)" :rows="3" />
        </NFormItem>
      </NForm>
    </CrudModal>
  </CommonPage>
</template>
