<script setup>
import { h, onMounted, ref } from 'vue'
import {
  NButton,
  NDrawer,
  NDrawerContent,
  NSelect,
  NTag,
} from 'naive-ui'

import CommonPage from '@/components/page/CommonPage.vue'
import QueryBarItem from '@/components/query-bar/QueryBarItem.vue'
import CrudTable from '@/components/table/CrudTable.vue'
import RuleItemEditor from '../rule/RuleItemEditor.vue'

import { formatDate } from '@/utils'
import api from '@/api'

defineOptions({ name: '版本归档' })

const $table = ref(null)
const queryItems = ref({})

// ── 甲方选项 ──
const clientOptions = ref([])
async function loadClients(keyword = '') {
  const res = await api.getClientList({ keyword, page: 1, page_size: 100 })
  clientOptions.value = (res.data || []).map((c) => ({
    label: c.name,
    value: c.id,
  }))
}

function handleClientChange(val) {
  if (val) {
    $table.value?.handleSearch()
  }
}

// ── 快照 Drawer ──
const snapshotVisible = ref(false)
const snapshotItems = ref([])
const snapshotLoading = ref(false)
const snapshotTitle = ref('')

async function viewSnapshot(row) {
  snapshotTitle.value = `版本 v${row.version} 快照`
  try {
    snapshotLoading.value = true
    const res = await api.getArchiveDetail({ archive_id: row.id })
    const data = res.data || {}
    // 快照结构为 { rule: {...}, items: [...] }，只取 items 数组传给明细编辑器
    snapshotItems.value = data.snapshot?.items || []
    snapshotVisible.value = true
  } finally {
    snapshotLoading.value = false
  }
}

onMounted(() => {
  loadClients()
})

const reasonLabelMap = {
  new_version: '新版本生效',
  reimport: '重新导入',
}

const columns = [
  {
    title: '版本号',
    key: 'version',
    width: 80,
    align: 'center',
    render(row) {
      return h('span', `v${row.version}`)
    },
  },
  {
    title: '归档原因',
    key: 'archived_reason',
    width: 120,
    align: 'center',
    render(row) {
      const label = reasonLabelMap[row.archived_reason] || row.archived_reason || '-'
      return h(NTag, { size: 'small' }, { default: () => label })
    },
  },
  {
    title: '归档人',
    key: 'archived_by',
    width: 100,
    align: 'center',
    render(row) {
      return h('span', row.archived_by_name || row.archived_by || '-')
    },
  },
  {
    title: '归档时间',
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
    width: 80,
    align: 'center',
    render(row) {
      return h(
        NButton,
        {
          size: 'small',
          type: 'info',
          onClick: () => viewSnapshot(row),
        },
        { default: () => '查看' }
      )
    },
  },
]
</script>

<template>
  <CommonPage show-footer title="版本归档">
    <CrudTable
      ref="$table"
      v-model:query-items="queryItems"
      :columns="columns"
      :get-data="api.getArchiveList"
      :is-pagination="false"
    >
      <template #queryBar>
        <QueryBarItem label="甲方" :label-width="40">
          <NSelect
            v-model:value="queryItems.client_id"
            :options="clientOptions"
            filterable
            remote
            placeholder="请选择甲方"
            style="width: 260px"
            @search="loadClients"
            @update:value="handleClientChange"
          />
        </QueryBarItem>
      </template>
    </CrudTable>

    <!-- 快照详情 Drawer -->
    <NDrawer :show="snapshotVisible" :width="700" @update:show="(v) => (snapshotVisible = v)">
      <NDrawerContent :title="snapshotTitle" closable>
        <RuleItemEditor :items="snapshotItems" readonly />
        <template #footer>
          <NButton @click="snapshotVisible = false">关闭</NButton>
        </template>
      </NDrawerContent>
    </NDrawer>
  </CommonPage>
</template>
