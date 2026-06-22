<script setup>
import { h, onMounted, ref, resolveDirective, withDirectives } from 'vue'
import {
  NButton,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NPopconfirm,
  NSelect,
  NSwitch,
  NTag,
} from 'naive-ui'

import CommonPage from '@/components/page/CommonPage.vue'
import QueryBarItem from '@/components/query-bar/QueryBarItem.vue'
import CrudModal from '@/components/table/CrudModal.vue'
import CrudTable from '@/components/table/CrudTable.vue'

import { formatDate, renderIcon } from '@/utils'
import { useCRUD } from '@/composables'
import api from '@/api'

defineOptions({ name: '模型配置' })

const $table = ref(null)
const queryItems = ref({})
const vPermission = resolveDirective('permission')

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
  name: 'AI模型配置',
  initForm: { is_embedding: false, max_tokens: 4096, is_active: true },
  doCreate: api.createAiConfig,
  doDelete: api.deleteAiConfig,
  doUpdate: api.updateAiConfig,
  refresh: () => $table.value?.handleSearch(),
})

const providerTypeOptions = [
  { label: 'OpenAI Compatible', value: 'openai_compatible' },
  { label: '火山引擎', value: 'volcengine' },
  { label: 'Azure OpenAI', value: 'azure_openai' },
]

async function handleTest(row) {
  try {
    const res = await api.testAiConfig({ config_id: row.id })
    if (res.code === 200) {
      $message?.success('连接测试成功')
    } else {
      $message?.error(res.msg || '连接测试失败')
    }
  } catch {
    $message?.error('连接测试失败')
  }
}

onMounted(() => {
  $table.value?.handleSearch()
})

const columns = [
  {
    title: '名称',
    key: 'name',
    width: 120,
    align: 'center',
    ellipsis: { tooltip: true },
  },
  {
    title: '提供商',
    key: 'provider_type',
    width: 120,
    align: 'center',
    render(row) {
      const label =
        providerTypeOptions.find((o) => o.value === row.provider_type)?.label || row.provider_type
      return h(NTag, { type: 'info', size: 'small' }, { default: () => label })
    },
  },
  {
    title: '模型标识',
    key: 'model_name',
    width: 150,
    align: 'center',
    ellipsis: { tooltip: true },
  },
  {
    title: 'Embedding',
    key: 'is_embedding',
    width: 80,
    align: 'center',
    render(row) {
      return h(
        NTag,
        { type: row.is_embedding ? 'success' : 'default', size: 'small' },
        { default: () => (row.is_embedding ? '是' : '否') }
      )
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
    width: 220,
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
          [[vPermission, 'post/api/v1/ai_config/update']]
        ),
        h(
          NPopconfirm,
          {
            onPositiveClick: () => handleDelete({ config_id: row.id }, false),
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
                [[vPermission, 'delete/api/v1/ai_config/delete']]
              ),
            default: () => h('div', {}, '确定删除该配置吗?'),
          }
        ),
        withDirectives(
          h(
            NButton,
            { size: 'small', type: 'info', onClick: () => handleTest(row) },
            { default: () => '测试', icon: renderIcon('carbon:connection-signal', { size: 16 }) }
          ),
          [[vPermission, 'post/api/v1/ai_config/test']]
        ),
      ]
    },
  },
]
</script>

<template>
  <CommonPage show-footer title="模型配置">
    <template #action>
      <NButton v-permission="'post/api/v1/ai_config/create'" type="primary" @click="handleAdd">
        <TheIcon icon="material-symbols:add" :size="18" class="mr-5" />新建配置
      </NButton>
    </template>

    <CrudTable
      ref="$table"
      v-model:query-items="queryItems"
      :columns="columns"
      :get-data="api.getAiConfigList"
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
          <NInput v-model:value="modalForm.name" placeholder="请输入名称" />
        </NFormItem>
        <NFormItem
          label="提供商类型"
          path="provider_type"
          :rule="{ required: true, message: '请选择提供商', trigger: ['change', 'blur'] }"
        >
          <NSelect
            v-model:value="modalForm.provider_type"
            :options="providerTypeOptions"
            placeholder="请选择提供商"
          />
        </NFormItem>
        <NFormItem
          label="API地址"
          path="api_base_url"
          :rule="{ required: true, message: '请输入API地址', trigger: ['input', 'blur'] }"
        >
          <NInput v-model:value="modalForm.api_base_url" placeholder="请输入API地址" />
        </NFormItem>
        <NFormItem
          label="API密钥"
          path="api_key"
          :rule="
            modalAction === 'add'
              ? { required: true, message: '请输入API密钥', trigger: ['input', 'blur'] }
              : undefined
          "
        >
          <NInput
            v-model:value="modalForm.api_key"
            type="password"
            show-password-on="click"
            :placeholder="modalAction === 'edit' ? '不修改请保持原值' : '请输入API密钥'"
          />
        </NFormItem>
        <NFormItem
          label="模型标识"
          path="model_name"
          :rule="{ required: true, message: '请输入模型标识', trigger: ['input', 'blur'] }"
        >
          <NInput v-model:value="modalForm.model_name" placeholder="请输入模型标识" />
        </NFormItem>
        <NFormItem label="Embedding模型" path="is_embedding">
          <NSwitch v-model:value="modalForm.is_embedding" />
        </NFormItem>
        <NFormItem v-if="modalForm.is_embedding" label="向量维度" path="embedding_dimension">
          <NInputNumber
            v-model:value="modalForm.embedding_dimension"
            :min="1"
            placeholder="请输入向量维度"
            style="width: 100%"
          />
        </NFormItem>
        <NFormItem label="最大Token" path="max_tokens">
          <NInputNumber
            v-model:value="modalForm.max_tokens"
            :min="1"
            placeholder="最大Token数"
            style="width: 100%"
          />
        </NFormItem>
        <NFormItem label="启用" path="is_active">
          <NSwitch v-model:value="modalForm.is_active" />
        </NFormItem>
      </NForm>
    </CrudModal>
  </CommonPage>
</template>
