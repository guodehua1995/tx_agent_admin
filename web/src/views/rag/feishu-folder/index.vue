<script setup>
import { computed, h, onMounted, ref, resolveDirective, withDirectives } from 'vue'
import {
  NButton,
  NDataTable,
  NDrawer,
  NDrawerContent,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NPopconfirm,
  NSelect,
  NSpace,
  NSwitch,
  NTag,
} from 'naive-ui'

import CommonPage from '@/components/page/CommonPage.vue'
import CrudModal from '@/components/table/CrudModal.vue'
import CrudTable from '@/components/table/CrudTable.vue'
import QueryBarItem from '@/components/query-bar/QueryBarItem.vue'

import { formatDate, renderIcon } from '@/utils'
import { useCRUD } from '@/composables'
import api from '@/api'

defineOptions({ name: '飞书文件夹监听' })

const $table = ref(null)
const queryItems = ref({})
const vPermission = resolveDirective('permission')

const docTypeOptions = ref([])
const kbOptions = ref([])

const isActiveOptions = [
  { label: '启用', value: true },
  { label: '停用', value: false },
]

const ingestStatusMap = {
  pending: { label: '待处理', type: 'default' },
  ingested: { label: '已入库', type: 'success' },
  failed: { label: '失败', type: 'error' },
  skipped: { label: '跳过', type: 'warning' },
  feishu_deleted: { label: '飞书已删除', type: 'error' },
  cleaned: { label: '已清理', type: 'default' },
}

const docStatusMap = {
  pending_extract: { label: '待提取', type: 'default' },
  extracted: { label: '已提取', type: 'info' },
  pending_review: { label: '待审核', type: 'warning' },
  approved: { label: '已审核', type: 'info' },
  slicing: { label: '切片中', type: 'info' },
  vectorizing: { label: '向量化中', type: 'info' },
  completed: { label: '已完成', type: 'success' },
  rejected: { label: '已驳回', type: 'error' },
  failed: { label: '处理失败', type: 'error' },
}

const scanStatusMap = {
  running: { label: '扫描中', type: 'info' },
  success: { label: '成功', type: 'success' },
  failed: { label: '失败', type: 'error' },
}

// ========== CRUD ==========
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
  name: '文件夹监听',
  initForm: { is_active: true, scan_interval_seconds: 600, auto_approve: false, recursive_scan: false },
  doCreate: (data) => {
    const payload = {
      name: data.name,
      folder_url: data.folder_url,
      knowledge_base_id: data.knowledge_base_id,
      doc_type_code: data.doc_type_code,
      scan_interval_seconds: data.scan_interval_seconds || 600,
      auto_approve: data.auto_approve ?? false,
      recursive_scan: data.recursive_scan ?? false,
      is_active: data.is_active,
    }
    return api.createFeishuFolder(payload)
  },
  doDelete: api.deleteFeishuFolder,
  doUpdate: (data) => {
    const payload = {
      id: data.id,
      name: data.name,
      knowledge_base_id: data.knowledge_base_id,
      doc_type_code: data.doc_type_code,
      scan_interval_seconds: data.scan_interval_seconds,
      auto_approve: data.auto_approve,
      recursive_scan: data.recursive_scan,
      is_active: data.is_active,
    }
    return api.updateFeishuFolder(payload)
  },
  refresh: () => $table.value?.handleSearch(),
})

const isEdit = computed(() => modalAction.value === 'edit')

function handleEdit(row) {
  rawHandleEdit(row)
}

async function loadOptions() {
  const [typeRes, kbRes] = await Promise.all([
    api.getDocumentTypeList(),
    api.getKnowledgeBaseList({ page: 1, page_size: 9999 }),
  ])
  docTypeOptions.value = (typeRes.data || []).map((item) => ({ label: item.name, value: item.code }))
  kbOptions.value = (kbRes.data || []).map((item) => ({ label: item.name, value: item.id }))
}

function getDocTypeName(code) {
  return docTypeOptions.value.find((o) => o.value === code)?.label || code
}

function getKbName(id) {
  return kbOptions.value.find((o) => o.value === id)?.label || id
}

// ========== Toggle ==========
async function handleToggle(row) {
  try {
    await api.toggleFeishuFolder({ id: row.id, is_active: !row.is_active })
    $message.success(!row.is_active ? '已启用' : '已停用')
    $table.value?.handleSearch()
  } catch (e) {
    $message.error(e.message || '操作失败')
  }
}

// ========== 立即扫描 ==========
async function handleScanNow(row) {
  try {
    await api.scanFeishuFolderNow({ folder_id: row.id })
    $message.success('已加入扫描队列，稍后刷新查看结果')
  } catch (e) {
    $message.error(e.message || '扫描请求失败')
  }
}

