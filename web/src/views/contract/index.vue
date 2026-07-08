<script setup>
import { h, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NButton,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NPopconfirm,
  NSelect,
  NTag,
  NDatePicker,
  useMessage,
} from 'naive-ui'

import CommonPage from '@/components/page/CommonPage.vue'
import QueryBarItem from '@/components/query-bar/QueryBarItem.vue'
import CrudModal from '@/components/table/CrudModal.vue'
import CrudTable from '@/components/table/CrudTable.vue'

import { formatDate, renderIcon } from '@/utils'
import { useCRUD } from '@/composables'
import api from '@/api'

defineOptions({ name: '合同管理' })

const router = useRouter()
const $table = ref(null)
const queryItems = ref({})
const message = useMessage()

const contractTypeOptions = ref([])
const clientOptions = ref([])

// ── 多选删除 ──────────────────────────────────────────────────

const checkedRowKeys = ref([])
const batchDeleteLoading = ref(false)

async function handleBatchDelete() {
  batchDeleteLoading.value = true
  try {
    let count = 0
    for (const id of checkedRowKeys.value) {
      try {
        await api.deleteContract({ id })
        count++
      } catch {
        // 单条失败继续
      }
    }
    message.success(`已删除 ${count} 条合同`)
    checkedRowKeys.value = []
    $table.value?.handleSearch()
  } finally {
    batchDeleteLoading.value = false
  }
}

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
  name: '合同',
  initForm: {},
  doCreate: () => Promise.resolve(),
  doDelete: api.deleteContract,
  doUpdate: api.updateContract,
  refresh: () => $table.value?.handleSearch(),
})

function handleView(row) {
  router.push({ name: '合同详情', query: { contract_id: row.id } })
}

// ── 审查相关 ──────────────────────────────────────────────────────

async function handleTriggerReview(row) {
  try {
    const res = await api.triggerContractReview({ contract_id: row.id })
    if (res.code === 200) {
      message.success(res.data?.message || '已加入审查队列')
      $table.value?.handleSearch()
    } else {
      message.warning(res.msg || '触发失败')
    }
  } catch (e) {
    message.error('触发审查失败')
  }
}

async function handleViewReview(row) {
  try {
    const res = await api.getReviewResult({ contract_id: row.id })
    if (res.code === 200) {
      const data = res.data
      if (data.status === 'completed' && data.feishu_doc_url) {
        window.open(data.feishu_doc_url, '_blank')
      } else if (data.status === 'pending' || data.status === 'analyzing') {
        message.info('审查任务正在处理中，请稍后再查看')
      } else if (data.status === 'failed') {
        message.error(`审查失败：${data.error_message || '未知错误'}`)
      } else if (data.status === 'completed' && !data.feishu_doc_url) {
        message.warning('审查已完成但暂无飞书文档链接')
      } else {
        message.warning('暂无审查结果')
      }
    } else {
      message.warning(res.msg || '查询审查结果失败')
    }
  } catch (e) {
    message.error('查询审查结果失败')
  }
}

async function loadOptions() {
  const [typeRes, clientRes] = await Promise.all([
    api.getContractTypeList(),
    api.getClientList({ page: 1, page_size: 9999 }),
  ])
  contractTypeOptions.value = (typeRes.data || []).map((item) => ({
    label: item.name,
    value: item.id,
  }))
  clientOptions.value = (clientRes.data || []).map((item) => ({
    label: item.name,
    value: item.id,
  }))
}

function getContractTypeName(id) {
  return contractTypeOptions.value.find((o) => o.value === id)?.label || '未知'
}

function getClientName(id) {
  return clientOptions.value.find((o) => o.value === id)?.label || '未知'
}

onMounted(() => {
  loadOptions()
  $table.value?.handleSearch()
})

