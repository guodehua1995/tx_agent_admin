<script setup>
import { h, onMounted, ref, resolveDirective, withDirectives } from 'vue'
import { NButton, NForm, NFormItem, NInput, NPopconfirm, NSelect, NSwitch, NTag } from 'naive-ui'

import CommonPage from '@/components/page/CommonPage.vue'
import CrudModal from '@/components/table/CrudModal.vue'
import CrudTable from '@/components/table/CrudTable.vue'

import { formatDate, renderIcon } from '@/utils'
import { useCRUD } from '@/composables'
import api from '@/api'

defineOptions({ name: '机器人配置' })

const $table = ref(null)
const queryItems = ref({})
const vPermission = resolveDirective('permission')

const agentOptions = ref([])

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
  name: '飞书机器人',
  initForm: { is_active: true },
  doCreate: api.createFeishuBot,
  doDelete: api.deleteFeishuBot,
  doUpdate: api.updateFeishuBot,
  refresh: () => $table.value?.handleSearch(),
})

async function loadAgents() {
  const res = await api.getAgentList({ page: 1, page_size: 9999 })
  agentOptions.value = (res.data || []).map((item) => ({ label: item.name, value: item.id }))
}

function getAgentName(id) {
  return agentOptions.value.find((o) => o.value === id)?.label || id
}

onMounted(() => {
  loadAgents()
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
    title: 'App ID',
    key: 'app_id',
    width: 150,
    align: 'center',
    ellipsis: { tooltip: true },
  },
  {
    title: '绑定Agent',
    key: 'agent_id',
    width: 120,
    align: 'center',
    render(row) {
      return h('span', getAgentName(row.agent_id))
    },
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
    width: 160,
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
          [[vPermission, 'post/api/v1/feishu/bot/update']]
        ),
        h(
          NPopconfirm,
          {
            onPositiveClick: () => handleDelete({ bot_id: row.id }, false),
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
                [[vPermission, 'delete/api/v1/feishu/bot/delete']]
              ),
            default: () => h('div', {}, '确定删除该机器人配置吗?'),
          }
        ),
      ]
    },
  },
]
</script>

<template>
  <CommonPage show-footer title="机器人配置">
    <template #action>
      <NButton v-permission="'post/api/v1/feishu/bot/create'" type="primary" @click="handleAdd">
        <TheIcon icon="material-symbols:add" :size="18" class="mr-5" />新建机器人
      </NButton>
    </template>

    <CrudTable
      ref="$table"
      v-model:query-items="queryItems"
      :columns="columns"
      :get-data="api.getFeishuBotList"
    />

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
          <NInput v-model:value="modalForm.name" placeholder="请输入机器人名称" />
        </NFormItem>
        <NFormItem
          label="App ID"
          path="app_id"
          :rule="{ required: true, message: '请输入App ID', trigger: ['input', 'blur'] }"
        >
          <NInput v-model:value="modalForm.app_id" placeholder="请输入飞书应用ID" />
        </NFormItem>
        <NFormItem
          label="App Secret"
          path="app_secret"
          :rule="
            modalAction === 'add'
              ? { required: true, message: '请输入App Secret', trigger: ['input', 'blur'] }
              : undefined
          "
        >
          <NInput
            v-model:value="modalForm.app_secret"
            type="password"
            show-password-on="click"
            :placeholder="modalAction === 'edit' ? '不修改请保持原值' : '请输入飞书应用密钥'"
          />
        </NFormItem>
        <NFormItem label="验证Token" path="verification_token">
          <NInput v-model:value="modalForm.verification_token" placeholder="事件验证Token (可选)" />
        </NFormItem>
        <NFormItem label="加密Key" path="encrypt_key">
          <NInput v-model:value="modalForm.encrypt_key" placeholder="事件加密Key (可选)" />
        </NFormItem>
        <NFormItem label="绑定Agent" path="agent_id">
          <NSelect
            v-model:value="modalForm.agent_id"
            :options="agentOptions"
            placeholder="请选择绑定的Agent (可选)"
            clearable
          />
        </NFormItem>
        <NFormItem label="启用" path="is_active">
          <NSwitch v-model:value="modalForm.is_active" />
        </NFormItem>
      </NForm>
    </CrudModal>
  </CommonPage>
</template>
