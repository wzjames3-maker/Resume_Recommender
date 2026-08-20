<template>
  <div class="upload-page p-16-24">
    <header class="page-header">
      <div class="page-heading">
        <el-button link :icon="ArrowLeft" @click="goBack">返回简历数据库</el-button>
        <div class="heading-copy">
          <span class="eyebrow">候选人数据</span>
          <h2>批量上传简历</h2>
          <p>一次上传多份简历，系统会自动去重、解析并关联候选人。</p>
        </div>
      </div>
      <div class="header-actions"><el-button v-if="isHrAdmin" plain :icon="Setting" @click="router.push('/hr/resumes/databases')">库管理</el-button></div>
    </header>

    <main class="upload-layout">
      <section class="upload-surface">
        <div class="section-heading"><div><h3>选择文件</h3><p>支持 DOC、DOCX 和 TXT，单次最多上传 100 份。</p></div><el-tag type="info" effect="plain">{{ selectedFiles.length }} 份待上传</el-tag></div>
        <input ref="fileInput" class="file-input" type="file" multiple accept=".doc,.docx,.txt" @change="onFileChange" />
        <div class="drop-zone" :class="{ 'drop-zone--active': dragActive, 'drop-zone--disabled': !selectedDatabaseIds.length }" @click="openFilePicker" @dragenter.prevent="dragActive = true" @dragover.prevent="dragActive = true" @dragleave.prevent="dragActive = false" @drop.prevent="onDrop">
          <el-icon class="upload-icon"><UploadFilled /></el-icon>
          <strong>拖拽简历到这里，或点击选择文件</strong>
          <span>支持批量选择，重复文件会自动标记，不会覆盖已有简历</span>
        </div>

        <div v-if="selectedFiles.length" class="file-list">
          <div class="list-heading"><strong>待上传文件</strong><el-button link type="danger" :icon="Delete" @click="selectedFiles = []">清空</el-button></div>
          <div v-for="(file, index) in selectedFiles" :key="file.name + file.size" class="file-row">
            <div class="file-info"><el-icon><Document /></el-icon><span>{{ file.name }}</span><small>{{ formatSize(file.size) }}</small></div>
            <el-button link type="danger" :icon="Delete" title="移除文件" @click="removeFile(index)" />
          </div>
        </div>
      </section>

      <aside class="settings-surface">
        <section class="settings-section">
          <div class="side-heading"><h3>导入设置</h3><el-icon><Setting /></el-icon></div>
          <div class="field-label-row"><label class="field-label">目标简历库</label><el-button v-if="isHrAdmin" link type="primary" @click="databaseDialogVisible = true">新建简历库</el-button></div>
          <div v-loading="loadingDatabases" class="database-checklist">
            <el-checkbox-group v-model="selectedDatabaseIds">
              <el-checkbox v-for="database in databases" :key="database.id" :label="database.id" :disabled="database.is_system">
                <span class="database-option"><span>{{ database.name }}<el-tag v-if="database.is_system" size="small" type="success" effect="plain">总库</el-tag></span><small>{{ database.resume_count }} 份简历 · {{ database.candidate_count }} 位候选人</small></span>
              </el-checkbox>
            </el-checkbox-group>
          </div>
          <p v-if="selectedDatabases.length" class="selected-database">本次文件将归入：{{ selectedDatabases.map((database) => database.name).join('、') }}。总库会始终保留，其他库可多选。</p>
          <el-divider />
          <label class="field-label">来源渠道</label>
          <el-select v-model="sourceChannel" class="full-width">
            <el-option v-for="(label, value) in channelLabels" :key="value" :label="label" :value="value" />
          </el-select>
          <p class="side-help">来源会写入候选人档案，便于后续按渠道统计和追踪。</p>
        </section>
      </aside>
    </main>

    <section v-if="uploadResults.length" class="result-surface">
      <div class="section-heading"><div><h3>处理结果</h3><p>解析完成后可在简历数据库中查看候选人详情。</p></div><el-tag :type="failedCount ? 'warning' : 'success'" effect="plain">成功 {{ successCount }} / {{ uploadResults.length }}</el-tag></div>
      <el-table :data="uploadResults" size="small">
        <el-table-column prop="file_name" label="文件名" min-width="260" show-overflow-tooltip />
        <el-table-column prop="resume_database_name" label="目标简历库" min-width="150" show-overflow-tooltip />
        <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag size="small" :type="statusTag(row.status)">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
        <el-table-column label="结果" min-width="220"><template #default="{ row }">{{ row.duplicate ? '重复文件，已关联已有候选人' : row.error_message || (row.candidate_id ? '已创建候选人档案' : '-') }}</template></el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="databaseDialogVisible" title="新建简历库" width="460px">
      <el-form label-position="top" @submit.prevent>
        <el-form-item label="简历库名称" required><el-input v-model="databaseName" maxlength="128" placeholder="例如：2026 技术岗位候选人" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="databaseDescription" type="textarea" :rows="3" maxlength="512" placeholder="说明这个库的用途、来源或适用团队" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="databaseDialogVisible = false">取消</el-button><el-button type="primary" :loading="creatingDatabase" :disabled="!databaseName.trim()" @click="createDatabase">创建并使用</el-button></template>
    </el-dialog>

    <footer class="action-bar">
      <el-button type="primary" :icon="Upload" :loading="uploading" :disabled="!selectedFiles.length || !selectedDatabaseIds.length" @click="submitUpload">开始上传 {{ selectedFiles.length ? '(' + selectedFiles.length + ')' : '' }}</el-button>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Delete, Document, Setting, Upload, UploadFilled } from '@element-plus/icons-vue'
