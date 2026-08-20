<template>
  <div class="pipeline-page p-16-24">
    <header class="page-header">
      <div>
        <div class="eyebrow">ATS V2</div>
        <h2>人才 Pipeline</h2>
        <p class="color-secondary">以申请为中心管理候选人流转，所有阶段变更都保留审计记录。</p>
      </div>
      <div class="header-actions">
        <el-select v-model="selectedJobId" placeholder="选择职位" clearable @change="loadPipeline" style="width: 260px">
          <el-option v-for="job in jobs" :key="job.id" :label="job.name" :value="job.id">
            <span>{{ job.name }}</span>
            <span class="option-meta">{{ job.status === 'OPEN' ? '开放' : job.status }}</span>
          </el-option>
        </el-select>
        <el-button :icon="Refresh" circle title="刷新 Pipeline" :loading="loading" @click="refresh" />
        <el-button v-if="isHrAdmin" type="primary" :icon="Plus" @click="router.push('/hr/jobs/new')">新建职位</el-button>
      </div>
    </header>

    <div class="summary-strip" aria-label="Pipeline 摘要">
      <div class="summary-item"><span>当前申请</span><strong>{{ applications.length }}</strong></div>
      <div class="summary-item"><span>流程阶段</span><strong>{{ stages.length }}</strong></div>
      <div class="summary-item"><span>筛选阶段</span><strong>{{ screeningCount }}</strong></div>
      <div class="summary-context">
        <span>{{ selectedJob?.name || '尚未选择职位' }}</span>
        <small v-if="selectedJob">{{ selectedJob.department || '未设置部门' }} · {{ selectedJob.city || '未设置城市' }}</small>
      </div>
    </div>

    <div class="toolbar">
      <el-input v-model="filters.q" clearable placeholder="搜索候选人姓名、电话或邮箱" @keyup.enter="refresh" @clear="refresh">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="filters.status" style="width: 150px" @change="refresh">
        <el-option label="在途申请" value="ACTIVE" />
        <el-option label="已录用" value="HIRED" />
        <el-option label="已淘汰" value="REJECTED" />
        <el-option label="全部状态" value="" />
      </el-select>
      <el-button v-if="filters.q || filters.status !== 'ACTIVE'" text @click="resetFilters">清除筛选</el-button>
    </div>

    <div v-loading="loading" class="board-frame">
      <el-empty v-if="!selectedJobId" description="请选择一个职位查看申请 Pipeline" />
      <el-empty v-else-if="!loading && stages.length === 0" description="该职位尚未配置流程阶段" />
      <el-empty v-else-if="!loading && applications.length === 0" description="当前筛选条件下暂无申请" />
      <div v-else class="pipeline-board">
        <section
          v-for="stage in stages"
          :key="stage.id"
          class="stage-column"
          :style="{ '--stage-color': stage.color || '#409eff' }"
          @dragover.prevent
          @drop="dropStage(stage)"
        >
          <div class="stage-header">
            <div class="stage-title"><span class="stage-dot" /><strong>{{ stage.name }}</strong></div>
            <el-tag size="small" effect="plain">{{ columnApplications(stage.id).length }}</el-tag>
          </div>
          <div class="stage-body">
            <article
              v-for="application in columnApplications(stage.id)"
              :key="application.id"
              class="application-card"
              draggable="true"
              @dragstart="startDrag(application)"
              @dragend="draggedApplicationId = null"
              @click="openDetail(application)"
            >
              <div class="card-head"><strong>{{ application.candidate_name }}</strong><el-icon class="drag-hint" title="拖动到其他阶段"><MoreFilled /></el-icon></div>
              <div class="card-meta">{{ application.channel || '未标注来源' }} · {{ formatDate(application.update_time) }}</div>
              <div class="card-tags">
                <el-tag v-if="application.relation_type" size="small" effect="plain">{{ relationLabel(application.relation_type) }}</el-tag>
                <el-tag v-if="application.owner_id" size="small" type="info" effect="plain">已分配</el-tag>
                <el-tag v-if="application.termination_reason" size="small" type="danger" effect="plain">{{ application.termination_reason }}</el-tag>
              </div>
              <div v-if="application.note" class="card-note">{{ application.note }}</div>
            </article>
            <div v-if="columnApplications(stage.id).length === 0" class="stage-empty">拖动申请到这里</div>
          </div>
        </section>
      </div>
    </div>

    <el-drawer v-model="detailVisible" :title="selectedApplication?.candidate_name || '申请详情'" size="min(560px, 100%)">
      <template v-if="selectedApplication">
        <div class="detail-subtitle">
          <span>{{ selectedApplication.job_name }}</span>
          <el-tag :type="statusTag(selectedApplication.status)" size="small">{{ statusLabel(selectedApplication.status) }}</el-tag>
          <el-button class="detail-candidate" link type="primary" size="small" @click="openCandidate">查看候选人</el-button>
        </div>
        <div class="detail-actions">
          <el-dropdown v-if="isOperator && selectedApplication.status === 'ACTIVE'" trigger="click" @command="moveSelected">
            <el-button type="primary">推进阶段 <el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
            <template #dropdown>
              <el-dropdown-menu><el-dropdown-item v-for="stage in stages" :key="stage.id" :command="stage.id" :disabled="stage.id === selectedApplication.current_stage?.id">{{ stage.name }}</el-dropdown-item></el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button v-if="isOperator && selectedApplication.status === 'ACTIVE'" type="danger" plain :icon="Close" @click="rejectSelected">淘汰</el-button>
          <el-button v-if="isHrAdmin && selectedApplication.status === 'REJECTED'" type="warning" plain @click="restoreSelected">恢复申请</el-button>
        </div>

        <el-descriptions :column="1" border class="detail-descriptions">
          <el-descriptions-item label="当前阶段">{{ selectedApplication.current_stage?.name || '未进入阶段' }}</el-descriptions-item>
          <el-descriptions-item label="申请时间">{{ formatDate(selectedApplication.applied_at) }}</el-descriptions-item>
          <el-descriptions-item label="来源">{{ selectedApplication.channel || '-' }}{{ selectedApplication.channel_detail ? ' · ' + selectedApplication.channel_detail : '' }}</el-descriptions-item>
          <el-descriptions-item label="负责人">{{ selectedApplication.owner_id ? '已分配' : '未分配' }}</el-descriptions-item>
          <el-descriptions-item label="备注">{{ selectedApplication.note || '-' }}</el-descriptions-item>
        </el-descriptions>

        <section class="detail-section">
          <div class="section-heading"><h3>AI 筛选提案</h3><el-button v-if="isOperator && selectedApplication.status === 'ACTIVE'" text type="primary" :loading="agentRunning" :icon="MagicStick" @click="runScreening">重新运行</el-button></div>
          <el-skeleton v-if="detailLoading" :rows="4" animated />
          <el-empty v-else-if="!detailProposal" description="暂无 AI 提案" />
          <div v-else class="proposal-panel">
            <div class="proposal-head"><el-tag :type="proposalTag(detailProposal.action)" effect="dark">{{ detailActionLabel(detailProposal.action) }}</el-tag><span v-if="detailProposal.payload.decision.score !== null">评分 {{ detailProposal.payload.decision.score }}</span><span class="color-secondary">{{ proposalStatusLabel(detailProposal.status) }}</span></div>
            <div class="proposal-grid">
              <div><span>硬条件</span><strong>{{ detailProposal.payload.decision.hard_met ? '满足' : '不满足' }}</strong></div>
              <div><span>证据完整度</span><strong>{{ detailProposal.payload.decision.evidence_ok ? '通过' : '不足' }}</strong></div>
              <div><span>必要维度</span><strong>{{ detailProposal.payload.decision.required_dims_ok ? '通过' : '不足' }}</strong></div>
            </div>
            <div v-if="detailProposal.payload.concerns?.length" class="proposal-list"><span class="list-label">关注点</span><ul><li v-for="item in detailProposal.payload.concerns" :key="item">{{ item }}</li></ul></div>
            <div class="proposal-footer">
              <div><el-button v-if="isOperator && detailProposal.status === 'PENDING'" size="small" type="success" :icon="Check" @click="acceptSelectedProposal">采纳</el-button><el-button v-if="isOperator && detailProposal.status === 'PENDING'" size="small" plain @click="dismissSelectedProposal">忽略</el-button></div>
              <span class="color-secondary text-12">版本 {{ detailProposal.payload.decision.score_version }}</span>
            </div>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-heading"><h3>申请时间线</h3></div>
          <el-timeline v-if="detailEvents.length"><el-timeline-item v-for="event in detailEvents" :key="event.id" :timestamp="formatDate(event.create_time)" placement="top"><strong>{{ eventLabel(event.event_type) }}</strong><div class="color-secondary text-12">{{ event.reason_text || (event.from_status || '-') + ' → ' + (event.to_status || '-') }}</div></el-timeline-item></el-timeline>
          <el-empty v-else description="暂无流转记录" />
        </section>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { ArrowDown, Check, Close, MagicStick, MoreFilled, Plus, Refresh, Search } from '@element-plus/icons-vue'
