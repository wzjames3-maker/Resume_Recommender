<template>
  <div class="hr-page p-16-24">
    <div class="flex-between mb-16">
      <div>
        <h2>职位</h2>
        <span class="color-secondary">维护开放职位与候选人筛选进度</span>
      </div>
      <el-button v-if="isWorkspaceManage" type="primary" @click="openJobDialog()">新建职位</el-button>
      <el-button v-if="isWorkspaceManage" plain @click="aiSettingVisible = true">AI 设置</el-button>
    </div>

    <el-card style="--el-card-padding: 0" v-loading="loading">
      <div class="p-16 border-b flex gap-12">
        <el-input v-model="filters.name" placeholder="按职位名称搜索" clearable @change="refresh" />
        <el-select v-model="filters.status" placeholder="状态" clearable @change="refresh" style="width: 140px">
          <el-option v-for="(label, value) in jobStatusLabels" :key="value" :label="label" :value="value" />
        </el-select>
        <el-button :type="filters.owner_id ? 'primary' : 'default'" plain @click="toggleMyJobs">待我处理</el-button>
      </div>

      <AppTable :data="jobs" :pagination-config="pagination" @change-page="loadJobs" @size-change="refresh" @expand-change="handleExpand">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="assignment-panel" v-loading="detailLoading === row.id">
              <el-tabs v-model="expandTab[row.id]" @tab-change="(name: string) => handleExpandTab(row, name)">
                <el-tab-pane label="候选人" name="assignments">
                  <el-empty v-if="jobDetails[row.id]?.assignments?.length === 0" description="暂无候选人" />
                  <el-table v-else :data="jobDetails[row.id]?.assignments" size="small">
                    <el-table-column prop="candidate_name" label="候选人" />
                    <el-table-column label="筛选状态" width="190">
                      <template #default="{ row: assignment }">
                        <el-select :model-value="assignment.status" size="small" @change="(value: AssignmentStatus) => onAssignmentStatusChange(assignment, value)">
                          <el-option v-for="(label, value) in assignmentStatusOptions" :key="value" :label="label" :value="value" />
                        </el-select>
                      </template>
                    </el-table-column>
                    <el-table-column label="关系类型" width="120">
                      <template #default="{ row: assignment }">
                        <el-select :model-value="assignment.relation_type" size="small" @change="(value: RelationType) => updateAssignmentFields(assignment, { relation_type: value })">
                          <el-option v-for="(label, value) in relationTypeLabels" :key="value" :label="label" :value="value" />
                        </el-select>
                      </template>
                    </el-table-column>
                    <el-table-column label="渠道" width="120">
                      <template #default="{ row: assignment }">
                        <el-select :model-value="assignment.channel" size="small" @change="(value: ResumeChannel) => updateAssignmentFields(assignment, { channel: value })">
                          <el-option v-for="(label, value) in channelLabels" :key="value" :label="label" :value="value" />
                        </el-select>
                      </template>
                    </el-table-column>
                    <el-table-column label="负责人" width="130">
                      <template #default="{ row: assignment }">
                        <el-select :model-value="assignment.owner_id" size="small" placeholder="负责人" clearable
                                   @change="(value: string | null) => updateAssignmentFields(assignment, { owner_id: value })">
                          <el-option v-for="member in members" :key="member.id" :label="member.nick_name" :value="member.id" />
                        </el-select>
                      </template>
                    </el-table-column>
                    <el-table-column prop="note" label="备注" show-overflow-tooltip />
                    <el-table-column label="操作" width="90">
                      <template #default="{ row: assignment }">
                        <el-button link type="primary" size="small" @click="openInterviewDrawer(row, assignment)">面试</el-button>
                      </template>
                    </el-table-column>
                  </el-table>
                </el-tab-pane>
                <el-tab-pane label="匹配候选人" name="matches">
                  <el-empty v-if="matches[row.id]?.records?.length === 0" description="暂无匹配候选人" />
                  <el-table v-else :data="matches[row.id]?.records || []" size="small">
                    <el-table-column prop="name" label="候选人" min-width="120" />
                    <el-table-column label="匹配分" width="90">
                      <template #default="{ row: match }"><el-tag size="small">{{ match.match_score }}</el-tag></template>
                    </el-table-column>
                    <el-table-column label="命中技能" min-width="160">
                      <template #default="{ row: match }">{{ match.matched_skills.join('、') || '-' }}</template>
                    </el-table-column>
                    <el-table-column prop="current_city" label="现居" width="100"><template #default="{ row: match }">{{ match.current_city || '-' }}</template></el-table-column>
                    <el-table-column label="操作" width="110">
                      <template #default="{ row: match }">
                        <el-button link type="primary" size="small" :disabled="row.status === 'CLOSED'" @click="addMatchToJob(row, match)">加入职位</el-button>
                      </template>
                    </el-table-column>
                  </el-table>
                </el-tab-pane>
              </el-tabs>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="职位" min-width="180" />
        <el-table-column prop="department" label="部门" min-width="130"><template #default="{ row }">{{ row.department || '-' }}</template></el-table-column>
        <el-table-column prop="city" label="城市" width="120"><template #default="{ row }">{{ row.city || '-' }}</template></el-table-column>
        <el-table-column label="HC" width="90"><template #default="{ row }">{{ row.active_assignment_count }}/{{ row.headcount }}</template></el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }"><el-tag :type="jobStatusTagType(row.status)">{{ jobStatusLabels[row.status] || row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column label="负责人" width="110">
          <template #default="{ row }">{{ memberName(row.owner_id) || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button v-if="isWorkspaceManage" link type="primary" @click="openJobDialog(row)">编辑</el-button>
            <el-button v-if="isWorkspaceManage" link type="warning" :disabled="row.status !== 'ON_HOLD' && row.status !== 'CLOSED'" @click="reopenJob(row)">恢复</el-button>
            <el-button v-if="isWorkspaceManage" link type="danger" :disabled="row.status === 'CLOSED'" @click="openCloseDialog(row)">关闭</el-button>
          </template>
        </el-table-column>
      </AppTable>
    </el-card>

    <el-dialog v-model="jobDialogVisible" :title="editingJob ? '编辑职位' : '新建职位'" width="620px">
      <el-form :model="jobForm" label-width="88px" @submit.prevent>
        <el-form-item label="职位名称" required><el-input v-model="jobForm.name" maxlength="128" /></el-form-item>
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="部门"><el-input v-model="jobForm.department" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="城市"><el-input v-model="jobForm.city" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="职级"><el-input v-model="jobForm.level" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="招聘人数"><el-input-number v-model="jobForm.headcount" :min="1" :max="999" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="状态">
              <el-select v-model="jobForm.status" style="width: 100%">
                <el-option v-for="(label, value) in jobStatusLabels" :key="value" :label="label" :value="value" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="负责人">
              <el-select v-model="jobForm.owner_id" clearable filterable placeholder="选择负责人" style="width: 100%">
                <el-option v-for="member in members" :key="member.id" :label="member.nick_name" :value="member.id" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item v-if="jobForm.status === 'CLOSED'" label="关闭原因" required>
          <el-select v-model="jobForm.close_reason" placeholder="选择关闭原因" style="width: 100%">
            <el-option v-for="(label, value) in jobCloseReasonLabels" :key="value" :label="label" :value="value" />
          </el-select>
        </el-form-item>
        <el-form-item label="职位描述"><el-input v-model="jobForm.description" type="textarea" :rows="5" maxlength="4096" show-word-limit /></el-form-item>
        <el-form-item label="技能要求">
          <div class="w-full">
            <el-input v-model="jobSkillsText" placeholder="用逗号分隔，例如 Python, Django" />
            <el-button class="mt-8" size="small" :loading="extractingSkills" :disabled="!jobForm.description.trim()" @click="extractSkillsFromDescription">AI 抽取技能</el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="jobDialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveJob">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="interviewDrawerVisible" title="面试记录" width="640px">
      <div class="flex-between mb-16">
        <span>{{ interviewCandidateName }} · 第 {{ interviewAssignment?.id?.slice(0, 8) }} 指派</span>
        <el-button type="primary" size="small" @click="addInterviewFormVisible = true">安排面试</el-button>
      </div>
      <el-form v-if="addInterviewFormVisible" label-width="88px" class="mb-16 p-16 border rounded">
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="面试官"><el-input v-model="interviewForm.interviewer" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="面试时间"><el-date-picker v-model="interviewForm.scheduled_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" style="width: 100%" /></el-form-item></el-col>
        </el-row>
        <div class="text-right">
          <el-button size="small" @click="addInterviewFormVisible = false">取消</el-button>
          <el-button size="small" type="primary" @click="createInterviewRecord">保存</el-button>
        </div>
      </el-form>
      <el-table :data="interviewList" size="small">
        <el-table-column prop="round_no" label="轮次" width="60" />
        <el-table-column prop="interviewer" label="面试官" min-width="100" />
        <el-table-column prop="scheduled_at" label="时间" min-width="150">
          <template #default="{ row }">{{ row.scheduled_at ? new Date(row.scheduled_at).toLocaleString() : '-' }}</template>
        </el-table-column>
        <el-table-column label="结果" width="130">
          <template #default="{ row }">
            <el-select v-model="row.status" size="small" @change="updateInterviewRecord(row)">
              <el-option label="待面试" value="PENDING" />
              <el-option label="通过" value="PASSED" />
              <el-option label="未通过" value="FAILED" />
              <el-option label="未到场" value="NO_SHOW" />
              <el-option label="取消" value="CANCELLED" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="反馈" min-width="160">
          <template #default="{ row }">
            <el-input v-model="row.feedback" size="small" @change="updateInterviewRecord(row)" placeholder="填写反馈" />
          </template>
        </el-table-column>
      </el-table>
      <template #footer><el-button @click="interviewDrawerVisible = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="closeDialogVisible" title="关闭职位" width="440px">
      <el-form label-width="96px">
        <el-form-item label="职位"><span>{{ closingJob?.name }}</span></el-form-item>
        <el-form-item label="在途关联">
          <el-tag type="warning">{{ closingJob?.active_assignment_count || 0 }}</el-tag>
          <span class="ml-8 color-secondary">将被批量收尾并标记为「职位关闭」</span>
        </el-form-item>
        <el-form-item label="关闭原因" required>
          <el-select v-model="closeReason" placeholder="选择关闭原因" style="width: 100%">
            <el-option v-for="(label, value) in jobCloseReasonLabels" :key="value" :label="label" :value="value" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="closeDialogVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!closeReason" :loading="saving" @click="confirmCloseJob">确认关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="statusDialogVisible" title="状态变更" width="440px">
      <el-form label-width="96px">
        <el-form-item label="候选人"><span>{{ statusDialogAssignment?.candidate_name }}</span></el-form-item>
        <el-form-item label="目标状态"><span>{{ assignmentStatusOptions[statusDialogTarget] || statusDialogTarget }}</span></el-form-item>
        <el-form-item v-if="isRestoreTransition" label="恢复原因" required>
          <el-input v-model="statusDialogNote" placeholder="填写误拒绝恢复原因" />
        </el-form-item>
        <el-form-item v-else label="终止原因" required>
          <el-select v-model="statusDialogReason" placeholder="选择终止原因" style="width: 100%">
            <el-option v-for="(label, value) in terminationReasonLabels" :key="value" :label="label" :value="value" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="statusDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="confirmStatusChange">确认</el-button>
      </template>
    </el-dialog>

    <AiSettingDialog v-model="aiSettingVisible" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import AppTable from '@/components/app-table/index.vue'