// ========== 清理飞书已删除文件 ==========
async function handleCleanupFile(row) {
  try {
    await api.cleanupFeishuFolderFile({ folder_id: currentFolder.value.id, file_token: row.file_token })
    $message.success('清理完成')
    loadFiles()
  } catch (e) {
    $message.error(e.message || '清理失败')
  }
}

// ========== 文件清单 Drawer ==========
const filesDrawerVisible = ref(false)
const filesLoading = ref(false)
const currentFolder = ref(null)
const fileList = ref([])
const fileTotal = ref(0)
const filePage = ref(1)
const filePageSize = ref(20)
const fileStatusFilter = ref('')

const fileStatusOptions = [
  { label: '全部', value: '' },
  { label: '待处理', value: 'pending' },
  { label: '已入库', value: 'ingested' },
  { label: '失败', value: 'failed' },
  { label: '跳过', value: 'skipped' },
  { label: '飞书已删除', value: 'feishu_deleted' },
  { label: '已清理', value: 'cleaned' },
]

async function openFilesDrawer(row) {
  currentFolder.value = row
  filePage.value = 1
  fileStatusFilter.value = ''
  filesDrawerVisible.value = true
  await loadFiles()
}

async function loadFiles() {
  if (!currentFolder.value) return
  filesLoading.value = true
  try {
    const res = await api.getFeishuFolderFiles({
      folder_id: currentFolder.value.id,
      page: filePage.value,
      page_size: filePageSize.value,
      ingest_status: fileStatusFilter.value || '',
    })
    fileList.value = res.data || []
    fileTotal.value = res.total || 0
  } catch (e) {
    $message.error(e.message || '加载文件清单失败')
  } finally {
    filesLoading.value = false
  }
}

const filePagination = computed(() => ({
  page: filePage.value,
  pageSize: filePageSize.value,
  itemCount: fileTotal.value,
  showSizePicker: false,
  onChange: (p) => {
    filePage.value = p
    loadFiles()
  },
}))

const fileColumns = [
  { title: '文件名', key: 'file_name', ellipsis: { tooltip: true } },
  { title: '类型', key: 'file_type', width: 100, align: 'center' },
  {
    title: 'Token',
    key: 'file_token',
    width: 200,
    align: 'center',
    ellipsis: { tooltip: true },
  },
  {
    title: '入库状态',
    key: 'ingest_status',
    width: 100,
    align: 'center',
    render(row) {
      const s = ingestStatusMap[row.ingest_status] || { label: row.ingest_status, type: 'default' }
      return h(NTag, { type: s.type, size: 'small' }, { default: () => s.label })
    },
  },
  {
    title: '关联文档ID',
    key: 'document_id',
    width: 110,
    align: 'center',
    render(row) {
      return h('span', row.document_id || '-')
    },
  },
  {
    title: '文档处理状态',
    key: 'doc_status',
    width: 120,
    align: 'center',
    render(row) {
      if (!row.doc_status) return h('span', '-')
      const s = docStatusMap[row.doc_status] || { label: row.doc_status, type: 'default' }
      return h(NTag, { type: s.type, size: 'small' }, { default: () => s.label })
    },
  },
  {
    title: '错误信息',
    key: 'ingest_error',
    width: 220,
    ellipsis: { tooltip: true },
    render(row) {
      const err = row.ingest_error || row.doc_error_message
      return h('span', { style: 'color: #d03050;' }, err || '-')
    },
  },
  {
    title: '创建时间',
    key: 'created_at',
    width: 160,
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
    render(row) {
      if (row.ingest_status !== 'feishu_deleted') return h('span', '-')
      return h(
        NPopconfirm,
        { onPositiveClick: () => handleCleanupFile(row) },
        {
          trigger: () => h(
            NButton,
            { size: 'small', type: 'error', quaternary: true },
            { default: () => '清理', icon: renderIcon('material-symbols:delete-outline', { size: 16 }) }
          ),
          default: () => h('div', {}, `确定清理该文件？将删除关联文档及向量数据。`),
        }
      )
    },
  },
]

