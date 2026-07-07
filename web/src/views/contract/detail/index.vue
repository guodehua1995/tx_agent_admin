<script setup>
import { h, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NButton,
  NCard,
  NDescriptions,
  NDescriptionsItem,
  NDivider,
  NEmpty,
  NForm,
  NFormItem,
  NGi,
  NGrid,
  NInput,
  NModal,
  NPopconfirm,
  NSpace,
  NSpin,
  NTag,
  NTree,
} from 'naive-ui'
import MarkdownIt from 'markdown-it'

import CommonPage from '@/components/page/CommonPage.vue'
import { formatDate, renderIcon } from '@/utils'
import api from '@/api'

const md = new MarkdownIt({
  html: true,
  linkify: true,
  typographer: true,
  breaks: true,
})

defineOptions({ name: '合同详情' })

const route = useRoute()
const router = useRouter()

const contractId = ref(Number(route.query.contract_id) || 0)
const loading = ref(false)
const contract = ref(null)
const similarContracts = ref([])

function buildClauseTree(clauses) {
  if (!clauses || clauses.length === 0) return []
  return clauses.map((item) => ({
    key: `clause-${item.id}`,
    label: `${item.clause_title || `条款 ${item.clause_index}`}`,
    children: item.children ? buildClauseTree(item.children) : [],
    prefix: () =>
      h(
        NTag,
        { type: 'info', size: 'tiny', style: 'margin-right: 6px' },
        { default: () => String(item.clause_index) }
      ),
    clause: item,
  }))
}

function clauseTree() {
  if (!contract.value?.clauses) return []
  return buildClauseTree(contract.value.clauses)
}

const selectedClause = ref(null)
const editing = ref(false)
const editText = ref('')
const editLoading = ref(false)

// 新增条款
const showCreateModal = ref(false)
const createForm = ref({ clause_title: '', original_text: '' })
const createLoading = ref(false)

function renderMarkdown(text) {
  if (!text) return ''
  return md.render(text)
}

function handleNodeSelect(keys, option) {
  editing.value = false
  if (option && option.length > 0) {
    selectedClause.value = option[0].clause
  }
}

function startEdit() {
  editText.value = selectedClause.value?.original_text || ''
  editing.value = true
}

function cancelEdit() {
  editing.value = false
  editText.value = ''
}

async function saveEdit() {
  if (!selectedClause.value) return
  editLoading.value = true
  try {
    await api.updateClause({
      id: selectedClause.value.id,
      original_text: editText.value,
    })
    // 更新本地数据
    selectedClause.value.original_text = editText.value
    editing.value = false
    $message?.success('条款已更新，向量库已同步')
  } catch {
    $message?.error('条款更新失败')
  } finally {
    editLoading.value = false
  }
}

function openCreateModal() {
  createForm.value = { clause_title: '', original_text: '' }
  showCreateModal.value = true
}

function closeCreateModal() {
  showCreateModal.value = false
}

async function handleCreate() {
  if (!createForm.value.clause_title.trim() || !createForm.value.original_text.trim()) {
    $message?.warning('条款标题和原文不能为空')
    return
  }
  createLoading.value = true
  try {
    await api.createClause({
      contract_id: contractId.value,
      clause_title: createForm.value.clause_title,
      original_text: createForm.value.original_text,
    })
    showCreateModal.value = false
    $message?.success('条款已创建，向量库已同步')
    await loadContract()
  } catch {
    $message?.error('条款创建失败')
  } finally {
    createLoading.value = false
  }
}

async function handleDelete() {
  if (!selectedClause.value) return
  try {
    await api.deleteClause({ id: selectedClause.value.id })
    selectedClause.value = null
    $message?.success('条款已删除，向量库已同步清理')
    await loadContract()
  } catch {
    $message?.error('条款删除失败')
  }
}

function getStatusTag(status) {
  const map = {
    pending_extract: { label: '待提取', type: 'default' },
    extracted: { label: '已提取', type: 'info' },
    slicing: { label: '切片中', type: 'warning' },
    pending_review: { label: '待审核', type: 'warning' },
    approved: { label: '已通过', type: 'success' },
    vectorizing: { label: '向量化中', type: 'info' },
    completed: { label: '已完成', type: 'success' },
    rejected: { label: '已拒绝', type: 'error' },
    failed: { label: '失败', type: 'error' },
  }
  return map[status] || { label: status, type: 'default' }
}

async function loadContract() {
  if (!contractId.value) return
  loading.value = true
  try {
    const res = await api.getContractDetail({ contract_id: contractId.value })
    contract.value = res.data
    // 加载相似合同
    loadSimilar()
  } catch {
    $message?.error('获取合同详情失败')
  } finally {
    loading.value = false
  }
}

