<template>
  <div class="hr-page p-16-24">
    <div class="flex-between mb-16">
      <div>
        <h2>候选人</h2>
        <span class="color-secondary">维护招聘候选人与职位指派</span>
      </div>
      <el-button v-if="isHrOperator" type="primary" @click="openCandidateDialog()">新建候选人</el-button>
      <el-button v-if="isHrOperator" type="primary" plain @click="openResumeUpload()">上传简历</el-button>
      <el-button v-if="isHrAdmin" plain @click="aiSettingVisible = true">AI 设置</el-button>
      <input ref="resumeInputRef" type="file" multiple accept=".docx,.txt" class="hidden-input" @change="handleResumeFiles" />
    </div>

    <el-card style="--el-card-padding: 0" v-loading="loading">
      <div class="p-16 border-b flex gap-12">
        <el-input v-model="filters.name" placeholder="按姓名搜索" clearable @change="refresh" />
        <el-input v-model="filters.city" placeholder="按城市搜索" clearable @change="refresh" />
        <el-input v-model="filters.skills" placeholder="按技能搜索" clearable @change="refresh" />
        <el-input-number v-model="filters.years_min" :min="0" :max="99" placeholder="最低年限" @change="refresh" style="width: 140px" />
        <el-input-number v-model="filters.years_max" :min="0" :max="99" placeholder="最高年限" @change="refresh" style="width: 140px" />
        <el-select v-model="filters.highest_degree" placeholder="学历" clearable @change="refresh" style="width: 120px">
          <el-option label="博士" value="博士" />
          <el-option label="硕士" value="硕士" />
          <el-option label="本科" value="本科" />
          <el-option label="大专" value="大专" />
          <el-option label="中专" value="中专" />
          <el-option label="高中" value="高中" />
        </el-select>
        <el-select v-model="filters.source" placeholder="来源" clearable @change="refresh" style="width: 140px">
          <el-option v-for="(label, value) in channelLabels" :key="value" :label="label" :value="value" />
        </el-select>
        <el-select v-model="filters.status" placeholder="状态" clearable @change="refresh" style="width: 140px">
          <el-option label="在库" value="ACTIVE" />
          <el-option label="已归档" value="ARCHIVED" />
        </el-select>
        <el-button :type="filters.owner_id ? 'primary' : 'default'" plain @click="toggleMyCandidates">待我处理</el-button>
        <el-input v-if="isHrOperator" v-model="aiQuery" placeholder="AI 搜索：如 找 3 年以上 Python 经验在上海的人" clearable @keyup.enter="aiSearch" style="width: 300px" />
        <el-button v-if="isHrOperator" type="primary" plain :loading="aiSearching" @click="aiSearch">AI 搜索</el-button>
      </div>

      <AppTable :data="candidates" :pagination-config="pagination" @change-page="loadCandidates" @size-change="refresh">
        <el-table-column prop="name" label="姓名" min-width="130" />
        <el-table-column label="城市" min-width="150">
          <template #default="{ row }">{{ row.current_city || '-' }} <span v-if="row.target_city">→ {{ row.target_city }}</span></template>
        </el-table-column>
        <el-table-column prop="years_experience" label="经验" width="90">
          <template #default="{ row }">{{ row.years_experience == null ? '-' : `${row.years_experience} 年` }}</template>
        </el-table-column>
        <el-table-column label="技能" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.skills.join('、') || '-' }}</template>
        </el-table-column>
        <el-table-column label="重复" width="110">
          <template #default="{ row }">
            <el-tooltip v-if="row.duplicate_ids?.length" :content="`与 ${row.duplicate_ids.length} 名候选人重复`" placement="top">
              <el-tag type="warning" size="small">疑似重复</el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }"><el-tag :type="row.status === 'ACTIVE' ? 'success' : 'info'">{{ row.status === 'ACTIVE' ? '在库' : '已归档' }}</el-tag></template>
        </el-table-column>
        <el-table-column label="操作" width="380" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openCandidateDetail(row)">详情</el-button>
            <el-button v-if="isHrAdmin" link type="primary" @click="openCandidateDialog(row)">编辑</el-button>
            <el-button v-if="isHrOperator" link type="primary" :disabled="row.status !== 'ACTIVE'" @click="openAssignmentDialog(row)">加入职位</el-button>
            <el-button v-if="isHrAdmin" link type="danger" :disabled="row.status !== 'ACTIVE'" @click="archive(row)">归档</el-button>
            <el-button link type="primary" @click="openResumeListDialog(row)">简历</el-button>
            <el-button v-if="isHrAdmin" link type="danger" :disabled="!row.duplicate_ids?.length" @click="openMergeDialog(row)">合并</el-button>
          </template>
        </el-table-column>
      </AppTable>
    </el-card>

    <el-dialog v-model="candidateDialogVisible" :title="editingCandidate ? '编辑候选人' : '新建候选人'" width="640px">
      <el-form :model="candidateForm" label-width="96px" @submit.prevent>
        <el-form-item label="姓名" required><el-input v-model="candidateForm.name" maxlength="128" /></el-form-item>
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="邮箱"><el-input v-model="candidateForm.email" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="手机号"><el-input v-model="candidateForm.phone" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="当前城市"><el-input v-model="candidateForm.current_city" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="目标城市"><el-input v-model="candidateForm.target_city" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12"><el-form-item label="最高学历"><el-input v-model="candidateForm.highest_degree" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="工作年限"><el-input-number v-model="candidateForm.years_experience" :min="0" :max="99" /></el-form-item></el-col>
        </el-row>
        <el-form-item label="技能"><el-input v-model="skillsText" placeholder="用逗号分隔，例如 Python, Django" /></el-form-item>
        <el-form-item label="来源"><el-input v-model="candidateForm.source" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="candidateForm.note" type="textarea" :rows="3" maxlength="4096" show-word-limit /></el-form-item>
      </el-form>
      <template #footer><el-button @click="candidateDialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveCandidate">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="candidateDetailVisible" title="候选人详情" width="640px">
      <el-descriptions :column="2" border>
        <el-descriptions-item label="姓名">{{ candidateDetail?.name }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="candidateDetail?.status === 'ACTIVE' ? 'success' : 'info'" size="small">{{ candidateDetail?.status === 'ACTIVE' ? '在库' : '已归档' }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="邮箱">{{ candidateDetail?.email || '-' }}</el-descriptions-item>
        <el-descriptions-item label="手机号">{{ candidateDetail?.phone || '-' }}</el-descriptions-item>
        <el-descriptions-item label="当前城市">{{ candidateDetail?.current_city || '-' }}</el-descriptions-item>
        <el-descriptions-item label="目标城市">{{ candidateDetail?.target_city || '-' }}</el-descriptions-item>
        <el-descriptions-item label="最高学历">{{ candidateDetail?.highest_degree || '-' }}</el-descriptions-item>
        <el-descriptions-item label="工作年限">{{ candidateDetail?.years_experience == null ? '-' : `${candidateDetail.years_experience} 年` }}</el-descriptions-item>
        <el-descriptions-item label="来源">{{ candidateDetail?.source || '-' }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ candidateDetail ? new Date(candidateDetail.create_time).toLocaleString() : '-' }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ candidateDetail ? new Date(candidateDetail.update_time).toLocaleString() : '-' }}</el-descriptions-item>
        <el-descriptions-item label="技能" :span="2">
          <template v-if="candidateDetail?.skills?.length">
            <el-tag v-for="skill in candidateDetail.skills" :key="skill" size="small" class="mr-8 mb-8">{{ skill }}</el-tag>
          </template>
          <span v-else>-</span>
        </el-descriptions-item>
        <el-descriptions-item label="备注" :span="2">{{ candidateDetail?.note || '-' }}</el-descriptions-item>
      </el-descriptions>
      <div class="mt-16">
        <div class="mb-8 color-secondary">关联职位</div>
        <el-empty v-if="!candidateDetail?.assignments?.length" description="暂无关联职位" />
        <el-table v-else :data="candidateDetail.assignments" size="small">
          <el-table-column prop="job_name" label="职位" min-width="140" />
          <el-table-column label="指派状态" width="120">
            <template #default="{ row }">
              <el-tag :type="assignmentTagType(row.status)" size="small">{{ assignmentStatusLabels[row.status] || row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="关系类型" width="90">
            <template #default="{ row }">{{ relationTypeLabels[row.relation_type] || row.relation_type || '-' }}</template>
          </el-table-column>
          <el-table-column label="渠道" width="90">
            <template #default="{ row }">{{ channelLabels[row.channel] || row.channel || '-' }}</template>
          </el-table-column>
          <el-table-column label="负责人" width="100">
            <template #default="{ row }">{{ memberName(row.owner_id) || '-' }}</template>
          </el-table-column>
          <el-table-column prop="note" label="备注" show-overflow-tooltip />
        </el-table>
      </div>
      <template #footer><el-button @click="candidateDetailVisible = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="uploadDialogVisible" title="上传简历" width="520px">
      <el-form label-width="96px">
        <el-form-item label="来源渠道">
          <el-select v-model="uploadChannel" style="width: 100%">
            <el-option v-for="(label, value) in channelLabels" :key="value" :label="label" :value="value" />
          </el-select>
        </el-form-item>
        <el-form-item label="上传结果">
          <div class="w-full">
            <div v-for="record in uploadResults" :key="record.resume_id" class="upload-result">
              <el-tag :type="record.status === 'SUCCESS' ? 'success' : record.status === 'FAILED' ? 'danger' : 'info'" size="small">
                {{ record.status === 'SUCCESS' ? '成功' : record.status === 'FAILED' ? '失败' : '解析中' }}
              </el-tag>
              <span class="ml-8">{{ record.file_name }}</span>
              <span v-if="record.duplicate" class="ml-8 color-secondary">重复，已关联既有候选人</span>
              <span v-if="record.status === 'FAILED'" class="ml-8 color-secondary">{{ record.error_message }}</span>
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadDialogVisible = false">关闭</el-button>
        <el-button type="primary" @click="openResumeUpload()">继续上传</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="assignmentDialogVisible" title="加入职位" width="480px">
      <el-form label-width="96px">
        <el-form-item label="候选人"><span>{{ assigningCandidate?.name }}</span></el-form-item>
        <el-form-item label="开放职位"><el-select v-model="selectedJobId" filterable placeholder="选择职位" style="width: 100%"><el-option v-for="job in openJobs" :key="job.id" :label="`${job.name}${job.city ? ` · ${job.city}` : ''}`" :value="job.id" /></el-select></el-form-item>
        <el-form-item label="关系类型">
          <el-select v-model="assignmentRelationType" style="width: 100%">
            <el-option v-for="(label, value) in relationTypeLabels" :key="value" :label="label" :value="value" />
          </el-select>
        </el-form-item>
        <el-form-item label="渠道">
          <el-select v-model="assignmentChannel" style="width: 100%">
            <el-option v-for="(label, value) in channelLabels" :key="value" :label="label" :value="value" />
          </el-select>
        </el-form-item>
        <el-form-item label="负责人">
          <el-select v-model="assignmentOwnerId" clearable filterable placeholder="选择负责人" style="width: 100%">
            <el-option v-for="member in members" :key="member.id" :label="member.nick_name" :value="member.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="assignmentNote" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="assignmentDialogVisible = false">取消</el-button><el-button type="primary" :disabled="!selectedJobId" :loading="saving" @click="createAssignment">确认加入</el-button></template>
    </el-dialog>

    <el-dialog v-model="resumeListVisible" title="简历" width="620px">
      <el-table :data="candidateResumes" size="small">
        <el-table-column prop="file_name" label="文件名" min-width="160" />
        <el-table-column prop="file_size" label="大小" width="90">
          <template #default="{ row }">{{ (row.file_size / 1024).toFixed(1) }} KB</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 'SUCCESS' ? 'success' : row.status === 'FAILED' ? 'danger' : 'info'" size="small">
              {{ row.status === 'SUCCESS' ? '成功' : row.status === 'FAILED' ? '失败' : '解析中' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="create_time" label="上传时间" min-width="150">
          <template #default="{ row }">{{ new Date(row.create_time).toLocaleString() }}</template>
        </el-table-column>
        <el-table-column label="操作" width="130">
          <template #default="{ row }">
            <el-button v-if="isHrOperator" link type="primary" size="small" :disabled="row.status !== 'SUCCESS'" @click="viewResumeContent(row)">查看</el-button>
            <el-button v-if="isHrOperator" link type="primary" size="small" @click="downloadResumeFile(row)">下载</el-button>
          </template>
        </el-table-column>
      </el-table>
      <template #footer><el-button @click="resumeListVisible = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="resumeContentVisible" title="简历原文" width="640px">
      <pre class="resume-content">{{ resumeContent }}</pre>
    </el-dialog>

    <el-dialog v-model="mergeDialogVisible" title="合并候选人" width="480px">
      <el-form label-width="96px">
        <el-form-item label="主候选人"><span>{{ mergingCandidate?.name }}</span></el-form-item>
        <el-form-item label="目标候选人">
          <el-select v-model="mergeTargetId" filterable placeholder="选择要合并进来的候选人" style="width: 100%">
            <el-option v-for="c in mergeCandidatesList" :key="c.id" :label="`${c.name}${c.phone ? ` · ${c.phone}` : ''}`" :value="c.id" />
          </el-select>
        </el-form-item>
        <div class="color-secondary">合并后目标候选人的简历与指派将迁移至主候选人，目标候选人被删除；存在冲突有效指派时将被拒绝。</div>
      </el-form>
      <template #footer><el-button @click="mergeDialogVisible = false">取消</el-button><el-button type="primary" :disabled="!mergeTargetId" :loading="saving" @click="confirmMerge">确认合并</el-button></template>
    </el-dialog>

    <AiSettingDialog v-model="aiSettingVisible" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import AppTable from '@/components/app-table/index.vue'
import AiSettingDialog from '@/views/hr/components/AiSettingDialog.vue'
import HrApi from '@/api/hr/recruitment'
import AuthorizationApi from '@/api/system/resource-authorization'
import type { Candidate, CandidateDetail, Job, RelationType, ResumeChannel, ResumeFile, ResumeUploadResult } from '@/api/type/hr'
import useStore from '@/stores'
import { MsgConfirm, MsgError, MsgSuccess } from '@/utils/message'

interface WorkspaceMember {
  id: string
  nick_name: string
  roles: string[]
}

const channelLabels: Record<string, string> = {
  REFERRAL: '内推',
  JOB_SITE: '招聘网站',
  HEADHUNTER: '猎头',
  CAMPUS: '校园',
  OTHER: '其他',
}

const relationTypeLabels: Record<string, string> = {
  APPLY: '投递',
  SEEK: '主动寻访',
  REFERRAL: '内推',
  HEADHUNTER: '猎头推荐',
}

const assignmentStatusLabels: Record<string, string> = {
  PENDING_SCREEN: '待筛选',
  SCREEN_PASSED: '筛选通过',
  INTERVIEWING: '面试中',
  OFFER: 'Offer 中',
  HIRED: '已入职',
  REJECTED: '已淘汰',
  WITHDRAWN: '已退出',
  CLOSED: '已关闭',
}

const loading = ref(false)
const saving = ref(false)
const candidates = ref<Candidate[]>([])
const openJobs = ref<Job[]>([])
const members = ref<WorkspaceMember[]>([])
const filters = reactive({
  name: '', city: '', skills: '', years_min: null as number | null, years_max: null as number | null,
  highest_degree: '', source: '', status: '', owner_id: '',
})
const pagination = reactive({ current_page: 1, page_size: 20, total: 0 })
const candidateDialogVisible = ref(false)
const assignmentDialogVisible = ref(false)
const uploadDialogVisible = ref(false)
const aiSettingVisible = ref(false)
const aiQuery = ref('')
const aiSearching = ref(false)
const uploadChannel = ref('OTHER')
const uploadResults = ref<ResumeUploadResult[]>([])
let resumePollTimer: ReturnType<typeof setInterval> | null = null
const resumeInputRef = ref<HTMLInputElement>()
const editingCandidate = ref<Candidate | null>(null)
const assigningCandidate = ref<Candidate | null>(null)
const selectedJobId = ref('')
const assignmentNote = ref('')
const assignmentRelationType = ref<RelationType>('APPLY')
const assignmentChannel = ref<ResumeChannel>('OTHER')
const assignmentOwnerId = ref<string | null>(null)
const skillsText = ref('')
const { user } = useStore()
const isHrAdmin = computed(() => user.getHrRole() === 'ADMIN')
const isHrOperator = computed(() => user.getHrRole() === 'OPERATOR' || user.getHrRole() === 'ADMIN')
const candidateForm = reactive({
  name: '', email: '', phone: '', current_city: '', target_city: '', highest_degree: '',
  years_experience: null as number | null, source: '', note: '',
})

function memberName(memberId: string | null) {
  if (!memberId) return ''
  return members.value.find((member) => member.id === memberId)?.nick_name || ''
}

function loadMembers() {
  AuthorizationApi.getUserMember(user.getWorkspaceId() || '').then((response) => {
    members.value = response.data || []
  }).catch(() => {})
}

function toggleMyCandidates() {
  filters.owner_id = filters.owner_id ? '' : user.userInfo?.id || ''
  refresh()
}

function resetCandidateForm(candidate?: Candidate) {
  candidateForm.name = candidate?.name || ''
  candidateForm.email = candidate?.email || ''
  candidateForm.phone = candidate?.phone || ''
  candidateForm.current_city = candidate?.current_city || ''
  candidateForm.target_city = candidate?.target_city || ''
  candidateForm.highest_degree = candidate?.highest_degree || ''
  candidateForm.years_experience = candidate?.years_experience ?? null
  candidateForm.source = candidate?.source || ''
  candidateForm.note = candidate?.note || ''
  skillsText.value = candidate?.skills.join(', ') || ''
}

function openCandidateDialog(candidate?: Candidate) {
  editingCandidate.value = candidate || null
  resetCandidateForm(candidate)
  candidateDialogVisible.value = true
}

const candidateDetailVisible = ref(false)
const candidateDetail = ref<CandidateDetail | null>(null)

function openCandidateDetail(candidate: Candidate) {
  candidateDetail.value = null
  candidateDetailVisible.value = true
  HrApi.getCandidate(candidate.id).then((response) => {
    candidateDetail.value = response.data
  })
}

function assignmentTagType(status: string) {
  if (status === 'HIRED') return 'success'
  if (status === 'REJECTED' || status === 'WITHDRAWN' || status === 'CLOSED') return 'info'
  return 'primary'
}

function loadCandidates() {
  HrApi.getCandidates(pagination, filters).then((response) => {
    candidates.value = response.data.records
    pagination.total = response.data.total
  })
}

function refresh() {
  pagination.current_page = 1
  loadCandidates()
}

function aiSearch() {
  const query = aiQuery.value.trim()
  if (!query) return
  aiSearching.value = true
  HrApi.parseSearch(query)
    .then((response) => {
      const conditions = response.data.conditions
      filters.name = ''
      filters.city = conditions.city || ''
      filters.skills = conditions.skills.join(', ')
      filters.years_min = conditions.years_min
      filters.years_max = conditions.years_max
      filters.highest_degree = conditions.highest_degree || ''
      filters.source = ''
      filters.status = conditions.status || ''
      refresh()
      MsgSuccess('已按 AI 解析条件搜索，可继续修改筛选条件')
    })
    .catch(() => {})
    .finally(() => {
      aiSearching.value = false
    })
}

function saveCandidate() {
  if (!candidateForm.name.trim()) return
  const data = { ...candidateForm, skills: skillsText.value.split(',').map((skill) => skill.trim()).filter(Boolean) }
  saving.value = true
  HrApi.checkDuplicate({ phone: candidateForm.phone, email: candidateForm.email, exclude_id: editingCandidate.value?.id || '' })
    .then((response) => {
      if (response.data.candidates.length > 0) {
        return MsgConfirm('发现疑似重复候选人', `有 ${response.data.candidates.length} 名候选人手机号或邮箱相同，是否继续保存？`, { type: 'warning' })
          .then(() => doSaveCandidate(data))
          .catch(() => {})
      }
      return doSaveCandidate(data)
    })
    .catch(() => {})
    .finally(() => {
      saving.value = false
    })
}

function doSaveCandidate(data: Record<string, unknown>) {
  const request = editingCandidate.value
    ? HrApi.updateCandidate(editingCandidate.value.id, data)
    : HrApi.createCandidate(data)
  return request.then(() => {
    candidateDialogVisible.value = false
    MsgSuccess('候选人已保存')
    refresh()
  })
}

function archive(candidate: Candidate) {
  MsgConfirm('归档候选人', `归档后将保留 ${candidate.name} 的历史指派记录。`, { confirmButtonClass: 'danger' })
    .then(() => HrApi.archiveCandidate(candidate.id))
    .then(() => {
      MsgSuccess('候选人已归档')
      refresh()
    })
    .catch(() => {})
}

function openAssignmentDialog(candidate: Candidate) {
  assigningCandidate.value = candidate
  selectedJobId.value = ''
  assignmentNote.value = ''
  assignmentRelationType.value = 'APPLY'
  assignmentChannel.value = 'OTHER'
  assignmentOwnerId.value = null
  HrApi.getJobs({ current_page: 1, page_size: 100 }, { status: 'OPEN' }).then((response) => {
    openJobs.value = response.data.records
    assignmentDialogVisible.value = true
  })
}

function createAssignment() {
  if (!assigningCandidate.value || !selectedJobId.value) return
  saving.value = true
  HrApi.createAssignment(selectedJobId.value, assigningCandidate.value.id, assignmentNote.value, {
    relation_type: assignmentRelationType.value,
    channel: assignmentChannel.value,
    owner_id: assignmentOwnerId.value || null,
  })
    .then(() => {
      assignmentDialogVisible.value = false
      MsgSuccess('已加入职位')
    })
    .catch(() => {})
    .finally(() => { saving.value = false })
}

function openResumeUpload() {
  uploadResults.value = []
  resumeInputRef.value?.click()
}

function handleResumeFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const files = input.files ? Array.from(input.files) : []
  input.value = ''
  if (files.length === 0) return
  uploadDialogVisible.value = true
  HrApi.uploadResumes(files, uploadChannel.value)
    .then((response) => {
      uploadResults.value = response.data
      const pendingIds = uploadResults.value.filter((record) => record.status === 'PENDING').map((record) => record.resume_id)
      if (pendingIds.length > 0) startResumePolling(pendingIds)
      else finishResumeUpload()
    })
    .catch(() => {})
}

function finishResumeUpload() {
  const failed = uploadResults.value.some((record) => record.status === 'FAILED')
  if (failed) MsgError('部分简历解析失败，请查看结果')
  else MsgSuccess('简历解析完成')
  refresh()
}

function startResumePolling(ids: string[]) {
  stopResumePolling()
  const endsAt = Date.now() + 60 * 1000
  resumePollTimer = setInterval(() => {
    HrApi.getResumeBatchStatus(ids)
      .then((response) => {
        const statusMap = new Map(response.data.map((item) => [item.resume_id, item]))
        let allDone = true
        for (const record of uploadResults.value) {
          const latest = statusMap.get(record.resume_id)
          if (!latest) continue
          record.status = latest.status
          record.error_message = latest.error_message || ''
          if (latest.status === 'PENDING') allDone = false
        }
        if (allDone || Date.now() > endsAt) {
          stopResumePolling()
          finishResumeUpload()
        }
      })
      .catch(() => {})
  }, 1000)
}

function stopResumePolling() {
  if (resumePollTimer) {
    clearInterval(resumePollTimer)
    resumePollTimer = null
  }
}

const resumeListVisible = ref(false)
const candidateResumes = ref<ResumeFile[]>([])
const resumeContentVisible = ref(false)
const resumeContent = ref('')
const mergingCandidate = ref<Candidate | null>(null)
const mergeDialogVisible = ref(false)
const mergeTargetId = ref('')
const mergeCandidatesList = ref<Candidate[]>([])

function openResumeListDialog(candidate: Candidate) {
  candidateResumes.value = []
  resumeListVisible.value = true
  HrApi.getCandidateResumes(candidate.id).then((response) => {
    candidateResumes.value = response.data
  })
}

function viewResumeContent(resume: ResumeFile) {
  resumeContent.value = ''
  resumeContentVisible.value = true
  HrApi.getResumeContent(resume.id).then((response) => {
    resumeContent.value = response.data.content
  }).catch(() => MsgError('简历内容提取失败'))
}

function downloadResumeFile(resume: ResumeFile) {
  HrApi.downloadResume(resume.id, resume.file_name)
}

function openMergeDialog(candidate: Candidate) {
  mergingCandidate.value = candidate
  mergeTargetId.value = ''
  HrApi.getCandidates({ current_page: 1, page_size: 100 }, { status: '' }).then((response) => {
    mergeCandidatesList.value = response.data.records.filter((item) => item.id !== candidate.id)
    mergeDialogVisible.value = true
  })
}

function confirmMerge() {
  if (!mergingCandidate.value || !mergeTargetId.value) return
  saving.value = true
  HrApi.mergeCandidates(mergingCandidate.value.id, mergeTargetId.value)
    .then(() => {
      mergeDialogVisible.value = false
      MsgSuccess('候选人已合并')
      refresh()
    })
    .catch(() => {})
    .finally(() => {
      saving.value = false
    })
}

onMounted(() => {
  loadMembers()
  loadCandidates()
})
watch(uploadDialogVisible, (visible) => {
  if (!visible) stopResumePolling()
})

onUnmounted(stopResumePolling)
</script>

<style scoped>
.hr-page { min-width: 0; }
.gap-12 { gap: 12px; }
.hidden-input { display: none; }
.upload-result { padding: 6px 0; }
.resume-content {
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 480px;
  overflow-y: auto;
  margin: 0;
}
</style>