import AiSettingDialog from '@/views/hr/components/AiSettingDialog.vue'
import HrApi from '@/api/hr/recruitment'
import AuthorizationApi from '@/api/system/resource-authorization'
import type {
  Assignment,
  AssignmentStatus,
  Interview,
  Job,
  JobCloseReason,
  JobDetail,
  JobMatchCandidate,
  JobMatchPage,
  JobStatus,
  RelationType,
  ResumeChannel,
  TerminationReason,
} from '@/api/type/hr'
import useStore from '@/stores'
import { MsgConfirm, MsgError, MsgSuccess } from '@/utils/message'
import { hasPermission } from '@/utils/permission'
import { RoleConst } from '@/utils/permission/data'

interface WorkspaceMember {
  id: string
  nick_name: string
  roles: string[]
}

const jobStatusLabels: Record<string, string> = {
  DRAFT: '草稿',
  OPEN: '开放',
  ON_HOLD: '暂停',
  CLOSED: '已关闭',
}

const jobCloseReasonLabels: Record<string, string> = {
  FILLED: '招满',
  CANCELLED: '取消',
  DUPLICATE: '重复需求',
  OTHER: '其他',
}

const assignmentStatusOptions: Record<string, string> = {
  PENDING_SCREEN: '待筛选',
  SCREEN_PASSED: '筛选通过',
  INTERVIEWING: '面试中',
  OFFER: 'Offer 中',
  HIRED: '已入职',
  REJECTED: '已淘汰',
  WITHDRAWN: '已退出',
  CLOSED: '已关闭',
}

