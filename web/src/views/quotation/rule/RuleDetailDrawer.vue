<script setup>
import { ref, watch } from 'vue'
import {
  NButton,
  NDescriptions,
  NDescriptionsItem,
  NDrawer,
  NDrawerContent,
  NInput,
  NSpace,
  NTag,
} from 'naive-ui'

import RuleItemEditor from './RuleItemEditor.vue'
import api from '@/api'

const props = defineProps({
  visible: {
    type: Boolean,
    default: false,
  },
  rule: {
    type: Object,
    default: null,
  },
  mode: {
    type: String, // 'view' | 'approve'
    default: 'view',
  },
})

const emit = defineEmits(['update:visible', 'refresh'])

const loading = ref(false)
const approvalComment = ref('')
const items = ref([])

const statusColorMap = {
  draft: 'default',
  pending_approval: 'warning',
  active: 'success',
  expired: 'error',
  archived: 'info',
}
const statusLabelMap = {
  draft: '草稿',
  pending_approval: '待审批',
  active: '生效中',
  expired: '已失效',
  archived: '已归档',
}

watch(
  () => props.visible,
  async (val) => {
    if (val && props.rule) {
      await loadDetail()
    } else {
      items.value = []
      approvalComment.value = ''
    }
  }
)

async function loadDetail() {
  try {
    loading.value = true
    const res = await api.getRuleDetail({ rule_id: props.rule.id })
    items.value = res.data?.items || []
  } finally {
    loading.value = false
  }
}

function close() {
  emit('update:visible', false)
}

async function handleApproval(action) {
  if (action === 'reject' && !approvalComment.value.trim()) {
    $message.warning('驳回必须填写审批意见')
    return
  }
  try {
    loading.value = true
    await api.doApproval({
      rule_id: props.rule.id,
      action,
      comment: approvalComment.value,
    })
    $message.success(action === 'approve' ? '审批通过' : '已驳回')
    close()
    emit('refresh')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <NDrawer :show="visible" :width="720" @update:show="(v) => emit('update:visible', v)">
    <NDrawerContent :title="mode === 'approve' ? '审批报价规则' : '报价规则详情'" closable>
      <template v-if="rule">
        <NDescriptions label-placement="left" :column="2" bordered size="small" style="margin-bottom: 16px">
          <NDescriptionsItem label="甲方">{{ rule.client_name || rule.client_id }}</NDescriptionsItem>
          <NDescriptionsItem label="版本">v{{ rule.version }}</NDescriptionsItem>
          <NDescriptionsItem label="状态">
            <NTag :type="statusColorMap[rule.status]" size="small">
              {{ statusLabelMap[rule.status] || rule.status }}
            </NTag>
          </NDescriptionsItem>
          <NDescriptionsItem label="来源">{{ rule.source_type === 'excel_import' ? 'Excel导入' : '手动录入' }}</NDescriptionsItem>
          <NDescriptionsItem label="创建人">{{ rule.creator_name || rule.creator_id }}</NDescriptionsItem>
          <NDescriptionsItem label="创建时间">{{ rule.created_at }}</NDescriptionsItem>
          <NDescriptionsItem v-if="rule.approver_id" label="审批人">{{ rule.approver_name || rule.approver_id }}</NDescriptionsItem>
          <NDescriptionsItem v-if="rule.approved_at" label="审批时间">{{ rule.approved_at }}</NDescriptionsItem>
        </NDescriptions>

        <h4 style="margin-bottom: 8px">明细列表</h4>
        <RuleItemEditor :items="items" readonly />

        <!-- 审批操作区 -->
        <template v-if="mode === 'approve'">
          <div style="margin-top: 24px; border-top: 1px solid #eee; padding-top: 16px">
            <h4 style="margin-bottom: 8px">审批操作</h4>
            <NInput
              v-model:value="approvalComment"
              type="textarea"
              placeholder="请输入审批意见（驳回时必填）"
              :rows="3"
              style="margin-bottom: 12px"
            />
            <NSpace>
              <NButton type="success" :loading="loading" @click="handleApproval('approve')">
                通过
              </NButton>
              <NButton type="error" :loading="loading" @click="handleApproval('reject')">
                驳回
              </NButton>
            </NSpace>
          </div>
        </template>
      </template>

      <template #footer>
        <NButton @click="close">关闭</NButton>
      </template>
    </NDrawerContent>
  </NDrawer>
</template>
