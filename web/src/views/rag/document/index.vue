<script setup>
import { computed, h, nextTick, onMounted, ref, resolveDirective, withDirectives } from 'vue'
import {
  NButton,
  NDrawer,
  NDrawerContent,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NPopconfirm,
  NSelect,
  NSpin,
  NTag,
} from 'naive-ui'
import { useRoute, useRouter } from 'vue-router'
import Vditor from 'vditor'
import 'vditor/dist/index.css'

import CommonPage from '@/components/page/CommonPage.vue'
import QueryBarItem from '@/components/query-bar/QueryBarItem.vue'
import CrudModal from '@/components/table/CrudModal.vue'
import CrudTable from '@/components/table/CrudTable.vue'

import { formatDate, renderIcon } from '@/utils'
import { useCRUD } from '@/composables'
import api from '@/api'

defineOptions({ name: '文档管理' })

const route = useRoute()
const router = useRouter()

const $table = ref(null)
const queryItems = ref({})
const vPermission = resolveDirective('permission')

const docTypeOptions = ref([])
const kbOptions = ref([])

// Content drawer state
const contentDrawerVisible = ref(false)
const contentDoc = ref(null)
const contentText = ref('')
const contentLoading = ref(false)
const contentSaving = ref(false)
const vditorContainer = ref(null)
const previewContainer = ref(null)
let vditorInstance = null

// 判断是否为飞书文档
const isFeishuDoc = computed(() => contentDoc.value?.source_type === 'feishu_doc')

// 飞书文档可编辑，或状态为 rejected 时可编辑
const isContentEditable = computed(
  () => isFeishuDoc.value || contentDoc.value?.status === 'rejected'
)

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
  handleEdit: rawHandleEdit,
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
      doc_type_id: data.doc_type_id,
      knowledge_base_id: data.knowledge_base_id,
      source_meta: buildSourceMeta(data),
    }
    return api.createDocument(payload)
  },
  doDelete: api.deleteDocument,
  doUpdate: (data) => {
    const payload = {
      id: data.id,
      title: data.title,
      doc_type_id: data.doc_type_id,
      knowledge_base_id: data.knowledge_base_id,
    }
    return api.updateDocument(payload)
  },
  refresh: () => $table.value?.handleSearch(),
})

function handleEdit(row) {
  rawHandleEdit(row)
  const meta = row.source_meta || {}
  modalForm.value.feishu_url = meta.feishu_url || ''
  modalForm.value.web_url = meta.url || ''
}

function handleUploadClick() {
  $message?.warning('暂不支持上传文档')
}

async function openContentDrawer(row) {
  contentDrawerVisible.value = true
  contentLoading.value = true
  contentDoc.value = null
  contentText.value = ''
  // 销毁之前的 vditor 实例
  if (vditorInstance) {
    vditorInstance.destroy()
    vditorInstance = null
  }
  try {
    const res = await api.getDocument({ document_id: row.id })
    contentDoc.value = res.data
    contentText.value = res.data?.content || ''
    // 如果是飞书文档且可编辑，初始化 vditor
    if (isFeishuDoc.value && isContentEditable.value) {
      nextTick(() => {
        initVditor()
      })
    }
    // 如果是飞书文档但不可编辑，渲染预览
    if (isFeishuDoc.value && !isContentEditable.value && contentText.value) {
      nextTick(() => {
        if (previewContainer.value) {
          Vditor.preview(previewContainer.value, contentText.value, {
            mode: 'light',
            theme: { current: 'light' },
          })
        }
      })
    }
  } catch {
    $message?.error('获取文档内容失败')
    contentDrawerVisible.value = false
  } finally {
    contentLoading.value = false
  }
}

function initVditor() {
  if (!vditorContainer.value) return
  vditorInstance = new Vditor(vditorContainer.value, {
    height: 500,
    mode: 'ir', // 即时渲染模式（所见即所得）
    value: contentText.value,
    placeholder: '请输入 Markdown 内容...',
    toolbar: [
      'headings',
      'bold',
      'italic',
      'strike',
      '|',
      'line',
      'quote',
      'list',
      'ordered-list',
      'check',
      '|',
      'code',
      'inline-code',
      'insert-before',
      'insert-after',
      '|',
      'upload',
      'link',
      'table',
      '|',
      'undo',
      'redo',
      '|',
      'fullscreen',
      'preview',
      'help',
    ],
    toolbarConfig: {
      pin: true,
    },
    cache: {
      enable: false,
    },
    after: () => {
      // 编辑器初始化完成
    },
    input: (value) => {
      contentText.value = value
    },
  })
}