// ========== Table columns ==========
const columns = [
  {
    title: '名称',
    key: 'name',
    width: 160,
    align: 'center',
    ellipsis: { tooltip: true },
  },
  {
    title: '文件夹Token',
    key: 'folder_token',
    width: 180,
    align: 'center',
    ellipsis: { tooltip: true },
  },
  {
    title: '知识库',
    key: 'knowledge_base_id',
    width: 140,
    align: 'center',
    render(row) {
      return h('span', getKbName(row.knowledge_base_id))
    },
  },
  {
    title: '文档类型',
    key: 'doc_type_code',
    width: 100,
    align: 'center',
    render(row) {
      return h(
        NTag,
        { type: 'info', size: 'small' },
        { default: () => getDocTypeName(row.doc_type_code) }
      )
    },
  },
  {
    title: '扫描周期(秒)',
    key: 'scan_interval_seconds',
    width: 110,
    align: 'center',
  },
  {
    title: '自动审批',
    key: 'auto_approve',
    width: 90,
    align: 'center',
    render(row) {
      return h(NTag, { type: row.auto_approve ? 'success' : 'default', size: 'small' }, {
        default: () => row.auto_approve ? '是' : '否',
      })
    },
  },
  {
    title: '递归扫描',
    key: 'recursive_scan',
    width: 90,
    align: 'center',
    render(row) {
      return h(NTag, { type: row.recursive_scan ? 'info' : 'default', size: 'small' }, {
        default: () => row.recursive_scan ? '是' : '否',
      })
    },
  },
  {
    title: '上次扫描',
    key: 'last_scanned_at',
    width: 160,
    align: 'center',
    render(row) {
      return h('span', row.last_scanned_at ? formatDate(row.last_scanned_at) : '-')
    },
  },
  {
    title: '扫描状态',
    key: 'last_scan_status',
    width: 100,
    align: 'center',
    render(row) {
      if (!row.last_scan_status) return h('span', '-')
      const s = scanStatusMap[row.last_scan_status] || {
        label: row.last_scan_status,
        type: 'default',
      }
      return h(NTag, { type: s.type, size: 'small' }, { default: () => s.label })
    },
  },
  {
    title: '启用',
    key: 'is_active',
    width: 80,
    align: 'center',
    render(row) {
      return h(NSwitch, {
        value: row.is_active,
        size: 'small',
        onUpdateValue: () => handleToggle(row),
      })
    },
  },
  {
    title: '创建时间',
    key: 'created_at',
    width: 160,
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
      return [
        withDirectives(
          h(
            NButton,
            {
              size: 'small',
              type: 'primary',
              quaternary: true,
              onClick: () => handleScanNow(row),
            },
            {
              default: () => '扫描',
              icon: renderIcon('material-symbols:sync', { size: 16 }),
            }
          ),
          [[vPermission, 'post/api/v1/feishu_folder/scan_now']]
        ),
        h(
          NButton,
          {
            size: 'small',
            type: 'info',
            quaternary: true,
            onClick: () => openFilesDrawer(row),
          },
          {
            default: () => '文件',
            icon: renderIcon('carbon:document', { size: 16 }),
          }
        ),
        withDirectives(
          h(
            NButton,
            {
              size: 'small',
              type: 'primary',
              quaternary: true,
              onClick: () => handleEdit(row),
            },
            {
              default: () => '编辑',
              icon: renderIcon('material-symbols:edit-outline', { size: 16 }),
            }
          ),
          [[vPermission, 'post/api/v1/feishu_folder/update']]
        ),
        h(
          NPopconfirm,
          {
            onPositiveClick: () => handleDelete({ folder_id: row.id }, false),
          },
          {
            trigger: () =>
              withDirectives(
                h(
                  NButton,
                  { size: 'small', type: 'error', quaternary: true },
                  {
                    default: () => '删除',
                    icon: renderIcon('material-symbols:delete-outline', { size: 16 }),
                  }
                ),
                [[vPermission, 'delete/api/v1/feishu_folder/delete']]
              ),
            default: () => h('div', {}, `确定删除监听【${row.name}】吗?`),
          }
        ),
      ]
    },
  },
]

onMounted(() => {
  loadOptions()
  $table.value?.handleSearch()
})
</script>

