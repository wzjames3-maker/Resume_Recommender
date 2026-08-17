<template>
  <div class="hr-page p-16-24">
    <div class="flex-between mb-16">
      <div>
        <h2>审计日志</h2>
        <span class="color-secondary">HR 模块敏感操作与越权拒绝记录</span>
      </div>
    </div>

    <el-card style="--el-card-padding: 0" v-loading="loading">
      <div class="p-16 border-b flex gap-12">
        <el-select v-model="filters.user_id" placeholder="操作者" clearable filterable style="width: 180px">
          <el-option v-for="member in members" :key="member.id" :label="member.nick_name" :value="member.id" />
        </el-select>
        <el-select v-model="filters.action" placeholder="动作" clearable style="width: 180px">
          <el-option v-for="(label, value) in actionLabels" :key="value" :label="label" :value="value" />
        </el-select>
        <el-select v-model="filters.object_type" placeholder="对象类型" clearable style="width: 150px">
          <el-option v-for="(label, value) in objectTypeLabels" :key="value" :label="label" :value="value" />
        </el-select>
        <el-date-picker
          v-model="timeRange"
          type="datetimerange"
          range-separator="至"
          start-placeholder="开始时间"
          end-placeholder="结束时间"
          value-format="YYYY-MM-DDTHH:mm:ss"
          style="width: 380px"
        />
        <el-button type="primary" plain @click="refresh">查询</el-button>
      </div>

      <AppTable :data="logs" :pagination-config="pagination" @change-page="loadLogs" @size-change="refresh">
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ new Date(row.create_time).toLocaleString() }}</template>
        </el-table-column>
        <el-table-column label="操作者" min-width="120">
          <template #default="{ row }">{{ row.nick_name || '-' }}</template>
        </el-table-column>
        <el-table-column label="动作" width="150">
          <template #default="{ row }">{{ actionLabels[row.action] || row.action }}</template>
        </el-table-column>
        <el-table-column label="对象类型" width="110">
          <template #default="{ row }">{{ objectTypeLabels[row.object_type] || row.object_type }}</template>
        </el-table-column>
        <el-table-column prop="object_id" label="对象 ID" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.object_id || '-' }}</template>
        </el-table-column>
        <el-table-column label="结果" width="90">
          <template #default="{ row }">
            <el-tag :type="resultTagType(row.result)" size="small">{{ resultLabels[row.result] || row.result }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="detail" label="补充" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">{{ row.detail || '-' }}</template>
        </el-table-column>
      </AppTable>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import AppTable from '@/components/app-table/index.vue'
import HrApi from '@/api/hr/recruitment'
import type { HrAccessMember, HrAuditAction, HrAuditLog, HrAuditObjectType, HrAuditResult } from '@/api/type/hr'
import { MsgError } from '@/utils/message'

const actionLabels: Record<string, string> = {
  VIEW_DETAIL: '查看详情',
  CREATE: '创建',
  UPDATE: '更新',
  ARCHIVE: '归档',
  RESTORE: '恢复',
  DELETE: '删除',
  JOB_CLOSE: '关闭职位',
  JOB_REOPEN: '恢复职位',
  ASSIGNMENT_TRANSITION: '关联流转',
  RESUME_UPLOAD: '简历上传',
  RESUME_DOWNLOAD: '简历下载',
  RESUME_DELETE: '简历删除',
  MERGE: '合并候选人',
  GRANT_ACCESS: '授予权限',
  REVOKE_ACCESS: '撤销权限',
  EXPORT: '导出',
  INTERVIEW_FEEDBACK: '面试反馈',
  OFFER_SEND: '发送 Offer',
  OFFER_ACCEPT: '接受 Offer',
  OFFER_REJECT: '拒绝 Offer',
  OFFER_WITHDRAW: '撤回 Offer',
  OFFER_APPROVE: '审批 Offer',
  HANDOFF: '入职交接',
  IMPORT: '批量导入',
  SEARCH: '简历检索',
  AGENT_RUN: 'Agent 运行',
  AGENT_DECIDE: 'Agent 决策',
  ACCESS_DENIED: '越权拒绝',
}

const objectTypeLabels: Record<string, string> = {
  CANDIDATE: '候选人',
  JOB: '职位',
  ASSIGNMENT: '关联',
  APPLICATION: '申请',
  INTERVIEW: '面试',
  OFFER: 'Offer',
  ONBOARDING: '入职交接',
  RESUME: '简历',
  HR_ACCESS: 'HR 授权',
  OTHER: '其他',
}

const resultLabels: Record<string, string> = {
  SUCCESS: '成功',
  FAILED: '失败',
  DENIED: '拒绝',
}

function resultTagType(result: HrAuditResult) {
  if (result === 'SUCCESS') return 'success'
  if (result === 'DENIED') return 'warning'
  return 'danger'
}

const loading = ref(false)
const logs = ref<HrAuditLog[]>([])
const members = ref<HrAccessMember[]>([])
const timeRange = ref<[string, string] | null>(null)
const filters = reactive({
  user_id: '',
  action: '' as HrAuditAction | '',
  object_type: '' as HrAuditObjectType | '',
})
const pagination = reactive({ current_page: 1, page_size: 10, total: 0 })

function loadLogs() {
  loading.value = true
  const [start_time, end_time] = timeRange.value || []
  HrApi.getAuditLogs({
    current_page: pagination.current_page,
    page_size: pagination.page_size,
    user_id: filters.user_id || undefined,
    action: filters.action || undefined,
    object_type: filters.object_type || undefined,
    start_time,
    end_time,
  })
    .then((response) => {
      logs.value = response.data.records
      pagination.total = response.data.total
    })
    .catch(() => MsgError('查询审计日志失败'))
    .finally(() => {
      loading.value = false
    })
}

function refresh() {
  pagination.current_page = 1
  loadLogs()
}

onMounted(() => {
  HrApi.getAccess()
    .then((response) => {
      members.value = response.data || []
    })
    .catch(() => {})
  loadLogs()
})
</script>

<style scoped>
.hr-page { min-width: 0; }
.gap-12 { gap: 12px; }
</style>
