<template>
  <div class="database-home p-16-24">
    <header class="page-header">
      <div>
        <span class="eyebrow">候选人数据</span>
        <h2>简历数据库</h2>
        <p>管理多个简历库，点击库名进入对应的候选人和简历数据。</p>
      </div>
      <div class="header-actions">
        <el-button v-if="isHrAdmin" plain :icon="Setting" @click="router.push('/hr/resumes/databases')">库管理</el-button>
        <el-button plain :icon="Search" @click="router.push('/hr/search')">语义检索</el-button>
        <el-button v-if="isHrOperator" type="primary" :icon="Upload" @click="router.push('/hr/resumes/upload')">批量上传简历</el-button>
      </div>
    </header>

    <section class="overview-strip">
      <div><span>有效简历库</span><strong>{{ activeDatabases.length }}</strong></div>
      <div><span>总库简历</span><strong>{{ totalDatabase?.resume_count || 0 }}</strong></div>
      <div><span>业务库</span><strong>{{ businessDatabases.length }}</strong></div>
      <div><span>待解析</span><strong>{{ totalDatabase?.pending_count || 0 }}</strong></div>
    </section>

    <section v-loading="loading" class="database-grid">
      <el-card v-for="database in activeDatabases" :key="database.id" class="database-card" shadow="never" @click="openDatabase(database)">
        <div class="card-topline"><el-tag v-if="database.is_system" type="success" effect="plain">总库</el-tag><el-tag v-else type="info" effect="plain">业务库</el-tag><el-icon><ArrowRight /></el-icon></div>
        <h3>{{ database.name }}</h3>
        <p>{{ database.description || '未填写说明' }}</p>
        <div class="card-stats"><div><strong>{{ database.resume_count }}</strong><span>份简历</span></div><div><strong>{{ database.candidate_count }}</strong><span>位候选人</span></div><div><strong>{{ database.pending_count }}</strong><span>待解析</span></div></div>
        <div class="card-action">进入{{ database.is_system ? '总库' : '此库' }}<el-icon><ArrowRight /></el-icon></div>
      </el-card>
      <el-empty v-if="!loading && !activeDatabases.length" description="暂无有效简历库" />
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, Search, Setting, Upload } from '@element-plus/icons-vue'
import HrApi from '@/api/hr/recruitment'
import type { ResumeDatabase } from '@/api/type/hr'
import useStore from '@/stores'
import { MsgError } from '@/utils/message'

const router = useRouter()
const { user } = useStore()
const isHrAdmin = computed(() => user.getHrRole() === 'ADMIN')
const isHrOperator = computed(() => user.getHrRole() === 'OPERATOR' || user.getHrRole() === 'ADMIN')
const databases = ref<ResumeDatabase[]>([])
const loading = ref(false)
const activeDatabases = computed(() => databases.value.filter((database) => database.status === 'ACTIVE'))
const totalDatabase = computed(() => activeDatabases.value.find((database) => database.is_system))
const businessDatabases = computed(() => activeDatabases.value.filter((database) => !database.is_system))

function loadDatabases() {
  loading.value = true
  HrApi.getResumeDatabases()
    .then((response) => { databases.value = response.data || [] })
    .catch(() => MsgError('简历库加载失败，请刷新重试'))
    .finally(() => { loading.value = false })
}

function openDatabase(database: ResumeDatabase) {
  router.push('/hr/resumes/databases/' + database.id)
}

onMounted(loadDatabases)
</script>

<style scoped>
.database-home { min-height: 100%; background: var(--el-bg-color-page); }
.page-header { display: flex; justify-content: space-between; align-items: flex-end; gap: 20px; margin-bottom: 20px; }
.eyebrow { display: block; margin-bottom: 4px; color: var(--el-color-primary); font-size: 12px; font-weight: 700; letter-spacing: 1px; }
h2 { margin: 0 0 6px; font-size: 24px; line-height: 32px; }
.page-header p { margin: 0; color: var(--el-text-color-secondary); font-size: 13px; }
.header-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.overview-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 20px; }
.overview-strip > div { display: flex; flex-direction: column; gap: 4px; min-height: 72px; padding: 14px 16px; border: 1px solid var(--el-border-color-light); border-radius: 6px; background: var(--el-bg-color); }
.overview-strip span { color: var(--el-text-color-secondary); font-size: 12px; }
.overview-strip strong { color: var(--el-text-color-primary); font-size: 22px; line-height: 28px; }
.database-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; min-height: 220px; }
.database-card { cursor: pointer; transition: border-color .2s, box-shadow .2s, transform .2s; }
.database-card:hover { border-color: var(--el-color-primary); box-shadow: var(--el-box-shadow-light); transform: translateY(-2px); }
.card-topline, .card-action { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.card-topline { color: var(--el-text-color-secondary); }
.database-card h3 { margin: 18px 0 6px; font-size: 18px; line-height: 24px; }
.database-card p { min-height: 36px; margin: 0; color: var(--el-text-color-secondary); font-size: 12px; line-height: 18px; }
.card-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 20px 0; padding: 12px 0; border-top: 1px solid var(--el-border-color-lighter); border-bottom: 1px solid var(--el-border-color-lighter); }
.card-stats div { display: flex; flex-direction: column; gap: 3px; }
.card-stats strong { font-size: 18px; line-height: 22px; }
.card-stats span { color: var(--el-text-color-secondary); font-size: 12px; }
.card-action { color: var(--el-color-primary); font-size: 13px; }
@media (max-width: 760px) { .page-header { align-items: flex-start; flex-direction: column; } .overview-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 440px) { .overview-strip { grid-template-columns: 1fr; } }
</style>