import HrApi from '@/api/hr/recruitment'
import type { AgentProposal, Application, ApplicationEvent, Job, JobStage } from '@/api/type/hr'
import useStore from '@/stores'
import { MsgError, MsgSuccess } from '@/utils/message'

const router = useRouter()
const route = useRoute()
const { user } = useStore()
const loading = ref(false)
const jobs = ref<Job[]>([])
const stages = ref<JobStage[]>([])
const applications = ref<Application[]>([])
const selectedJobId = ref<string>((route.query.job as string) || '')
const draggedApplicationId = ref<string | null>(null)
const detailVisible = ref(false)
const selectedApplication = ref<Application | null>(null)
const detailEvents = ref<ApplicationEvent[]>([])
const detailProposal = ref<AgentProposal | null>(null)
const detailLoading = ref(false)
const agentRunning = ref(false)
const filters = reactive({ q: '', status: 'ACTIVE' })

const isOperator = computed(() => ['ADMIN', 'OPERATOR'].includes(user.getHrRole() || ''))
const isHrAdmin = computed(() => user.getHrRole() === 'ADMIN')
const selectedJob = computed(() => jobs.value.find((job) => job.id === selectedJobId.value) || null)
const screeningCount = computed(() => applications.value.filter((item) => item.current_stage?.key === 'SCREEN').length)

