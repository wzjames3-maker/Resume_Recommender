<template>
  <div class="hr-page p-16-24">
    <div class="flex-between mb-16">
      <div>
        <h2>人事成员</h2>
        <span class="color-secondary">为工作空间成员授予 HR 模块访问权限</span>
      </div>
      <el-button type="primary" :loading="saving" :disabled="!changedItems.length" @click="saveAll">保存修改</el-button>
    </div>

    <el-card style="--el-card-padding: 0" v-loading="loading">
      <el-table :data="members">
        <el-table-column prop="nick_name" label="成员" min-width="160" />
        <el-table-column label="工作空间角色" min-width="150">
          <template #default="{ row }">{{ row.roles?.join('、') || '-' }}</template>
        </el-table-column>
        <el-table-column label="HR 角色" width="240">
          <template #default="{ row }">
            <el-select v-model="row.hr_role" placeholder="未授权" clearable>
              <el-option v-for="(label, value) in roleLabels" :key="value" :label="label" :value="value" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="权限说明" min-width="260">
          <template #default="{ row }">{{ roleHints[row.hr_role || ''] }}</template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import HrApi from '@/api/hr/recruitment'
import type { HrAccessMember, HrAccessSetItem, HrRole } from '@/api/type/hr'
import { MsgError, MsgSuccess } from '@/utils/message'

const roleLabels: Record<string, string> = {
  VIEWER: '查看者',
  OPERATOR: '操作员',
  ADMIN: '管理员',
}

const roleHints: Record<string, string> = {
  '': '不可访问 HR 模块',
  VIEWER: '只读：列表/详情（联系方式脱敏），无简历下载、无编辑/流转',
  OPERATOR: '建档、上传简历、关联职位、状态流转（联系方式明文）',
  ADMIN: '全部权限 + 职位管理、归档/合并、授权管理与审计查询',
}

const loading = ref(false)
const saving = ref(false)
const members = ref<HrAccessMember[]>([])
const origin = reactive(new Map<string, HrRole | null>())

const changedItems = computed(() => {
  const items: HrAccessSetItem[] = []
  for (const member of members.value) {
    if (origin.get(member.id) !== member.hr_role) {
      items.push({ user_id: member.id, role: member.hr_role ?? null })
    }
  }
  return items
})

function loadAccess() {
  loading.value = true
  HrApi.getAccess()
    .then((response) => {
      members.value = response.data || []
      origin.clear()
      for (const member of members.value) {
        origin.set(member.id, member.hr_role)
      }
    })
    .catch(() => MsgError('加载成员列表失败'))
    .finally(() => {
      loading.value = false
    })
}

function saveAll() {
  const items = changedItems.value
  if (!items.length) return
  saving.value = true
  HrApi.updateAccess(items)
    .then(() => {
      MsgSuccess('已保存成员角色')
      loadAccess()
    })
    .catch(() => {})
    .finally(() => {
      saving.value = false
    })
}

onMounted(loadAccess)
</script>

<style scoped>
.hr-page { min-width: 0; }
</style>
