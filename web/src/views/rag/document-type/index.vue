<script setup>
import { h, onMounted, ref, resolveDirective, withDirectives } from 'vue'
import {
  NButton,
  NForm,
  NFormItem,
  NInput,
  NPopconfirm,
  NSwitch,
  NTag,
} from 'naive-ui'

import CommonPage from '@/components/page/CommonPage.vue'
import CrudModal from '@/components/table/CrudModal.vue'
import CrudTable from '@/components/table/CrudTable.vue'

import { formatDate, renderIcon } from '@/utils'
import { useCRUD } from '@/composables'
import api from '@/api'

defineOptions({ name: '文档类型' })

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
  name: '文档类型',
  initForm: { needs_structuring: false, is_active: true },
  doCreate: api.createDocumentType,
  doDelete: api.deleteDocumentType,
  doUpdate: api.updateDocumentType,
  refresh: () => $table.value?.handleSearch(),
})

onMounted(() => {
  $table.value?.handleSearch()
})

const columns = [
  {
    title: '类型名称',
    key: 'name',
    width: 150,
    align: 'center',
    ellipsis: { tooltip: true },
  },
  {
    title: '编码',
    key: 'code',
    width: 120,
    align: 'center',
    render(row) {
      return h(NTag, { type: 'info', size: 'small' }, { default: () => row.code })
    },
  },
  {
    title: '需要结构化',
    key: 'needs_structuring',
    width: 100,
    align: 'center',
    render(row) {
      return h(NTag, { type: row.needs_structuring ? 'success' : 'default', size: 'small' }, { default: () => (row.needs_structuring ? '是' : '否') })
    },
  },
  {
    title: '状态',
    key: 'is_active',
    width: 80,
    align: 'center',
    render(row) {
      return h(NTag, { type: row.is_active ? 'success' : 'default', size: 'small' }, { default: () => (row.is_active ? '启用' : '停用') })
    },
  },
  {
    title: '描述',
    key: 'description',
    width: 200,
    align: 'center',
    ellipsis: { tooltip: true },
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
            { size: 'small', type: 'primary', style: 'margin-right: 8px;', onClick: () => handleEdit(row) },
            { default: () => '编辑', icon: renderIcon('material-symbols:edit-outline', { size: 16 }) }
          ),
          [[vPermission, 'post/api/v1/document/type/update']]
        ),
        h(
          NPopconfirm,
          { onPositiveClick: () => handleDelete({ type_id: row.id }, false), onNegativeClick: () => {} },
          {
            trigger: () =>
              withDirectives(
                h(
                  NButton,
                  { size: 'small', type: 'error' },
                  { default: () => '删除', icon: renderIcon('material-symbols:delete-outline', { size: 16 }) }
                ),
                [[vPermission, 'delete/api/v1/document/type/delete']]
              ),
            default: () => h('div', {}, '确定删除该文档类型吗?'),
          }
        ),
      ]
    },
  },
]
</script>

<template>
  <CommonPage show-footer title="文档类型">
    <template #action>
      <NButton v-permission="'post/api/v1/document/type/create'" type="primary" @click="handleAdd">
        <TheIcon icon="material-symbols:add" :size="18" class="mr-5" />新建类型
      </NButton>
    </template>

    <CrudTable
      ref="$table"
      v-model:query-items="queryItems"
      :columns="columns"
      :get-data="api.getDocumentTypeList"
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
        <NFormItem label="类型名称" path="name" :rule="{ required: true, message: '请输入类型名称', trigger: ['input', 'blur'] }">
          <NInput v-model:value="modalForm.name" placeholder="请输入类型名称" />
        </NFormItem>
        <NFormItem label="编码" path="code" :rule="{ required: true, message: '请输入编码', trigger: ['input', 'blur'] }">
          <NInput v-model:value="modalForm.code" placeholder="请输入编码 (如 feishu_doc)" />
        </NFormItem>
        <NFormItem label="描述" path="description">
          <NInput v-model:value="modalForm.description" type="textarea" placeholder="请输入描述" />
        </NFormItem>
        <NFormItem label="需要结构化" path="needs_structuring">
          <NSwitch v-model:value="modalForm.needs_structuring" />
        </NFormItem>
        <NFormItem label="启用" path="is_active">
          <NSwitch v-model:value="modalForm.is_active" />
        </NFormItem>
      </NForm>
    </CrudModal>
  </CommonPage>
</template>
