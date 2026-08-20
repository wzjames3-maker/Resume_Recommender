<template>
  <div class="hr-page p-16-24">
    <div class="database-detail-header mb-16">
      <div class="detail-heading">
        <el-button link :icon="ArrowLeft" @click="router.push('/hr/candidates')">返回{{ currentDatabaseId ? '多库管理' : '简历数据库' }}</el-button>
        <div>
          <div class="eyebrow">CANDIDATE RECORDS</div>
          <h2>{{ currentDatabase?.name || '全部候选人' }}</h2>
          <span class="color-secondary">候选人档案仅展示姓名/手机号/邮箱，简历原文通过语义检索命中</span>
        </div>
      </div>
      <div class="flex gap-12">
        <el-dropdown v-if="isHrOperator" trigger="click" @command="onImportCommand">
          <el-button plain>导入候选人<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="upload">上传简历（docx/txt）</el-dropdown-item>
              <el-dropdown-item v-if="isHrAdmin" command="csv">CSV 批量导入</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button v-if="isHrAdmin" plain @click="router.push('/hr/resumes/databases')">库管理</el-button>
        <el-button v-if="isHrAdmin" plain @click="aiSettingVisible = true">AI 设置</el-button>
        <el-button plain @click="router.push({ path: '/hr/search', query: { database_id: currentDatabaseId } })">库内检索</el-button>
        <el-button v-if="isHrAdmin" plain :loading="exporting" @click="exportCandidates">导出</el-button>
      </div>
      <input ref="resumeInputRef" type="file" multiple accept=".docx,.txt" class="hidden-input" @change="handleResumeFiles" />
    </div>

    <el-card style="--el-card-padding: 0" v-loading="loading">
      <div class="filter-toolbar p-16 border-b">
        <el-input v-model="filters.name" placeholder="按姓名/手机号/邮箱搜索" clearable style="width: 320px" />
        <el-button plain @click="resetCandidateFilters">重置</el-button>
      </div>

      <AppTable :data="candidates" :pagination-config="pagination" @change-page="loadCandidates" @size-change="refresh">
        <el-table-column label="姓名" min-width="200">
          <template #default="{ row }">
            <span class="candidate-name">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="手机号" min-width="180">
          <template #default="{ row }">{{ row.phone || '-' }}</template>
        </el-table-column>
        <el-table-column label="邮箱" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ row.email || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="router.push(`/hr/candidates/${row.id}`)">详情</el-button>
            <el-dropdown trigger="click" @command="(cmd: string) => handleRowCommand(cmd, row)">
              <el-button link type="primary">更多<el-icon class="el-icon--right"><arrow-down /></el-icon></el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item v-if="isHrAdmin" command="edit">编辑</el-dropdown-item>
                  <el-dropdown-item v-if="isHrOperator" command="assign" :disabled="row.status !== 'ACTIVE'">加入职位</el-dropdown-item>
                  <el-dropdown-item command="resumes">简历</el-dropdown-item>
                  <el-dropdown-item v-if="isHrAdmin" command="remove" divided>删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
      </AppTable>
    </el-card>

    <el-dialog v-model="candidateDialogVisible" :title="editingCandidate ? '编辑候选人' : '新建候选人'" width="480px">
      <el-form :model="candidateForm" label-width="80px" @submit.prevent>
        <el-form-item label="姓名" required><el-input v-model="candidateForm.name" maxlength="128" placeholder="必填" /></el-form-item>
        <el-form-item label="手机号"><el-input v-model="candidateForm.phone" maxlength="20" placeholder="例：13800001111" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="candidateForm.email" maxlength="128" placeholder="例：name@example.com" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="candidateDialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveCandidate">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="candidateDetailVisible" title="候选人详情" width="480px">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="姓名">{{ candidateDetail?.name || '-' }}</el-descriptions-item>
        <el-descriptions-item label="手机号">{{ candidateDetail?.phone || '-' }}</el-descriptions-item>
        <el-descriptions-item label="邮箱">{{ candidateDetail?.email || '-' }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ candidateDetail ? new Date(candidateDetail.create_time).toLocaleString() : '-' }}</el-descriptions-item>
      </el-descriptions>
      <template #footer><el-button @click="candidateDetailVisible = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="importDialogVisible" title="批量导入候选人" width="720px">
      <div class="mb-16">
        <el-button link type="primary" @click="downloadImportTemplate">下载 CSV 模板</el-button>
        <span class="ml-8 color-secondary">UTF-8 编码，最多 200 行，必填列：name</span>
      </div>
      <el-alert type="info" :closable="false" class="mb-16" title="导入操作将写入审计日志，请确认数据来源与合规信息。" />
      <el-upload drag accept=".csv" :auto-upload="false" :limit="1" :on-change="handleImportFile" :on-remove="() => (importFile = null)">
        <div class="el-upload__text">拖拽 CSV 到此处，或<em>点击选择文件</em></div>
      </el-upload>
      <div v-if="importReport" class="mt-16">
        <div class="mb-8">
          <el-tag type="success" class="mr-8">成功 {{ importReport.success }}</el-tag>
          <el-tag type="warning" class="mr-8">疑似重复 {{ importReport.duplicates }}</el-tag>
          <el-tag type="danger">失败 {{ importReport.failed }}</el-tag>
        </div>
        <el-table :data="importReport.records" size="small" max-height="260">
          <el-table-column prop="row_no" label="行号" width="60" />
          <el-table-column prop="name" label="姓名" min-width="100" />
          <el-table-column label="结果" width="100">
            <template #default="{ row }">
              <el-tag :type="row.status === 'created' ? 'success' : row.status === 'duplicate' ? 'warning' : 'danger'" size="small">
                {{ row.status === 'created' ? '已创建' : row.status === 'duplicate' ? '疑似重复' : '失败' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="reason" label="原因" min-width="200" show-overflow-tooltip />
        </el-table>
      </div>
      <template #footer>
        <el-button @click="importDialogVisible = false">关闭</el-button>
        <el-button type="primary" :disabled="!importFile" :loading="importing" @click="submitImport">开始导入</el-button>
      </template>
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
            <el-empty v-if="!uploadResults.length" description="请选择要上传的简历文件" :image-size="60" />
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
        <el-button type="primary" @click="openResumeUpload()">{{ uploadResults.length ? '继续上传' : '选择文件' }}</el-button>
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

    <el-dialog v-model="resumeListVisible" title="简历" width="620px">
      <el-table :data="candidateResumes" size="small">
        <el-table-column prop="file_name" label="文件名" min-width="160" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 'SUCCESS' ? 'success' : row.status === 'FAILED' ? 'danger' : 'info'" size="small">
              {{ row.status === 'SUCCESS' ? '成功' : row.status === 'FAILED' ? '失败' : '解析中' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="270">
          <template #default="{ row }">
            <el-button v-if="isHrOperator" link type="primary" size="small" @click="viewResumeContent(row)">查看</el-button>
            <el-button v-if="isHrOperator" link type="primary" size="small" @click="downloadResumeFile(row)">下载</el-button>
            <el-button v-if="isHrAdmin" link type="danger" size="small" @click="removeResume(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <template #footer><el-button @click="resumeListVisible = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="resumeContentVisible" title="简历原文" width="640px">
      <pre class="resume-content">{{ resumeContent }}</pre>
    </el-dialog>

    <AiSettingDialog v-model="aiSettingVisible" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { debounce } from 'lodash-es'
import { useRoute, useRouter } from 'vue-router'
import { ArrowDown, ArrowLeft } from '@element-plus/icons-vue'
import AppTable from '@/components/app-table/index.vue'
import AiSettingDialog from '@/views/hr/components/AiSettingDialog.vue'
import HrApi from '@/api/hr/recruitment'
import type { UploadFile } from 'element-plus'
import type { Candidate, CandidateDetail, ImportReport, Job, ResumeFile, ResumeUploadResult } from '@/api/type/hr'
import useStore from '@/stores'
import { MsgConfirm, MsgError, MsgSuccess } from '@/utils/message'
import { channelLabels } from '@/views/hr/constants'

interface WorkspaceMember {
  id: string
  nick_name: string
  roles: string[]
}

const loading = ref(false)
const saving = ref(false)
const exporting = ref(false)
const candidates = ref<Candidate[]>([])
const openJobs = ref<Job[]>([])
const members = ref<WorkspaceMember[]>([])
const databases = ref<{ id: string; name: string; status: string }[]>([])
const filters = reactive({ name: '' })
const pagination = reactive({ current_page: 1, page_size: 20, total: 0 })
const candidateDialogVisible = ref(false)
const assignmentDialogVisible = ref(false)
const uploadDialogVisible = ref(false)
const aiSettingVisible = ref(false)
const uploadChannel = ref('OTHER')
const uploadResults = ref<ResumeUploadResult[]>([])
let resumePollTimer: ReturnType<typeof setInterval> | null = null
const resumeInputRef = ref<HTMLInputElement>()
const editingCandidate = ref<Candidate | null>(null)
const assigningCandidate = ref<Candidate | null>(null)
const selectedJobId = ref('')
const assignmentNote = ref('')
const { user } = useStore()
const route = useRoute()
const router = useRouter()
const isHrAdmin = computed(() => user.getHrRole() === 'ADMIN')
const isHrOperator = computed(() => user.getHrRole() === 'OPERATOR' || user.getHrRole() === 'ADMIN')
const currentDatabaseId = computed(() => typeof route.params.databaseId === 'string' ? route.params.databaseId : '')
const currentDatabase = computed(() => databases.value.find((d) => d.id === currentDatabaseId.value) || null)

const debouncedRefresh = debounce(() => refresh(), 300)
watch(() => filters.name, debouncedRefresh)

const candidateForm = reactive({ name: '', email: '', phone: '' })

function loadMembers() {
  HrApi.getMembers().then((r) => { members.value = r.data || [] }).catch(() => {})
}
function loadDatabases() {
  HrApi.getResumeDatabases().then((r) => { databases.value = (r.data || []).filter((d: { status: string }) => d.status === 'ACTIVE') }).catch(() => {})
}
function resetCandidateFilters() {
  filters.name = ''
  refresh()
}
function resetCandidateForm(c?: Candidate) {
  candidateForm.name = c?.name || ''
  candidateForm.email = c?.email || ''
  candidateForm.phone = c?.phone || ''
}
function openCandidateDialog(c?: Candidate) {
  editingCandidate.value = c || null
  resetCandidateForm(c)
  candidateDialogVisible.value = true
}
const candidateDetailVisible = ref(false)
const candidateDetail = ref<CandidateDetail | null>(null)
function handleRowCommand(cmd: string, row: Candidate) {
  if (cmd === 'edit') openCandidateDialog(row)
  else if (cmd === 'assign') openAssignmentDialog(row)
  else if (cmd === 'resumes') openResumeListDialog(row)
  else if (cmd === 'remove') removeCandidate(row)
}
function loadCandidates() {
  loading.value = true
  const params: Record<string, unknown> = { name: filters.name || undefined }
  if (currentDatabaseId.value) params.resume_database_id = currentDatabaseId.value
  HrApi.getCandidates(pagination, params).then((r) => {
    candidates.value = r.data.records
    pagination.total = r.data.total
  }).catch(() => {}).finally(() => { loading.value = false })
}
function refresh() {
  pagination.current_page = 1
  loadCandidates()
}
function saveCandidate() {
  if (!candidateForm.name.trim()) return
  const data = { name: candidateForm.name.trim(), email: candidateForm.email.trim() || undefined, phone: candidateForm.phone.trim() }
  saving.value = true
  HrApi.checkDuplicate({ phone: data.phone, email: data.email, exclude_id: editingCandidate.value?.id || '' })
    .then((r) => {
      if (r.data.candidates.length > 0) {
        return MsgConfirm('发现疑似重复候选人', `有 ${r.data.candidates.length} 名候选人手机号或邮箱相同，是否继续保存？`, { type: 'warning' }).then(() => doSaveCandidate(data)).catch(() => {})
      }
      return doSaveCandidate(data)
    }).catch(() => {}).finally(() => { saving.value = false })
}
function doSaveCandidate(data: Record<string, unknown>) {
  const req = editingCandidate.value ? HrApi.updateCandidate(editingCandidate.value.id, data) : HrApi.createCandidate(data)
  return req.then(() => {
    candidateDialogVisible.value = false
    MsgSuccess('候选人已保存')
    refresh()
  })
}
function removeCandidate(row: Candidate) {
  MsgConfirm('删除候选人', `确认删除 ${row.name}？该操作将写入审计日志。`, { confirmButtonClass: 'danger' })
    .then(() => HrApi.deleteCandidate(row.id)).then(() => { MsgSuccess('候选人已删除'); refresh() }).catch(() => {})
}
function exportCandidates() {
  MsgConfirm('导出候选人', '确认导出当前筛选结果？').then(() => {
    exporting.value = true
    return HrApi.exportCandidates({ name: filters.name || undefined })
  }).then(() => MsgSuccess('候选人已导出')).catch(() => {}).finally(() => { exporting.value = false })
}
const importDialogVisible = ref(false)
const importing = ref(false)
const importFile = ref<File | null>(null)
const importReport = ref<ImportReport | null>(null)
function handleImportFile(file: UploadFile) { importFile.value = file.raw || null; importReport.value = null }
function downloadImportTemplate() { HrApi.downloadImportTemplate() }
function submitImport() {
  if (!importFile.value) return
  importing.value = true
  HrApi.importCandidates(importFile.value).then((r) => { importReport.value = r.data; MsgSuccess('导入完成'); refresh() }).catch(() => {}).finally(() => { importing.value = false })
}
function onImportCommand(cmd: string) {
  if (cmd === 'upload') {
    const did = currentDatabaseId.value || undefined
    router.push({ path: '/hr/resumes/upload', query: did ? { database_id: did } : {} })
  } else if (cmd === 'csv') importDialogVisible.value = true
}
function openAssignmentDialog(c: Candidate) {
  assigningCandidate.value = c
  selectedJobId.value = ''
  assignmentNote.value = ''
  HrApi.getJobs({ current_page: 1, page_size: 100 }, { status: 'OPEN' }).then((r) => { openJobs.value = r.data.records; assignmentDialogVisible.value = true })
}
function createAssignment() {
  if (!assigningCandidate.value || !selectedJobId.value) return
  saving.value = true
  HrApi.createAssignment(selectedJobId.value, assigningCandidate.value.id, assignmentNote.value, {}).then(() => {
    assignmentDialogVisible.value = false; MsgSuccess('已加入职位')
  }).catch(() => {}).finally(() => { saving.value = false })
}
function openResumeUpload() {
  uploadResults.value = []
  resumeInputRef.value?.click()
}
function handleResumeFiles(e: Event) {
  const input = e.target as HTMLInputElement
  const files = input.files ? Array.from(input.files) : []
  input.value = ''
  if (!files.length) return
  const target = databases.value.find((d) => (d as unknown as { is_system?: boolean }).is_system) || databases.value[0]
  if (!target) { MsgError('暂无可用简历库'); return }
  uploadDialogVisible.value = true
  HrApi.uploadResumes(files, uploadChannel.value, [target.id]).then((r) => {
    uploadResults.value = r.data
    const pending = uploadResults.value.filter((x) => x.status === 'PENDING').map((x) => x.resume_id)
    if (pending.length) startResumePolling(pending); else finishResumeUpload()
  }).catch(() => {})
}
function finishResumeUpload() {
  const failed = uploadResults.value.some((x) => x.status === 'FAILED')
  if (failed) MsgError('部分简历解析失败'); else MsgSuccess('简历解析完成')
  refresh()
}
function startResumePolling(ids: string[]) {
  stopResumePolling()
  const endsAt = Date.now() + 60 * 1000
  resumePollTimer = setInterval(() => {
    HrApi.getResumeBatchStatus(ids).then((r) => {
      const map = new Map(r.data.map((x) => [x.resume_id, x]))
      let allDone = true
      for (const rec of uploadResults.value) {
        const cur = map.get(rec.resume_id)
        if (!cur) continue
        rec.status = cur.status as never
        rec.error_message = (cur as { error_message?: string }).error_message || ''
        if (cur.status === 'PENDING') allDone = false
      }
      if (allDone || Date.now() > endsAt) { stopResumePolling(); finishResumeUpload() }
    }).catch(() => {})
  }, 1000)
}
function stopResumePolling() { if (resumePollTimer) { clearInterval(resumePollTimer); resumePollTimer = null } }
const resumeListVisible = ref(false)
const candidateResumes = ref<ResumeFile[]>([])
const resumeContentVisible = ref(false)
const resumeContent = ref('')
function openResumeListDialog(c: Candidate) {
  candidateResumes.value = []
  resumeListVisible.value = true
  HrApi.getCandidateResumes(c.id).then((r) => { candidateResumes.value = r.data })
}
function viewResumeContent(r: ResumeFile) {
  resumeContent.value = ''
  resumeContentVisible.value = true
  HrApi.getResumeContent(r.id).then((x) => { resumeContent.value = x.data.content }).catch(() => MsgError('简历内容提取失败'))
}
function downloadResumeFile(r: ResumeFile) { HrApi.downloadResume(r.id, r.file_name) }
function removeResume(r: ResumeFile) {
  MsgConfirm('删除简历', `确认删除简历「${r.file_name}」？`, { confirmButtonClass: 'danger' })
    .then(() => HrApi.deleteResume(r.id)).then(() => {
      MsgSuccess('简历已删除')
      if (candidateResumes.value.length) {
        const cid = (candidateResumes.value[0] as unknown as { candidate_id?: string }).candidate_id
        if (cid) HrApi.getCandidateResumes(cid).then((x) => { candidateResumes.value = x.data })
      }
      refresh()
    }).catch(() => {})
}

onMounted(() => { loadMembers(); loadDatabases(); loadCandidates() })
watch(currentDatabaseId, () => { refresh() })
onUnmounted(() => { if (resumePollTimer) clearInterval(resumePollTimer) })
</script>

<style scoped>
.hr-page { min-width: 0; }
.database-detail-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 20px; }
.detail-heading { display: flex; align-items: flex-start; gap: 12px; }
.detail-heading h2 { margin: 0 0 4px; }
.candidate-name { font-weight: 600; }
.hidden-input { display: none; }
.upload-result { padding: 6px 0; }
.resume-content { white-space: pre-wrap; word-break: break-all; max-height: 480px; overflow-y: auto; margin: 0; }
</style>