const relationTypeLabels: Record<string, string> = {
  APPLY: '投递',
  SEEK: '主动寻访',
  REFERRAL: '内推',
  HEADHUNTER: '猎头推荐',
}

const channelLabels: Record<string, string> = {
  REFERRAL: '内推',
  JOB_SITE: '招聘网站',
  HEADHUNTER: '猎头',
  CAMPUS: '校园',
  OTHER: '其他',
}

const terminationReasonLabels: Record<string, string> = {
  NOT_FIT: '不合适',
  SALARY: '薪资不符',
  UNREACHABLE: '无法联系',
  CANDIDATE_WITHDRAW: '候选人退出',
  JOB_CLOSED: '职位关闭',
  MERGED: '合并',
  OTHER: '其他',
}

const TERMINAL_STATUSES = ['REJECTED', 'WITHDRAWN', 'CLOSED']

const loading = ref(false)
const saving = ref(false)
const jobs = ref<Job[]>([])
const members = ref<WorkspaceMember[]>([])
const filters = reactive({ name: '', status: '', owner_id: '' })
const pagination = reactive({ current_page: 1, page_size: 20, total: 0 })
const jobDetails = reactive<Record<string, JobDetail>>({})
const matches = reactive<Record<string, JobMatchPage>>({})
const detailLoading = ref('')
const jobDialogVisible = ref(false)
const aiSettingVisible = ref(false)
const editingJob = ref<Job | null>(null)
const jobSkillsText = ref('')
const extractingSkills = ref(false)
const expandTab = reactive<Record<string, string>>({})
const jobForm = reactive({
  name: '', department: '', city: '', level: '', headcount: 1, description: '',
  status: 'OPEN' as JobStatus, close_reason: null as JobCloseReason | null, owner_id: null as string | null,
})
const isWorkspaceManage = computed(() => hasPermission([RoleConst.WORKSPACE_MANAGE.getWorkspaceRole], 'OR'))
const interviewDrawerVisible = ref(false)
const interviewList = ref<Interview[]>([])
const interviewAssignment = ref<Assignment | null>(null)
const interviewCandidateName = ref('')
const addInterviewFormVisible = ref(false)
const interviewForm = reactive({ interviewer: '', scheduled_at: null as string | null })
const closeDialogVisible = ref(false)
const closingJob = ref<Job | null>(null)
const closeReason = ref('')
const statusDialogVisible = ref(false)
const statusDialogAssignment = ref<Assignment | null>(null)
const statusDialogTarget = ref<AssignmentStatus | ''>('')
const statusDialogReason = ref<TerminationReason | ''>('')
const statusDialogNote = ref('')
const { user } = useStore()

