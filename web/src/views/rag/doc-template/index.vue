<script setup>
import { h, nextTick, onMounted, ref, resolveDirective, withDirectives } from 'vue'
import {
  NButton,
  NDrawer,
  NDrawerContent,
  NForm,
  NFormItem,
  NInput,
  NModal,
  NPopconfirm,
  NSpace,
} from 'naive-ui'
import Vditor from 'vditor'
import 'vditor/dist/index.css'

import CommonPage from '@/components/page/CommonPage.vue'
import QueryBarItem from '@/components/query-bar/QueryBarItem.vue'
import CrudTable from '@/components/table/CrudTable.vue'

import { formatDate, renderIcon } from '@/utils'
import api from '@/api'

defineOptions({ name: '文档模板' })

const $table = ref(null)
const queryItems = ref({})
const vPermission = resolveDirective('permission')

// Drawer state
const drawerVisible = ref(false)
const drawerTitle = ref('新建模板')
const drawerLoading = ref(false)
const drawerForm = ref({
  id: null,
  name: '',
  naming_format: '',
  folder_token: '',
  description: '',
  markdown_content: '',
})
const drawerFormRef = ref(null)
const isEdit = ref(false)

// Vditor
let vditorInstance = null
const vditorRef = ref(null)

// Import modal
const importModalVisible = ref(false)
const choiceModalVisible = ref(false)
const importUrl = ref('')
const importLoading = ref(false)

// ========== Table columns ==========
const columns = [
  { title: '名称', key: 'name', width: 150, align: 'center', ellipsis: { tooltip: true } },
  { title: '描述', key: 'description', width: 200, align: 'center', ellipsis: { tooltip: true } },
  {
    title: '命名格式',
    key: 'naming_format',
    width: 120,
    align: 'center',
    ellipsis: { tooltip: true },
  },
  {
    title: '文件夹Token',
    key: 'folder_token',
    width: 150,
    align: 'center',
    ellipsis: { tooltip: true },
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
          [[vPermission, 'post/api/v1/doc_template/update']]
        ),
        h(
          NPopconfirm,
          { onPositiveClick: () => handleDelete(row) },
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
                [[vPermission, 'delete/api/v1/doc_template/delete']]
              ),
            default: () => h('div', {}, `确定删除模板【${row.name}】吗?`),
          }
        ),
      ]
    },
  },
]

// ========== Actions ==========
function handleAdd() {
  choiceModalVisible.value = true
}

function onChoiceSelect(type) {
  choiceModalVisible.value = false
  if (type === 'import') {
    importUrl.value = ''
    importModalVisible.value = true
  } else {
    openDrawer({
      name: '',
      naming_format: '',
      folder_token: '',
      description: '',
      markdown_content: '',
    })
  }
}

async function handleImport() {
  if (!importUrl.value.trim()) {
    $message.warning('请输入飞书文档URL')
    return
  }
  importLoading.value = true
  try {
    const res = await api.parseDocTemplateUrl({ url: importUrl.value.trim() })
    importModalVisible.value = false
    openDrawer({
      name: '',
      naming_format: '',
      folder_token: '',
      description: '',
      markdown_content: res.data.markdown_content,
    })
  } catch (e) {
    $message.error(e.message || '解析失败')
  } finally {
    importLoading.value = false
  }
}

async function handleEdit(row) {
  try {
    const res = await api.getDocTemplate({ template_id: row.id })
    openDrawer(res.data, true)
  } catch (e) {
    $message.error('获取模板详情失败')
  }
}

async function handleDelete(row) {
  try {
    await api.deleteDocTemplate({ template_id: row.id })
    $message.success('删除成功')
    $table.value?.handleSearch()
  } catch (e) {
    $message.error('删除失败')
  }
}

function openDrawer(data, edit = false) {
  isEdit.value = edit
  drawerTitle.value = edit ? '编辑模板' : '新建模板'
  drawerForm.value = {
    id: data.id || null,
    name: data.name || '',
    naming_format: data.naming_format || '',
    folder_token: data.folder_token || '',
    description: data.description || '',
    markdown_content: data.markdown_content || '',
  }
  drawerVisible.value = true
  nextTick(() => initVditor())
}

function initVditor() {
  if (vditorInstance) {
    vditorInstance.destroy()
    vditorInstance = null
  }
  nextTick(() => {
    const container = vditorRef.value
    if (!container) return
    vditorInstance = new Vditor(container, {
      height: '100%',
      mode: 'ir',
      value: drawerForm.value.markdown_content,
      placeholder: '请输入 Markdown 模板内容...',
      toolbar: [
        'headings',
        'bold',
        'italic',
        'strike',
        '|',
        'line',
        'quote',
        'list',
        'ordered-list',
        'check',
        '|',
        'code',
        'inline-code',
        'table',
        '|',
        'undo',
        'redo',
        '|',
        'fullscreen',
        'preview',
      ],
      toolbarConfig: { pin: true },
      cache: { enable: false },
      after: () => {},
      input: (value) => {
        drawerForm.value.markdown_content = value
      },
    })
  })
}

function closeDrawer() {
  if (vditorInstance) {
    vditorInstance.destroy()
    vditorInstance = null
  }
  drawerVisible.value = false
}

