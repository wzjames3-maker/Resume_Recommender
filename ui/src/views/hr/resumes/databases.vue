<template>
  <div class="database-page p-16-24">
    <header class="page-header">
      <div class="page-heading">
        <el-button link :icon="ArrowLeft" @click="router.push('/hr/candidates')">返回简历数据库</el-button>
        <div class="heading-copy">
          <span class="eyebrow">候选人数据</span>
          <h2>简历库管理</h2>
          <p>维护总库和业务库，查看每个库的简历与候选人规模。</p>
        </div>
      </div>
      <div class="header-actions">
        <el-button plain :icon="Refresh" :loading="loading" @click="loadDatabases">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">新建简历库</el-button>
      </div>
    </header>

    <section class="summary-grid">
      <div class="summary-item"><span>有效简历库</span><strong>{{ activeDatabases.length }}</strong></div>
      <div class="summary-item"><span>总库简历</span><strong>{{ totalDatabase?.resume_count || 0 }}</strong></div>
      <div class="summary-item"><span>业务库简历归属</span><strong>{{ businessResumeCount }}</strong></div>
      <div class="summary-item"><span>待解析</span><strong>{{ pendingCount }}</strong></div>
    </section>

    <section class="table-surface">
      <el-table v-loading="loading" :data="databases" row-key="id">
        <el-table-column label="简历库" min-width="230">
          <template #default="{ row }">
            <div class="database-name"><strong>{{ row.name }}</strong><el-tag v-if="row.is_system" size="small" type="success" effect="plain">总库</el-tag><el-tag v-else-if="row.status === 'ARCHIVED'" size="small" type="info" effect="plain">已归档</el-tag></div>
            <small>{{ row.description || '未填写说明' }}</small>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag size="small" :type="row.status === 'ACTIVE' ? 'success' : 'info'">{{ row.status === 'ACTIVE' ? '使用中' : '已归档' }}</el-tag></template></el-table-column>
        <el-table-column prop="resume_count" label="简历数" width="110" />
        <el-table-column prop="candidate_count" label="候选人数" width="120" />
        <el-table-column prop="pending_count" label="待解析" width="110" />
        <el-table-column prop="create_time" label="创建时间" min-width="175" />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button v-if="!row.is_system && row.status === 'ACTIVE'" link type="danger" @click="archiveDatabase(row)">归档</el-button>
            <span v-else class="muted-action">{{ row.is_system ? '系统库' : '已归档' }}</span>
          </template>
        </el-table-column>
        <template #empty><el-empty description="暂无简历库" /></template>
      </el-table>
    </section>

    <el-dialog v-model="dialogVisible" title="新建简历库" width="460px">
      <el-form label-position="top" @submit.prevent>
        <el-form-item label="简历库名称" required><el-input v-model="form.name" maxlength="128" placeholder="例如：2026 技术岗位候选人" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="form.description" type="textarea" :rows="3" maxlength="512" placeholder="说明这个库的用途、来源或适用团队" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" :disabled="!form.name.trim()" @click="createDatabase">创建简历库</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft, Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessageBox } from 'element-plus'
import HrApi from '@/api/hr/recruitment'
import type { ResumeDatabase } from '@/api/type/hr'
import { MsgError, MsgSuccess } from '@/utils/message'

const router = useRouter()
const databases = ref<ResumeDatabase[]>([])
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const form = reactive({ name: '', description: '' })

const activeDatabases = computed(() => databases.value.filter((database) => database.status === 'ACTIVE'))
const totalDatabase = computed(() => databases.value.find((database) => database.is_system))
const businessResumeCount = computed(() => activeDatabases.value.filter((database) => !database.is_system).reduce((sum, database) => sum + database.resume_count, 0))
const pendingCount = computed(() => totalDatabase.value?.pending_count || 0)

function loadDatabases() {
  loading.value = true
  HrApi.getResumeDatabases()
    .then((response) => { databases.value = response.data || [] })
    .catch(() => MsgError('简历库加载失败，请刷新重试'))
    .finally(() => { loading.value = false })
}

function openCreate() {
  form.name = ''
  form.description = ''
  dialogVisible.value = true
}

function createDatabase() {
  const name = form.name.trim()
  if (!name) return
  saving.value = true
  HrApi.createResumeDatabase({ name, description: form.description.trim() })
    .then((response) => {
      databases.value = [response.data, ...databases.value]
      dialogVisible.value = false
      MsgSuccess('简历库已创建')
    })
    .catch(() => MsgError('简历库创建失败，请检查名称后重试'))
    .finally(() => { saving.value = false })
}

async function archiveDatabase(database: ResumeDatabase) {
  try {
    await ElMessageBox.confirm('归档“' + database.name + '”后，新上传和检索将不能再选择它，已有简历不会被删除。', '确认归档', { type: 'warning' })
    await HrApi.archiveResumeDatabase(database.id)
    database.status = 'ARCHIVED'
    MsgSuccess('简历库已归档')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') MsgError('简历库归档失败')
  }
}

onMounted(loadDatabases)
</script>

<style scoped>
.database-page { min-height: 100%; background: var(--el-bg-color-page); }
.page-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 20px; margin-bottom: 20px; }
.page-heading { display: flex; align-items: flex-start; gap: 16px; }
.heading-copy { padding-left: 16px; border-left: 1px solid var(--el-border-color); }
.eyebrow { display: block; margin-bottom: 4px; color: var(--el-color-primary); font-size: 12px; font-weight: 700; letter-spacing: 1px; }
h2 { margin: 0 0 6px; font-size: 24px; line-height: 32px; }
.heading-copy p { margin: 0; color: var(--el-text-color-secondary); font-size: 13px; }
.header-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
.summary-item { display: flex; flex-direction: column; gap: 6px; min-height: 80px; padding: 16px; border: 1px solid var(--el-border-color-light); border-radius: 6px; background: var(--el-bg-color); }
.summary-item span { color: var(--el-text-color-secondary); font-size: 12px; }
.summary-item strong { color: var(--el-text-color-primary); font-size: 24px; line-height: 30px; }
.table-surface { border: 1px solid var(--el-border-color-light); border-radius: 6px; background: var(--el-bg-color); }
.database-name { display: flex; align-items: center; gap: 8px; }
.database-name + small { display: block; margin-top: 4px; color: var(--el-text-color-secondary); }
.muted-action { color: var(--el-text-color-secondary); font-size: 12px; }
@media (max-width: 800px) { .page-header { flex-direction: column; } .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 480px) { .summary-grid { grid-template-columns: 1fr; } }
</style>
