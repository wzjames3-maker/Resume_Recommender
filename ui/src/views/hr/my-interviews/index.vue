<template>
  <div class="hr-page p-16-24">
    <div class="flex-between mb-16">
      <div>
        <h2>我的面试</h2>
        <span class="color-secondary">查看被安排的面试并提交反馈（仅本人可见）</span>
      </div>
      <el-button type="primary" plain :loading="loading" @click="loadInterviews">刷新</el-button>
    </div>

    <el-card style="--el-card-padding: 0" v-loading="loading">
      <el-table :data="interviews" empty-text="暂无被安排的面试">
        <el-table-column prop="candidate_name" label="候选人" min-width="120" />
        <el-table-column prop="job_name" label="职位" min-width="140" />
        <el-table-column prop="round_no" label="轮次" width="70" />
        <el-table-column label="面试时间" min-width="160">
          <template #default="{ row }">{{ row.scheduled_at ? new Date(row.scheduled_at).toLocaleString() : '-' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="interviewStatusTag(row.status)" size="small">{{ interviewStatusLabels[row.status] || row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="反馈截止" min-width="170">
          <template #default="{ row }">
            <span v-if="row.feedback_deadline">
              {{ new Date(row.feedback_deadline).toLocaleString() }}
              <el-tag v-if="row.feedback_submitted_at" type="success" size="small">已提交</el-tag>
              <el-tag v-else-if="row.is_overdue" type="danger" size="small">逾期</el-tag>
            </span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="我的反馈" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.feedback || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'PENDING' || row.feedback" link type="primary" @click="openFeedback(row)">提交反馈</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="feedbackDialogVisible" title="提交面试反馈" width="520px">
      <el-form label-width="88px">
        <el-form-item label="面试">{{ feedbackTarget?.candidate_name }} · {{ feedbackTarget?.job_name }} · 第 {{ feedbackTarget?.round_no }} 轮</el-form-item>
        <el-form-item label="结果" required>
          <el-select v-model="feedbackForm.status" style="width: 100%">
            <el-option label="通过" value="PASSED" />
            <el-option label="未通过" value="FAILED" />
            <el-option label="未到场" value="NO_SHOW" />
          </el-select>
        </el-form-item>
        <el-form-item label="反馈">
          <el-input v-model="feedbackForm.feedback" type="textarea" :rows="4" maxlength="4096" show-word-limit placeholder="面试评价（可重复提交修改）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="feedbackDialogVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!feedbackForm.status" :loading="submitting" @click="submitFeedback">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import HrApi from '@/api/hr/recruitment'
import type { MyInterview } from '@/api/type/hr'
import { MsgSuccess } from '@/utils/message'

const loading = ref(false)
const submitting = ref(false)
const interviews = ref<MyInterview[]>([])
const feedbackDialogVisible = ref(false)
const feedbackTarget = ref<MyInterview | null>(null)
const feedbackForm = reactive({ status: '' as string, feedback: '' })

const interviewStatusLabels: Record<string, string> = {
  PENDING: '待面试',
  PASSED: '通过',
  FAILED: '未通过',
  NO_SHOW: '未到场',
  CANCELLED: '已取消',
}

function interviewStatusTag(status: string) {
  if (status === 'PASSED') return 'success'
  if (status === 'FAILED') return 'danger'
  if (status === 'NO_SHOW') return 'warning'
  return 'info'
}

function loadInterviews() {
  loading.value = true
  HrApi.getMyInterviews()
    .then((response) => {
      interviews.value = response.data
    })
    .catch(() => {})
    .finally(() => {
      loading.value = false
    })
}

function openFeedback(interview: MyInterview) {
  feedbackTarget.value = interview
  feedbackForm.status = interview.status === 'PENDING' ? 'PASSED' : interview.status
  feedbackForm.feedback = interview.feedback || ''
  feedbackDialogVisible.value = true
}

function submitFeedback() {
  if (!feedbackTarget.value || !feedbackForm.status) return
  submitting.value = true
  HrApi.submitInterviewFeedback(feedbackTarget.value.interview_id, { ...feedbackForm })
    .then(() => {
      MsgSuccess('反馈已提交')
      feedbackDialogVisible.value = false
      loadInterviews()
    })
    .catch(() => {})
    .finally(() => {
      submitting.value = false
    })
}

onMounted(loadInterviews)
</script>