import HrApi from '@/api/hr/recruitment'
import type { ResumeChannel, ResumeDatabase, ResumeStatus, ResumeUploadResult } from '@/api/type/hr'
import { channelLabels } from '@/views/hr/constants'
import useStore from '@/stores'
import { MsgError, MsgSuccess } from '@/utils/message'

const route = useRoute()
const router = useRouter()
const { user } = useStore()
const isHrAdmin = computed(() => user.getHrRole() === 'ADMIN')
const fileInput = ref<HTMLInputElement>()
const selectedFiles = ref<File[]>([])
const uploadResults = ref<ResumeUploadResult[]>([])
const sourceChannel = ref<ResumeChannel>('OTHER')
const databases = ref<ResumeDatabase[]>([])
const selectedDatabaseIds = ref<string[]>([])
const databaseDialogVisible = ref(false)
const databaseName = ref('')
const databaseDescription = ref('')
const loadingDatabases = ref(false)
const creatingDatabase = ref(false)
const dragActive = ref(false)
const uploading = ref(false)
const supportedExtensions = ['doc', 'docx', 'txt']

const successCount = computed(() => uploadResults.value.filter((item) => item.status === 'SUCCESS').length)
const failedCount = computed(() => uploadResults.value.filter((item) => item.status === 'FAILED').length)
const selectedDatabases = computed(() => databases.value.filter((database) => selectedDatabaseIds.value.includes(database.id)))

function goBack() {
  const databaseId = typeof route.query.database_id === 'string' ? route.query.database_id : ''
  router.push(databaseId ? '/hr/resumes/databases/' + databaseId : '/hr/candidates')
}
function openFilePicker() {
  if (!selectedDatabaseIds.value.length) { MsgError('请先选择目标简历库'); return }
  fileInput.value?.click()
}
function onFileChange(event: Event) { addFiles(Array.from((event.target as HTMLInputElement).files || [])); (event.target as HTMLInputElement).value = '' }
function onDrop(event: DragEvent) { dragActive.value = false; addFiles(Array.from(event.dataTransfer?.files || [])) }

function addFiles(files: File[]) {
  const invalid = files.find((file) => !supportedExtensions.includes(file.name.split('.').pop()?.toLowerCase() || ''))
  if (invalid) { MsgError('仅支持 DOC、DOCX 和 TXT 文件'); return }
  const next = [...selectedFiles.value]
  files.forEach((file) => { if (!next.some((item) => item.name === file.name && item.size === file.size)) next.push(file) })
  if (next.length > 100) { MsgError('单次最多上传 100 份简历'); return }
  selectedFiles.value = next
}

function removeFile(index: number) { selectedFiles.value.splice(index, 1) }