const columns = [
  {
    type: 'selection',
    width: 40,
    align: 'center',
  },
  {
    title: '合同名称',
    key: 'project_name',
    width: 240,
    align: 'center',
    ellipsis: { tooltip: true },
    render(row) {
      const rawName = row.project_name || row.document_title || '-'
      const maxLen = 12
      const displayName = rawName.length > maxLen ? rawName.substring(0, maxLen) + '...' : rawName
      const children = []
      if (row.document_url) {
        children.push(
          h(
            NButton,
            {
              text: true,
              style: 'margin-right: 2px;',
              onClick: () => window.open(row.document_url, '_blank'),
            },
            {
              icon: renderIcon('material-symbols:open-in-new', { size: 14 }),
            }
          )
        )
      }
      children.push(
        h(
          NButton,
          {
            text: true,
            type: 'primary',
            onClick: () => handleView(row),
          },
          { default: () => displayName }
        )
      )
      return children
    },
  },
  {
    title: '甲方',
    key: 'party_a_name',
    width: 140,
    align: 'center',
    ellipsis: { tooltip: true },
    render(row) {
      return h('span', row.party_a_name || '-')
    },
  },
  {
    title: '乙方',
    key: 'party_b_name',
    width: 140,
    align: 'center',
    ellipsis: { tooltip: true },
    render(row) {
      return h('span', row.party_b_name || '-')
    },
  },
  {
    title: '合同类型',
    key: 'contract_type_name',
    width: 120,
    align: 'center',
    render(row) {
      return h(
        NTag,
        { type: 'info', size: 'small' },
        { default: () => row.contract_type_name || '未分类' }
      )
    },
  },
  {
    title: '签订日期',
    key: 'signing_date',
    width: 120,
    align: 'center',
    render(row) {
      return h('span', row.signing_date ? formatDate(row.signing_date) : '-')
    },
  },
  {
    title: '到期日期',
    key: 'expiry_date',
    width: 120,
    align: 'center',
    render(row) {
      if (!row.expiry_date) return h('span', '-')
      const exp = new Date(row.expiry_date)
      const now = new Date()
      const diffDays = Math.ceil((exp - now) / (1000 * 60 * 60 * 24))
      const type = diffDays < 0 ? 'error' : diffDays < 30 ? 'warning' : 'default'
      return h(NTag, { type, size: 'small' }, { default: () => formatDate(row.expiry_date) })
    },
  },
  {
    title: '金额',
    key: 'total_amount',
    width: 120,
    align: 'center',
    render(row) {
      if (row.total_amount == null) return h('span', '-')
      return h('span', Number(row.total_amount).toLocaleString())
    },
  },
  {
    title: '条款数',
    key: 'clause_count',
    width: 80,
    align: 'center',
    render(row) {
      return h('span', row.clause_count || 0)
    },
  },
  {
    title: '操作',
    key: 'actions',
    width: 180,
    align: 'center',
    fixed: 'right',
    render(row) {
      const hasReview = !!row.review_status
      return [
        h(
          NButton,
          {
            size: 'small',
            type: 'primary',
            style: 'margin-right: 6px;',
            onClick: () => handleEdit(row),
          },
          {
            default: () => '编辑',
            icon: renderIcon('material-symbols:edit-outline', { size: 16 }),
          }
        ),
        h(
          NButton,
          {
            size: 'small',
            type: hasReview ? 'info' : 'warning',
            style: 'margin-right: 6px;',
            onClick: () => hasReview ? handleViewReview(row) : handleTriggerReview(row),
          },
          {
            default: () => hasReview ? '审查结果' : '审查',
            icon: renderIcon(
              hasReview ? 'material-symbols:description-outline' : 'material-symbols:rate-review-outline',
              { size: 16 }
            ),
          }
        ),
        h(
          NPopconfirm,
          {
            onPositiveClick: () => handleDelete({ id: row.id }, false),
          },
          {
            trigger: () =>
              h(NButton, { size: 'small', type: 'error' }, {
                default: () => '删除',
                icon: renderIcon('material-symbols:delete-outline', { size: 16 }),
              }),
            default: () => h('div', {}, '确定删除该合同吗?'),
          }
        ),
      ]
    },
  },
]
</script>

