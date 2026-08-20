<template>
  <div class="hr-page p-16-24">
    <div class="dashboard-heading flex-between mb-16">
      <div>
        <div class="eyebrow">RECRUITING OPERATIONS</div>
        <h2>招聘工作台</h2>
        <span class="color-secondary">从今日待办开始，快速推进候选人和职位流程</span>
      </div>
      <el-button circle :icon="Refresh" title="刷新工作台" aria-label="刷新工作台" :loading="loading" @click="loadDashboard" />
    </div>

    <div class="quick-grid mb-16">
      <el-card shadow="never" class="quick-card" role="button" tabindex="0" @click="router.push('/hr/resumes/upload')" @keyup.enter="router.push('/hr/resumes/upload')">
        <span class="quick-icon quick-icon--blue"><el-icon><Upload /></el-icon></span>
        <div class="quick-copy"><div class="quick-title">批量上传简历</div><div class="quick-desc">上传并自动解析候选人档案</div></div>
        <el-icon class="quick-arrow"><ArrowRight /></el-icon>
      </el-card>
      <el-card shadow="never" class="quick-card" role="button" tabindex="0" @click="router.push('/hr/jobs/new')" @keyup.enter="router.push('/hr/jobs/new')">
        <span class="quick-icon quick-icon--green"><el-icon><Plus /></el-icon></span>
        <div class="quick-copy"><div class="quick-title">新建职位</div><div class="quick-desc">维护需求、技能和招聘人数</div></div>
        <el-icon class="quick-arrow"><ArrowRight /></el-icon>
      </el-card>
      <el-card shadow="never" class="quick-card" role="button" tabindex="0" @click="router.push('/hr/search')" @keyup.enter="router.push('/hr/search')">
        <span class="quick-icon quick-icon--purple"><el-icon><Search /></el-icon></span>
        <div class="quick-copy"><div class="quick-title">语义检索</div><div class="quick-desc">用自然语言定位候选人</div></div>
        <el-icon class="quick-arrow"><ArrowRight /></el-icon>
      </el-card>
      <el-card shadow="never" class="quick-card" role="button" tabindex="0" @click="router.push('/hr/interviews')" @keyup.enter="router.push('/hr/interviews')">
        <span class="quick-icon quick-icon--orange"><el-icon><Calendar /></el-icon></span>
        <div class="quick-copy"><div class="quick-title">面试管理</div><div class="quick-desc">查看日程和反馈进度</div></div>
        <el-icon class="quick-arrow"><ArrowRight /></el-icon>
      </el-card>
      <el-card v-if="isHrOperator" shadow="never" class="quick-card" role="button" tabindex="0" @click="router.push('/hr/agents')" @keyup.enter="router.push('/hr/agents')">
        <span class="quick-icon quick-icon--teal"><el-icon><MagicStick /></el-icon></span>
        <div class="quick-copy"><div class="quick-title">Agent 工作台</div><div class="quick-desc">查看提案、证据和运行状态</div></div>
        <el-icon class="quick-arrow"><ArrowRight /></el-icon>
      </el-card>
    </div>

    <section class="metric-strip mb-16" aria-label="招聘工作台关键指标">
      <div class="metric-item"><span class="metric-label">我负责的候选人</span><strong class="metric-value">{{ candidateTotal }}</strong><span class="metric-meta">当前在库</span></div>
      <div class="metric-item"><span class="metric-label">开放职位</span><strong class="metric-value">{{ jobTotal }}</strong><span class="metric-meta">开放 / 暂停</span></div>
      <div class="metric-item"><span class="metric-label">我的面试</span><strong class="metric-value">{{ interviews.length }}</strong><span class="metric-meta">待处理任务</span></div>
      <div class="metric-item metric-item--alert"><span class="metric-label">待补反馈</span><strong class="metric-value">{{ pendingFeedback }}</strong><span class="metric-meta">其中逾期 {{ overdueInterviews }} 条</span></div>
    </section>

    <el-row :gutter="16">
      <el-col :span="12">
        <el-card style="--el-card-padding: 0">
          <template #header>
            <div class="flex-between">
              <span>我的待处理</span>
              <el-button link type="primary" @click="router.push('/hr/candidates/list')">全部候选人</el-button>
            </div>
          </template>
          <div class="p-16">
            <el-empty v-if="!loading && candidateTotal === 0 && jobTotal === 0" description="暂无待办" />
            <div v-else class="todo-list">
              <div class="todo-item">
                <div class="todo-label">我负责的在库候选人</div>
                <div class="todo-value">{{ candidateTotal }}</div>
              </div>
              <div class="todo-item">
                <div class="todo-label">我负责的开放/暂停职位</div>
                <div class="todo-value">{{ jobTotal }}</div>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card style="--el-card-padding: 0">
          <template #header>
            <div class="flex-between">
              <span>我的面试</span>
              <el-button link type="primary" @click="router.push('/hr/interviews')">全部面试</el-button>
            </div>
          </template>
          <div class="p-16">
            <el-empty v-if="!loading && interviews.length === 0" description="暂无面试任务" />
            <div v-for="item in interviews.slice(0, 5)" :key="item.interview_id" class="interview-item">
              <div class="flex-between">
                <span class="interview-name">{{ item.candidate_name }} · {{ item.job_name }}</span>
                <el-tag v-if="item.is_overdue" type="danger" size="small">逾期</el-tag>
                <el-tag v-else-if="item.feedback_submitted_at" type="success" size="small">已反馈</el-tag>
                <el-tag v-else type="warning" size="small">待反馈</el-tag>
              </div>
              <div class="color-secondary text-12">
                {{ item.scheduled_at ? new Date(item.scheduled_at).toLocaleString() : '未排期' }}
                <template v-if="item.feedback_deadline"> · 截止 {{ new Date(item.feedback_deadline).toLocaleString() }}</template>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-collapse v-model="agentCollapse" class="mt-16">
      <el-collapse-item v-if="isHrOperator" title="Agent 采纳率（反馈闭环）" name="agent">
        <div class="color-secondary text-12 mb-8">按 Agent × 分数带统计提案决策，用于阈值标定与试点观测</div>
      <el-table :data="agentStats?.by_agent || []" empty-text="暂无 Agent 运行数据" size="small">
        <el-table-column label="Agent" width="170">
          <template #default="{ row }">{{ agentTypeLabel(row.agent_type) }}</template>
        </el-table-column>
        <el-table-column label="运行" width="160">
          <template #default="{ row }">
            {{ row.runs }}<span class="color-secondary">（成功 {{ row.succeeded }} · 失败 {{ row.failed }} · 跳过 {{ row.skipped }}）</span>
          </template>
        </el-table-column>
        <el-table-column label="提案" width="160">
          <template #default="{ row }">
            {{ row.proposal_total }}<span class="color-secondary">（待决 {{ row.proposal_total - row.decided }} · 已决 {{ row.decided }}）</span>
          </template>
        </el-table-column>
        <el-table-column label="采纳率" width="110">
          <template #default="{ row }">
            <el-tag v-if="row.accept_rate != null" :type="row.accept_rate >= 0.5 ? 'success' : 'warning'" size="small">
              {{ (row.accept_rate * 100).toFixed(0) }}%
            </el-tag>
            <span v-else class="color-secondary">-</span>
          </template>
        </el-table-column>
        <el-table-column label="分数带采纳（ADVANCE/DECLINE/HOLD）" min-width="220">
          <template #default="{ row }">
            <span v-if="!Object.keys(row.score_bands || {}).length" class="color-secondary">-</span>
            <el-tag v-for="(band, key) in row.score_bands || {}" :key="key" class="mr-8" size="small" effect="plain">
              {{ bandLabel(String(key)) }}：{{ band.accept_rate != null ? (band.accept_rate * 100).toFixed(0) + '%' : '-' }}（{{ band.count }}）
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, Calendar, MagicStick, Plus, Refresh, Search, Upload } from '@element-plus/icons-vue'
import HrApi from '@/api/hr/recruitment'
import type { AgentStats, MyInterview } from '@/api/type/hr'
import useStore from '@/stores'
import { MsgError } from '@/utils/message'