function loadJobs() {
  return HrApi.getJobs({ current_page: 1, page_size: 100 }, {})
    .then((response) => {
      jobs.value = response.data.records
      if (!selectedJobId.value || !jobs.value.some((job) => job.id === selectedJobId.value)) selectedJobId.value = jobs.value.find((job) => job.status === 'OPEN')?.id || jobs.value[0]?.id || ''
      return loadPipeline()
    })
    .catch(() => MsgError('职位列表加载失败'))
}

function loadPipeline() {
  if (!selectedJobId.value) { stages.value = []; applications.value = []; return Promise.resolve() }
  loading.value = true
  return Promise.all([
    HrApi.getJobStages(selectedJobId.value),
    HrApi.getApplications({ current_page: 1, page_size: 200 }, { job_id: selectedJobId.value, status: filters.status || undefined, q: filters.q || undefined }),
  ])
    .then(([stageResponse, applicationResponse]) => { stages.value = [...stageResponse.data].sort((a, b) => a.order - b.order); applications.value = applicationResponse.data.records })
    .catch(() => MsgError('Pipeline 加载失败'))
    .finally(() => { loading.value = false })
}

function refresh() { loadPipeline() }
function resetFilters() { filters.q = ''; filters.status = 'ACTIVE'; refresh() }
function columnApplications(stageId: string) { return applications.value.filter((application) => application.current_stage?.id === stageId) }
function startDrag(application: Application) { draggedApplicationId.value = application.id }

