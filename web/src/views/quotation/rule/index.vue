<script setup>
import { h, onMounted, ref, resolveDirective, withDirectives } from 'vue'
import {
  NButton,
  NDrawer,
  NDrawerContent,
  NFormItem,
  NPopconfirm,
  NSelect,
  NSpace,
  NTag,
} from 'naive-ui'

import CommonPage from '@/components/page/CommonPage.vue'
import QueryBarItem from '@/components/query-bar/QueryBarItem.vue'
import CrudTable from '@/components/table/CrudTable.vue'

import RuleItemEditor from './RuleItemEditor.vue'
import RuleDetailDrawer from './RuleDetailDrawer.vue'
import ExcelImportDrawer from './ExcelImportDrawer.vue'

import { formatDate, renderIcon } from '@/utils'
import api from '@/api'

defineOptions({ name: '报价规则管理' })

const $table = ref(null)
const queryItems = ref({})
const vPermission = resolveDirective('permission')

// ── 甲方选项 ──
const clientOptions = ref([])
async function loadClients(keyword = '') {
  const res = await api.getClientList({ keyword, page: 1, page_size: 100 })
  clientOptions.value = (res.data || []).map((c) => ({
    label: c.name,
    value: c.id,
  }))
}

// ── 状态映射 ──
const statusColorMap = {
  draft: 'default',
  pending_approval: 'warning',
  active: 'success',
  expired: 'error',
  archived: 'info',
}
const statusLabelMap = {
  draft: '草稿',
  pending_approval: '待审批',
  active: '生效中',
  expired: '已失效',
  archived: '已归档',
}
const statusOptions = [
  { label: '全部', value: '' },
  { label: '草稿', value: 'draft' },
  { label: '待审批', value: 'pending_approval' },
  { label: '生效中', value: 'active' },
  { label: '已失效', value: 'expired' },
]

// ── 详情/审批 Drawer ──
const detailVisible = ref(false)
const detailRule = ref(null)
const detailMode = ref('view')

function openDetail(row, mode = 'view') {
  detailRule.value = row
  detailMode.value = mode
  detailVisible.value = true
}

// ── 新增方式选择 ──
const methodVisible = ref(false)

// ── 手动录入 Drawer（三模式：create / edit_draft / new_version）──
const manualVisible = ref(false)
const manualMode = ref('create') // 'create' | 'edit_draft' | 'new_version'
const manualClientId = ref(null)
const manualClientReadonly = ref(false)
const manualItems = ref([])
const manualLoading = ref(false)
const editRuleId = ref(null)
const sourceRuleId = ref(null)

const manualDrawerTitle = computed(() => {
  if (manualMode.value === 'edit_draft') return '编辑报价规则（草稿）'
  if (manualMode.value === 'new_version') return '派生新版本报价规则'
  return '新增报价规则（手动录入）'
})

function openManual() {
  methodVisible.value = false
  manualMode.value = 'create'
  manualClientId.value = null
  manualClientReadonly.value = false
  manualItems.value = []
  editRuleId.value = null
  sourceRuleId.value = null
  manualVisible.value = true
}

async function openEditDraft(row) {
  manualMode.value = 'edit_draft'
  manualLoading.value = true
  try {
    const res = await api.getRuleDetail({ rule_id: row.id })
    manualClientId.value = row.client_id
    manualClientReadonly.value = true
    manualItems.value = res.data?.items || []
    editRuleId.value = row.id
    sourceRuleId.value = null
    manualVisible.value = true
  } finally {
    manualLoading.value = false
  }
}

async function openEditNewVersion(row) {
  manualMode.value = 'new_version'
  manualLoading.value = true
  try {
    const res = await api.getRuleDetail({ rule_id: row.id })
    manualClientId.value = row.client_id
    manualClientReadonly.value = true
    manualItems.value = res.data?.items || []
    editRuleId.value = null
    sourceRuleId.value = row.id
    manualVisible.value = true
  } finally {
    manualLoading.value = false
  }
}

