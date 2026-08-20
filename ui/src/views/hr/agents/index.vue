<template>
  <div class="hr-page p-16-24">
    <div class="flex-between mb-16">
      <div>
        <div class="eyebrow">CONTROLLED COPILOT</div>
        <h2>Agent 工作台</h2>
        <span class="color-secondary">集中查看运行记录、提案收件箱和证据链，所有写入动作仍需人工确认</span>
      </div>
      <el-button circle :icon="Refresh" title="刷新 Agent 工作台" aria-label="刷新 Agent 工作台" :loading="loading" @click="refreshAll" />
    </div>

    <div class="summary-grid mb-16">
      <div class="summary-item">
        <span class="summary-label">运行记录（筛选范围）</span>
        <strong>{{ runSummary.total_runs }}</strong>
      </div>
      <div class="summary-item">
        <span class="summary-label">待处理提案</span>
        <strong>{{ proposalPage.total }}</strong>
      </div>
      <div class="summary-item">
        <span class="summary-label">失败运行（筛选范围）</span>
        <strong class="danger-text">{{ runSummary.status_counts.FAILED || 0 }}</strong>
      </div>
      <div class="summary-item">
        <span class="summary-label">Token / 耗时（筛选范围）</span>
        <strong>{{ formatNumber(runSummary.total_tokens) }}</strong>
        <span class="summary-sub">{{ formatDuration(runSummary.total_duration_ms) }}</span>
      </div>
    </div>

    <el-card shadow="never" style="--el-card-padding: 0">
      <el-tabs v-model="activeTab" class="workbench-tabs">
        <el-tab-pane label="运行概览" name="overview">
          <AppTable :data="overviewRows">
            <el-table-column label="Agent 类型" min-width="170">
              <template #default="{ row }">
                <div class="primary-cell">{{ agentLabel(row.agent_type) }}</div>
              </template>
            </el-table-column>
            <el-table-column label="运行数" width="90" align="right">
              <template #default="{ row }">{{ row.runs }}</template>
            </el-table-column>
            <el-table-column label="成功" width="80" align="right">
              <template #default="{ row }"><span class="success-text">{{ row.succeeded }}</span></template>
            </el-table-column>
            <el-table-column label="失败" width="80" align="right">
              <template #default="{ row }"><span class="danger-text">{{ row.failed }}</span></template>
            </el-table-column>
            <el-table-column label="跳过" width="80" align="right">
              <template #default="{ row }">{{ row.skipped }}</template>
            </el-table-column>
            <el-table-column label="提案" width="90" align="right">
              <template #default="{ row }">{{ row.proposal_total }}</template>
            </el-table-column>
            <el-table-column label="已决" width="90" align="right">
              <template #default="{ row }">{{ row.decided }}</template>
            </el-table-column>
            <el-table-column label="采纳率" width="110" align="right">
              <template #default="{ row }">
                <span :class="{ 'success-text': row.accept_rate != null && row.accept_rate > 0.5 }">
                  {{ formatRate(row.accept_rate) }}
                </span>
              </template>
            </el-table-column>
          </AppTable>
        </el-tab-pane>
        <el-tab-pane label="运行记录" name="runs">
          <div class="filter-bar p-16 border-b">
            <el-input v-model="runFilters.search" clearable placeholder="搜索目标 ID / 运行信息" style="width: 220px" @keyup.enter="refreshRuns" />
            <el-select v-model="runFilters.agent_type" clearable placeholder="Agent 类型" style="width: 190px" @change="refreshRuns">
              <el-option v-for="item in agentTypes" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
            <el-select v-model="runFilters.status" clearable placeholder="运行状态" style="width: 150px" @change="refreshRuns">
              <el-option v-for="item in runStatuses" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
            <el-select v-model="runFilters.trigger_type" clearable placeholder="触发方式" style="width: 140px" @change="refreshRuns">
              <el-option label="事件触发" value="EVENT" />
              <el-option label="人工触发" value="MANUAL" />
            </el-select>
            <el-select v-model="runFilters.ref_object_type" clearable placeholder="目标类型" style="width: 140px" @change="refreshRuns">
              <el-option label="Application" value="APPLICATION" />
              <el-option label="Job" value="JOB" />
              <el-option label="Interview" value="INTERVIEW" />
            </el-select>
            <el-date-picker
              v-model="runFilters.date_range"
              type="daterange"
              value-format="YYYY-MM-DD"
              start-placeholder="开始日期"
              end-placeholder="结束日期"
              range-separator="至"
              style="width: 250px"
              @change="refreshRuns"
            />
            <el-button type="primary" plain @click="refreshRuns">查询</el-button>
            <el-button plain @click="resetRunFilters">重置</el-button>
          </div>
          <AppTable
            :data="runPage.records"
            :pagination-config="runPagination"
            @change-page="loadRuns"
            @size-change="refreshRuns"
            @row-click="openRun"
          >
            <el-table-column label="Agent" min-width="180">
              <template #default="{ row }">
                <div class="primary-cell">{{ agentLabel(row.agent_type) }}</div>
                <div class="secondary-cell">{{ row.trigger_type === 'EVENT' ? '事件触发' : '人工触发' }}</div>
              </template>
            </el-table-column>
            <el-table-column label="目标" min-width="210">
              <template #default="{ row }">
                <div class="primary-cell">{{ targetLabel(row) }}</div>
                <div class="secondary-cell">{{ row.ref_object_type }} · {{ row.ref_object_id }}</div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="120">
              <template #default="{ row }">
                <el-tag :type="runStatusType(row.status)" size="small">{{ runStatusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="模型 / Token" min-width="150">
              <template #default="{ row }">
                <div class="primary-cell">{{ row.llm_model || '未调用模型' }}</div>
                <div class="secondary-cell">{{ row.total_tokens }} tokens · {{ row.duration_ms }} ms</div>
              </template>
            </el-table-column>
            <el-table-column label="时间" width="180">
              <template #default="{ row }">{{ formatTime(row.create_time) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="120" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click.stop="openRun(row)">查看详情</el-button>
              </template>
            </el-table-column>
          </AppTable>
        </el-tab-pane>

        <el-tab-pane label="Proposal 收件箱" name="proposals">
          <div class="filter-bar p-16 border-b">
            <el-select v-model="proposalFilters.status" placeholder="提案状态" style="width: 160px" @change="refreshProposals">
              <el-option v-for="item in proposalStatuses" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
            <el-select v-model="proposalFilters.agent_type" clearable placeholder="Agent 类型" style="width: 190px" @change="refreshProposals">
              <el-option v-for="item in agentTypes" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </div>
          <AppTable
            :data="proposalPage.records"
            :pagination-config="proposalPagination"
            @change-page="loadProposals"
            @size-change="refreshProposals"
          >
            <el-table-column label="建议" min-width="180">
              <template #default="{ row }">
                <div class="primary-cell">{{ agentLabel(row.run_agent_type || row.target_type) }}</div>
                <div class="secondary-cell">{{ actionLabel(row.action) }}</div>
              </template>
            </el-table-column>
            <el-table-column label="目标" min-width="210">
              <template #default="{ row }">
                <div class="primary-cell">{{ row.target_type }}</div>
                <div class="secondary-cell">{{ row.target_id }}</div>
              </template>
            </el-table-column>
            <el-table-column label="摘要" min-width="260" show-overflow-tooltip>
              <template #default="{ row }">{{ row.summary || '查看提案详情中的结构化输出' }}</template>
            </el-table-column>
            <el-table-column label="证据" width="90">
              <template #default="{ row }">{{ row.evidence_count }}</template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tag :type="proposalStatusType(row.status)" size="small">{{ proposalStatusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="190" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openProposalRun(row)">查看证据</el-button>
                <el-button v-if="row.status === 'PENDING'" link type="danger" @click="dismiss(row)">忽略</el-button>
              </template>
            </el-table-column>
          </AppTable>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <el-drawer v-model="runDrawerVisible" :title="runDetail ? agentLabel(runDetail.run.agent_type) + ' 运行详情' : '运行详情'" size="720px">
      <el-skeleton v-if="runDetailLoading" :rows="8" animated />
      <template v-else-if="runDetail">
        <div class="detail-header mb-16">
          <div>
            <div class="primary-cell">{{ targetLabel(runDetail.run) }}</div>
            <div class="secondary-cell">{{ runDetail.run.ref_object_type }} · {{ runDetail.run.ref_object_id }}</div>
          </div>
          <div class="flex align-center gap-8">
            <el-tag :type="runStatusType(runDetail.run.status)">{{ runStatusLabel(runDetail.run.status) }}</el-tag>
            <el-button
              v-if="canRetry(runDetail.run.status)"
              size="small"
              :loading="retrying"
              @click="retryRun"
            >重试</el-button>
          </div>
        </div>

        <el-descriptions :column="2" border size="small" class="mb-16">
          <el-descriptions-item label="触发方式">{{ runDetail.run.trigger_type === 'EVENT' ? '事件触发' : '人工触发' }}</el-descriptions-item>
          <el-descriptions-item label="Prompt">{{ runDetail.run.prompt_version || '-' }}</el-descriptions-item>
          <el-descriptions-item label="模型">{{ runDetail.run.llm_model || '-' }}</el-descriptions-item>
          <el-descriptions-item label="Token">{{ runDetail.run.total_tokens }}</el-descriptions-item>
          <el-descriptions-item label="耗时">{{ runDetail.run.duration_ms }} ms</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatTime(runDetail.run.create_time) }}</el-descriptions-item>
        </el-descriptions>

        <el-alert v-if="runDetail.run.error" :title="runDetail.run.error" type="error" :closable="false" class="mb-16" />

        <section class="detail-section">
          <div class="section-title">工具轨迹</div>
          <el-timeline v-if="runDetail.run.tool_trace?.length">
            <el-timeline-item v-for="(trace, index) in runDetail.run.tool_trace" :key="index" :timestamp="String(trace.elapsed_ms || '') + ' ms'">
              <div class="primary-cell">{{ String(trace.tool || 'tool') }}</div>
              <div class="secondary-cell">{{ trace.rows != null ? String(trace.rows) + ' rows' : '已完成' }}</div>
            </el-timeline-item>
          </el-timeline>
          <el-empty v-else description="暂无工具轨迹" :image-size="60" />
        </section>

        <section class="detail-section">
          <div class="section-title">证据链（{{ runDetail.evidence.length }}）</div>
          <div v-if="runDetail.evidence.length" class="evidence-list">
            <div v-for="(item, index) in runDetail.evidence" :key="index" class="evidence-item">
              <div class="flex-between mb-8">
                <span class="secondary-cell">{{ item.paragraph_id || '未标注段落' }}</span>
                <el-tag v-if="item.relevance != null" size="small" type="success" effect="plain">相关度 {{ Math.round(Number(item.relevance) * 100) }}%</el-tag>
              </div>
              <p>{{ item.excerpt }}</p>
              <el-button
                v-if="item.paragraph_id"
                link
                type="primary"
                class="evidence-link"
                @click="openEvidence(item.paragraph_id)"
              >查看原文</el-button>
            </div>
          </div>
          <el-empty v-else description="没有提取到证据摘录" :image-size="60" />
        </section>

        <section class="detail-section">
          <div class="section-title">关联 Proposal</div>
          <div v-if="runDetail.proposals.length" class="proposal-list">
            <div v-for="proposal in runDetail.proposals" :key="proposal.id" class="proposal-item">
              <div class="flex-between mb-8">
                <strong>{{ actionLabel(proposal.action) }}</strong>
                <el-tag :type="proposalStatusType(proposal.status)" size="small">{{ proposalStatusLabel(proposal.status) }}</el-tag>
              </div>
              <div class="secondary-cell">{{ proposal.evidence_count }} 条证据 · {{ formatTime(proposal.create_time) }}</div>
              <div v-if="proposal.status === 'PENDING'" class="mt-12">
                <el-button size="small" type="primary" @click="accept(proposal)">接受提案</el-button>
                <el-button size="small" @click="dismiss(proposal)">忽略</el-button>
              </div>
            </div>
          </div>
          <el-empty v-else description="没有关联 Proposal" :image-size="60" />
        </section>

        <section class="detail-section">
          <div class="section-title">结构化输出</div>
          <pre class="json-output">{{ stringify(runDetail.run.output) }}</pre>
        </section>
      </template>
    </el-drawer>

    <el-dialog v-model="feedbackDialogVisible" title="Interview Feedback 重试" width="540px">
      <el-form label-width="88px">
        <el-form-item label="反馈内容" required>
          <el-input
            v-model="feedbackText"
            type="textarea"
            :rows="6"
            maxlength="4000"
            show-word-limit
            placeholder="请重新输入面试反馈文本（原反馈未安全保留，必须重新提供）"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="feedbackDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="retrying" @click="confirmFeedbackRetry">重试</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="evidenceDrawerVisible" title="简历原文证据" size="620px">
      <el-skeleton v-if="evidenceLoading" :rows="8" animated />
      <template v-else-if="evidenceDetail">
        <div class="evidence-source mb-16">
          <div class="primary-cell">{{ evidenceDetail.file_name }}</div>
          <div class="secondary-cell">{{ evidenceDetail.title || '未命名段落' }} · 第 {{ evidenceDetail.position + 1 }} 段</div>
        </div>
        <pre class="source-output">{{ evidenceDetail.content }}</pre>
      </template>
      <el-empty v-else description="原文段落不可用" :image-size="60" />
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import HrApi from '@/api/hr/recruitment'
import type { AgentStats, AgentWorkbenchEvidenceDetail, AgentWorkbenchPage, AgentWorkbenchProposal, AgentWorkbenchRun, AgentWorkbenchRunDetail } from '@/api/type/hr'
import { MsgConfirm, MsgError, MsgSuccess } from '@/utils/message'

