<script setup>
import { ref, watch } from 'vue'
import {
  NButton,
  NDrawer,
  NDrawerContent,
  NFormItem,
  NSelect,
  NSpace,
  NUpload,
  NAlert,
} from 'naive-ui'

import RuleItemEditor from './RuleItemEditor.vue'
import api from '@/api'

const props = defineProps({
  visible: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['update:visible', 'refresh'])

const loading = ref(false)
const clientId = ref(null)
const clientOptions = ref([])
const parsedItems = ref([])
const parseError = ref('')
const fileParsed = ref(false)

watch(
  () => props.visible,
  (val) => {
    if (val) {
      loadClients()
    } else {
      resetState()
    }
  }
)

function resetState() {
  clientId.value = null
  parsedItems.value = []
  parseError.value = ''
  fileParsed.value = false
}

async function loadClients(keyword = '') {
  const res = await api.getClientList({ keyword, page: 1, page_size: 100 })
  clientOptions.value = (res.data || []).map((c) => ({
    label: c.name,
    value: c.id,
  }))
}

function handleClientSearch(query) {
  loadClients(query)
}

async function handleUpload({ file }) {
  parseError.value = ''
  parsedItems.value = []
  fileParsed.value = false

  const formData = new FormData()
  formData.append('file', file.file)

  try {
    loading.value = true
    const res = await api.parseExcel(formData)
    if (res.code === 200 || res.code === 0) {
      parsedItems.value = res.data || []
      fileParsed.value = true
      $message.success(`解析成功，共 ${parsedItems.value.length} 个一级项目`)
    } else {
      parseError.value = res.msg || '解析失败'
    }
  } catch (e) {
    parseError.value = e.message || '解析请求失败'
  } finally {
    loading.value = false
  }

  return false // prevent default upload behavior
}

async function handleImport() {
  if (!clientId.value) {
    $message.warning('请选择甲方')
    return
  }
  if (!parsedItems.value.length) {
    $message.warning('没有可导入的数据')
    return
  }
  try {
    loading.value = true
    await api.importExcel({
      client_id: clientId.value,
      source_type: 'excel_import',
      items: parsedItems.value,
    })
    $message.success('导入成功')
    emit('update:visible', false)
    emit('refresh')
  } finally {
    loading.value = false
  }
}

function close() {
  emit('update:visible', false)
}
</script>

<template>
  <NDrawer :show="visible" :width="780" @update:show="(v) => emit('update:visible', v)">
    <NDrawerContent title="Excel 报价单导入" closable>
      <NSpace vertical size="large">
        <!-- 选择甲方 -->
        <NFormItem label="甲方" :show-feedback="false" label-placement="left">
          <NSelect
            v-model:value="clientId"
            :options="clientOptions"
            filterable
            remote
            placeholder="请选择甲方"
            style="width: 260px"
            @search="handleClientSearch"
          />
        </NFormItem>

        <!-- 上传文件 -->
        <div>
          <h4 style="margin-bottom: 8px">Step 1: 上传文件</h4>
          <NUpload
            accept=".xlsx,.xls"
            :max="1"
            :default-upload="false"
            :custom-request="handleUpload"
            @change="({ file }) => handleUpload({ file })"
          >
            <NButton>选择 Excel 文件（.xlsx / .xls）</NButton>
          </NUpload>
          <NAlert v-if="parseError" type="error" style="margin-top: 8px">
            {{ parseError }}
          </NAlert>
        </div>

        <!-- 解析结果预览 -->
        <div v-if="fileParsed">
          <h4 style="margin-bottom: 8px">
            Step 2: 预览解析结果（可编辑）
          </h4>
          <RuleItemEditor v-model:items="parsedItems" />
        </div>
      </NSpace>

      <template #footer>
        <NSpace>
          <NButton @click="close">取消</NButton>
          <NButton
            type="primary"
            :loading="loading"
            :disabled="!fileParsed || !clientId"
            @click="handleImport"
          >
            确认导入
          </NButton>
        </NSpace>
      </template>
    </NDrawerContent>
  </NDrawer>
</template>