async function handleSaveContent() {
  if (!contentDoc.value) return
  // 如果是 vditor 编辑器，获取最新内容
  if (vditorInstance && isFeishuDoc.value) {
    contentText.value = vditorInstance.getValue()
  }
  contentSaving.value = true
  try {
    const res = await api.updateDocumentContent({
      id: contentDoc.value.id,
      content: contentText.value,
    })
    if (res.code === 0) {
      $message?.success('内容已更新，已重新提交审核')
      contentDrawerVisible.value = false
      $table.value?.handleSearch()
    } else {
      $message?.error(res.msg || '保存失败')
    }
  } catch {
    $message?.error('保存失败')
  } finally {
    contentSaving.value = false
  }
}

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
  const editDocId = route.query.edit_doc_id
  if (editDocId) {
    openContentDrawer({ id: Number(editDocId) })
    router.replace({ query: {} })
  }
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
    width: 280,
    align: 'center',
    fixed: 'right',
    render(row) {
      const buttons = [
        h(
          NButton,
          {
            size: 'small',
            type: 'info',
            style: 'margin-right: 8px;',
            onClick: () => openContentDrawer(row),
          },
          {
            default: () => '查看',
            icon: renderIcon('material-symbols:visibility-outline', { size: 16 }),
          }
        ),
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
          [[vPermission, 'post/api/v1/document/update']]
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
                  { size: 'small', type: 'error', style: 'margin-right: 8px;' },
                  {
                    default: () => '删除',
                    icon: renderIcon('material-symbols:delete-outline', { size: 16 }),
                  }
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
            :disabled="modalAction === 'edit'"
          />
        </NFormItem>
        <NFormItem
          v-if="modalAction === 'add' && modalForm.source_type === 'feishu_doc'"
          label="飞书文档链接"
          path="feishu_url"
          :rule="{ required: true, message: '请输入飞书文档链接', trigger: ['input', 'blur'] }"
        >
          <NInput v-model:value="modalForm.feishu_url" placeholder="请输入飞书云文档URL" />
        </NFormItem>
        <NFormItem
          v-if="modalAction === 'add' && modalForm.source_type === 'web_url'"
          label="网页地址"
          path="web_url"
          :rule="{ required: true, message: '请输入网页地址', trigger: ['input', 'blur'] }"
        >
          <NInput v-model:value="modalForm.web_url" placeholder="请输入网页URL" />
        </NFormItem>
        <NFormItem
          v-if="modalAction === 'add' && modalForm.source_type === 'file_upload'"
          label="上传文件"
        >
          <NButton @click="handleUploadClick">选择文件</NButton>
        </NFormItem>
        <NFormItem
          label="文档类型"
          path="doc_type_id"
          :rule="{
            required: true,
            type: 'number',
            message: '请选择文档类型',
            trigger: ['change', 'blur'],
          }"
        >
          <NSelect
            v-model:value="modalForm.doc_type_id"
            :options="docTypeOptions"
            placeholder="请选择文档类型"
          />
        </NFormItem>
        <NFormItem
          label="知识库"
          path="knowledge_base_id"
          :rule="{
            required: true,
            type: 'number',
            message: '请选择知识库',
            trigger: ['change', 'blur'],
          }"
        >
          <NSelect
            v-model:value="modalForm.knowledge_base_id"
            :options="kbOptions"
            placeholder="请选择知识库"
          />
        </NFormItem>
      </NForm>
    </CrudModal>

    <!-- Content View/Edit Drawer -->
    <NDrawer v-model:show="contentDrawerVisible" placement="right" :width="800">
      <NDrawerContent :title="contentDoc ? `文档内容 - ${contentDoc.title}` : '文档内容'">
        <NSpin :show="contentLoading">
          <template v-if="contentDoc">
            <div style="margin-bottom: 12px; display: flex; align-items: center; gap: 8px">
              <NTag :type="statusColorMap[contentDoc.status] || 'default'" size="small">
                {{
                  statusOptions.find((o) => o.value === contentDoc.status)?.label ||
                  contentDoc.status
                }}
              </NTag>
              <NTag v-if="isFeishuDoc" type="info" size="small">飞书文档</NTag>
              <span v-if="isContentEditable" style="color: #f0a020; font-size: 13px"
                >可编辑 - 保存后将重新提交审核</span
              >
              <span v-else style="color: #999; font-size: 13px">只读</span>
            </div>

            <!-- 飞书文档使用 Vditor 编辑器 -->
            <template v-if="isFeishuDoc">
              <!-- 编辑模式：所见即所得 -->
              <div v-if="isContentEditable" ref="vditorContainer" style="min-height: 500px" />
              <!-- 预览模式 -->
              <div v-else-if="contentDoc.content" ref="previewContainer" class="vditor-preview" />
              <NEmpty v-else description="暂无文档内容" style="margin-top: 40px" />
            </template>

            <!-- 非飞书文档使用普通文本框 -->
            <template v-else>
              <NInput
                v-if="contentDoc.content || isContentEditable"
                v-model:value="contentText"
                type="textarea"
                :rows="20"
                :disabled="!isContentEditable"
                placeholder="暂无文档内容"
                style="font-family: monospace"
              />
              <NEmpty v-else description="暂无文档内容" style="margin-top: 40px" />
            </template>
          </template>
        </NSpin>
        <template #footer>
          <NButton
            v-if="isContentEditable"
            v-permission="'post/api/v1/document/update_content'"
            type="primary"
            :loading="contentSaving"
            :disabled="!contentText.trim()"
            @click="handleSaveContent"
          >
            保存并提审
          </NButton>
        </template>
      </NDrawerContent>
    </NDrawer>
  </CommonPage>
</template>