function dropStage(stage: JobStage) {
  const applicationId = draggedApplicationId.value
  draggedApplicationId.value = null
  const application = applications.value.find((item) => item.id === applicationId)
  if (!application || application.current_stage?.id === stage.id || application.status !== 'ACTIVE') return
  HrApi.moveApplicationStage(application.id, { to_stage_id: stage.id, reason_text: 'Pipeline 拖拽流转' })
    .then(() => { MsgSuccess('已移入' + stage.name); loadPipeline(); if (selectedApplication.value?.id === application.id) openDetail(application) })
    .catch(() => MsgError('阶段流转失败'))
}

function openDetail(application: Application) {
  selectedApplication.value = application
  detailVisible.value = true
  detailLoading.value = true
  detailEvents.value = []
  detailProposal.value = null
  Promise.all([HrApi.getApplicationEvents(application.id), HrApi.getApplicationProposals(application.id)])
    .then(([eventResponse, proposalResponse]) => { detailEvents.value = eventResponse.data || []; detailProposal.value = (proposalResponse.data || []).find((proposal) => proposal.status === 'PENDING') || proposalResponse.data?.[0] || null })
    .catch(() => MsgError('申请详情加载失败'))
    .finally(() => { detailLoading.value = false })
}

function moveSelected(stageId: string) {
  if (!selectedApplication.value) return
  const stage = stages.value.find((item) => item.id === stageId)
  if (!stage || selectedApplication.value.current_stage?.id === stageId) return
  const currentOrder = selectedApplication.value.current_stage?.order ?? 0
  if (stage.order < currentOrder) {
    ElMessageBox.prompt('回退到更早阶段必须填写原因，原因会写入申请时间线。', '阶段回退', {
      confirmButtonText: '确认回退', cancelButtonText: '取消',
      inputPlaceholder: '例如：补充材料后重新评估',
    })
      .then(({ value }) => HrApi.moveApplicationStage(selectedApplication.value!.id, {
        to_stage_id: stageId,
        reason_text: value || '人工回退',
        idempotency_key: 'back-' + Date.now(),
      }))
      .then(() => { MsgSuccess('已回退到' + stage.name); detailVisible.value = false; loadPipeline() })
      .catch(() => {})
    return
  }
  HrApi.moveApplicationStage(selectedApplication.value.id, { to_stage_id: stageId, reason_text: '详情页流转' })
    .then(() => { MsgSuccess('已移入' + stage.name); detailVisible.value = false; loadPipeline() })
    .catch(() => MsgError('阶段流转失败'))
}

function runScreening() {
  if (!selectedApplication.value) return
  agentRunning.value = true
  HrApi.runScreeningAgent(selectedApplication.value.id)
    .then(() => { MsgSuccess('筛选任务已提交'); openDetail(selectedApplication.value as Application) })
    .catch(() => MsgError('筛选任务提交失败'))
    .finally(() => { agentRunning.value = false })
}

function rejectSelected() {
  if (!selectedApplication.value) return
  ElMessageBox.prompt('请输入淘汰原因，原因会写入申请时间线。', '淘汰申请', { confirmButtonText: '确认淘汰', cancelButtonText: '取消', inputPlaceholder: '例如：硬条件不满足' })
    .then(({ value }) => HrApi.terminalApplication(selectedApplication.value!.id, { action: 'reject', termination_reason: 'NOT_FIT', reason_text: value }))
    .then(() => { MsgSuccess('申请已淘汰'); detailVisible.value = false; loadPipeline() })
    .catch(() => {})
}

