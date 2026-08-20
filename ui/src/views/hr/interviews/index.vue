<template>
  <div class="hr-page p-16-24">
    <div class="flex-between mb-16">
      <div>
        <div class="eyebrow">INTERVIEW OPERATIONS</div>
        <h2>面试管理</h2>
        <span class="color-secondary">全局查看面试日程、状态与反馈进度</span>
      </div>
      <el-button link type="primary" @click="router.push('/hr/my-interviews')">我的面试</el-button>
    </div>

    <el-card shadow="never" style="--el-card-padding: 0">
      <div class="filter-toolbar p-16 border-b">
        <el-input v-model="filters.search" clearable placeholder="搜索候选人 / 职位 / 面试官" style="width: 240px" @keyup.enter="refresh" />
        <el-select v-model="filters.status" clearable placeholder="状态" style="width: 140px" @change="refresh">
          <el-option label="待面试" value="PENDING" />
          <el-option label="通过" value="PASSED" />
          <el-option label="未通过" value="FAILED" />
          <el-option label="未到场" value="NO_SHOW" />
          <el-option label="已取消" value="CANCELLED" />
        </el-select>
        <el-checkbox v-model="filters.overdue" @change="refresh">仅看逾期</el-checkbox>
        <el-button plain @click="resetFilters">重置</el-button>
      </div>
      <AppTable :data="records" :pagination-config="pagination" @change-page="load" @size-change="refresh">
        <el-table-column label="候选人" min-width="150">
          <template #default="{ row }">
            <div class="primary-cell">{{ row.candidate_name || '-' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="职位" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.job_name || '-' }}</template>
        </el-table-column>
        <el-table-column label="轮次" width="70" align="center">
          <template #default="{ row }">第 {{ row.round_no }} 轮</template>
        </el-table-column>
        <el-table-column label="面试官" min-width="120">
          <template #default="{ row }">{{ row.interviewer || '-' }}</template>
        </el-table-column>
        <el-table-column label="面试时间" width="170">
          <template #default="{ row }">{{ formatTime(row.scheduled_at) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <div class="flex align-center gap-6">
              <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
              <el-tag v-if="row.is_overdue" type="danger" size="small" effect="plain">逾期</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="反馈" min-width="150">
          <template #default="{ row }">
            <span v-if="row.feedback_submitted_at">{{ formatTime(row.feedback_submitted_at) }}</span>
            <span v-else-if="row.feedback_deadline" class="color-secondary">截止 {{ formatTime(row.feedback_deadline) }}</span>
            <span v-else class="color-secondary">未提交</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openFeedback(row)">查看反馈</el-button>
          </template>
        </el-table-column>
      </AppTable>
    </el-card>

    <el-drawer v-model="feedbackDrawerVisible" title="面试反馈" size="540px">
      <template v-if="feedbackTarget">
        <div class="mb-16">
          <div class="primary-cell">{{ feedbackTarget.candidate_name }} · {{ feedbackTarget.job_name }}</div>
          <div class="secondary-cell">第 {{ feedbackTarget.round_no }} 轮 · {{ feedbackTarget.interviewer || '未指定面试官' }}</div>
        </div>
        <div class="feedback-box">{{ feedbackTarget.feedback || '暂无反馈内容' }}</div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import HrApi from '@/api/hr/recruitment'
import type { InterviewAdminRecord } from '@/api/type/hr'

const router = useRouter()
const records = ref<InterviewAdminRecord[]>([])
const filters = reactive({ search: '', status: '', overdue: false })
const pagination = reactive({ current_page: 1, page_size: 20, total: 0 })
const feedbackDrawerVisible = ref(false)
const feedbackTarget = ref<InterviewAdminRecord | null>(null)

function params() {
  return {
    current_page: pagination.current_page,
    page_size: pagination.page_size,
    search: filters.search || undefined,
    status: filters.status || undefined,
    overdue: filters.overdue ? '1' : undefined,
  }
}
function load() {
  HrApi.getInterviewsAdmin(params())
    .then((response) => {
      records.value = response.data?.records || []
      pagination.total = response.data?.total || 0
    })
    .catch(() => {})
}
function refresh() {
  pagination.current_page = 1
  load()
}
function resetFilters() {
  filters.search = ''
  filters.status = ''
  filters.overdue = false
  refresh()
}
function statusLabel(value: string) {
  return ({ PENDING: '待面试', PASSED: '通过', FAILED: '未通过', NO_SHOW: '未到场', CANCELLED: '已取消' } as Record<string, string>)[value] || value
}
function statusType(value: string) {
  return ({ PASSED: 'success', FAILED: 'danger', NO_SHOW: 'warning', CANCELLED: 'info' } as Record<string, string>)[value] || 'primary'
}
function formatTime(value: string | null) {
  return value ? new Date(value).toLocaleString() : '-'
}
function openFeedback(row: InterviewAdminRecord) {
  feedbackTarget.value = row
  feedbackDrawerVisible.value = true
}

onMounted(load)
</script>

<style scoped lang="scss">
.filter-bar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.primary-cell { color: var(--el-text-color-primary); font-weight: 600; }
.secondary-cell { color: var(--el-text-color-secondary); font-size: 12px; }
.feedback-box { padding: 16px; border: 1px solid var(--el-border-color-lighter); border-radius: 6px; background: var(--el-fill-color-lighter); color: var(--el-text-color-primary); line-height: 1.75; white-space: pre-wrap; }
</style>