const router = useRouter()
const { user } = useStore()
const isHrOperator = computed(() => user.getHrRole() === 'OPERATOR' || user.getHrRole() === 'ADMIN')

const loading = ref(false)
const candidateTotal = ref(0)
const jobTotal = ref(0)
const interviews = ref<MyInterview[]>([])
const pendingFeedback = computed(() => interviews.value.filter((item) => !item.feedback_submitted_at && item.status === 'PENDING').length)
const overdueInterviews = computed(() => interviews.value.filter((item) => item.is_overdue && !item.feedback_submitted_at).length)
const agentStats = ref<AgentStats | null>(null)
const agentCollapse = ref<string[]>([])

function agentTypeLabel(agentType: string) {
  const labels: Record<string, string> = {
    SCREENING: '初筛评估',
    JD_DRAFT: 'JD 起草',
    INTERVIEW_COPILOT: '面试助手',
    SOURCING: '人才库激活',
    COMMUNICATION_DRAFT: '沟通草稿',
  }
  return labels[agentType] || agentType
}

function bandLabel(band: string) {
  const labels: Record<string, string> = { '0-59': '0-59', '60-79': '60-79', '80-100': '80-100', 'no-score': '无分' }
  return labels[band] || band
}

function loadDashboard() {
  loading.value = true
  const myId = user.userInfo?.id || ''
  Promise.all([
    HrApi.getCandidates({ current_page: 1, page_size: 1 }, { owner_id: myId, status: 'ACTIVE' }),
    HrApi.getJobs({ current_page: 1, page_size: 1 }, { owner_id: myId, status: '' }),
    HrApi.getMyInterviews(),
    isHrOperator.value ? HrApi.getAgentStats() : Promise.resolve({ data: { by_agent: [] } as AgentStats }),
  ])
    .then(([candidateRes, jobRes, interviewRes, statsRes]) => {
      candidateTotal.value = candidateRes.data.total || 0
      jobTotal.value = jobRes.data.total || 0
      interviews.value = interviewRes.data || []
      agentStats.value = (statsRes as { data: AgentStats }).data || null
    })
    .catch(() => MsgError('工作台数据加载失败'))
    .finally(() => {
      loading.value = false
    })
}

