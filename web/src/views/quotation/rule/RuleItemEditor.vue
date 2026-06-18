<script setup>
import { h } from 'vue'
import {
  NButton,
  NCard,
  NDataTable,
  NFormItem,
  NInput,
  NInputNumber,
  NSpace,
} from 'naive-ui'

const props = defineProps({
  items: {
    type: Array,
    default: () => [],
  },
  readonly: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['update:items'])

function updateItems(newItems) {
  emit('update:items', [...newItems])
}

// ── 一级项目操作 ──
function addLevel1() {
  const items = [...props.items]
  items.push({
    _key: Date.now() + Math.random(),
    name: '',
    code: '',
    unit_price: null,
    unit: '',
    remark: '',
    sort_order: items.length,
    children: [],
  })
  updateItems(items)
}

function removeLevel1(index) {
  const items = [...props.items]
  items.splice(index, 1)
  updateItems(items)
}

function moveLevel1(index, direction) {
  const items = [...props.items]
  const targetIndex = index + direction
  if (targetIndex < 0 || targetIndex >= items.length) return
  ;[items[index], items[targetIndex]] = [items[targetIndex], items[index]]
  items.forEach((item, i) => (item.sort_order = i))
  updateItems(items)
}

// ── 二级项目操作 ──
function addLevel2(parentIndex) {
  const items = [...props.items]
  const parent = { ...items[parentIndex] }
  parent.children = [...(parent.children || [])]
  parent.children.push({
    _key: Date.now() + Math.random(),
    name: '',
    code: '',
    unit_price: null,
    unit: '',
    remark: '',
    sort_order: parent.children.length,
  })
  items[parentIndex] = parent
  updateItems(items)
}

function removeLevel2(parentIndex, childIndex) {
  const items = [...props.items]
  const parent = { ...items[parentIndex] }
  parent.children = [...(parent.children || [])]
  parent.children.splice(childIndex, 1)
  items[parentIndex] = parent
  updateItems(items)
}

function moveLevel2(parentIndex, childIndex, direction) {
  const items = [...props.items]
  const parent = { ...items[parentIndex] }
  parent.children = [...(parent.children || [])]
  const targetIndex = childIndex + direction
  if (targetIndex < 0 || targetIndex >= parent.children.length) return
  ;[parent.children[childIndex], parent.children[targetIndex]] = [
    parent.children[targetIndex],
    parent.children[childIndex],
  ]
  parent.children.forEach((item, i) => (item.sort_order = i))
  items[parentIndex] = parent
  updateItems(items)
}

function updateLevel1Field(index, field, value) {
  const items = [...props.items]
  items[index] = { ...items[index], [field]: value }
  updateItems(items)
}

function updateLevel2Field(parentIndex, childIndex, field, value) {
  const items = [...props.items]
  const parent = { ...items[parentIndex] }
  parent.children = [...(parent.children || [])]
  parent.children[childIndex] = { ...parent.children[childIndex], [field]: value }
  items[parentIndex] = parent
  updateItems(items)
}

// ── 只读模式下的树形表格列 ──
const readonlyColumns = [
  { title: '项目名称', key: 'name', width: 200, ellipsis: { tooltip: true } },
  { title: '编码', key: 'code', width: 120 },
  {
    title: '单价',
    key: 'unit_price',
    width: 120,
    render(row) {
      return row.unit_price != null ? h('span', row.unit_price.toFixed(4)) : h('span', '-')
    },
  },
  { title: '单位', key: 'unit', width: 80 },
  { title: '备注', key: 'remark', width: 150, ellipsis: { tooltip: true } },
]

function getTreeData() {
  return (props.items || []).map((item, i) => ({
    key: item._key || `l1-${i}`,
    name: item.name,
    code: item.code,
    unit_price: item.unit_price,
    unit: item.unit,
    remark: item.remark,
    children: (item.children || []).map((child, j) => ({
      key: child._key || `l2-${i}-${j}`,
      name: child.name,
      code: child.code,
      unit_price: child.unit_price,
      unit: child.unit,
      remark: child.remark,
    })),
  }))
}
</script>

<template>
  <!-- 只读模式：树形表格 -->
  <div v-if="readonly">
    <NDataTable
      :columns="readonlyColumns"
      :data="getTreeData()"
      :row-key="(row) => row.key"
      default-expand-all
      size="small"
    />
  </div>

  <!-- 编辑模式 -->
  <div v-else>
    <NSpace vertical>
      <NButton type="primary" size="small" @click="addLevel1">
        + 新增一级项目
      </NButton>

      <NCard
        v-for="(item, index) in items"
        :key="item._key || index"
        size="small"
        :bordered="true"
        style="margin-bottom: 8px"
      >
        <template #header>
          <NSpace align="center" size="small">
            <span style="font-weight: 600">一级项目 {{ index + 1 }}</span>
            <NButton size="tiny" quaternary :disabled="index === 0" @click="moveLevel1(index, -1)">
              ↑
            </NButton>
            <NButton
              size="tiny"
              quaternary
              :disabled="index === items.length - 1"
              @click="moveLevel1(index, 1)"
            >
              ↓
            </NButton>
            <NButton size="tiny" type="error" quaternary @click="removeLevel1(index)">
              删除
            </NButton>
          </NSpace>
        </template>

        <NSpace vertical size="small">
          <NSpace>
            <NFormItem label="名称" :show-feedback="false" label-placement="left">
              <NInput
                :value="item.name"
                placeholder="项目名称"
                style="width: 180px"
                @update:value="(v) => updateLevel1Field(index, 'name', v)"
              />
            </NFormItem>
            <NFormItem label="编码" :show-feedback="false" label-placement="left">
              <NInput
                :value="item.code"
                placeholder="编码"
                style="width: 120px"
                @update:value="(v) => updateLevel1Field(index, 'code', v)"
              />
            </NFormItem>
            <NFormItem label="备注" :show-feedback="false" label-placement="left">
              <NInput
                :value="item.remark"
                placeholder="备注"
                style="width: 150px"
                @update:value="(v) => updateLevel1Field(index, 'remark', v)"
              />
            </NFormItem>
          </NSpace>

          <!-- 二级明细 -->
          <NButton size="tiny" dashed @click="addLevel2(index)">
            + 新增二级项目
          </NButton>

          <div
            v-for="(child, ci) in item.children || []"
            :key="child._key || ci"
            style="
              display: flex;
              align-items: center;
              gap: 6px;
              padding: 4px 0;
              border-bottom: 1px dashed #eee;
            "
          >
            <NInput
              :value="child.name"
              placeholder="名称"
              size="small"
              style="width: 140px"
              @update:value="(v) => updateLevel2Field(index, ci, 'name', v)"
            />
            <NInput
              :value="child.code"
              placeholder="编码"
              size="small"
              style="width: 100px"
              @update:value="(v) => updateLevel2Field(index, ci, 'code', v)"
            />
            <NInputNumber
              :value="child.unit_price"
              placeholder="单价"
              size="small"
              :precision="4"
              :min="0"
              style="width: 120px"
              @update:value="(v) => updateLevel2Field(index, ci, 'unit_price', v)"
            />
            <NInput
              :value="child.unit"
              placeholder="单位"
              size="small"
              style="width: 70px"
              @update:value="(v) => updateLevel2Field(index, ci, 'unit', v)"
            />
            <NInput
              :value="child.remark"
              placeholder="备注"
              size="small"
              style="width: 120px"
              @update:value="(v) => updateLevel2Field(index, ci, 'remark', v)"
            />
            <NButton
              size="tiny"
              quaternary
              :disabled="ci === 0"
              @click="moveLevel2(index, ci, -1)"
            >
              ↑
            </NButton>
            <NButton
              size="tiny"
              quaternary
              :disabled="ci === (item.children || []).length - 1"
              @click="moveLevel2(index, ci, 1)"
            >
              ↓
            </NButton>
            <NButton size="tiny" type="error" quaternary @click="removeLevel2(index, ci)">
              ×
            </NButton>
          </div>
        </NSpace>
      </NCard>
    </NSpace>
  </div>
</template>
