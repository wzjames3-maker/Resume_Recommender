<template>
  <div class="hr-page p-16-24">
    <div class="flex-between mb-16">
      <div>
        <h2>候选人</h2>
        <span class="color-secondary">维护招聘候选人与职位指派</span>
      </div>
      <el-button type="primary" @click="openCandidateDialog()">新建候选人</el-button>
      <el-button type="primary" plain @click="openResumeUpload()">上传简历</el-button>
      <el-button plain @click="aiSettingVisible = true">AI 设置</el-button>
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
        <el-table-column label="状态" width="100">
          <template #default="{ row }"><el-tag :type="row.status === 'ACTIVE' ? 'success' : 'info'">{{ row.status === 'ACTIVE' ? '在库' : '已归档' }}</el-tag></template>
        </el-table-column>
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <el-button v-if="isWorkspaceManage" link type="primary" @click="openCandidateDialog(row)">编辑</el-button>
            <el-button link type="primary" :disabled="row.status !== 'ACTIVE'" @click="openAssignmentDialog(row)">加入职位</el-button>
            <el-button v-if="isWorkspaceManage" link type="danger" :disabled="row.status !== 'ACTIVE'" @click="archive(row)">归档</el-button>
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
              <el-tag :type="record.status === 'SUCCESS' ? 'success' : 'danger'" size="small">
                {{ record.status === 'SUCCESS' ? '成功' : '失败' }}
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
        <el-form-item label="备注"><el-input v-model="assignmentNote" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="assignmentDialogVisible = false">取消</el-button><el-button type="primary" :disabled="!selectedJobId" :loading="saving" @click="createAssignment">确认加入</el-button></template>
    </el-dialog>

    <AiSettingDialog v-model="aiSettingVisible" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import AppTable from '@/components/app-table/index.vue'
import AiSettingDialog from '@/views/hr/components/AiSettingDialog.vue'
import HrApi from '@/api/hr/recruitment'
import type { Candidate, Job, ResumeUploadResult } from '@/api/type/hr'
import { MsgConfirm, MsgError, MsgSuccess } from '@/utils/message'
import { hasPermission } from '@/utils/permission'
import { RoleConst } from '@/utils/permission/data'

const channelLabels: Record<string, string> = {
  REFERRAL: '内推',
  JOB_SITE: '招聘网站',
  HEADHUNTER: '猎头',
  CAMPUS: '校园',
  OTHER: '其他',
}

const loading = ref(false)
const saving = ref(false)
const candidates = ref<Candidate[]>([])
const openJobs = ref<Job[]>([])
const filters = reactive({
  name: '', city: '', skills: '', years_min: null as number | null, years_max: null as number | null,
  highest_degree: '', source: '', status: '',
})
const pagination = reactive({ current_page: 1, page_size: 20, total: 0 })
const candidateDialogVisible = ref(false)
const assignmentDialogVisible = ref(false)
const uploadDialogVisible = ref(false)
const aiSettingVisible = ref(false)
const uploadChannel = ref('OTHER')
const uploadResults = ref<ResumeUploadResult[]>([])
const resumeInputRef = ref<HTMLInputElement>()
const editingCandidate = ref<Candidate | null>(null)
const assigningCandidate = ref<Candidate | null>(null)
const selectedJobId = ref('')
const assignmentNote = ref('')
const skillsText = ref('')
const isWorkspaceManage = computed(() => hasPermission([RoleConst.WORKSPACE_MANAGE.getWorkspaceRole], 'OR'))
const candidateForm = reactive({
  name: '', email: '', phone: '', current_city: '', target_city: '', highest_degree: '',
  years_experience: null as number | null, source: '', note: '',
})

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

function saveCandidate() {
  if (!candidateForm.name.trim()) return
  saving.value = true
  const data = { ...candidateForm, skills: skillsText.value.split(',').map((skill) => skill.trim()).filter(Boolean) }
  const request = editingCandidate.value
    ? HrApi.updateCandidate(editingCandidate.value.id, data)
    : HrApi.createCandidate(data)
  request.then(() => {
    candidateDialogVisible.value = false
    MsgSuccess('候选人已保存')
    refresh()
  }).finally(() => { saving.value = false })
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
  HrApi.getJobs({ current_page: 1, page_size: 100 }, { status: 'OPEN' }).then((response) => {
    openJobs.value = response.data.records
    assignmentDialogVisible.value = true
  })
}

function createAssignment() {
  if (!assigningCandidate.value || !selectedJobId.value) return
  saving.value = true
  HrApi.createAssignment(selectedJobId.value, assigningCandidate.value.id, assignmentNote.value)
    .then(() => {
      assignmentDialogVisible.value = false
      MsgSuccess('已加入职位')
    })
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
      const failed = uploadResults.value.some((record) => record.status === 'FAILED')
      if (failed) MsgError('部分简历解析失败，请查看结果')
      else MsgSuccess('简历上传完成')
      refresh()
    })
    .catch(() => {})
}

onMounted(loadCandidates)
</script>

<style scoped>
.hr-page { min-width: 0; }
.gap-12 { gap: 12px; }
.hidden-input { display: none; }
.upload-result { padding: 6px 0; }
</style>
