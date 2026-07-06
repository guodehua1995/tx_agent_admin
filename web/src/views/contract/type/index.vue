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

defineOptions({ name: '合同类型管理' })

const $table = ref(null)
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
  name: '合同类型',
  initForm: { is_active: true },
  doCreate: api.createContractType,
  doDelete: api.deleteContractType,
  doUpdate: api.updateContractType,
  refresh: () => $table.value?.handleSearch(),
})

onMounted(() => {
  $table.value?.handleSearch()
})

const columns = [
  {
    title: '类型名称',
    key: 'name',
    width: 160,
    align: 'center',
    ellipsis: { tooltip: true },
  },
  {
    title: '类型编码',
    key: 'code',
    width: 140,
    align: 'center',
    ellipsis: { tooltip: true },
  },
  {
    title: '说明',
    key: 'description',
    width: 200,
    align: 'center',
    ellipsis: { tooltip: true },
    render(row) {
      return h('span', row.description || '-')
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
        { default: () => (row.is_active ? '启用' : '禁用') }
      )
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
          [[vPermission, 'put/api/v1/contract/type/update']]
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
                [[vPermission, 'delete/api/v1/contract/type/delete']]
              ),
            default: () => h('div', {}, '确定删除该合同类型吗?'),
          }
        ),
      ]
    },
  },
]
</script>

<template>
  <CommonPage show-footer title="合同类型管理">
    <template #action>
      <NButton v-permission="'post/api/v1/contract/type/create'" type="primary" @click="handleAdd">
        <TheIcon icon="material-symbols:add" :size="18" class="mr-5" />新增类型
      </NButton>
    </template>

    <CrudTable
      ref="$table"
      :columns="columns"
      :get-data="api.getContractTypeList"
      :is-pagination="false"
    >
      <template #queryBar>
        <div />
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
        :label-width="80"
        :model="modalForm"
        :disabled="modalAction === 'view'"
      >
        <NFormItem
          label="类型名称"
          path="name"
          :rule="{ required: true, message: '请输入类型名称', trigger: ['input', 'blur'] }"
        >
          <NInput v-model:value="modalForm.name" placeholder="请输入类型名称" />
        </NFormItem>
        <NFormItem
          label="类型编码"
          path="code"
          :rule="{ required: true, message: '请输入类型编码', trigger: ['input', 'blur'] }"
        >
          <NInput
            v-model:value="modalForm.code"
            placeholder="请输入类型编码（英文）"
            :disabled="modalAction === 'edit'"
          />
        </NFormItem>
        <NFormItem label="说明" path="description">
          <NInput
            v-model:value="modalForm.description"
            type="textarea"
            placeholder="请输入类型说明"
            :rows="3"
          />
        </NFormItem>
        <NFormItem label="启用" path="is_active">
          <NSwitch v-model:value="modalForm.is_active" />
        </NFormItem>
      </NForm>
    </CrudModal>
  </CommonPage>
</template>