onMounted(loadDashboard)
</script>

<style scoped>
.hr-page { min-width: 0; }
.flex-between { display: flex; justify-content: space-between; align-items: center; }
.mb-16 { margin-bottom: 16px; }
.quick-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
}
.eyebrow { margin-bottom: 5px; color: var(--el-color-primary); font-size: 11px; font-weight: 700; letter-spacing: 1.2px; }
.dashboard-heading { align-items: flex-end; }
.quick-card { min-height: 82px; cursor: pointer; transition: border-color .2s, box-shadow .2s, transform .2s; }
.quick-card :deep(.el-card__body) { display: flex; align-items: center; gap: 12px; min-height: 82px; box-sizing: border-box; width: 100%; }
.quick-card:hover { border-color: var(--el-color-primary-light-5); box-shadow: 0 6px 18px rgba(51, 112, 255, .10) !important; transform: translateY(-1px); }
.quick-icon { display: inline-flex; align-items: center; justify-content: center; flex: 0 0 34px; width: 34px; height: 34px; border-radius: 9px; font-size: 17px; }
.quick-icon--blue { color: #3370ff; background: #eaf0ff; }
.quick-icon--green { color: #20a37a; background: #e5f7f0; }
.quick-icon--purple { color: #8656d8; background: #f1eaff; }
.quick-icon--orange { color: #d9822b; background: #fff1df; }
.quick-icon--teal { color: #168c92; background: #e1f7f7; }
.quick-copy { min-width: 0; flex: 1; }
.quick-title { margin-bottom: 5px; color: var(--el-text-color-primary); font-weight: 600; }
.quick-desc { overflow: hidden; color: var(--el-text-color-secondary); font-size: 12px; line-height: 18px; text-overflow: ellipsis; white-space: nowrap; }
.quick-arrow { color: var(--el-text-color-placeholder); }
.quick-secondary { grid-column: 1 / -1; font-size: 13px; color: var(--el-text-color-secondary); }
.metric-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border: 1px solid var(--hr-border); border-radius: 8px; background: var(--el-bg-color); overflow: hidden; }
.metric-item { display: flex; flex-direction: column; gap: 3px; min-height: 84px; padding: 14px 18px; border-right: 1px solid var(--hr-border); }
.metric-item:last-child { border-right: 0; }
.metric-label { color: var(--el-text-color-secondary); font-size: 12px; }
.metric-value { color: var(--el-text-color-primary); font-size: 25px; line-height: 30px; }
.metric-meta { color: var(--el-text-color-placeholder); font-size: 11px; }
.metric-item--alert .metric-value { color: var(--el-color-danger); }
.p-16 { padding: 16px; }
.todo-list { display: flex; flex-direction: column; gap: 12px; }
.todo-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}
.todo-label { color: var(--el-text-color-regular); }
.todo-value { font-size: 24px; font-weight: 600; color: var(--el-color-primary); }
.interview-item {
  padding: 10px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.interview-item:last-child { border-bottom: none; }
.interview-name { font-weight: 500; }
.text-12 { font-size: 12px; line-height: 18px; margin-top: 4px; }
@media (max-width: 900px) {
  .metric-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .metric-item:nth-child(2) { border-right: 0; }
  .metric-item:nth-child(-n + 2) { border-bottom: 1px solid var(--hr-border); }
}
@media (max-width: 640px) {
  .dashboard-heading { align-items: flex-start; }
  .quick-grid { grid-template-columns: 1fr; }
}
</style>
