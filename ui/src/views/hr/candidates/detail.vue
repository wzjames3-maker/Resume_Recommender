<template>
  <div class="hr-page p-16-24" v-loading="loading">
    <div class="flex-between mb-16">
      <div class="flex gap-12 align-center">
        <el-button plain @click="router.push('/hr/candidates/list')">返回列表</el-button>
        <h2 class="m-0">{{ candidate?.name || '候选人详情' }}</h2>
        <el-tag v-if="candidate" :type="candidate.status === 'ACTIVE' ? 'success' : 'info'">
          {{ candidate.status === 'ACTIVE' ? '在库' : '已归档' }}
        </el-tag>
      </div>
      <div v-if="candidate" class="flex gap-12">
        <el-button v-if="isHrOperator" plain @click="editCandidate">编辑</el-button>
        <el-button v-if="isHrAdmin && candidate.status === 'ACTIVE'" plain @click="archive">归档</el-button>
        <el-button v-if="isHrAdmin && candidate.status === 'ARCHIVED'" type="success" plain @click="restore">恢复</el-button>
        <el-button v-if="isHrAdmin" type="danger" plain @click="remove">删除</el-button>
      </div>
    </div>

    <el-card v-if="candidate" class="mb-16" style="--el-card-padding: 0">
      <template #header><span>基本信息</span></template>
      <el-descriptions :column="1" border class="p-16">
        <el-descriptions-item label="姓名">{{ candidate.name }}</el-descriptions-item>
        <el-descriptions-item label="手机号">{{ candidate.phone || '-' }}</el-descriptions-item>
        <el-descriptions-item label="邮箱">{{ candidate.email || '-' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card v-if="candidate" class="mb-16" style="--el-card-padding: 0">
      <template #header><span>关联职位</span></template>
      <el-table :data="candidate.assignments || []" size="default">
        <el-table-column prop="job_name" label="职位" min-width="160" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="assignmentTagType(row.status)" size="small">{{ assignmentStatusLabels[row.status] || row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="关系类型" width="100">
          <template #default="{ row }">{{ relationTypeLabels[row.relation_type] || row.relation_type || '-' }}</template>
        </el-table-column>
        <el-table-column label="渠道" width="100">
          <template #default="{ row }">{{ channelLabels[row.channel] || row.channel || '-' }}</template>
        </el-table-column>
        <el-table-column label="负责人" width="120">
          <template #default="{ row }">{{ ownerName(row.owner_id) }}</template>
        </el-table-column>
        <el-table-column prop="note" label="备注" min-width="180" show-overflow-tooltip />
      </el-table>
    </el-card>

    <el-card v-if="candidate" style="--el-card-padding: 0">
      <template #header>
        <span>简历</span>
      </template>
      <el-table :data="resumes" size="default" v-loading="resumeLoading">
        <el-table-column prop="file_name" label="文件名" min-width="200" show-overflow-tooltip />
        <el-table-column prop="extension" label="类型" width="80" />
        <el-table-column label="大小" width="100">
          <template #default="{ row }">{{ formatFileSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="解析状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.status === 'SUCCESS' ? 'success' : row.status === 'FAILED' ? 'danger' : 'warning'" size="small">
              {{ row.status === 'SUCCESS' ? '成功' : row.status === 'FAILED' ? '失败' : '解析中' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="viewContent(row)">查看</el-button>
            <el-button link type="primary" @click="download(row)">下载</el-button>
            <el-button v-if="isHrAdmin" link type="danger" @click="removeResume(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="contentVisible" title="简历内容" width="720px">
      <pre class="resume-content">{{ resumeContent }}</pre>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import HrApi from '@/api/hr/recruitment'
import type { CandidateDetail, ResumeFile } from '@/api/type/hr'
import {
  assignmentStatusLabels,
  assignmentTagType,
  channelLabels,
  formatFileSize,
  relationTypeLabels,
} from '@/views/hr/constants'
import useStore from '@/stores'
import { MsgConfirm, MsgError, MsgSuccess } from '@/utils/message'

const route = useRoute()
const router = useRouter()
const { user } = useStore()

const isHrAdmin = computed(() => user.getHrRole() === 'ADMIN')
const isHrOperator = computed(() => user.getHrRole() === 'OPERATOR' || user.getHrRole() === 'ADMIN')

const loading = ref(false)
const members = ref<Array<{ id: string; nick_name: string }>>([])
const candidate = ref<CandidateDetail | null>(null)
const resumes = ref<ResumeFile[]>([])
const resumeLoading = ref(false)
const contentVisible = ref(false)
const resumeContent = ref('')

function ownerName(ownerId: string | null) {
  if (!ownerId) return '-'
  return members.value.find((member) => member.id === ownerId)?.nick_name || ownerId
}

function loadMembers() {
  HrApi.getMembers().then((response) => {
    members.value = response.data || []
  }).catch(() => {})
}

function loadDetail() {
  const id = String(route.params.id || '')
  if (!id) return
  loading.value = true
  HrApi.getCandidate(id)
    .then((response) => {
      candidate.value = response.data
    })
    .catch(() => MsgError('候选人不存在或无权访问'))
    .finally(() => {
      loading.value = false
    })
}

function loadResumes() {
  const id = String(route.params.id || '')
  if (!id) return
  resumeLoading.value = true
  HrApi.getCandidateResumes(id)
    .then((response) => {
      resumes.value = response.data
    })
    .catch(() => {})
    .finally(() => {
      resumeLoading.value = false
    })
}

function editCandidate() {
  router.push({ path: '/hr/candidates/list', query: { edit_candidate: candidate.value?.id } })
}

function archive() {
  if (!candidate.value) return
  MsgConfirm('归档候选人', `归档后将保留 ${candidate.value.name} 的历史指派记录。`, { confirmButtonClass: 'danger' })
    .then(() => HrApi.archiveCandidate(candidate.value!.id))
    .then(() => {
      MsgSuccess('候选人已归档')
      loadDetail()
    })
    .catch(() => {})
}

function restore() {
  if (!candidate.value) return
  MsgConfirm('恢复候选人', `将 ${candidate.value.name} 恢复为在库状态，可继续加入职位。`)
    .then(() => HrApi.restoreCandidate(candidate.value!.id))
    .then(() => {
      MsgSuccess('候选人已恢复')
      loadDetail()
    })
    .catch(() => {})
}

function remove() {
  if (!candidate.value) return
  MsgConfirm(
    '删除候选人',
    `删除即匿名化处理：姓名被替换、联系方式等个人信息将被清空，且该候选人的简历文件会被删除。确认删除 ${candidate.value.name}？`,
    { confirmButtonClass: 'danger' },
  )
    .then(() => HrApi.deleteCandidate(candidate.value!.id))
    .then(() => {
      MsgSuccess('候选人已删除')
      router.push('/hr/candidates/list')
    })
    .catch(() => {})
}

function viewContent(resume: ResumeFile) {
  resumeContent.value = ''
  contentVisible.value = true
  HrApi.getResumeContent(resume.id)
    .then((response) => {
      resumeContent.value = response.data.content
    })
    .catch(() => MsgError('简历内容提取失败'))
}

function download(resume: ResumeFile) {
  HrApi.downloadResume(resume.id, resume.file_name)
}

function removeResume(resume: ResumeFile) {
  MsgConfirm(
    '删除简历',
    `确认删除简历「${resume.file_name}」？该操作会同时删除语义索引与流转日志，不可恢复。`,
    { confirmButtonClass: 'danger' },
  )
    .then(() => HrApi.deleteResume(resume.id))
    .then(() => {
      MsgSuccess('简历已删除')
      loadResumes()
    })
    .catch(() => {})
}

onMounted(() => {
  loadMembers()
  loadDetail()
  loadResumes()
})

watch(
  () => route.params.id,
  () => {
    loadDetail()
    loadResumes()
  },
)
</script>

<style scoped>
.hr-page { min-width: 0; }
.flex-between { display: flex; justify-content: space-between; align-items: center; }
.flex { display: flex; }
.gap-12 { gap: 12px; }
.align-center { align-items: center; }
.m-0 { margin: 0; }
.mb-16 { margin-bottom: 16px; }
.p-16 { padding: 16px; }
.mr-8 { margin-right: 8px; }
.mb-8 { margin-bottom: 8px; }
.resume-content {
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 480px;
  overflow-y: auto;
  margin: 0;
}
</style>