function restoreSelected() {
  if (!selectedApplication.value) return
  HrApi.restoreApplication(selectedApplication.value.id, { reason_text: '人工恢复申请' })
    .then(() => { MsgSuccess('申请已恢复'); detailVisible.value = false; loadPipeline() })
    .catch(() => MsgError('恢复申请失败'))
}

function acceptSelectedProposal() {
  if (!detailProposal.value) return
  HrApi.acceptProposal(detailProposal.value.id, { decision_note: 'HR 在 Pipeline 详情中采纳' })
    .then(() => { MsgSuccess('提案已采纳'); if (selectedApplication.value) openDetail(selectedApplication.value) })
    .catch(() => MsgError('采纳提案失败'))
}

function dismissSelectedProposal() {
  if (!detailProposal.value) return
  HrApi.dismissProposal(detailProposal.value.id, { decision_note: 'HR 在 Pipeline 详情中忽略' })
    .then(() => { MsgSuccess('提案已忽略'); if (selectedApplication.value) openDetail(selectedApplication.value) })
    .catch(() => MsgError('忽略提案失败'))
}

function openCandidate() { if (selectedApplication.value) router.push('/hr/candidates/' + selectedApplication.value.candidate_id) }
function formatDate(value: string | null | undefined) { return value ? new Date(value).toLocaleString() : '-' }
function statusLabel(status: string) { return ({ ACTIVE: '在途', HIRED: '已录用', REJECTED: '已淘汰', WITHDRAWN: '已撤回', CLOSED: '已关闭' } as Record<string, string>)[status] || status }
function statusTag(status: string) { return ({ ACTIVE: 'primary', HIRED: 'success', REJECTED: 'danger', WITHDRAWN: 'warning', CLOSED: 'info' } as Record<string, string>)[status] || 'info' }
function relationLabel(relation: string) { return ({ APPLY: '主动申请', SEEK: '人才库', REFERRAL: '内推', HEADHUNTER: '猎头' } as Record<string, string>)[relation] || relation }
function detailActionLabel(action: string) { return ({ ADVANCE: '建议推进', DECLINE: '建议淘汰', HOLD: '建议暂缓', DRAFT: '草稿' } as Record<string, string>)[action] || action }
function proposalStatusLabel(status: string) { return ({ PENDING: '待人工决策', ACCEPTED: '已采纳', DISMISSED: '已忽略', EXPIRED: '已过期' } as Record<string, string>)[status] || status }
function proposalTag(action: string) { return ({ ADVANCE: 'success', DECLINE: 'danger', HOLD: 'warning', DRAFT: 'info' } as Record<string, string>)[action] || 'info' }
function eventLabel(eventType: string) { return ({ CREATED: '创建申请', IMPORTED: '导入申请', STAGE_MOVED: '阶段变更', HIRED: '录用', REJECTED: '淘汰', WITHDRAWN: '候选人撤回', CLOSED: '申请关闭', RESTORED: '恢复申请' } as Record<string, string>)[eventType] || eventType }

onMounted(loadJobs)
</script>