async function handleSave() {
  drawerFormRef.value?.validate(async (errors) => {
    if (errors) return
    if (!drawerForm.value.markdown_content.trim()) {
      $message.warning('请输入模板内容')
      return
    }
    drawerLoading.value = true
    try {
      if (isEdit.value) {
        await api.updateDocTemplate(drawerForm.value)
        $message.success('更新成功')
      } else {
        await api.createDocTemplate(drawerForm.value)
        $message.success('创建成功')
      }
      closeDrawer()
      $table.value?.handleSearch()
    } catch (e) {
      $message.error(e.message || '保存失败')
    } finally {
      drawerLoading.value = false
    }
  })
}

onMounted(() => {
  $table.value?.handleSearch()
})
</script>

<template>
  <CommonPage show-footer title="文档模板">
    <template #action>
      <NButton v-permission="'post/api/v1/doc_template/create'" type="primary" @click="handleAdd">
        <TheIcon icon="material-symbols:add" :size="18" class="mr-5" />新建模板
      </NButton>
    </template>

    <CrudTable
      ref="$table"
      v-model:query-items="queryItems"
      :columns="columns"
      :get-data="api.getDocTemplateList"
    >
      <template #queryBar>
        <QueryBarItem label="命名格式" :label-width="70">
          <NInput
            v-model:value="queryItems.naming_format"
            clearable
            type="text"
            placeholder="搜索命名格式"
            @keypress.enter="$table?.handleSearch()"
          />
        </QueryBarItem>
        <QueryBarItem label="文件夹Token" :label-width="80">
          <NInput
            v-model:value="queryItems.folder_token"
            clearable
            type="text"
            placeholder="搜索文件夹Token"
            @keypress.enter="$table?.handleSearch()"
          />
        </QueryBarItem>
      </template>
    </CrudTable>

    <!-- Choice Modal: 直接创建 or 导入云文档 -->
    <NModal v-model:show="choiceModalVisible" preset="dialog" title="新建模板" :show-icon="false">
      <NSpace justify="center" style="padding: 20px 0">
        <NButton type="primary" size="large" @click="onChoiceSelect('create')">直接创建</NButton>
        <NButton type="info" size="large" @click="onChoiceSelect('import')">导入云文档</NButton>
      </NSpace>
    </NModal>

    <!-- Import URL Modal -->
    <NModal
      v-model:show="importModalVisible"
      preset="dialog"
      title="导入飞书云文档"
      :show-icon="false"
    >
      <div style="padding: 16px 0">
        <NInput
          v-model:value="importUrl"
          placeholder="请输入飞书云文档URL"
          @keypress.enter="handleImport"
        />
        <NSpace justify="end" style="margin-top: 16px">
          <NButton @click="importModalVisible = false">取消</NButton>
          <NButton type="primary" :loading="importLoading" @click="handleImport">导入</NButton>
        </NSpace>
      </div>
    </NModal>

    <!-- Editor Drawer -->
    <NDrawer
      v-model:show="drawerVisible"
      placement="right"
      :width="'90%'"
      :on-after-leave="closeDrawer"
    >
      <NDrawerContent :title="drawerTitle" :native-scrollbar="false">
        <div style="display: flex; height: calc(100vh - 130px); gap: 16px">
          <!-- Left: Form Fields -->
          <div style="width: 30%; min-width: 280px; overflow-y: auto">
            <NForm ref="drawerFormRef" :model="drawerForm" label-placement="top">
              <NFormItem
                label="模板名称"
                path="name"
                :rule="{ required: true, message: '请输入模板名称', trigger: ['input', 'blur'] }"
              >
                <NInput v-model:value="drawerForm.name" placeholder="请输入模板名称" />
              </NFormItem>
              <NFormItem label="命名格式" path="naming_format">
                <NInput v-model:value="drawerForm.naming_format" placeholder="选填，默认AI起名" />
              </NFormItem>
              <NFormItem
                label="飞书文件夹Token"
                path="folder_token"
                :rule="{ required: true, message: '请输入文件夹Token', trigger: ['input', 'blur'] }"
              >
                <NInput v-model:value="drawerForm.folder_token" placeholder="生成文档保存路径" />
              </NFormItem>
              <NFormItem
                label="描述"
                path="description"
                :rule="{ required: true, message: '请输入描述', trigger: ['input', 'blur'] }"
              >
                <NInput
                  v-model:value="drawerForm.description"
                  type="textarea"
                  placeholder="告知AI什么情况下调用当前模板"
                  :rows="4"
                />
              </NFormItem>
            </NForm>
          </div>
          <!-- Right: Markdown Editor -->
          <div style="flex: 1; border: 1px solid #e0e0e6; border-radius: 4px; overflow: hidden">
            <div ref="vditorRef" style="height: 100%" />
          </div>
        </div>
        <!-- Footer -->
        <template #footer>
          <NSpace justify="end">
            <NButton @click="closeDrawer">取消</NButton>
            <NButton type="primary" :loading="drawerLoading" @click="handleSave">保存</NButton>
          </NSpace>
        </template>
      </NDrawerContent>
    </NDrawer>
  </CommonPage>
</template>
