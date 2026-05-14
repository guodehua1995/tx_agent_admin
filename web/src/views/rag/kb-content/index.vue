<script setup>
import { h, onMounted, ref, resolveDirective, withDirectives } from 'vue'
import { NButton, NForm, NFormItem, NInput, NPopconfirm, NSelect, NTag } from 'naive-ui'
import { useRoute, useRouter } from 'vue-router'

import CommonPage from '@/components/page/CommonPage.vue'
import QueryBarItem from '@/components/query-bar/QueryBarItem.vue'
import CrudModal from '@/components/table/CrudModal.vue'
import CrudTable from '@/components/table/CrudTable.vue'

import { formatDate, renderIcon } from '@/utils'
import { useCRUD } from '@/composables'
import api from '@/api'

defineOptions({ name: '知识库内容' })

const route = useRoute()
const router = useRouter()

const kbId = ref(Number(route.query.kb_id) || 0)
const kbName = ref('')
const $table = ref(null)
const queryItems = ref({})
const vPermission = resolveDirective('permission')

const docTypeOptions = ref([])

function buildSourceMeta(form) {
  if (form.source_type === 'feishu_doc') return { feishu_url: form.feishu_url || '' }
  if (form.source_type === 'web_url') return { url: form.web_url || '' }
  return {}
}

const {
  modalVisible,
  modalAction,
  modalTitle,
  modalLoading,
  handleAdd,
  handleDelete,
  handleSave,
  modalForm,
  modalFormRef,
} = useCRUD({
  name: '文档',
  initForm: { feishu_url: '', web_url: '' },
  doCreate: (data) => {
    const payload = {
      title: data.title,
      source_type: data.source_type,
      doc_type_code: data.doc_type_code,
      knowledge_base_id: kbId.value,
      source_meta: buildSourceMeta(data),
    }
    return api.createKBContentDoc(payload)
  },
  doDelete: api.deleteKBContentDoc,
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

function getDocTypeName(code) {
  return docTypeOptions.value.find((o) => o.value === code)?.label || code
}

async function loadOptions() {
  const typeRes = await api.getDocumentTypeList()
  docTypeOptions.value = (typeRes.data || []).map((item) => ({
    label: item.name,
    value: item.code,
  }))
}

async function loadKbInfo() {
  if (!kbId.value) return
  try {
    const res = await api.getKnowledgeBase({ kb_id: kbId.value })
    kbName.value = res.data?.name || ''
  } catch {
    kbName.value = ''
  }
}

function getListData(params) {
  return api.getKBContentList({ ...params, kb_id: kbId.value })
}

function goBack() {
  router.push('/rag-knowledge/knowledge-base')
}

function goToChunks(row) {
  router.push({ path: '/rag-knowledge/doc-content', query: { doc_id: row.id, kb_id: kbId.value } })
}

onMounted(() => {
  if (!kbId.value) {
    $message?.error('缺少知识库ID参数')
    goBack()
    return
  }
  loadKbInfo()
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
      const label =
        sourceTypeOptions.find((o) => o.value === row.source_type)?.label || row.source_type
      return h(NTag, { size: 'small' }, { default: () => label })
    },
  },
  {
    title: '文档类型',
    key: 'doc_type_code',
    width: 100,
    align: 'center',
    render(row) {
      return h('span', getDocTypeName(row.doc_type_code))
    },
  },
  {
    title: '状态',
    key: 'status',
    width: 100,
    align: 'center',
    render(row) {
      const label = statusOptions.find((o) => o.value === row.status)?.label || row.status
      return h(
        NTag,
        { type: statusColorMap[row.status] || 'default', size: 'small' },
        { default: () => label }
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
    width: 200,
    align: 'center',
    fixed: 'right',
    render(row) {
      return [
        h(
          NButton,
          {
            size: 'small',
            type: 'info',
            style: 'margin-right: 8px;',
            onClick: () => goToChunks(row),
            disabled: row.status !== 'completed',
          },
          {
            default: () => '查看分片',
            icon: renderIcon('material-symbols:list-alt-outline', { size: 16 }),
          }
        ),
        h(
          NPopconfirm,
          {
            onPositiveClick: () => handleDelete({ document_id: row.id }, false),
            onNegativeClick: () => {},
          },
          {
            trigger: () =>
              withDirectives(
                h(
                  NButton,
                  { size: 'small', type: 'error' },
                  {
                    default: () => '删除',
                    icon: renderIcon('material-symbols:delete-outline', { size: 16 }),
                  }
                ),
                [[vPermission, 'delete/api/v1/kb_content/delete']]
              ),
            default: () => h('div', {}, '确定删除该文档吗？关联的向量数据也将被清除。'),
          }
        ),
      ]
    },
  },
]
</script>

<template>
  <CommonPage show-footer :title="`知识库内容 - ${kbName || '加载中...'}`">
    <template #action>
      <NButton quaternary style="margin-right: 12px" @click="goBack">
        <TheIcon icon="material-symbols:arrow-back" :size="18" class="mr-5" />返回
      </NButton>
      <NButton v-permission="'post/api/v1/kb_content/create'" type="primary" @click="handleAdd">
        <TheIcon icon="material-symbols:add" :size="18" class="mr-5" />新建文档
      </NButton>
    </template>

    <CrudTable
      ref="$table"
      v-model:query-items="queryItems"
      :columns="columns"
      :get-data="getListData"
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
          label="标题"
          path="title"
          :rule="{ required: true, message: '请输入标题', trigger: ['input', 'blur'] }"
        >
          <NInput v-model:value="modalForm.title" placeholder="请输入文档标题" />
        </NFormItem>
        <NFormItem
          label="来源类型"
          path="source_type"
          :rule="{ required: true, message: '请选择来源类型', trigger: ['change', 'blur'] }"
        >
          <NSelect
            v-model:value="modalForm.source_type"
            :options="sourceTypeOptions"
            placeholder="请选择来源类型"
          />
        </NFormItem>
        <NFormItem
          v-if="modalForm.source_type === 'feishu_doc'"
          label="飞书文档链接"
          path="feishu_url"
          :rule="{ required: true, message: '请输入飞书文档链接', trigger: ['input', 'blur'] }"
        >
          <NInput v-model:value="modalForm.feishu_url" placeholder="请输入飞书云文档URL" />
        </NFormItem>
        <NFormItem
          v-if="modalForm.source_type === 'web_url'"
          label="网页地址"
          path="web_url"
          :rule="{ required: true, message: '请输入网页地址', trigger: ['input', 'blur'] }"
        >
          <NInput v-model:value="modalForm.web_url" placeholder="请输入网页URL" />
        </NFormItem>
        <NFormItem
          label="文档类型"
          path="doc_type_code"
          :rule="{ required: true, message: '请选择文档类型', trigger: ['change', 'blur'] }"
        >
          <NSelect
            v-model:value="modalForm.doc_type_code"
            :options="docTypeOptions"
            placeholder="请选择文档类型"
          />
        </NFormItem>
      </NForm>
    </CrudModal>
  </CommonPage>
</template>
