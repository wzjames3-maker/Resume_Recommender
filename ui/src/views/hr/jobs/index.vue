<template>
  <div class="hr-page p-16-24">
    <div class="flex-between mb-16">
      <div>
        <h2>职位</h2>
        <span class="color-secondary">维护开放职位与候选人筛选进度</span>
      </div>
      <el-button v-if="isWorkspaceManage" type="primary" @click="openJobDialog()">新建职位</el-button>
    </div>

    <el-card style="--el-card-padding: 0" v-loading="loading">
      <div class="p-16 border-b flex gap-12">
        <el-input v-model="filters.name" placeholder="按职位名称搜索" clearable @change="refresh" />
        <el-select v-model="filters.status" placeholder="状态" clearable @change="refresh" style="width: 140px">
          <el-option label="开放" value="OPEN" />
          <el-option label="已关闭" value="CLOSED" />
        </el-select>
      </div>

      <AppTable :data="jobs" :pagination-config="pagination" @change-page="loadJobs" @size-change="refresh" @expand-change="handleExpand">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="assignment-panel" v-loading="detailLoading === row.id">
              <el-empty v-if="jobDetails[row.id]?.assignments?.length === 0" description="暂无候选人" />
              <el-table v-else :data="jobDetails[row.id]?.assignments" size="small">
                <el-table-column prop="candidate_name" label="候选人" />
                <el-table-column label="筛选状态" width="190">
                  <template #default="{ row: assignment }">
                    <el-select v-model="assignment.status" size="small" @change="updateAssignmentStatus(assignment)">
                      <el-option label="待筛选" value="PENDING_SCREEN" />
                      <el-option label="筛选通过" value="SCREEN_PASSED" />
                      <el-option label="已淘汰" value="REJECTED" />
                      <el-option label="已关闭" value="CLOSED" />
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column prop="note" label="备注" show-overflow-tooltip />
              </el-table>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="职位" min-width="180" />
        <el-table-column prop="department" label="部门" min-width="130"><template #default="{ row }">{{ row.department || '-' }}</template></el-table-column>
        <el-table-column prop="city" label="城市" width="120"><template #default="{ row }">{{ row.city || '-' }}</template></el-table-column>
        <el-table-column label="HC" width="90"><template #default="{ row }">{{ row.active_assignment_count }}/{{ row.headcount }}</template></el-table-column>
        <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.status === 'OPEN' ? 'success' : 'info'">{{ row.status === 'OPEN' ? '开放' : '已关闭' }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <el-button v-if="isWorkspaceManage" link type="primary" @click="openJobDialog(row)">编辑</el-button>
            <el-button v-if="isWorkspaceManage" link type="danger" :disabled="row.status === 'CLOSED'" @click="closeJob(row)">关闭</el-button>
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
        <el-form-item label="职位描述"><el-input v-model="jobForm.description" type="textarea" :rows="5" maxlength="4096" show-word-limit /></el-form-item>
      </el-form>
      <template #footer><el-button @click="jobDialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveJob">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import AppTable from '@/components/app-table/index.vue'
import HrApi from '@/api/hr/recruitment'
import type { Assignment, Job, JobDetail } from '@/api/type/hr'
import { MsgConfirm, MsgSuccess } from '@/utils/message'
import { hasPermission } from '@/utils/permission'
import { RoleConst } from '@/utils/permission/data'

const loading = ref(false)
const saving = ref(false)
const jobs = ref<Job[]>([])
const filters = reactive({ name: '', status: '' })
const pagination = reactive({ current_page: 1, page_size: 20, total: 0 })
const jobDetails = reactive<Record<string, JobDetail>>({})
const detailLoading = ref('')
const jobDialogVisible = ref(false)
const editingJob = ref<Job | null>(null)
const jobForm = reactive({ name: '', department: '', city: '', level: '', headcount: 1, description: '' })
const isWorkspaceManage = computed(() => hasPermission([RoleConst.WORKSPACE_MANAGE.getWorkspaceRole], 'OR'))

function resetJobForm(job?: Job) {
  jobForm.name = job?.name || ''
  jobForm.department = job?.department || ''
  jobForm.city = job?.city || ''
  jobForm.level = job?.level || ''
  jobForm.headcount = job?.headcount || 1
  jobForm.description = job?.description || ''
}

function loadJobs() {
  HrApi.getJobs(pagination, filters).then((response) => {
    jobs.value = response.data.records
    pagination.total = response.data.total
  })
}

function handleExpand(job: Job, expandedRows: Job[]) {
  if (expandedRows.some((row) => row.id === job.id) && !jobDetails[job.id]) loadJobDetail(job)
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

function saveJob() {
  if (!jobForm.name.trim()) return
  saving.value = true
  const request = editingJob.value ? HrApi.updateJob(editingJob.value.id, jobForm) : HrApi.createJob(jobForm)
  request.then(() => {
    jobDialogVisible.value = false
    MsgSuccess('职位已保存')
    refresh()
  }).finally(() => { saving.value = false })
}

function closeJob(job: Job) {
  MsgConfirm('关闭职位', `关闭后不能再向“${job.name}”加入候选人。`, { confirmButtonClass: 'danger' })
    .then(() => HrApi.updateJob(job.id, { status: 'CLOSED' }))
    .then(() => {
      MsgSuccess('职位已关闭')
      refresh()
    })
    .catch(() => {})
}

function updateAssignmentStatus(assignment: Assignment) {
  HrApi.updateAssignment(assignment.id, { status: assignment.status }).then(() => {
    MsgSuccess('筛选状态已更新')
    const job = jobs.value.find((item) => item.id === assignment.job_id)
    if (job) loadJobDetail(job)
    refresh()
  })
}

onMounted(loadJobs)
</script>

<style scoped>
.hr-page { min-width: 0; }
.gap-12 { gap: 12px; }
.assignment-panel { padding: 12px 32px; }
</style>
