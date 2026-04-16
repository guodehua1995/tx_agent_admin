<script setup>
import { h, onMounted, ref, resolveDirective, withDirectives } from 'vue'
import {
  NButton,
  NCard,
  NDescriptions,
  NDescriptionsItem,
  NDrawer,
  NDrawerContent,
  NEmpty,
  NInput,
  NSelect,
  NSpace,
  NSpin,
  NTag,
  NTimeline,
  NTimelineItem,
} from 'naive-ui'
import { useRouter } from 'vue-router'

import CommonPage from '@/components/page/CommonPage.vue'
import QueryBarItem from '@/components/query-bar/QueryBarItem.vue'
import CrudTable from '@/components/table/CrudTable.vue'

import { formatDate, renderIcon } from '@/utils'
import api from '@/api'

defineOptions({ name: '审核管理' })

const router = useRouter()

const $table = ref(null)
const queryItems = ref({})
const vPermission = resolveDirective('permission')

const statusOptions = [
  { label: '待审核', value: 'pending_review' },
  { label: '已通过', value: 'approved' },
  { label: '已拒绝', value: 'rejected' },
]

const statusColorMap = {
  pending_review: 'warning',
  approved: 'success',
  rejected: 'error',
}

// Review drawer state
const drawerVisible = ref(false)
const reviewDoc = ref(null)
const reviewDocContent = ref('')
const reviewHistory = ref([])
const reviewComment = ref('')
const reviewLoading = ref(false)
const drawerContentLoading = ref(false)

async function openReviewDrawer(row) {
  drawerVisible.value = true
  reviewDoc.value = row
  reviewDocContent.value = ''
  reviewComment.value = ''
  reviewHistory.value = []
  drawerContentLoading.value = true
  try {
    const [docRes, histRes] = await Promise.all([
      api.getDocument({ document_id: row.id }),
      api.getReviewHistory({ document_id: row.id }),
    ])
    reviewDoc.value = docRes.data
    reviewDocContent.value = docRes.data?.content || ''
    reviewHistory.value = histRes.data || []
  } catch {
    reviewHistory.value = []
  } finally {
    drawerContentLoading.value = false
  }
}

async function handleApprove() {
  if (!reviewDoc.value) return
  reviewLoading.value = true
  try {
    const res = await api.approveReview({
      document_id: reviewDoc.value.id,
      action: 'approve',
      comment: reviewComment.value || undefined,
    })
    if (res.code === 0) {
      $message?.success('审核通过')
      drawerVisible.value = false
      $table.value?.handleSearch()
    } else {
      $message?.error(res.msg || '操作失败')
    }
  } catch {
    $message?.error('操作失败')
  } finally {
    reviewLoading.value = false
  }
}

async function handleReject() {
  if (!reviewDoc.value) return
  reviewLoading.value = true
  try {
    const res = await api.rejectReview({
      document_id: reviewDoc.value.id,
      action: 'reject',
      comment: reviewComment.value || undefined,
    })
    if (res.code === 0) {
      $message?.success('已拒绝')
      drawerVisible.value = false
      $table.value?.handleSearch()
    } else {
      $message?.error(res.msg || '操作失败')
    }
  } catch {
    $message?.error('操作失败')
  } finally {
    reviewLoading.value = false
  }
}

async function handleEditFromReview() {
  if (!reviewDoc.value) return
  reviewLoading.value = true
  try {
    const res = await api.rejectReview({
      document_id: reviewDoc.value.id,
      action: 'reject',
      comment: '审核人转为编辑，自动驳回',
    })
    if (res.code === 0) {
      drawerVisible.value = false
      router.push({ path: '/rag-knowledge/document', query: { edit_doc_id: reviewDoc.value.id } })
    } else {
      $message?.error(res.msg || '驳回失败，无法跳转编辑')
    }
  } catch {
    $message?.error('驳回失败，无法跳转编辑')
  } finally {
    reviewLoading.value = false
  }
}

onMounted(() => {
  $table.value?.handleSearch()
})