const isRestoreTransition = computed(
  () => statusDialogAssignment.value?.status === 'REJECTED' && statusDialogTarget.value === 'PENDING_SCREEN',
)

function memberName(memberId: string | null) {
  if (!memberId) return ''
  return members.value.find((member) => member.id === memberId)?.nick_name || ''
}

function loadMembers() {
  AuthorizationApi.getUserMember(user.getWorkspaceId() || '').then((response) => {
    members.value = response.data || []
  }).catch(() => {})
}

function resetJobForm(job?: Job) {
  jobForm.name = job?.name || ''
  jobForm.department = job?.department || ''
  jobForm.city = job?.city || ''
  jobForm.level = job?.level || ''
  jobForm.headcount = job?.headcount || 1
  jobForm.description = job?.description || ''
  jobForm.status = (job?.status || 'OPEN') as JobStatus
  jobForm.close_reason = job?.close_reason || null
  jobForm.owner_id = job?.owner_id || null
  jobSkillsText.value = job?.skill_requirements?.join(', ') || ''
}

function loadJobs() {
  HrApi.getJobs(pagination, filters).then((response) => {
    jobs.value = response.data.records
    pagination.total = response.data.total
  })
}

function handleExpand(job: Job, expandedRows: Job[]) {
  if (expandedRows.some((row) => row.id === job.id) && !jobDetails[job.id]) {
    loadJobDetail(job)
    loadMatches(job)
  }
}

