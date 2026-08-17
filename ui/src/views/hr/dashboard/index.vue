<template>
  <div class="hr-page p-16-24">
    <div class="flex-between mb-16">
      <div>
        <h2>招聘工作台</h2>
        <span class="color-secondary">聚合待办与快捷入口</span>
      </div>
    </div>

    <div class="quick-grid mb-16">
      <el-card shadow="never" class="quick-card" @click="router.push('/hr/candidates?upload=1')">
        <div class="quick-title">批量上传简历</div>
        <div class="quick-desc">上传 docx/txt 简历并自动解析关联候选人</div>
      </el-card>
      <el-card shadow="never" class="quick-card" @click="router.push('/hr/jobs?new=1')">
        <div class="quick-title">新建职位</div>
        <div class="quick-desc">维护招聘需求与技能要求</div>
      </el-card>
      <el-card shadow="never" class="quick-card" @click="router.push('/hr/search')">
        <div class="quick-title">语义检索</div>
        <div class="quick-desc">自然语言查找候选人</div>
      </el-card>
      <el-card shadow="never" class="quick-card" @click="router.push('/hr/my-interviews')">
        <div class="quick-title">我的面试</div>
        <div class="quick-desc">查看反馈截止与逾期状态</div>
      </el-card>
      <div class="quick-secondary">
        需要手动建档？<el-link type="primary" :underline="false" @click="router.push('/hr/candidates?new=1')">新建候选人</el-link>
      </div>
    </div>

    <el-row :gutter="16">
      <el-col :span="12">
        <el-card style="--el-card-padding: 0">
          <template #header>
            <div class="flex-between">
              <span>我的待处理</span>
              <el-button link type="primary" @click="router.push('/hr/candidates')">全部候选人</el-button>
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
              <el-button link type="primary" @click="router.push('/hr/my-interviews')">全部面试</el-button>
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

    <el-card v-if="isHrOperator" style="--el-card-padding: 0" class="mt-16">
      <template #header>
        <div class="flex-between">
          <span>Agent 采纳率（反馈闭环）</span>
          <span class="color-secondary text-12">按 Agent × 分数带统计提案决策，用于阈值标定与试点观测</span>
        </div>
      </template>
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
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
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
const agentStats = ref<AgentStats | null>(null)

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
.quick-card { cursor: pointer; transition: box-shadow .2s; }
.quick-card:hover { box-shadow: var(--el-box-shadow-light); }
.quick-title { font-weight: 600; margin-bottom: 6px; }
.quick-desc { font-size: 12px; color: var(--el-text-color-secondary); }
.quick-secondary { grid-column: 1 / -1; font-size: 13px; color: var(--el-text-color-secondary); }
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
</style>