const activeTab = ref('runs')
const loading = ref(false)
const retrying = ref(false)
const feedbackDialogVisible = ref(false)
const feedbackText = ref('')
const evidenceDrawerVisible = ref(false)
const evidenceLoading = ref(false)
const evidenceDetail = ref<AgentWorkbenchEvidenceDetail | null>(null)
const overviewLoading = ref(false)
const overviewRows = ref<AgentStats['by_agent']>([])
const runDrawerVisible = ref(false)
const runDetailLoading = ref(false)
const runDetail = ref<AgentWorkbenchRunDetail | null>(null)
const runPage = ref<AgentWorkbenchPage<AgentWorkbenchRun>>({ records: [], total: 0, current_page: 1, page_size: 20 })
const proposalPage = ref<AgentWorkbenchPage<AgentWorkbenchProposal>>({ records: [], total: 0, current_page: 1, page_size: 20 })
const runFilters = reactive({
  agent_type: '',
  status: '',
  trigger_type: '',
  ref_object_type: '',
  search: '',
  date_range: [] as string[],
})
const proposalFilters = reactive({ agent_type: '', status: 'PENDING' })
const runPagination = reactive({ current_page: 1, page_size: 20, total: 0 })
const proposalPagination = reactive({ current_page: 1, page_size: 20, total: 0 })

