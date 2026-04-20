<script setup>
import { onMounted, ref, resolveDirective, withDirectives, h, computed } from 'vue'
import {
  NButton,
  NCard,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NPopconfirm,
  NSpace,
  NSpin,
  NTooltip,
} from 'naive-ui'

import CommonPage from '@/components/page/CommonPage.vue'
import CrudModal from '@/components/table/CrudModal.vue'

import { renderIcon } from '@/utils'
import { useCRUD } from '@/composables'
import api from '@/api'

defineOptions({ name: '全局配置' })

const vPermission = resolveDirective('permission')
const loading = ref(false)
const groupedData = ref({})

const {
  modalVisible,
  modalAction,
  modalTitle,
  modalLoading,
  handleAdd,
  handleSave,
  modalForm,
  modalFormRef,
} = useCRUD({
  name: '配置项',
  initForm: { config_key: '', config_value: '', config_group: 'default', description: '' },
  doCreate: api.createGlobalConfig,
  doDelete: api.deleteGlobalConfig,
  doUpdate: api.updateGlobalConfig,
  refresh: () => loadData(),
})

const groupList = computed(() => Object.keys(groupedData.value))

async function loadData() {
  loading.value = true
  try {
    const res = await api.getGlobalConfigGrouped()
    groupedData.value = res.data || {}
  } finally {
    loading.value = false
  }
}

async function handleSaveGroup(group) {
  const configs = groupedData.value[group] || []
  const items = configs.map((c) => ({ id: c.id, config_value: c.config_value }))
  try {
    const res = await api.batchUpdateGlobalConfig({ items })
    if (res.code === 200) {
      $message?.success(`${group} 保存成功`)
    } else {
      $message?.error(res.msg || '保存失败')
    }
  } catch {
    $message?.error('保存失败')
  }
}

async function handleSaveAll() {
  const items = []
  for (const configs of Object.values(groupedData.value)) {
    for (const c of configs) {
      items.push({ id: c.id, config_value: c.config_value })
    }
  }
  if (items.length === 0) {
    $message?.warning('暂无配置项')
    return
  }
  try {
    const res = await api.batchUpdateGlobalConfig({ items })
    if (res.code === 200) {
      $message?.success('全部保存成功')
    } else {
      $message?.error(res.msg || '保存失败')
    }
  } catch {
    $message?.error('保存失败')
  }
}

async function handleDeleteConfig(configId) {
  try {
    await api.deleteGlobalConfig({ config_id: configId })
    $message?.success('删除成功')
    loadData()
  } catch {
    $message?.error('删除失败')
  }
}

onMounted(() => {
  loadData()
})
</script>

<template>
  <CommonPage show-footer title="全局配置">
    <template #action>
      <NButton
        v-permission="'post/api/v1/global_config/create'"
        type="primary"
        style="margin-right: 12px"
        @click="handleAdd"
      >
        <TheIcon icon="material-symbols:add" :size="18" class="mr-5" />新增配置
      </NButton>
      <NButton
        v-permission="'post/api/v1/global_config/batch_update'"
        type="info"
        @click="handleSaveAll"
      >
        <TheIcon icon="material-symbols:save-outline" :size="18" class="mr-5" />全部保存
      </NButton>
    </template>

    <NSpin :show="loading">
      <NEmpty v-if="groupList.length === 0 && !loading" description="暂无配置项，请点击新增" />
      <NSpace vertical :size="16">
        <NCard v-for="group in groupList" :key="group" :title="group" size="small">
          <template #header-extra>
            <NButton
              v-permission="'post/api/v1/global_config/batch_update'"
              size="small"
              type="primary"
              @click="handleSaveGroup(group)"
            >
              保存本组
            </NButton>
          </template>
          <NForm label-placement="left" label-align="left" :label-width="200">
            <NFormItem v-for="item in groupedData[group]" :key="item.id">
              <template #label>
                <span>{{ item.config_key }}</span>
                <NTooltip v-if="item.description">
                  <template #trigger>
                    <TheIcon
                      icon="material-symbols:info-outline"
                      :size="14"
                      style="margin-left: 4px; cursor: help; vertical-align: middle; opacity: 0.6"
                    />
                  </template>
                  {{ item.description }}
                </NTooltip>
              </template>
              <div style="display: flex; align-items: center; gap: 8px; width: 100%">
                <NInput v-model:value="item.config_value" style="flex: 1" />
                <NPopconfirm @positive-click="handleDeleteConfig(item.id)">
                  <template #trigger>
                    <NButton
                      v-permission="'delete/api/v1/global_config/delete'"
                      size="small"
                      type="error"
                      quaternary
                    >
                      <TheIcon icon="material-symbols:delete-outline" :size="16" />
                    </NButton>
                  </template>
                  确定删除此配置项吗?
                </NPopconfirm>
              </div>
            </NFormItem>
          </NForm>
        </NCard>
      </NSpace>
    </NSpin>

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
      >
        <NFormItem
          label="配置键"
          path="config_key"
          :rule="{ required: true, message: '请输入配置键', trigger: ['input', 'blur'] }"
        >
          <NInput v-model:value="modalForm.config_key" placeholder="如: feishu.doc_bot.app_id" />
        </NFormItem>
        <NFormItem label="配置值" path="config_value">
          <NInput
            v-model:value="modalForm.config_value"
            type="textarea"
            placeholder="配置值"
            :rows="2"
          />
        </NFormItem>
        <NFormItem
          label="分组"
          path="config_group"
          :rule="{ required: true, message: '请输入分组名', trigger: ['input', 'blur'] }"
        >
          <NInput v-model:value="modalForm.config_group" placeholder="如: 飞书集成" />
        </NFormItem>
        <NFormItem label="描述" path="description">
          <NInput
            v-model:value="modalForm.description"
            type="textarea"
            placeholder="配置项说明 (可选)"
            :rows="2"
          />
        </NFormItem>
      </NForm>
    </CrudModal>
  </CommonPage>
</template>
