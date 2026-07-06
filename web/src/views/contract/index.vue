<script setup>
import { h, onMounted, ref, resolveDirective, withDirectives } from 'vue'
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
const vPermission = resolveDirective('permission')

const contractTypeOptions = ref([])
const clientOptions = ref([])

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
    title: '合同名称',
    key: 'project_name',
    width: 180,
    align: 'center',
    ellipsis: { tooltip: true },
    render(row) {
      return h(
        NButton,
        {
          text: true,
          type: 'primary',
          onClick: () => handleView(row),
        },
        { default: () => row.project_name || row.document_title || '-' }
      )
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
      return h(
        NTag,
        { type, size: 'small' },
        { default: () => formatDate(row.expiry_date) }
      )
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
            onClick: () => handleView(row),
          },
          {
            default: () => '详情',
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
          [[vPermission, 'put/api/v1/contract/update']]
        ),
        h(
          NPopconfirm,
          {
            onPositiveClick: () => handleDelete({ id: row.id }, false),
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
                [[vPermission, 'delete/api/v1/contract/delete']]
              ),
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
      <NButton
        v-permission="'get/api/v1/contract/list'"
        type="primary"
        @click="$table?.handleSearch()"
      >
        <TheIcon icon="material-symbols:refresh" :size="18" class="mr-5" />刷新
      </NButton>
    </template>

    <CrudTable
      ref="$table"
      v-model:query-items="queryItems"
      :columns="columns"
      :get-data="api.getContractList"
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
            :default-value="modalForm.signing_date ? new Date(modalForm.signing_date).getTime() : null"
            :value="modalForm.signing_date ? new Date(modalForm.signing_date).getTime() : null"
            :on-update:value="(v) => { if (v) modalForm.signing_date = new Date(v).toISOString() }"
          />
        </NFormItem>
        <NFormItem label="生效日期" path="effective_date">
          <NDatePicker
            v-model:value="modalForm.effective_date"
            type="date"
            clearable
            :value="modalForm.effective_date ? new Date(modalForm.effective_date).getTime() : null"
            :on-update:value="(v) => { if (v) modalForm.effective_date = new Date(v).toISOString() }"
          />
        </NFormItem>
        <NFormItem label="到期日期" path="expiry_date">
          <NDatePicker
            v-model:value="modalForm.expiry_date"
            type="date"
            clearable
            :value="modalForm.expiry_date ? new Date(modalForm.expiry_date).getTime() : null"
            :on-update:value="(v) => { if (v) modalForm.expiry_date = new Date(v).toISOString() }"
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