const columns = [
  {
    title: '文档标题',
    key: 'title',
    width: 200,
    align: 'center',
    ellipsis: { tooltip: true },
  },
  {
    title: '来源类型',
    key: 'source_type',
    width: 100,
    align: 'center',
    render(row) {
      const labelMap = { feishu_doc: '飞书文档', file_upload: '文件上传', web_url: '网页链接' }
      return h(NTag, { size: 'small' }, { default: () => labelMap[row.source_type] || row.source_type })
    },
  },
  {
    title: '状态',
    key: 'status',
    width: 100,
    align: 'center',
    render(row) {
      const labelMap = { pending_review: '待审核', approved: '已通过', rejected: '已拒绝' }
      return h(NTag, { type: statusColorMap[row.status] || 'default', size: 'small' }, { default: () => labelMap[row.status] || row.status })
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
    width: 200,
    align: 'center',
    fixed: 'right',
    render(row) {
      const buttons = [
        h(
          NButton,
          { size: 'small', type: 'info', style: 'margin-right: 8px;', onClick: () => openReviewDrawer(row) },
          { default: () => '查看', icon: renderIcon('material-symbols:visibility-outline', { size: 16 }) }
        ),
      ]
      if (row.status === 'pending_review') {
        buttons.push(
          withDirectives(
            h(
              NButton,
              {
                size: 'small',
                type: 'success',
                style: 'margin-right: 8px;',
                onClick: async () => {
                  reviewDoc.value = row
                  reviewComment.value = ''
                  await handleApprove()
                },
              },
              { default: () => '通过', icon: renderIcon('material-symbols:check', { size: 16 }) }
            ),
            [[vPermission, 'post/api/v1/review/approve']]
          ),
          withDirectives(
            h(
              NButton,
              {
                size: 'small',
                type: 'error',
                onClick: async () => {
                  reviewDoc.value = row
                  reviewComment.value = ''
                  await handleReject()
                },
              },
              { default: () => '拒绝', icon: renderIcon('material-symbols:close', { size: 16 }) }
            ),
            [[vPermission, 'post/api/v1/review/reject']]
          )
        )
      }
      return buttons
    },
  },
]
</script>

<template>
  <CommonPage show-footer title="审核管理">
    <CrudTable
      ref="$table"
      v-model:query-items="queryItems"
      :columns="columns"
      :get-data="api.getReviewList"
    >
      <template #queryBar>
        <QueryBarItem label="状态" :label-width="40">
          <NSelect
            v-model:value="queryItems.status"
            clearable
            :options="statusOptions"
            placeholder="请选择状态"
          />
        </QueryBarItem>
      </template>
    </CrudTable>

    <!-- Review Detail Drawer -->
    <NDrawer v-model:show="drawerVisible" placement="right" :width="600">
      <NDrawerContent title="审核详情">
        <NSpin :show="drawerContentLoading">
          <template v-if="reviewDoc">
            <NDescriptions label-placement="left" :column="1" bordered size="small">
              <NDescriptionsItem label="文档标题">{{ reviewDoc.title }}</NDescriptionsItem>
              <NDescriptionsItem label="来源类型">{{ reviewDoc.source_type }}</NDescriptionsItem>
              <NDescriptionsItem label="状态">
                <NTag :type="statusColorMap[reviewDoc.status] || 'default'" size="small">
                  {{ statusOptions.find((o) => o.value === reviewDoc.status)?.label || reviewDoc.status }}
                </NTag>
              </NDescriptionsItem>
              <NDescriptionsItem label="创建日期">{{ formatDate(reviewDoc.created_at) }}</NDescriptionsItem>
            </NDescriptions>

            <NCard title="文档内容" size="small" style="margin-top: 16px">
              <NInput
                v-if="reviewDocContent"
                :value="reviewDocContent"
                type="textarea"
                :rows="12"
                readonly
                style="font-family: monospace;"
              />
              <NEmpty v-else description="暂无文档内容" />
            </NCard>

            <NCard title="审核历史" size="small" style="margin-top: 16px" v-if="reviewHistory.length">
              <NTimeline>
                <NTimelineItem
                  v-for="(item, idx) in reviewHistory"
                  :key="idx"
                  :type="item.action === 'approve' ? 'success' : 'error'"
                  :title="item.action === 'approve' ? '通过' : '拒绝'"
                  :content="item.comment || '无备注'"
                  :time="formatDate(item.created_at)"
                />
              </NTimeline>
            </NCard>

            <div v-if="reviewDoc.status === 'pending_review'" style="margin-top: 16px">
              <NInput
                v-model:value="reviewComment"
                type="textarea"
                placeholder="审核意见 (可选)"
                :rows="3"
                style="margin-bottom: 12px"
              />
              <NSpace>
               <!-- <NButton
                  v-permission="'post/api/v1/review/reject'"
                  type="warning"
                  :loading="reviewLoading"
                  @click="handleEditFromReview"
                >
                  编辑
                </NButton>-->
              
                <NButton
                  v-permission="'post/api/v1/review/approve'"
                  type="success"
                  :loading="reviewLoading"
                  @click="handleApprove"
                >
                  通过
                </NButton>
                <NButton
                  v-permission="'post/api/v1/review/reject'"
                  type="error"
                  :loading="reviewLoading"
                  @click="handleReject"
                >
                  拒绝
                </NButton>
              </NSpace>
            </div>
          </template>
        </NSpin>
      </NDrawerContent>
    </NDrawer>
  </CommonPage>
</template>