<template>
  <CommonPage show-footer title="合同管理">
    <template #action>
      <NPopconfirm
        v-if="checkedRowKeys.length > 0"
        @positive-click="handleBatchDelete"
      >
        <template #trigger>
          <NButton type="error" :loading="batchDeleteLoading" style="margin-right: 12px">
            <TheIcon icon="material-symbols:delete-outline" :size="18" class="mr-5" />
            批量删除 ({{ checkedRowKeys.length }})
          </NButton>
        </template>
        确定删除选中的 {{ checkedRowKeys.length }} 条合同吗？
      </NPopconfirm>
      <NButton type="primary" @click="$table?.handleSearch()">
        <TheIcon icon="material-symbols:refresh" :size="18" class="mr-5" />刷新
      </NButton>
    </template>

    <CrudTable
      ref="$table"
      v-model:query-items="queryItems"
      :columns="columns"
      :get-data="api.getContractList"
      @on-checked="(keys) => (checkedRowKeys = keys)"
    >
      <template #queryBar>
        <QueryBarItem label="关键词" :label-width="50">
          <NInput
            v-model:value="queryItems.keyword"
            clearable
            type="text"
            placeholder="合同名称/项目名"
            @keypress.enter="$table?.handleSearch()"
          />
        </QueryBarItem>
        <QueryBarItem label="甲方" :label-width="40">
          <NInput
            v-model:value="queryItems.party_a"
            clearable
            type="text"
            placeholder="甲方名称"
            @keypress.enter="$table?.handleSearch()"
          />
        </QueryBarItem>
        <QueryBarItem label="乙方" :label-width="40">
          <NInput
            v-model:value="queryItems.party_b"
            clearable
            type="text"
            placeholder="乙方名称"
            @keypress.enter="$table?.handleSearch()"
          />
        </QueryBarItem>
        <QueryBarItem label="合同类型" :label-width="70">
          <NSelect
            v-model:value="queryItems.contract_type_id"
            clearable
            :options="contractTypeOptions"
            placeholder="请选择合同类型"
            style="width: 200px"
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
        :label-width="90"
        :model="modalForm"
        :disabled="modalAction === 'view'"
      >
        <NFormItem label="合同类型" path="contract_type_id">
          <NSelect
            v-model:value="modalForm.contract_type_id"
            :options="contractTypeOptions"
            placeholder="请选择合同类型"
            clearable
          />
        </NFormItem>
        <NFormItem label="项目名称" path="project_name">
          <NInput v-model:value="modalForm.project_name" placeholder="请输入项目名称" />
        </NFormItem>
        <NFormItem label="甲方" path="party_a_client_id">
          <NSelect
            v-model:value="modalForm.party_a_client_id"
            :options="clientOptions"
            placeholder="请选择甲方"
            clearable
            filterable
          />
        </NFormItem>
        <NFormItem label="乙方" path="party_b_client_id">
          <NSelect
            v-model:value="modalForm.party_b_client_id"
            :options="clientOptions"
            placeholder="请选择乙方"
            clearable
            filterable
          />
        </NFormItem>
        <NFormItem label="签订日期" path="signing_date">
          <NDatePicker
            v-model:value="modalForm.signing_date"
            type="date"
            clearable
            :default-value="
              modalForm.signing_date ? new Date(modalForm.signing_date).getTime() : null
            "
            :value="modalForm.signing_date ? new Date(modalForm.signing_date).getTime() : null"
            :on-update:value="
              (v) => {
                if (v) modalForm.signing_date = new Date(v).toISOString()
              }
            "
          />
        </NFormItem>
        <NFormItem label="生效日期" path="effective_date">
          <NDatePicker
            v-model:value="modalForm.effective_date"
            type="date"
            clearable
            :value="modalForm.effective_date ? new Date(modalForm.effective_date).getTime() : null"
            :on-update:value="
              (v) => {
                if (v) modalForm.effective_date = new Date(v).toISOString()
              }
            "
          />
        </NFormItem>
        <NFormItem label="到期日期" path="expiry_date">
          <NDatePicker
            v-model:value="modalForm.expiry_date"
            type="date"
            clearable
            :value="modalForm.expiry_date ? new Date(modalForm.expiry_date).getTime() : null"
            :on-update:value="
              (v) => {
                if (v) modalForm.expiry_date = new Date(v).toISOString()
              }
            "
          />
        </NFormItem>
        <NFormItem label="合同金额" path="total_amount">
          <NInputNumber
            v-model:value="modalForm.total_amount"
            placeholder="请输入合同金额"
            :min="0"
            :step="1000"
            clearable
          />
        </NFormItem>
        <NFormItem label="摘要" path="summary">
          <NInput
            v-model:value="modalForm.summary"
            type="textarea"
            placeholder="请输入合同摘要"
            :rows="3"
          />
        </NFormItem>
      </NForm>
    </CrudModal>

  </CommonPage>
</template>