function handleExpandTab(job: Job, name: string) {
  if (name === 'matches' && !matches[job.id]) loadMatches(job)
}

function loadMatches(job: Job) {
  HrApi.getJobMatches(job.id, { current_page: 1, page_size: 50 }).then((response) => {
    matches[job.id] = response.data
  })
}

function refresh() {
  pagination.current_page = 1
  loadJobs()
}

function loadJobDetail(job: Job) {
  detailLoading.value = job.id
  HrApi.getJob(job.id).then((response) => {
    jobDetails[job.id] = response.data
  }).finally(() => {
    if (detailLoading.value === job.id) detailLoading.value = ''
  })
}

function openJobDialog(job?: Job) {
  editingJob.value = job || null
  resetJobForm(job)
  jobDialogVisible.value = true
}

function extractSkillsFromDescription() {
  const description = jobForm.description.trim()
  if (!description) return
  extractingSkills.value = true
  HrApi.extractSkills(description)
    .then((response) => {
      jobSkillsText.value = response.data.skills.join(', ')
      MsgSuccess('技能已抽取，可编辑后随职位保存')
    })
    .catch(() => {})
    .finally(() => {
      extractingSkills.value = false
    })
}

function saveJob() {
  if (!jobForm.name.trim()) return
  if (jobForm.status === 'CLOSED' && !jobForm.close_reason) {
    MsgError('关闭职位需要选择关闭原因')
    return
  }
  saving.value = true
  const data = {
    ...jobForm,
    skill_requirements: jobSkillsText.value.split(',').map((skill) => skill.trim()).filter(Boolean),
  }
  if (editingJob.value && jobForm.status === 'CLOSED' && editingJob.value.status !== 'CLOSED') {
    HrApi.closeJob(editingJob.value.id, jobForm.close_reason as JobCloseReason)
      .then((response) => {
        jobDialogVisible.value = false
        const count = response.data.closed_count
        MsgSuccess(count > 0 ? `职位已关闭，收尾 ${count} 个在途关联` : '职位已关闭')
        refresh()
      })
      .catch(() => {})
      .finally(() => { saving.value = false })
    return
  }
  const request = editingJob.value ? HrApi.updateJob(editingJob.value.id, data) : HrApi.createJob(data)
  request.then(() => {
    jobDialogVisible.value = false
    MsgSuccess('职位已保存')
    refresh()
  }).catch(() => {}).finally(() => { saving.value = false })
}

function toggleMyJobs() {
  filters.owner_id = filters.owner_id ? '' : user.userInfo?.id || ''
  refresh()
}

function openCloseDialog(job: Job) {
  closingJob.value = job
  closeReason.value = ''
  closeDialogVisible.value = true
}

function confirmCloseJob() {
  if (!closingJob.value || !closeReason.value) return
  saving.value = true
  HrApi.closeJob(closingJob.value.id, closeReason.value as JobCloseReason)
    .then((response) => {
      closeDialogVisible.value = false
      const count = response.data.closed_count
      MsgSuccess(count > 0 ? `职位已关闭，收尾 ${count} 个在途关联` : '职位已关闭')
      refresh()
    })
    .catch(() => {})
    .finally(() => { saving.value = false })
}

function reopenJob(job: Job) {
  MsgConfirm('恢复招聘', `将把“${job.name}”重新开放，并清空关闭原因。`)
    .then(() => HrApi.reopenJob(job.id))
    .then(() => {
      MsgSuccess('职位已恢复')
      refresh()
    })
    .catch(() => {})
}