<template>
  <CommonPage show-footer title="飞书文件夹监听">
    <template #action>
      <NButton
        v-permission="'post/api/v1/feishu_folder/create'"
        type="primary"
        @click="handleAdd"
      >
        <TheIcon icon="material-symbols:add" :size="18" class="mr-5" />新建监听
      </NButton>
    </template>

    <CrudTable
      ref="$table"
      v-model:query-items="queryItems"
      :scroll-x="1700"
      :columns="columns"
      :get-data="api.getFeishuFolderList"
    >
      <template #queryBar>
        <QueryBarItem label="名称" :label-width="50">
          <NInput
            v-model:value="queryItems.name"
            clearable
            placeholder="搜索名称"
            @keypress.enter="$table?.handleSearch()"
          />
        </QueryBarItem>
        <QueryBarItem label="知识库" :label-width="60">
          <NSelect
            v-model:value="queryItems.knowledge_base_id"
            :options="kbOptions"
            clearable
            placeholder="选择知识库"
            style="width: 180px"
            @update:value="$table?.handleSearch()"
          />
        </QueryBarItem>
        <QueryBarItem label="状态" :label-width="50">
          <NSelect
            v-model:value="queryItems.is_active"
            :options="isActiveOptions"
            clearable
            placeholder="启停状态"
            style="width: 120px"
            @update:value="$table?.handleSearch()"
          />
        </QueryBarItem>
      </template>
    </CrudTable>

    <!-- 新建/编辑表单 -->
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
        :label-width="110"
        :model="modalForm"
        :disabled="modalAction === 'view'"
      >
        <NFormItem
          label="名称"
          path="name"
          :rule="{ required: true, message: '请输入名称', trigger: ['input', 'blur'] }"
        >
          <NInput v-model:value="modalForm.name" placeholder="请输入文件夹显示名" />
        </NFormItem>
        <NFormItem
          v-if="!isEdit"
          label="飞书文件夹"
          path="folder_url"
          :rule="{
            required: true,
            message: '请输入飞书文件夹 URL 或 folder_token',
            trigger: ['input', 'blur'],
          }"
        >
          <NInput
            v-model:value="modalForm.folder_url"
            placeholder="https://xxx.feishu.cn/drive/folder/<token> 或 folder_token"
          />
        </NFormItem>
        <NFormItem
          v-else
          label="飞书文件夹"
        >
          <NInput
            :value="modalForm.folder_url || modalForm.folder_token"
            disabled
            placeholder="已绑定，不可修改"
          />
        </NFormItem>
        <NFormItem
          label="目标知识库"
          path="knowledge_base_id"
          :rule="{ required: true, type: 'number', message: '请选择知识库', trigger: ['change', 'blur'] }"
        >
          <NSelect
            v-model:value="modalForm.knowledge_base_id"
            :options="kbOptions"
            placeholder="请选择目标知识库"
          />
        </NFormItem>
        <NFormItem
          label="文档类型"
          path="doc_type_code"
          :rule="{ required: true, message: '请选择文档类型', trigger: ['change', 'blur'] }"
        >
          <NSelect
            v-model:value="modalForm.doc_type_code"
            :options="docTypeOptions"
            placeholder="请选择文档类型 (扫描入库时统一使用)"
          />
        </NFormItem>
        <NFormItem label="扫描周期(秒)" path="scan_interval_seconds">
          <NInputNumber
            v-model:value="modalForm.scan_interval_seconds"
            :min="60"
            :max="86400"
            placeholder="留空使用默认 600 秒"
            style="width: 100%"
          />
        </NFormItem>
        <NFormItem label="自动审批" path="auto_approve">
          <NSwitch v-model:value="modalForm.auto_approve" />
          <span style="margin-left: 8px; color: #999; font-size: 12px;">跳过人工审核，自动进入向量化</span>
        </NFormItem>
        <NFormItem label="递归扫描" path="recursive_scan">
          <NSwitch v-model:value="modalForm.recursive_scan" />
          <span style="margin-left: 8px; color: #999; font-size: 12px;">扫描子文件夹中的文件</span>
        </NFormItem>
        <NFormItem label="启用" path="is_active">
          <NSwitch v-model:value="modalForm.is_active" />
        </NFormItem>
      </NForm>
    </CrudModal>

    <!-- 文件清单 Drawer -->
    <NDrawer v-model:show="filesDrawerVisible" :width="900" placement="right">
      <NDrawerContent
        :title="`已扫描文件清单 - ${currentFolder?.name || ''}`"
        :native-scrollbar="false"
        closable
      >
        <NSpace vertical>
          <NSpace align="center">
            <span>状态过滤:</span>
            <NSelect
              v-model:value="fileStatusFilter"
              :options="fileStatusOptions"
              style="width: 160px"
              @update:value="
                () => {
                  filePage = 1
                  loadFiles()
                }
              "
            />
            <NButton size="small" @click="loadFiles">
              <TheIcon icon="material-symbols:refresh" :size="16" class="mr-5" />刷新
            </NButton>
            <span v-if="currentFolder?.last_error" style="color: #d03050;">
              上次错误: {{ currentFolder.last_error }}
            </span>
          </NSpace>

          <NDataTable
            remote
            :columns="fileColumns"
            :data="fileList"
            :loading="filesLoading"
            :pagination="filePagination"
            :scroll-x="1100"
          />
        </NSpace>
      </NDrawerContent>
    </NDrawer>
  </CommonPage>
</template>