function loadDatabases() {
  loadingDatabases.value = true
  HrApi.getResumeDatabases()
    .then((response) => {
      databases.value = (response.data || []).filter((database) => database.status === 'ACTIVE')
      const total = databases.value.find((database) => database.is_system || database.is_default)
      const preferredId = typeof route.query.database_id === 'string' ? route.query.database_id : ''
      const preferred = databases.value.find((database) => database.id === preferredId)
      selectedDatabaseIds.value = total ? [total.id, ...(preferred && preferred.id !== total.id ? [preferred.id] : [])] : preferred ? [preferred.id] : databases.value[0] ? [databases.value[0].id] : []
    })
    .catch(() => MsgError('简历库加载失败，请刷新重试'))
    .finally(() => { loadingDatabases.value = false })
}

function createDatabase() {
  const name = databaseName.value.trim()
  if (!name) return
  creatingDatabase.value = true
  HrApi.createResumeDatabase({ name, description: databaseDescription.value.trim() })
    .then((response) => {
      databases.value = [response.data, ...databases.value]
      selectedDatabaseIds.value = Array.from(new Set([...selectedDatabaseIds.value, response.data.id]))
      databaseName.value = ''
      databaseDescription.value = ''
      databaseDialogVisible.value = false
      MsgSuccess('简历库已创建并选中')
    })
    .catch(() => MsgError('简历库创建失败，请检查名称后重试'))
    .finally(() => { creatingDatabase.value = false })
}

let pollTimer: ReturnType<typeof setInterval> | null = null
function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null } }
function startPolling(ids: string[]) {
  stopPolling()
  const endsAt = Date.now() + 60 * 1000
  pollTimer = setInterval(() => {
    HrApi.getResumeBatchStatus(ids)
      .then((response) => {
        const statusMap = new Map(response.data.map((item: { resume_id: string }) => [item.resume_id, item]))
        let allDone = true
        for (const record of uploadResults.value) {
          const latest = statusMap.get(record.resume_id) as { status: string; error_message?: string } | undefined
          if (!latest) continue
          ;(record as { status: string; error_message: string }).status = latest.status
          ;(record as { status: string; error_message: string }).error_message = latest.error_message || ''
          if (latest.status === 'PENDING') allDone = false
        }
        if (allDone || Date.now() > endsAt) {
          stopPolling()
          const failed = uploadResults.value.some((r) => r.status === 'FAILED')
          if (failed) MsgError('部分简历解析失败，请查看结果')
        }
      })
      .catch(() => {})
  }, 1000)
}
function submitUpload() {
  if (!selectedFiles.value.length || !selectedDatabaseIds.value.length) { MsgError('请先选择目标简历库和简历文件'); return }
  uploading.value = true
  HrApi.uploadResumes(selectedFiles.value, sourceChannel.value, selectedDatabaseIds.value)
    .then((response) => {
      uploadResults.value = response.data; selectedFiles.value = []; MsgSuccess('简历上传任务已提交')
      const pending = uploadResults.value.filter((r) => r.status === 'PENDING').map((r) => r.resume_id)
      if (pending.length) startPolling(pending)
    })
    .catch(() => MsgError('简历上传失败，请检查文件后重试'))
    .finally(() => { uploading.value = false })
}

onMounted(loadDatabases)
onUnmounted(stopPolling)

function formatSize(size: number) {
  if (size < 1024) return size + ' B'
  if (size < 1024 * 1024) return (size / 1024).toFixed(1) + ' KB'
  return (size / 1024 / 1024).toFixed(1) + ' MB'
}

function statusLabel(status: ResumeStatus) { return ({ PENDING: '解析中', SUCCESS: '成功', FAILED: '失败' } as Record<ResumeStatus, string>)[status] }
function statusTag(status: ResumeStatus) { return ({ PENDING: 'info', SUCCESS: 'success', FAILED: 'danger' } as Record<ResumeStatus, string>)[status] }
</script>

