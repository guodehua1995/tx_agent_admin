<script setup>
import { h, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NButton,
  NCard,
  NDivider,
  NEmpty,
  NGi,
  NGrid,
  NInput,
  NSelect,
  NSpin,
  NTag,
  NCollapse,
  NCollapseItem,
} from 'naive-ui'

import CommonPage from '@/components/page/CommonPage.vue'
import { renderIcon } from '@/utils'
import api from '@/api'

defineOptions({ name: '合同对比' })

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const contractOptions = ref([])
const selectedContractIds = ref([])
const clauseTitle = ref('')
const summaryResult = ref([])
const fulltextResult = ref([])
const compareMode = ref('summary')

async function loadContracts() {
  try {
    const res = await api.getContractList({ page: 1, page_size: 9999 })
    contractOptions.value = (res.data || []).map((item) => ({
      label: `${item.project_name || item.document_title || '-'} (${item.party_a_name || ''})`,
      value: item.id,
    }))
    // 如果从详情页跳转过来，预选该合同
    const cid = route.query.contract_id
    if (cid) {
      selectedContractIds.value = [Number(cid)]
    }
  } catch {
    $message?.error('加载合同列表失败')
  }
}

async function handleCompare() {
  if (!clauseTitle.value.trim()) {
    $message?.warning('请输入条款标题关键词')
    return
  }
  if (selectedContractIds.value.length < 2 && compareMode.value === 'fulltext') {
    $message?.warning('全文对比至少需要选择 2 个合同')
    return
  }

  loading.value = true
  try {
    if (compareMode.value === 'summary') {
      const res = await api.compareClauseSummaries({
        clause_title: clauseTitle.value.trim(),
        contract_ids: selectedContractIds.value.length > 0 ? selectedContractIds.value : null,
      })
      summaryResult.value = res.data || []
      fulltextResult.value = []
    } else {
      const res = await api.compareClauseFulltext({
        clause_title: clauseTitle.value.trim(),
        contract_ids: selectedContractIds.value,
      })
      fulltextResult.value = res.data || []
      summaryResult.value = []
    }
  } catch {
    $message?.error('对比失败')
  } finally {
    loading.value = false
  }
}

// 按合同分组
function groupedByContract(items) {
  const map = {}
  items.forEach((item) => {
    const key = item.contract_id
    if (!map[key]) {
      map[key] = { contract_id: key, items: [] }
    }
    map[key].items.push(item)
  })
  return Object.values(map)
}

function goBack() {
  router.push({ name: '合同列表' })
}

function viewContract(id) {
  router.push({ name: '合同详情', query: { contract_id: id } })
}

onMounted(() => {
  loadContracts()
})
</script>

<template>
  <CommonPage show-footer title="合同对比">
    <template #action>
      <NButton @click="goBack">
        <TheIcon icon="material-symbols:arrow-back" :size="18" class="mr-5" />返回列表
      </NButton>
    </template>

    <!-- 对比条件 -->
    <NCard title="对比条件" size="small" style="margin-bottom: 16px">
      <NGrid :cols="24" :x-gap="16" :y-gap="12">
        <NGi :span="8">
          <NInput
            v-model:value="clauseTitle"
            placeholder="请输入条款标题关键词，如：违约责任"
            @keypress.enter="handleCompare"
          />
        </NGi>
        <NGi :span="10">
          <NSelect
            v-model:value="selectedContractIds"
            :options="contractOptions"
            multiple
            placeholder="限定合同范围（可选，不选则对比全部合同）"
            clearable
            filterable
            :max-tag-count="3"
          />
        </NGi>
        <NGi :span="4">
          <NSelect
            v-model:value="compareMode"
            :options="[
              { label: '摘要对比', value: 'summary' },
              { label: '全文对比', value: 'fulltext' },
            ]"
          />
        </NGi>
        <NGi :span="2">
          <NButton type="primary" :loading="loading" @click="handleCompare" block>
            <TheIcon icon="material-symbols:compare-arrows" :size="18" class="mr-5" />对比
          </NButton>
        </NGi>
      </NGrid>
    </NCard>

    <NSpin :show="loading">
      <!-- 摘要对比结果 -->
      <template v-if="summaryResult.length > 0">
        <NCard
          v-for="(group, gIdx) in groupedByContract(summaryResult)"
          :key="group.contract_id"
          size="small"
          style="margin-bottom: 12px"
        >
          <template #header>
            <NButton text type="primary" @click="viewContract(group.contract_id)">
              合同 #{{ group.contract_id }}
            </NButton>
          </template>
          <div
            v-for="(item, idx) in group.items"
            :key="idx"
            style="padding: 10px 0; border-bottom: 1px solid #f5f5f5"
          >
            <div style="margin-bottom: 6px">
              <NTag type="info" size="small" style="margin-right: 6px">
                {{ item.clause_index }}
              </NTag>
              <strong>{{ item.clause_title }}</strong>
            </div>
            <div style="color: #666; font-size: 13px; white-space: pre-wrap">
              {{ item.summary || '无摘要' }}
            </div>
          </div>
        </NCard>
      </template>

      <!-- 全文对比结果 -->
      <template v-if="fulltextResult.length > 0">
        <NCard
          v-for="(group, gIdx) in groupedByContract(fulltextResult)"
          :key="group.contract_id"
          size="small"
          style="margin-bottom: 12px"
        >
          <template #header>
            <NButton text type="primary" @click="viewContract(group.contract_id)">
              合同 #{{ group.contract_id }}
            </NButton>
          </template>
          <NCollapse>
            <NCollapseItem
              v-for="(item, idx) in group.items"
              :key="idx"
              :title="`${item.clause_title || ''} (序号: ${item.clause_index})`"
              :name="`${group.contract_id}-${idx}`"
            >
              <div style="white-space: pre-wrap; line-height: 1.8; font-size: 14px">
                {{ item.original_text }}
              </div>
            </NCollapseItem>
          </NCollapse>
        </NCard>
      </template>

      <NEmpty
        v-if="summaryResult.length === 0 && fulltextResult.length === 0 && !loading"
        description="请输入条款标题关键词并点击对比"
      />
    </NSpin>
  </CommonPage>
</template>