async function loadSimilar() {
  try {
    const res = await api.findSimilarContracts({
      contract_id: contractId.value,
      limit: 5,
    })
    similarContracts.value = res.data || []
  } catch {
    // 静默失败
  }
}

function goBack() {
  router.push({ name: '合同列表' })
}

function goToCompare() {
  router.push({
    name: '合同对比',
    query: { contract_id: contractId.value },
  })
}

function viewContract(id) {
  router.push({ name: '合同详情', query: { contract_id: id } })
}

onMounted(() => {
  loadContract()
})
</script>

<template>
  <CommonPage show-footer title="合同详情">
    <template #action>
      <NButton @click="goBack">
        <TheIcon icon="material-symbols:arrow-back" :size="18" class="mr-5" />返回列表
      </NButton>
      <NButton type="primary" style="margin-left: 12px" @click="goToCompare">
        <TheIcon icon="material-symbols:compare-arrows" :size="18" class="mr-5" />对比合同
      </NButton>
    </template>

    <NSpin :show="loading">
      <template v-if="contract">
        <!-- 合同基本信息 -->
        <NCard title="基本信息" size="small" style="margin-bottom: 16px">
          <NDescriptions :column="3" label-placement="left" bordered>
            <NDescriptionsItem label="项目名称">
              {{ contract.project_name || contract.document_title || '-' }}
            </NDescriptionsItem>
            <NDescriptionsItem label="合同类型">
              <NTag type="info" size="small">
                {{ contract.contract_type_name || '未分类' }}
              </NTag>
            </NDescriptionsItem>
            <NDescriptionsItem label="文档状态">
              <NTag
                v-if="contract.document_status"
                :type="getStatusTag(contract.document_status).type"
                size="small"
              >
                {{ getStatusTag(contract.document_status).label }}
              </NTag>
              <span v-else>-</span>
            </NDescriptionsItem>
            <NDescriptionsItem label="合同链接">
              <a
                v-if="contract.document_url"
                :href="contract.document_url"
                target="_blank"
                rel="noopener noreferrer"
                style="color: #1890ff; text-decoration: none"
              >
                <TheIcon icon="material-symbols:link" :size="16" class="mr-5" />访问合同
              </a>
              <span v-else>-</span>
            </NDescriptionsItem>
            <NDescriptionsItem label="甲方">
              {{ contract.party_a_name || '-' }}
            </NDescriptionsItem>
            <NDescriptionsItem label="乙方">
              {{ contract.party_b_name || '-' }}
            </NDescriptionsItem>
            <NDescriptionsItem label="签订日期">
              {{ contract.signing_date ? formatDate(contract.signing_date) : '-' }}
            </NDescriptionsItem>
            <NDescriptionsItem label="生效日期">
              {{ contract.effective_date ? formatDate(contract.effective_date) : '-' }}
            </NDescriptionsItem>
            <NDescriptionsItem label="到期日期">
              <NTag
                v-if="contract.expiry_date"
                :type="
                  new Date(contract.expiry_date) < new Date()
                    ? 'error'
                    : (new Date(contract.expiry_date) - new Date()) / (1000 * 60 * 60 * 24) < 30
                    ? 'warning'
                    : 'default'
                "
                size="small"
              >
                {{ formatDate(contract.expiry_date) }}
              </NTag>
              <span v-else>-</span>
            </NDescriptionsItem>
            <NDescriptionsItem label="合同金额">
              {{
                contract.total_amount != null ? Number(contract.total_amount).toLocaleString() : '-'
              }}
            </NDescriptionsItem>
            <NDescriptionsItem label="条款数量">
              {{ contract.clause_count || 0 }}
            </NDescriptionsItem>
          </NDescriptions>
          <div v-if="contract.summary" style="margin-top: 12px">
            <NDivider title-placement="left"> 合同摘要 </NDivider>
            <p style="white-space: pre-wrap; color: #666">{{ contract.summary }}</p>
          </div>
        </NCard>

        <!-- 条款树 + 条款详情 -->
        <NGrid :cols="24" :x-gap="16">
          <NGi :span="8">
            <NCard title="条款目录" size="small" style="max-height: 600px; overflow-y: auto">
              <NTree
                v-if="clauseTree().length > 0"
                :data="clauseTree()"
                :default-expand-all="false"
                selectable
                block-line
                @update:selected-keys="(keys, option) => handleNodeSelect(keys, option)"
              />
              <NEmpty v-else description="暂无条款数据" />
            </NCard>
          </NGi>
          <NGi :span="16">
            <NCard title="条款详情" size="small" style="max-height: 600px; overflow-y: auto">
              <template #header-extra>
                <NButton size="small" type="info" @click="openCreateModal">
                  <TheIcon icon="material-symbols:add" :size="16" class="mr-5" />新增
                </NButton>
              </template>
              <template v-if="selectedClause">
                <div
                  style="
                    margin-bottom: 12px;
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                  "
                >
                  <div>
                    <NTag type="info" size="small" style="margin-right: 8px">
                      序号: {{ selectedClause.clause_index }}
                    </NTag>
                    <NTag v-if="selectedClause.clause_level" type="default" size="small">
                      层级: {{ selectedClause.clause_level }}
                    </NTag>
                  </div>
                  <NSpace v-if="!editing">
                    <NButton size="small" type="primary" @click="startEdit">
                      <TheIcon icon="material-symbols:edit-outline" :size="16" class="mr-5" />编辑
                    </NButton>
                    <NPopconfirm @positive-click="handleDelete">
                      <template #trigger>
                        <NButton size="small" type="error">
                          <TheIcon
                            icon="material-symbols:delete-outline"
                            :size="16"
                            class="mr-5"
                          />删除
                        </NButton>
                      </template>
                      确定删除该条款及其子条款吗？向量库将同步清理。
                    </NPopconfirm>
                  </NSpace>
                </div>
                <h3 style="margin-bottom: 8px">
                  {{ selectedClause.clause_title || `条款 ${selectedClause.clause_index}` }}
                </h3>
                <div
                  v-if="selectedClause.summary"
                  style="
                    margin-bottom: 16px;
                    padding: 12px;
                    background: #f6f8fa;
                    border-radius: 6px;
                    font-size: 13px;
                    color: #666;
                  "
                >
                  <strong>摘要：</strong>{{ selectedClause.summary }}
                </div>
                <!-- 编辑模式 -->
                <template v-if="editing">
                  <NInput
                    v-model:value="editText"
                    type="textarea"
                    :rows="15"
                    placeholder="请输入条款原文（支持 Markdown 格式）"
                    style="margin-bottom: 12px"
                  />
                  <div style="display: flex; gap: 8px">
                    <NButton type="primary" size="small" :loading="editLoading" @click="saveEdit">
                      保存
                    </NButton>
                    <NButton size="small" @click="cancelEdit"> 取消 </NButton>
                  </div>
                </template>
                <!-- 预览模式 -->
                <div
                  v-else
                  class="markdown-body"
                  style="line-height: 1.8; font-size: 14px"
                  v-html="renderMarkdown(selectedClause.original_text)"
                />
              </template>
              <NEmpty v-else description="请在左侧选择条款查看详情" />
            </NCard>
          </NGi>
        </NGrid>

        <!-- 新增条款弹窗 -->
        <NModal v-model:show="showCreateModal" title="新增条款" preset="card" style="width: 600px">
          <NForm label-placement="left" label-width="80">
            <NFormItem label="条款标题" required>
              <NInput v-model:value="createForm.clause_title" placeholder="如：违约责任" />
            </NFormItem>
            <NFormItem label="条款原文" required>
              <NInput
                v-model:value="createForm.original_text"
                type="textarea"
                :rows="12"
                placeholder="请输入条款原文（支持 Markdown 格式）"
              />
            </NFormItem>
          </NForm>
          <template #footer>
            <NSpace justify="end">
              <NButton @click="closeCreateModal">取消</NButton>
              <NButton type="primary" :loading="createLoading" @click="handleCreate">
                创建并同步向量库
              </NButton>
            </NSpace>
          </template>
        </NModal>

        <!-- 相似合同 -->
        <NCard
          v-if="similarContracts.length > 0"
          title="相似合同"
          size="small"
          style="margin-top: 16px"
        >
          <div
            v-for="item in similarContracts"
            :key="item.id"
            style="
              padding: 10px 12px;
              border-bottom: 1px solid #f0f0f0;
              display: flex;
              align-items: center;
              justify-content: space-between;
            "
          >
            <div>
              <NButton text type="primary" @click="viewContract(item.id)">
                {{ item.project_name || item.document_title || '-' }}
              </NButton>
              <NTag size="small" type="info" style="margin-left: 8px">
                {{ item.contract_type_name || '未分类' }}
              </NTag>
            </div>
            <span style="color: #999; font-size: 13px">
              {{ item.party_a_name || '-' }} / {{ item.party_b_name || '-' }}
            </span>
          </div>
        </NCard>
      </template>
      <NEmpty v-else description="合同不存在" />
    </NSpin>
  </CommonPage>
</template>
