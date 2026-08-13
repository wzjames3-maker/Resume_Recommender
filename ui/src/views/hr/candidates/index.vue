<template>
  <div class="hr-page p-16-24">
    <div class="flex-between mb-16">
      <div>
        <h2>候选人</h2>
        <span class="color-secondary">维护招聘候选人与职位指派</span>
      </div>
      <el-button type="primary" @click="openCandidateDialog()">新建候选人</el-button>
    </div>

    <el-card style="--el-card-padding: 0" v-loading="loading">
      <div class="p-16 border-b flex gap-12">
        <el-input v-model="filters.name" placeholder="按姓名搜索" clearable @change="refresh" />
        <el-input v-model="filters.city" placeholder="按城市搜索" clearable @change="refresh" />
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
            <el-button link type="primary" @click="openCandidateDialog(row)">编辑</el-button>
            <el-button link type="primary" :disabled="row.status !== 'ACTIVE'" @click="openAssignmentDialog(row)">加入职位</el-button>
            <el-button link type="danger" :disabled="row.status !== 'ACTIVE'" @click="archive(row)">归档</el-button>
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

    <el-dialog v-model="assignmentDialogVisible" title="加入职位" width="480px">
      <el-form label-width="96px">
        <el-form-item label="候选人"><span>{{ assigningCandidate?.name }}</span></el-form-item>
        <el-form-item label="开放职位"><el-select v-model="selectedJobId" filterable placeholder="选择职位" style="width: 100%"><el-option v-for="job in openJobs" :key="job.id" :label="`${job.name}${job.city ? ` · ${job.city}` : ''}`" :value="job.id" /></el-select></el-form-item>
        <el-form-item label="备注"><el-input v-model="assignmentNote" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="assignmentDialogVisible = false">取消</el-button><el-button type="primary" :disabled="!selectedJobId" :loading="saving" @click="createAssignment">确认加入</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import AppTable from '@/components/app-table/index.vue'
import HrApi from '@/api/hr/recruitment'
import type { Candidate, Job } from '@/api/type/hr'
import { MsgConfirm, MsgSuccess } from '@/utils/message'

const loading = ref(false)
const saving = ref(false)
const candidates = ref<Candidate[]>([])
const openJobs = ref<Job[]>([])
const filters = reactive({ name: '', city: '', status: '' })
const pagination = reactive({ current_page: 1, page_size: 20, total: 0 })
const candidateDialogVisible = ref(false)
const assignmentDialogVisible = ref(false)
const editingCandidate = ref<Candidate | null>(null)
const assigningCandidate = ref<Candidate | null>(null)
const selectedJobId = ref('')
const assignmentNote = ref('')
const skillsText = ref('')
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

onMounted(loadCandidates)
</script>

<style scoped>
.hr-page { min-width: 0; }
.gap-12 { gap: 12px; }
</style>