<style scoped>
.pipeline-page { min-height: 100%; background: var(--el-bg-color-page); }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 24px; margin-bottom: 18px; }
.eyebrow { color: var(--el-color-primary); font-size: 12px; font-weight: 700; letter-spacing: 1px; margin-bottom: 6px; }
h2 { margin: 0 0 6px; font-size: 24px; line-height: 32px; }
.page-header p { margin: 0; font-size: 13px; }
.header-actions, .toolbar, .detail-actions, .card-tags, .proposal-footer { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.option-meta { margin-left: 12px; color: var(--el-text-color-secondary); font-size: 12px; }
.summary-strip { display: flex; align-items: stretch; min-height: 72px; margin-bottom: 16px; border: 1px solid var(--el-border-color-light); border-radius: 6px; background: var(--el-bg-color); }
.summary-item { min-width: 150px; padding: 14px 20px; border-right: 1px solid var(--el-border-color-lighter); }
.summary-item span, .summary-context small { display: block; color: var(--el-text-color-secondary); font-size: 12px; }
.summary-item strong { display: block; margin-top: 4px; font-size: 22px; line-height: 28px; }
.summary-context { display: flex; flex-direction: column; justify-content: center; padding: 12px 20px; color: var(--el-text-color-primary); }
.summary-context small { margin-top: 3px; }
.toolbar { margin-bottom: 12px; }
.toolbar .el-input { width: min(360px, 100%); }
.board-frame { min-height: 420px; padding: 12px; border: 1px solid var(--el-border-color-light); border-radius: 6px; background: var(--el-fill-color-lighter); }
.pipeline-board { display: flex; align-items: flex-start; gap: 12px; min-height: 396px; overflow-x: auto; padding-bottom: 8px; }
.stage-column { flex: 0 0 276px; min-height: 390px; border: 1px solid var(--el-border-color-light); border-top: 3px solid var(--stage-color); border-radius: 6px; background: var(--el-bg-color); }
.stage-header { display: flex; justify-content: space-between; align-items: center; padding: 12px 14px; border-bottom: 1px solid var(--el-border-color-lighter); }
.stage-title { display: flex; align-items: center; gap: 8px; min-width: 0; }
.stage-title strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.stage-dot { width: 8px; height: 8px; flex: 0 0 8px; border-radius: 50%; background: var(--stage-color); }
.stage-body { min-height: 330px; padding: 10px; }
.application-card { padding: 12px; margin-bottom: 10px; border: 1px solid var(--el-border-color-lighter); border-radius: 5px; background: var(--el-bg-color); cursor: pointer; transition: border-color .16s, box-shadow .16s, transform .16s; }
.application-card:hover { border-color: var(--el-color-primary-light-5); box-shadow: var(--el-box-shadow-light); transform: translateY(-1px); }
.application-card:last-child { margin-bottom: 0; }
.card-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.card-head strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.drag-hint { color: var(--el-text-color-placeholder); }
.card-meta, .card-note, .text-12 { color: var(--el-text-color-secondary); font-size: 12px; line-height: 18px; }
.card-meta { margin: 6px 0 8px; }
.card-note { margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--el-border-color-lighter); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.stage-empty { padding: 30px 10px; color: var(--el-text-color-placeholder); font-size: 12px; text-align: center; }
.detail-subtitle, .section-heading, .proposal-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.detail-subtitle { margin: -8px 0 16px; color: var(--el-text-color-secondary); }
.detail-candidate { margin-left: auto; }
.detail-actions { margin-bottom: 18px; }
.detail-descriptions { margin-bottom: 22px; }
.detail-section { padding-top: 20px; margin-top: 20px; border-top: 1px solid var(--el-border-color-lighter); }
.section-heading { margin-bottom: 14px; }
.section-heading h3 { margin: 0; font-size: 15px; }
.proposal-panel { padding: 14px; border: 1px solid var(--el-border-color-light); border-radius: 6px; background: var(--el-fill-color-lighter); }
.proposal-head { margin-bottom: 14px; font-size: 13px; }
.proposal-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.proposal-grid div { padding: 10px; border-radius: 4px; background: var(--el-bg-color); }
.proposal-grid span, .proposal-grid strong { display: block; }
.proposal-grid span { color: var(--el-text-color-secondary); font-size: 12px; }
.proposal-grid strong { margin-top: 4px; font-size: 13px; }
.proposal-list { margin-top: 14px; }
.list-label { font-size: 12px; font-weight: 600; }
.proposal-list ul { margin: 8px 0 0; padding-left: 18px; color: var(--el-text-color-secondary); font-size: 12px; line-height: 20px; }
.proposal-footer { justify-content: space-between; margin-top: 14px; }
@media (max-width: 900px) {
  .page-header { flex-direction: column; }
  .header-actions { width: 100%; }
  .header-actions .el-select { flex: 1; min-width: 220px; }
  .summary-strip { overflow-x: auto; }
  .summary-item { min-width: 125px; }
}
</style>