const agentTypes = [
  { value: 'SCREENING', label: 'Screening 初筛' },
  { value: 'JD_DRAFT', label: 'JD 起草' },
  { value: 'INTERVIEW_COPILOT', label: 'Interview Copilot' },
  { value: 'SOURCING', label: 'Sourcing 激活' },
  { value: 'COMMUNICATION_DRAFT', label: '沟通草稿' },
]
const runStatuses = [
  { value: 'RUNNING', label: '运行中' },
  { value: 'SUCCEEDED', label: '成功' },
  { value: 'FAILED', label: '失败' },
  { value: 'SKIPPED', label: '已跳过' },
]
const proposalStatuses = [
  { value: 'PENDING', label: '待处理' },
  { value: 'ACCEPTED', label: '已接受' },
  { value: 'DISMISSED', label: '已忽略' },
  { value: 'EXPIRED', label: '已过期' },
]

const runSummary = computed(() => runPage.value.summary || { total_runs: 0, status_counts: {}, total_tokens: 0, total_duration_ms: 0 })
function formatNumber(value: number) {
  return value != null ? value.toLocaleString('zh-CN') : '0'
}
function formatDuration(ms: number) {
  if (!ms) return '0 ms'
  if (ms < 60000) return Math.round(ms) + ' ms'
  const seconds = ms / 1000
  if (seconds < 3600) return seconds.toFixed(1) + ' s'
  return (seconds / 3600).toFixed(2) + ' h'
}
function formatRate(value: number | null | undefined) {
  if (value == null) return '-'
  return Math.round(value * 100) + '%'
}