async function handleManualSave() {
  if (manualMode.value === 'create') {
    if (!manualClientId.value) {
      $message.warning('请选择甲方')
      return
    }
  }
  if (!manualItems.value.length) {
    $message.warning('请至少添加一个项目')
    return
  }
  try {
    manualLoading.value = true
    if (manualMode.value === 'create') {
      await api.createRule({
        client_id: manualClientId.value,
        source_type: 'manual',
        items: manualItems.value,
      })
      $message.success('创建成功')
    } else if (manualMode.value === 'edit_draft') {
      await api.editDraft({
        rule_id: editRuleId.value,
        items: manualItems.value,
      })
      $message.success('编辑成功')
    } else if (manualMode.value === 'new_version') {
      await api.editNewVersion({
        source_rule_id: sourceRuleId.value,
        source_type: 'manual',
        items: manualItems.value,
      })
      $message.success('已派生新版本')
    }
    manualVisible.value = false
    $table.value?.handleSearch()
  } finally {
    manualLoading.value = false
  }
}

// ── Excel 导入 Drawer ──
const excelVisible = ref(false)
function openExcel() {
  methodVisible.value = false
  excelVisible.value = true
}

// ── 提交审批 ──
async function handleSubmit(row) {
  try {
    await api.submitRule({ rule_id: row.id })
    $message.success('已提交审批')
    $table.value?.handleSearch()
  } catch (e) {
    // error handled by interceptor
  }
}

// ── 取消 ──
async function handleCancel(row) {
  try {
    await api.cancelRule({ rule_id: row.id })
    $message.success('已取消')
    $table.value?.handleSearch()
  } catch (e) {
    // noop
  }
}

// ── 删除 ──
async function handleDelete(row) {
  try {
    await api.deleteRule({ id: row.id })
    $message.success('已删除')
    $table.value?.handleSearch()
  } catch (e) {
    // noop
  }
}

onMounted(() => {
  loadClients()
  $table.value?.handleSearch()
})

