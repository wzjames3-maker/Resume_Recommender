<template>
  <div class="hr-page p-16-24">
    <div class="flex-between mb-16">
      <div>
        <h2>我的面试</h2>
        <span class="color-secondary">查看被安排的面试并提交反馈（仅本人可见）；AI 面试助手生成面题与评估草稿（草稿不自动提交）</span>
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
        <el-table-column label="AI 备忘" min-width="130">
          <template #default="{ row }">
            <el-tag
              v-if="copilotStatusByInterview[row.interview_id]"
              :type="proposalStatusTagType(copilotStatusByInterview[row.interview_id])"
              size="small"
            >
              {{ proposalStatusLabel(copilotStatusByInterview[row.interview_id]) }}
            </el-tag>
            <span v-else class="color-secondary">-</span>
          </template>
        </el-table-column>
        <el-table-column label="我的反馈" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.feedback || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="210" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'PENDING'" link type="primary" :loading="copilotRunning === row.interview_id" @click="runCopilot(row, 'prepare')">
              AI 面试助手
            </el-button>
            <el-button v-if="row.feedback_submitted_at" link type="primary" :loading="copilotRunning === row.interview_id" @click="runCopilot(row, 'feedback')">
              AI 评估草稿
            </el-button>
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

    <el-drawer v-model="copilotVisible" title="AI 面试助手" size="640px">
      <div v-if="copilotLoading" v-loading="true" class="p-16" style="min-height: 200px" />
      <template v-else-if="copilotProposal">
        <div class="flex-between mb-16">
          <el-tag :type="proposalStatusTagType(copilotProposal.status)" size="small">
            {{ proposalStatusLabel(copilotProposal.status) }}
          </el-tag>
          <span class="color-secondary">
            {{ copilotProposal.payload.phase === 'prepare' ? '面试前问题清单' : '面后评估草稿' }}
          </span>
        </div>
        <template v-if="copilotProposal.payload.phase === 'prepare'">
          <div v-if="copilotProposal.payload.weak_spots?.length" class="ai-block">
            <div class="ai-title">候选短板（面试针对性依据）</div>
            <ul class="ai-list">
              <li v-for="(spot, idx) in copilotProposal.payload.weak_spots" :key="idx">
                <b>{{ spot.name }}</b>：{{ spot.detail }}
                <ul v-if="spot.evidence?.length" class="ai-evidence">
                  <li v-for="(ev, eIdx) in spot.evidence" :key="eIdx">
                    <span class="color-secondary">证据（相关度 {{ ev.relevance }}）：</span>{{ ev.excerpt }}
                  </li>
                </ul>
              </li>
            </ul>
          </div>
          <div class="ai-block mt-16">
            <div class="ai-title">面试问题清单（建议至少覆盖基础/进阶/深挖）</div>
            <ol class="ai-list">
              <li v-for="(q, idx) in copilotProposal.payload.questions || []" :key="idx">
                <div>{{ q.question }}</div>
                <div class="color-secondary">考察点：{{ q.target }} · 难度：{{ difficultyLabel(q.difficulty) }}</div>
                <div v-if="q.follow_up" class="color-secondary">追问：{{ q.follow_up }}</div>
              </li>
            </ol>
          </div>
          <div v-if="copilotProposal.payload.focus?.length" class="ai-block mt-16">
            <div class="ai-title">面试重点</div>
            <el-tag v-for="item in copilotProposal.payload.focus" :key="item" class="mr-8" size="small">{{ item }}</el-tag>
          </div>
        </template>
        <template v-else>
          <div class="ai-block">
            <div class="ai-title">评估草稿（不自动提交，供人工参考）</div>
            <pre class="jd-pre">{{ copilotProposal.payload.evaluation_draft }}</pre>
          </div>
          <div v-if="copilotProposal.payload.recommendation_hint" class="ai-block mt-16">
            <div class="ai-title">倾向建议（仅供参考）</div>
            {{ copilotProposal.payload.recommendation_hint }}
          </div>
          <div v-if="copilotProposal.payload.open_items?.length" class="ai-block mt-16">
            <div class="ai-title">待补充考察</div>
            <ul class="ai-list"><li v-for="(item, idx) in copilotProposal.payload.open_items" :key="idx">{{ item }}</li></ul>
          </div>
        </template>
        <div class="text-right mt-16">
          <el-button v-if="copilotProposal.status === 'PENDING' && isHrOperator" type="primary" :loading="copilotSaving" @click="ackCopilotProposal">
            确认采纳
          </el-button>
          <el-button v-if="copilotProposal.status === 'PENDING' && isHrOperator" :loading="copilotSaving" @click="dismissCopilotProposal">忽略</el-button>
          <el-button @click="copilotVisible = false">关闭</el-button>
        </div>
        <div v-if="copilotProposal.status === 'PENDING' && !isHrOperator" class="mt-16 color-secondary">
          草稿仅供查看；确认/忽略需要 OPERATOR 以上权限。
        </div>
      </template>
      <el-empty v-else description="暂无 AI 备忘，点击列表中的「AI 面试助手」生成" />
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import HrApi from '@/api/hr/recruitment'
import type { CopilotProposal, MyInterview } from '@/api/type/hr'
import useStore from '@/stores'
import { MsgConfirm, MsgSuccess } from '@/utils/message'

const { user } = useStore()
const isHrOperator = user.getHrRole() === 'OPERATOR' || user.getHrRole() === 'ADMIN'

const loading = ref(false)
const submitting = ref(false)
const interviews = ref<MyInterview[]>([])
const feedbackDialogVisible = ref(false)
const feedbackTarget = ref<MyInterview | null>(null)
const feedbackForm = reactive({ status: '' as string, feedback: '' })