function agentLabel(value: string) {
  return agentTypes.find((item) => item.value === value)?.label || value
}
function actionLabel(value: string) {
  return ({ ADVANCE: '建议推进', DECLINE: '建议拒绝', HOLD: '建议暂缓', DRAFT: '草稿' } as Record<string, string>)[value] || value
}
function runStatusLabel(value: string) {
  return ({ PENDING: '等待中', RUNNING: '运行中', SUCCEEDED: '成功', FAILED: '失败', SKIPPED: '已跳过' } as Record<string, string>)[value] || value
}
function runStatusType(value: string) {
  return ({ SUCCEEDED: 'success', FAILED: 'danger', SKIPPED: 'warning', RUNNING: 'primary' } as Record<string, string>)[value] || 'info'
}
function proposalStatusLabel(value: string) {
  return ({ PENDING: '待处理', ACCEPTED: '已接受', DISMISSED: '已忽略', EXPIRED: '已过期' } as Record<string, string>)[value] || value
}
function proposalStatusType(value: string) {
  return ({ PENDING: 'warning', ACCEPTED: 'success', DISMISSED: 'info', EXPIRED: 'info' } as Record<string, string>)[value] || 'info'
}
function targetLabel(run: AgentWorkbenchRun) {
  const meta = run.input_meta || {}
  return String(meta.job_name || meta.candidate_name || meta.application_id || meta.job_id || meta.interview_id || run.ref_object_id)
}
function formatTime(value: string) {
  return value ? new Date(value).toLocaleString() : '-'
}
function stringify(value: unknown) {
  return value == null ? '暂无输出' : JSON.stringify(value, null, 2)
}
function canRetry(status: string) {
  return status === 'FAILED' || status === 'SKIPPED'
}
function runParams() {
  return {
    current_page: runPagination.current_page,
    page_size: runPagination.page_size,
    agent_type: runFilters.agent_type || undefined,
    status: runFilters.status || undefined,
    trigger_type: runFilters.trigger_type || undefined,
    ref_object_type: runFilters.ref_object_type || undefined,
    search: runFilters.search || undefined,
    created_from: runFilters.date_range[0] || undefined,
    created_to: runFilters.date_range[1] || undefined,
  }
}
function proposalParams() {
  return {
    current_page: proposalPagination.current_page,
    page_size: proposalPagination.page_size,
    agent_type: proposalFilters.agent_type || undefined,
    status: proposalFilters.status || undefined,
  }
}
function loadRuns() {
  loading.value = true
  HrApi.getAgentRuns(runParams())
    .then((response) => {
      runPage.value = response.data || runPage.value
      runPagination.total = runPage.value.total
    })
    .catch(() => {})
    .finally(() => { loading.value = false })
}
function loadProposals() {
  HrApi.getAgentProposalInbox(proposalParams())
    .then((response) => {
      proposalPage.value = response.data || proposalPage.value
      proposalPagination.total = proposalPage.value.total
    })
    .catch(() => {})
}
function refreshRuns() {
  runPagination.current_page = 1
  loadRuns()
}
function refreshProposals() {
  proposalPagination.current_page = 1
  loadProposals()
}
function resetRunFilters() {
  runFilters.agent_type = ''
  runFilters.status = ''
  runFilters.trigger_type = ''
  runFilters.ref_object_type = ''
  runFilters.search = ''
  runFilters.date_range = []
  refreshRuns()
}
function refreshAll() {
  loadOverview()
  loadRuns()
  loadProposals()
}
function loadOverview() {
  overviewLoading.value = true
  HrApi.getAgentStats()
    .then((response) => { overviewRows.value = response.data?.by_agent || [] })
    .catch(() => { overviewRows.value = [] })
    .finally(() => { overviewLoading.value = false })
}
function openRun(row: AgentWorkbenchRun) {
  runDrawerVisible.value = true
  runDetailLoading.value = true
  runDetail.value = null
  HrApi.getAgentRun(row.id)
    .then((response) => { runDetail.value = response.data || null })
    .catch(() => {})
    .finally(() => { runDetailLoading.value = false })
}
function openProposalRun(proposal: AgentWorkbenchProposal) {
  if (!proposal.run_id) return
  const row = runPage.value.records.find((item) => item.id === proposal.run_id)
  if (row) openRun(row)
  else {
    runDrawerVisible.value = true
    runDetailLoading.value = true
    HrApi.getAgentRun(proposal.run_id)
      .then((response) => { runDetail.value = response.data || null })
      .catch(() => {})
      .finally(() => { runDetailLoading.value = false })
  }
}
function openEvidence(paragraphId: string | null) {
  if (!paragraphId) return
  evidenceDrawerVisible.value = true
  evidenceLoading.value = true
  evidenceDetail.value = null
  HrApi.getAgentEvidenceParagraph(paragraphId)
    .then((response) => { evidenceDetail.value = response.data || null })
    .catch(() => {})
    .finally(() => { evidenceLoading.value = false })
}
function doRetry(data: Record<string, unknown> = {}) {
  if (!runDetail.value) return
  retrying.value = true
  HrApi.retryAgentRun(runDetail.value.run.id, data)
    .then((response) => {
      if (response.data?.status === 'FAILED') MsgError(String(response.data.error || '重试失败'))
      else MsgSuccess('已创建新的 Agent 运行')
      openRun(runDetail.value!.run)
      refreshAll()
    })
    .catch(() => {})
    .finally(() => { retrying.value = false })
}
function retryRun() {
  if (!runDetail.value) return
  const run = runDetail.value.run
  if (run.agent_type === 'INTERVIEW_COPILOT' && run.input_meta?.phase === 'feedback') {
    feedbackText.value = ''
    feedbackDialogVisible.value = true
    return
  }
  doRetry()
}
function confirmFeedbackRetry() {
  if (!feedbackText.value.trim()) {
    MsgError('请填写面试反馈内容')
    return
  }
  feedbackDialogVisible.value = false
  doRetry({ feedback: feedbackText.value.trim() })
}
function accept(proposal: AgentWorkbenchProposal) {
  MsgConfirm('接受提案', '确认按该提案调用 ATS 命令执行？')
    .then(() => HrApi.acceptProposal(proposal.id, { decision_note: 'Agent 工作台接受' }))
    .then(() => { MsgSuccess('提案已接受'); refreshAll(); if (runDetail.value) openRun(runDetail.value.run) })
    .catch(() => {})
}
function dismiss(proposal: AgentWorkbenchProposal) {
  MsgConfirm('忽略提案', '确认忽略该 Proposal？')
    .then(() => HrApi.dismissProposal(proposal.id, { decision_note: 'Agent 工作台忽略' }))
    .then(() => { MsgSuccess('提案已忽略'); refreshAll(); if (runDetail.value) openRun(runDetail.value.run) })
    .catch(() => {})
}