// ── 表格列 ──
const columns = [
  {
    title: '甲方',
    key: 'client_name',
    width: 180,
    align: 'center',
    ellipsis: { tooltip: true },
  },
  {
    title: '版本',
    key: 'version',
    width: 60,
    align: 'center',
    render(row) {
      return h('span', `v${row.version}`)
    },
  },
  {
    title: '状态',
    key: 'status',
    width: 100,
    align: 'center',
    render(row) {
      return h(
        NTag,
        { type: statusColorMap[row.status] || 'default', size: 'small' },
        { default: () => statusLabelMap[row.status] || row.status }
      )
    },
  },
  {
    title: '来源',
    key: 'source_type',
    width: 100,
    align: 'center',
    render(row) {
      return h('span', row.source_type === 'excel_import' ? 'Excel导入' : '手动录入')
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
    width: 300,
    align: 'center',
    fixed: 'right',
    render(row) {
      const buttons = []
      const btnStyle = 'margin-right: 6px;'

      // 详情 - 始终显示
      buttons.push(
        h(NButton, { size: 'small', type: 'info', style: btnStyle, onClick: () => openDetail(row, 'view') }, { default: () => '详情' })
      )

      if (row.status === 'draft') {
        // 编辑
        buttons.push(
          h(NButton, { size: 'small', type: 'primary', style: btnStyle, onClick: () => openEditDraft(row) }, { default: () => '编辑' })
        )
        // 删除
        buttons.push(
          h(NPopconfirm, { onPositiveClick: () => handleDelete(row) }, {
            trigger: () => h(NButton, { size: 'small', type: 'error', style: btnStyle }, { default: () => '删除' }),
            default: () => h('div', '确认删除该草稿？'),
          })
        )
        // 提交审批
        buttons.push(
          h(NPopconfirm, { onPositiveClick: () => handleSubmit(row) }, {
            trigger: () => h(NButton, { size: 'small', type: 'warning', style: btnStyle }, { default: () => '提交审批' }),
            default: () => h('div', '确认提交审批？'),
          })
        )
      }

      if (row.status === 'pending_approval') {
        // 审批
        buttons.push(
          withDirectives(
            h(NButton, { size: 'small', type: 'success', style: btnStyle, onClick: () => openDetail(row, 'approve') }, { default: () => '审批' }),
            [[vPermission, 'post/api/v1/quotation/approval/action']]
          )
        )
      }

      if (row.status === 'active') {
        // 编辑（派生新版本）
        buttons.push(
          h(NButton, { size: 'small', type: 'primary', style: btnStyle, onClick: () => openEditNewVersion(row) }, { default: () => '编辑' })
        )
        // 取消
        buttons.push(
          h(NPopconfirm, { onPositiveClick: () => handleCancel(row) }, {
            trigger: () => h(NButton, { size: 'small', type: 'warning', style: btnStyle }, { default: () => '取消' }),
            default: () => h('div', '确认取消该生效版本？取消后状态变为已失效。'),
          })
        )
      }

      if (row.status === 'expired') {
        // 编辑（派生新版本）
        buttons.push(
          h(NButton, { size: 'small', type: 'primary', style: btnStyle, onClick: () => openEditNewVersion(row) }, { default: () => '编辑' })
        )
      }

      return buttons
    },
  },
]
</script>

<template>
  <CommonPage show-footer title="报价规则管理">
    <template #action>
      <NButton type="primary" @click="methodVisible = true">
        <TheIcon icon="material-symbols:add" :size="18" class="mr-5" />新增规则
      </NButton>
    </template>

    <CrudTable
      ref="$table"
      v-model:query-items="queryItems"
      :columns="columns"
      :get-data="api.getRuleList"
    >
      <template #queryBar>
        <QueryBarItem label="甲方" :label-width="40">
          <NSelect
            v-model:value="queryItems.client_id"
            :options="clientOptions"
            filterable
            remote
            clearable
            placeholder="选择甲方"
            style="width: 200px"
            @search="loadClients"
          />
        </QueryBarItem>
        <QueryBarItem label="状态" :label-width="40">
          <NSelect
            v-model:value="queryItems.status"
            :options="statusOptions"
            clearable
            placeholder="选择状态"
            style="width: 140px"
          />
        </QueryBarItem>
      </template>
    </CrudTable>

    <!-- 方式选择弹窗 -->
    <n-modal v-model:show="methodVisible" preset="dialog" title="选择新增方式">
      <NSpace justify="center" style="padding: 20px 0">
        <NButton type="primary" size="large" @click="openManual">
          手动录入
        </NButton>
        <NButton type="info" size="large" @click="openExcel">
          Excel 导入
        </NButton>
      </NSpace>
    </n-modal>

    <!-- 手动录入/编辑 Drawer（三模式） -->
    <NDrawer :show="manualVisible" :width="720" @update:show="(v) => (manualVisible = v)">
      <NDrawerContent :title="manualDrawerTitle" closable>
        <NSpace vertical size="large">
          <NFormItem label="甲方" :show-feedback="false" label-placement="left">
            <NSelect
              v-model:value="manualClientId"
              :options="clientOptions"
              filterable
              remote
              :disabled="manualClientReadonly"
              placeholder="请选择甲方"
              style="width: 260px"
              @search="loadClients"
            />
          </NFormItem>
          <RuleItemEditor v-model:items="manualItems" />
        </NSpace>
        <template #footer>
          <NSpace>
            <NButton @click="manualVisible = false">取消</NButton>
            <NButton type="primary" :loading="manualLoading" @click="handleManualSave">
              保存
            </NButton>
          </NSpace>
        </template>
      </NDrawerContent>
    </NDrawer>

    <!-- Excel 导入 Drawer -->
    <ExcelImportDrawer
      v-model:visible="excelVisible"
      @refresh="$table?.handleSearch()"
    />

    <!-- 详情/审批 Drawer -->
    <RuleDetailDrawer
      v-model:visible="detailVisible"
      :rule="detailRule"
      :mode="detailMode"
      @refresh="$table?.handleSearch()"
    />
  </CommonPage>
</template>