const copilotVisible = ref(false)
const copilotLoading = ref(false)
const copilotRunning = ref('')
const copilotSaving = ref(false)
const copilotProposal = ref<CopilotProposal | null>(null)
const copilotStatusByInterview = ref<Record<string, string>>({})

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

function proposalStatusLabel(status: string) {
  const labels: Record<string, string> = { PENDING: '待确认', ACCEPTED: '已确认', DISMISSED: '已忽略', EXPIRED: '已过期' }
  return labels[status] || status
}

function proposalStatusTagType(status: string) {
  if (status === 'PENDING') return 'warning'
  if (status === 'ACCEPTED') return 'success'
  return 'info'
}

function difficultyLabel(difficulty: string) {
  const labels: Record<string, string> = { 基础: '基础', 进阶: '进阶', 深挖: '深挖' }
  return labels[difficulty] || difficulty
}

function loadInterviews() {
  loading.value = true
  HrApi.getMyInterviews()
    .then((response) => {
      interviews.value = response.data
      response.data.forEach((interview) => {
        HrApi.getInterviewProposals(interview.interview_id)
          .then((proposalResponse) => {
            const proposals = proposalResponse.data || []
            copilotStatusByInterview.value[interview.interview_id] = proposals[0]?.status || ''
          })
          .catch(() => {})
      })
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

function runCopilot(interview: MyInterview, phase: 'prepare' | 'feedback') {
  const data: Record<string, unknown> = { phase }
  if (phase === 'feedback') data.feedback = interview.feedback || ''
  MsgConfirm(
    phase === 'prepare' ? '生成面试问题' : '生成评估草稿',
    phase === 'prepare'
      ? '基于职位要求与候选人简历短板生成结构化面试问题清单（草稿，不自动提交反馈）。'
      : '基于已提交的面试反馈生成评估草稿（草稿，不会自动提交或改变结果）。',
  )
    .then(() => {
      copilotRunning.value = interview.interview_id
      HrApi.runInterviewCopilot(interview.interview_id, data)
        .then((response) => {
          if (response.data?.status === 'SKIPPED' || response.data?.status === 'FAILED') {
            MsgConfirm(
              'AI 暂不可用',
              (response.data?.error as string) || 'AI 生成未成功，请稍后重试。',
              { showCancelButton: false, confirmButtonText: '知道了' },
            ).catch(() => {})
          } else {
            MsgSuccess('AI 备忘已生成')
            loadCopilotProposals(interview.interview_id)
          }
          loadInterviews()
        })
        .catch(() => {})
        .finally(() => {
          copilotRunning.value = ''
        })
    })
    .catch(() => {})
}

function loadCopilotProposals(interviewId: string) {
  copilotLoading.value = true
  HrApi.getInterviewProposals(interviewId)
    .then((response) => {
      const proposals = response.data || []
      copilotProposal.value = proposals.find((p) => p.status === 'PENDING') || proposals[0] || null
      copilotVisible.value = true
      copilotStatusByInterview.value[interviewId] = copilotProposal.value?.status || ''
    })
    .catch(() => {})
    .finally(() => {
      copilotLoading.value = false
    })
}

function loadCopilotProposalsCached() {
  const proposal = copilotProposal.value
  if (!proposal) return
  HrApi.getInterviewProposals(proposal.target_id)
    .then((response) => {
      copilotProposal.value = response.data?.find((p) => p.status === 'PENDING') || response.data?.[0] || null
    })
    .catch(() => {})
}

function ackCopilotProposal() {
  if (!copilotProposal.value) return
  MsgConfirm('确认采纳', '确认这份 AI 备忘？仅记录确认，不改变任何面试或流程状态。')
    .then(() => {
      if (!copilotProposal.value) return
      copilotSaving.value = true
      HrApi.acceptProposal(copilotProposal.value.id, { decision_note: '面试官确认 AI 备忘' })
        .then(() => {
          MsgSuccess('已确认')
          loadInterviews()
          loadCopilotProposalsCached()
        })
        .catch(() => {})
        .finally(() => {
          copilotSaving.value = false
        })
    })
    .catch(() => {})
}

function dismissCopilotProposal() {
  if (!copilotProposal.value) return
  MsgConfirm('忽略备忘', '确定忽略这份 AI 备忘？')
    .then(() => {
      if (!copilotProposal.value) return
      copilotSaving.value = true
      HrApi.dismissProposal(copilotProposal.value.id, { decision_note: '面试官忽略备忘' })
        .then(() => {
          MsgSuccess('已忽略')
          loadInterviews()
          loadCopilotProposalsCached()
        })
        .catch(() => {})
        .finally(() => {
          copilotSaving.value = false
        })
    })
    .catch(() => {})
}

onMounted(loadInterviews)
</script>

<style scoped>
.ai-block {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 12px 16px;
  background: var(--el-fill-color-lighter);
}

.ai-title {
  font-weight: 600;
  font-size: 13px;
  margin-bottom: 8px;
  color: var(--el-text-color-primary);
}

.ai-list {
  margin: 0;
  padding-left: 18px;
  color: var(--el-text-color-regular);
  line-height: 1.9;
}

.ai-evidence {
  margin: 4px 0 0;
  padding-left: 16px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.jd-pre {
  max-height: 380px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.7;
  margin: 0;
}

.mt-16 { margin-top: 16px; }
.mb-16 { margin-bottom: 16px; }
.mr-8 { margin-right: 8px; }
</style>