function jobStatusTagType(status: string) {
  if (status === 'OPEN') return 'success'
  if (status === 'ON_HOLD') return 'warning'
  if (status === 'CLOSED') return 'info'
  return 'info'
}

function onAssignmentStatusChange(assignment: Assignment, target: AssignmentStatus) {
  if (assignment.status === target) return
  const terminal = TERMINAL_STATUSES.includes(target)
  const restore = assignment.status === 'REJECTED' && target === 'PENDING_SCREEN'
  if (terminal || restore) {
    statusDialogAssignment.value = assignment
    statusDialogTarget.value = target
    statusDialogReason.value = ''
    statusDialogNote.value = ''
    statusDialogVisible.value = true
    return
  }
  updateAssignmentFields(assignment, { status: target })
}

function confirmStatusChange() {
  const assignment = statusDialogAssignment.value
  const target = statusDialogTarget.value
  if (!assignment || !target) return
  if (isRestoreTransition.value) {
    if (!statusDialogNote.value.trim()) {
      MsgError('请填写恢复原因')
      return
    }
    saving.value = true
    HrApi.updateAssignment(assignment.id, { status: target, note: statusDialogNote.value.trim() })
      .then(() => {
        statusDialogVisible.value = false
        MsgSuccess('候选人已恢复待筛选')
        reloadAssignment(assignment)
      })
      .catch(() => {})
      .finally(() => { saving.value = false })
    return
  }
  if (!statusDialogReason.value) {
    MsgError('请选择终止原因')
    return
  }
  saving.value = true
  HrApi.updateAssignment(assignment.id, { status: target, termination_reason: statusDialogReason.value })
    .then(() => {
      statusDialogVisible.value = false
      MsgSuccess('状态已更新')
      reloadAssignment(assignment)
    })
    .catch(() => {})
    .finally(() => { saving.value = false })
}

function updateAssignmentFields(assignment: Assignment, data: Partial<Assignment>) {
  HrApi.updateAssignment(assignment.id, data)
    .then(() => {
      MsgSuccess('指派已更新')
      reloadAssignment(assignment)
    })
    .catch(() => {})
}

function reloadAssignment(assignment: Assignment) {
  const job = jobs.value.find((item) => item.id === assignment.job_id)
  if (job) loadJobDetail(job)
  refresh()
}

function addMatchToJob(job: Job, match: JobMatchCandidate) {
  HrApi.createAssignment(job.id, match.candidate_id)
    .then(() => {
      MsgSuccess(`已将 ${match.name} 加入职位`)
      loadMatches(job)
      loadJobDetail(job)
      refresh()
    })
    .catch(() => {})
}

function openInterviewDrawer(job: Job, assignment: Assignment) {
  interviewAssignment.value = assignment
  interviewCandidateName.value = assignment.candidate_name || ''
  interviewList.value = []
  addInterviewFormVisible.value = false
  interviewForm.interviewer = ''
  interviewForm.scheduled_at = null
  interviewDrawerVisible.value = true
  HrApi.getInterviews(assignment.id).then((response) => {
    interviewList.value = response.data
  })
}

function createInterviewRecord() {
  if (!interviewAssignment.value) return
  HrApi.createInterview(interviewAssignment.value.id, interviewForm)
    .then(() => {
      MsgSuccess('面试已安排')
      addInterviewFormVisible.value = false
      interviewForm.interviewer = ''
      interviewForm.scheduled_at = null
      if (interviewAssignment.value) {
        HrApi.getInterviews(interviewAssignment.value.id).then((response) => {
          interviewList.value = response.data
        })
      }
    })
    .catch(() => {})
}

function updateInterviewRecord(interview: Interview) {
  HrApi.updateInterview(interview.id, { status: interview.status, feedback: interview.feedback })
    .then(() => MsgSuccess('面试记录已更新'))
    .catch(() => {})
}

onMounted(() => {
  loadMembers()
  loadJobs()
})
</script>

<style scoped>
.hr-page { min-width: 0; }
.gap-12 { gap: 12px; }
.assignment-panel { padding: 12px 32px; }
</style>