<style scoped>
.upload-page { min-height: 100%; background: var(--el-bg-color-page); }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 20px; margin-bottom: 20px; }
.header-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.page-heading { display: flex; align-items: flex-start; gap: 16px; }
.heading-copy { padding-left: 16px; border-left: 1px solid var(--el-border-color); }
.eyebrow { display: block; margin-bottom: 4px; color: var(--el-color-primary); font-size: 12px; font-weight: 700; letter-spacing: 1px; }
h2 { margin: 0 0 6px; font-size: 24px; line-height: 32px; }
.heading-copy p, .section-heading p { margin: 0; color: var(--el-text-color-secondary); font-size: 13px; }
.upload-layout { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 16px; align-items: start; }
.upload-surface, .settings-surface, .result-surface { border: 1px solid var(--el-border-color-light); border-radius: 6px; background: var(--el-bg-color); }
.upload-surface, .result-surface { padding: 24px; }
.settings-surface { padding: 0 18px; }
.section-heading, .side-heading, .list-heading { display: flex; justify-content: space-between; align-items: center; gap: 14px; }
.section-heading { margin-bottom: 18px; }
.section-heading h3, .side-heading h3 { margin: 0 0 5px; font-size: 16px; }
.file-input { display: none; }
.drop-zone { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 220px; padding: 28px; border: 1px dashed var(--el-border-color); border-radius: 6px; background: var(--el-fill-color-lighter); color: var(--el-text-color-secondary); cursor: pointer; transition: border-color .16s, background .16s; }
.drop-zone:hover, .drop-zone--active { border-color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
.drop-zone strong { margin: 10px 0 6px; color: var(--el-text-color-primary); font-size: 15px; }
.drop-zone span { font-size: 12px; }
.upload-icon { color: var(--el-color-primary); font-size: 36px; }
.file-list { margin-top: 20px; }
.list-heading { padding-bottom: 10px; border-bottom: 1px solid var(--el-border-color-lighter); }
.file-row { display: flex; justify-content: space-between; align-items: center; min-height: 46px; border-bottom: 1px solid var(--el-border-color-lighter); }
.file-info { display: flex; align-items: center; gap: 9px; min-width: 0; }
.file-info span { max-width: min(520px, 65vw); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-info small { color: var(--el-text-color-secondary); }
.settings-section { padding: 20px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.settings-section:last-child { border-bottom: 0; }
.side-heading .el-icon { color: var(--el-text-color-secondary); }
.field-label-row { display: flex; justify-content: space-between; align-items: center; }
.field-label { display: block; margin-bottom: 8px; color: var(--el-text-color-regular); font-size: 13px; }
.field-label-row .field-label { margin-bottom: 0; }
.full-width { width: 100%; }
.database-checklist { min-height: 68px; padding: 8px 0 2px; }
.database-checklist .el-checkbox-group { display: grid; gap: 8px; }
.database-checklist .el-checkbox { height: auto; margin-right: 0; white-space: normal; }
.database-option { display: flex; justify-content: space-between; align-items: center; gap: 12px; line-height: 20px; }
.database-option span { display: flex; align-items: center; gap: 6px; }
.database-option small { color: var(--el-text-color-secondary); }
.selected-database { margin: 8px 0 0; color: var(--el-color-primary); font-size: 12px; line-height: 18px; }
.drop-zone--disabled { cursor: not-allowed; opacity: .62; }
.side-help { margin: 10px 0 0; color: var(--el-text-color-secondary); font-size: 12px; line-height: 18px; }
.process-list { display: grid; gap: 16px; margin: 0; padding: 0; list-style: none; }
.process-list li { display: flex; gap: 10px; align-items: flex-start; }
.process-list li > span { display: inline-flex; justify-content: center; align-items: center; width: 20px; height: 20px; border-radius: 50%; background: var(--el-color-primary-light-8); color: var(--el-color-primary); font-size: 12px; }
.process-list strong, .process-list small { display: block; }
.process-list small { margin-top: 3px; color: var(--el-text-color-secondary); font-size: 12px; }
.summary-list { display: grid; gap: 10px; margin: 0; }
.summary-list div { display: flex; justify-content: space-between; gap: 12px; font-size: 12px; }
.summary-list dt { color: var(--el-text-color-secondary); }
.summary-list dd { margin: 0; color: var(--el-text-color-primary); }
.success-text { color: var(--el-color-success) !important; }
.danger-text { color: var(--el-color-danger) !important; }
.result-surface { margin-top: 16px; }
.action-bar { display: flex; justify-content: flex-end; gap: 10px; padding: 16px 0 4px; }
@media (max-width: 900px) { .page-header { flex-direction: column; } .upload-layout { grid-template-columns: 1fr; } .settings-surface { order: -1; } }
@media (max-width: 640px) { .page-heading { gap: 8px; } .heading-copy { padding-left: 10px; } .upload-surface, .result-surface { padding: 16px; } .file-info span { max-width: 48vw; } }
</style>