onMounted(refreshAll)
</script>

<style scoped lang="scss">
.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
.summary-item {
  min-height: 88px;
  padding: 16px;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
  border-radius: 6px;
}
.summary-item strong { display: block; margin-top: 8px; font-size: 24px; color: var(--el-text-color-primary); }
.summary-label, .secondary-cell { color: var(--el-text-color-secondary); font-size: 12px; }
.summary-sub { display: block; margin-top: 4px; color: var(--el-text-color-secondary); font-size: 12px; }
.primary-cell { color: var(--el-text-color-primary); font-weight: 600; }
.danger-text { color: var(--el-color-danger) !important; }
.success-text { color: var(--el-color-success); }
.filter-bar { display: flex; align-items: center; gap: 12px; }
.workbench-tabs :deep(.el-tabs__header) { margin: 0; padding: 0 16px; }
.detail-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.detail-section { margin-top: 20px; }
.section-title { margin-bottom: 10px; color: var(--el-text-color-primary); font-weight: 600; }
.evidence-list, .proposal-list { display: grid; gap: 10px; }
.evidence-item, .proposal-item { padding: 12px; border: 1px solid var(--el-border-color-lighter); border-radius: 6px; background: var(--el-fill-color-lighter); }
.evidence-item p { margin: 0; color: var(--el-text-color-regular); line-height: 1.65; white-space: pre-wrap; }
.evidence-link { margin-top: 8px; padding-left: 0; }
.source-output { max-height: calc(100vh - 170px); overflow: auto; margin: 0; padding: 16px; border: 1px solid var(--el-border-color-lighter); border-radius: 6px; background: var(--el-fill-color-lighter); color: var(--el-text-color-primary); line-height: 1.75; white-space: pre-wrap; word-break: break-word; }
.json-output { max-height: 280px; overflow: auto; margin: 0; padding: 12px; border-radius: 6px; background: #1f2937; color: #e5e7eb; font-size: 12px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
@media (max-width: 900px) {
  .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .filter-bar { flex-wrap: wrap; }
}
</style>
