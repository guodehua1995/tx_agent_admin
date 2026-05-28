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
import { useRouter } from 'vue-router'

import CommonPage from '@/components/page/CommonPage.vue'
import QueryBarItem from '@/components/query-bar/QueryBarItem.vue'
import CrudModal from '@/components/table/CrudModal.vue'
import CrudTable from '@/components/table/CrudTable.vue'

import { formatDate, renderIcon } from '@/utils'
import { useCRUD } from '@/composables'
import api from '@/api'

defineOptions({ name: '知识库管理' })

const router = useRouter()
const $table = ref(null)
const queryItems = ref({})
const vPermission = resolveDirective('permission')

const embeddingModelOptions = ref([])

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
  name: '知识库',
  initForm: {
    is_active: true,
    retrieval_mode: 'vector',
    chunk_mode: 'sentence',
    chunk_size: 512,
    chunk_overlap: 50,
    similarity_top_k: 5,
    similarity_threshold: 0.5,
    context_chunks_window: 0,
  },
  doCreate: api.createKnowledgeBase,
  doDelete: api.deleteKnowledgeBase,
  doUpdate: api.updateKnowledgeBase,
  refresh: () => $table.value?.handleSearch(),
})

const retrievalModeOptions = [
  { label: '向量检索', value: 'vector' },
  { label: '混合检索', value: 'hybrid' },
]

const chunkModeOptions = [
  { label: '按句分块', value: 'sentence' },
  { label: 'Markdown分块', value: 'markdown' },
  { label: '层次分块', value: 'hierarchical' },
]

async function loadEmbeddingModels() {
  const res = await api.getAiConfigList({ is_embedding: true, page: 1, page_size: 9999 })
  embeddingModelOptions.value = (res.data || []).map((item) => ({
    label: item.name,
    value: item.id,
  }))
}

function getEmbeddingModelName(id) {
  return embeddingModelOptions.value.find((o) => o.value === id)?.label || id
}

onMounted(() => {
  loadEmbeddingModels()
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
    title: '描述',
    key: 'description',
    width: 200,
    align: 'center',
    ellipsis: { tooltip: true },
  },
  {
    title: '召回模式',
    key: 'retrieval_mode',
    width: 100,
    align: 'center',
    render(row) {
      const label =
        retrievalModeOptions.find((o) => o.value === row.retrieval_mode)?.label ||
        row.retrieval_mode
      return h(NTag, { size: 'small' }, { default: () => label })
    },
  },
  {
    title: '切片模式',
    key: 'chunk_mode',
    width: 100,
    align: 'center',
    render(row) {
      const label =
        chunkModeOptions.find((o) => o.value === row.chunk_mode)?.label || row.chunk_mode
      return h(NTag, { size: 'small' }, { default: () => label })
    },
  },
  {
    title: 'Top-K',
    key: 'similarity_top_k',
    width: 80,
    align: 'center',
  },
  {
    title: '关联召回',
    key: 'context_chunks_window',
    width: 90,
    align: 'center',
    render(row) {
      const v = row.context_chunks_window || 0
      return h('span', v > 0 ? `±${v}` : '-')
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
        h(
          NButton,
          {
            size: 'small',
            type: 'info',
            style: 'margin-right: 8px;',
            onClick: () =>
              router.push({ path: '/rag-knowledge/kb-content', query: { kb_id: row.id } }),
          },
          {
            default: () => '管理内容',
            icon: renderIcon('material-symbols:folder-open-outline', { size: 16 }),
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
          [[vPermission, 'post/api/v1/knowledge_base/update']]
        ),
        h(
          NPopconfirm,
          {
            onPositiveClick: () => handleDelete({ kb_id: row.id }, false),
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
                [[vPermission, 'delete/api/v1/knowledge_base/delete']]
              ),
            default: () => h('div', {}, '确定删除该知识库吗? 关联的文档也将被删除。'),
          }
        ),
      ]
    },
  },
]
</script>

<template>
  <CommonPage show-footer title="知识库管理">
    <template #action>
      <NButton v-permission="'post/api/v1/knowledge_base/create'" type="primary" @click="handleAdd">
        <TheIcon icon="material-symbols:add" :size="18" class="mr-5" />新建知识库
      </NButton>
    </template>

    <CrudTable
      ref="$table"
      v-model:query-items="queryItems"
      :columns="columns"
      :get-data="api.getKnowledgeBaseList"
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
          <NInput v-model:value="modalForm.name" placeholder="请输入知识库名称" />
        </NFormItem>
        <NFormItem label="描述" path="description">
          <NInput v-model:value="modalForm.description" type="textarea" placeholder="请输入描述" />
        </NFormItem>
        <NFormItem
          label="Embedding模型"
          path="embedding_model_id"
          :rule="{
            required: true,
            type: 'number',
            message: '请选择Embedding模型',
            trigger: ['change', 'blur'],
          }"
        >
          <NSelect
            v-model:value="modalForm.embedding_model_id"
            :options="embeddingModelOptions"
            placeholder="请选择Embedding模型"
          />
        </NFormItem>
        <NFormItem label="召回模式" path="retrieval_mode">
          <NSelect v-model:value="modalForm.retrieval_mode" :options="retrievalModeOptions" />
        </NFormItem>
        <NFormItem label="切片模式" path="chunk_mode">
          <NSelect v-model:value="modalForm.chunk_mode" :options="chunkModeOptions" />
        </NFormItem>
        <NFormItem label="分块大小" path="chunk_size">
          <NInputNumber
            v-model:value="modalForm.chunk_size"
            :min="64"
            :max="4096"
            style="width: 100%"
          />
        </NFormItem>
        <NFormItem label="分块重叠" path="chunk_overlap">
          <NInputNumber
            v-model:value="modalForm.chunk_overlap"
            :min="0"
            :max="512"
            style="width: 100%"
          />
        </NFormItem>
        <NFormItem label="Top-K" path="similarity_top_k">
          <NInputNumber
            v-model:value="modalForm.similarity_top_k"
            :min="1"
            :max="50"
            style="width: 100%"
          />
        </NFormItem>
        <NFormItem label="相似度阈值" path="similarity_threshold">
          <NInputNumber
            v-model:value="modalForm.similarity_threshold"
            :min="0"
            :max="1"
            :step="0.1"
            style="width: 100%"
          />
        </NFormItem>
        <NFormItem label="关联召回" path="context_chunks_window">
          <NInputNumber
            v-model:value="modalForm.context_chunks_window"
            :min="0"
            :max="5"
            style="width: 100%"
          />
          <template #feedback>
            <span style="color: var(--n-text-color-3, #999); font-size: 12px">
              命中 chunk 后，关联召回同文档前后各 N 个 chunk（0 表示不扩展）
            </span>
          </template>
        </NFormItem>
        <NFormItem label="启用" path="is_active">
          <NSwitch v-model:value="modalForm.is_active" />
        </NFormItem>
      </NForm>
    </CrudModal>
  </CommonPage>
</template>
