<script setup>
import { computed, h, nextTick, onMounted, ref, resolveDirective, withDirectives } from 'vue'
import {
  NButton,
  NCard,
  NDescriptions,
  NDescriptionsItem,
  NDrawer,
  NDrawerContent,
  NEmpty,
  NImage,
  NInput,
  NSelect,
  NSpace,
  NSpin,
  NTag,
  NTimeline,
  NTimelineItem,
} from 'naive-ui'
import { useRouter } from 'vue-router'
import Vditor from 'vditor'
import 'vditor/dist/index.css'

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

// 分页审核状态
const isPagedDoc = computed(() => reviewDoc.value?.pages?.length > 0)
const pageList = computed(() => reviewDoc.value?.pages || [])
const currentPageIndex = ref(0)
const currentPageDetail = ref(null)
const currentPageContent = ref('')
const pagePreviewContainer = ref(null)

async function openReviewDrawer(row) {
  drawerVisible.value = true
  reviewDoc.value = row
  reviewDocContent.value = ''
  reviewComment.value = ''
  reviewHistory.value = []
  currentPageDetail.value = null
  currentPageContent.value = ''
  currentPageIndex.value = 0
  drawerContentLoading.value = true
  try {
    const [docRes, histRes] = await Promise.all([
      api.getReview({ document_id: row.id }),
      api.getReviewHistory({ document_id: row.id }),
    ])
    reviewDoc.value = docRes.data
    reviewDocContent.value = docRes.data?.content || ''
    reviewHistory.value = histRes.data || []
    // 如果是分页文档，加载第一页
    if (isPagedDoc.value) {
      await loadReviewPageDetail(0)
    }
  } catch {
    reviewHistory.value = []
  } finally {
    drawerContentLoading.value = false
  }
}

async function loadReviewPageDetail(index) {
  const page = pageList.value[index]
  if (!page) return
  currentPageIndex.value = index
  try {
    const res = await api.getDocPageDetail({ doc_id: reviewDoc.value.id, page_number: page.page_number })
    currentPageDetail.value = res.data
    currentPageContent.value = res.data?.content || ''
    // 只读预览
    nextTick(() => {
      if (pagePreviewContainer.value && currentPageContent.value) {
        Vditor.preview(pagePreviewContainer.value, currentPageContent.value, {
          mode: 'light',
          theme: { current: 'light' },
        })
      }
    })
  } catch {
    $message?.error('获取页面详情失败')
  }
}

// 审核仅提交 approve/reject，不提供内容修改能力

async function handleApprove() {
  if (!reviewDoc.value) return
  reviewLoading.value = true
  try {
    const payload = {
      document_id: reviewDoc.value.id,
      action: 'approve',
      comment: reviewComment.value || undefined,
    }
    const res = await api.approveReview(payload)
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
      return h(
        NTag,
        { size: 'small' },
        { default: () => labelMap[row.source_type] || row.source_type }
      )
    },
  },
  {
    title: '状态',
    key: 'status',
    width: 100,
    align: 'center',
    render(row) {
      const labelMap = { pending_review: '待审核', approved: '已通过', rejected: '已拒绝' }
      return h(
        NTag,
        { type: statusColorMap[row.status] || 'default', size: 'small' },
        { default: () => labelMap[row.status] || row.status }
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
    width: 200,
    align: 'center',
    fixed: 'right',
    render(row) {
      const buttons = [
        h(
          NButton,
          {
            size: 'small',
            type: 'info',
            style: 'margin-right: 8px;',
            onClick: () => openReviewDrawer(row),
          },
          {
            default: () => '查看',
            icon: renderIcon('material-symbols:visibility-outline', { size: 16 }),
          }
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
    <NDrawer v-model:show="drawerVisible" placement="right" :width="900">
      <NDrawerContent title="审核详情">
        <NSpin :show="drawerContentLoading">
          <template v-if="reviewDoc">
            <NDescriptions label-placement="left" :column="1" bordered size="small">
              <NDescriptionsItem label="文档标题">{{ reviewDoc.title }}</NDescriptionsItem>
              <NDescriptionsItem label="来源类型">{{ reviewDoc.source_type }}</NDescriptionsItem>
              <NDescriptionsItem label="状态">
                <NTag :type="statusColorMap[reviewDoc.status] || 'default'" size="small">
                  {{
                    statusOptions.find((o) => o.value === reviewDoc.status)?.label ||
                    reviewDoc.status
                  }}
                </NTag>
              </NDescriptionsItem>
              <NDescriptionsItem label="创建日期">{{
                formatDate(reviewDoc.created_at)
              }}</NDescriptionsItem>
            </NDescriptions>

            <!-- 分页文档浏览模式 -->
            <template v-if="isPagedDoc">
              <NCard title="分页浏览" size="small" style="margin-top: 16px">
                <div style="display: flex; gap: 16px">
                  <!-- 左侧：页面缩略图列表 -->
                  <div style="width: 120px; flex-shrink: 0; max-height: 500px; overflow-y: auto">
                    <div
                      v-for="(page, idx) in pageList"
                      :key="page.page_number"
                      :style="{
                        border: idx === currentPageIndex ? '2px solid #18a058' : '1px solid #e0e0e0',
                        borderRadius: '6px',
                        padding: '4px',
                        marginBottom: '6px',
                        cursor: 'pointer',
                        textAlign: 'center',
                        background: idx === currentPageIndex ? '#f0faf4' : '#fff',
                      }"
                      @click="loadReviewPageDetail(idx)"
                    >
                      <NImage
                        v-if="page.screenshot_url"
                        :src="page.screenshot_url"
                        :img-props="{ style: 'width: 100px; border-radius: 4px' }"
                        preview-disabled
                      />
                      <div v-else style="width: 100px; height: 56px; background: #f5f5f5; border-radius: 4px; display: flex; align-items: center; justify-content: center; color: #999; font-size: 12px">
                        无截图
                      </div>
                      <div style="font-size: 11px; margin-top: 2px; color: #666">第 {{ page.page_number }} 页</div>
                    </div>
                  </div>

                  <!-- 右侧：当前页截图+内容 -->
                  <div style="flex: 1; min-width: 0">
                    <div v-if="currentPageDetail?.screenshot_url" style="margin-bottom: 12px">
                      <NImage
                        :src="currentPageDetail.screenshot_url"
                        :img-props="{ style: 'max-width: 100%; border-radius: 4px' }"
                      />
                    </div>
                    <NCard size="small" :title="`第 ${currentPageDetail?.page_number || '-'} 页内容`">
                      <NInput
                        v-if="reviewDoc.status === 'pending_review'"
                        v-model:value="currentPageContent"
                        type="textarea"
                        :rows="10"
                        placeholder="暂无页面内容"
                        style="font-family: monospace"
                        @blur="saveCurrentPageEdit"
                      />
                      <template v-else>
                        <div v-if="currentPageContent" ref="pagePreviewContainer" class="vditor-preview" />
                        <NEmpty v-else description="暂无页面内容" />
                      </template>
                    </NCard>
                  </div>
                </div>
              </NCard>
            </template>

            <!-- 非分页文档内容 -->
            <template v-else>
              <NCard title="文档内容" size="small" style="margin-top: 16px">
                <NInput
                  v-if="reviewDocContent"
                  :value="reviewDocContent"
                  type="textarea"
                  :rows="12"
                  readonly
                  style="font-family: monospace"
                />
                <NEmpty v-else description="暂无文档内容" />
              </NCard>
            </template>

            <NCard
              v-if="reviewHistory.length"
              title="审核历史"
              size="small"
              style="margin-top: 16px"
            >
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
