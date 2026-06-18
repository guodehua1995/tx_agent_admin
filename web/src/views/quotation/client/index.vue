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
import QueryBarItem from '@/components/query-bar/QueryBarItem.vue'
import CrudModal from '@/components/table/CrudModal.vue'
import CrudTable from '@/components/table/CrudTable.vue'

import { formatDate, renderIcon } from '@/utils'
import { useCRUD } from '@/composables'
import api from '@/api'

defineOptions({ name: '甲方管理' })

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
  name: '甲方',
  initForm: {
    is_active: true,
  },
  doCreate: api.createClient,
  doDelete: api.deleteClient,
  doUpdate: api.updateClient,
  refresh: () => $table.value?.handleSearch(),
})

onMounted(() => {
  $table.value?.handleSearch()
})

const columns = [
  {
    title: '甲方名称',
    key: 'name',
    width: 200,
    align: 'center',
    ellipsis: { tooltip: true },
  },
  {
    title: '简称',
    key: 'short_name',
    width: 120,
    align: 'center',
    ellipsis: { tooltip: true },
  },
  {
    title: '联系人',
    key: 'contact',
    width: 100,
    align: 'center',
  },
  {
    title: '电话',
    key: 'phone',
    width: 140,
    align: 'center',
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
          [[vPermission, 'put/api/v1/quotation/client/update']]
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
                [[vPermission, 'delete/api/v1/quotation/client/delete']]
              ),
            default: () => h('div', {}, '确定删除该甲方吗?'),
          }
        ),
      ]
    },
  },
]
</script>

<template>
  <CommonPage show-footer title="甲方管理">
    <template #action>
      <NButton v-permission="'post/api/v1/quotation/client/create'" type="primary" @click="handleAdd">
        <TheIcon icon="material-symbols:add" :size="18" class="mr-5" />新增甲方
      </NButton>
    </template>

    <CrudTable
      ref="$table"
      v-model:query-items="queryItems"
      :columns="columns"
      :get-data="api.getClientList"
    >
      <template #queryBar>
        <QueryBarItem label="关键词" :label-width="50">
          <NInput
            v-model:value="queryItems.keyword"
            clearable
            type="text"
            placeholder="名称/简称"
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
        :label-width="80"
        :model="modalForm"
        :disabled="modalAction === 'view'"
      >
        <NFormItem
          label="甲方名称"
          path="name"
          :rule="{ required: true, message: '请输入甲方名称', trigger: ['input', 'blur'] }"
        >
          <NInput v-model:value="modalForm.name" placeholder="请输入甲方名称" />
        </NFormItem>
        <NFormItem label="简称" path="short_name">
          <NInput v-model:value="modalForm.short_name" placeholder="请输入简称" />
        </NFormItem>
        <NFormItem label="联系人" path="contact">
          <NInput v-model:value="modalForm.contact" placeholder="请输入联系人" />
        </NFormItem>
        <NFormItem label="电话" path="phone">
          <NInput v-model:value="modalForm.phone" placeholder="请输入电话" />
        </NFormItem>
        <NFormItem label="备注" path="remark">
          <NInput v-model:value="modalForm.remark" type="textarea" placeholder="请输入备注" />
        </NFormItem>
        <NFormItem label="启用" path="is_active">
          <NSwitch v-model:value="modalForm.is_active" />
        </NFormItem>
      </NForm>
    </CrudModal>
  </CommonPage>
</template>
