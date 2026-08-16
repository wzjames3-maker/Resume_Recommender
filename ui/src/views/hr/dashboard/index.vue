<template>
  <div class="hr-page p-16-24">
    <div class="flex-between mb-16">
      <div>
        <h2>招聘工作台</h2>
        <span class="color-secondary">聚合待办与快捷入口</span>
      </div>
    </div>

    <div class="quick-grid mb-16">
      <el-card shadow="never" class="quick-card" @click="router.push('/hr/candidates?new=1')">
        <div class="quick-title">新建候选人</div>
        <div class="quick-desc">录入候选人并完善合规信息</div>
      </el-card>
      <el-card shadow="never" class="quick-card" @click="router.push('/hr/jobs?new=1')">
        <div class="quick-title">新建职位</div>
        <div class="quick-desc">维护招聘需求与技能要求</div>
      </el-card>
      <el-card shadow="never" class="quick-card" @click="router.push('/hr/search')">
        <div class="quick-title">语义检索</div>
        <div class="quick-desc">自然语言查找候选人</div>
      </el-card>
      <el-card shadow="never" class="quick-card" @click="router.push('/hr/my-interviews')">
        <div class="quick-title">我的面试</div>
        <div class="quick-desc">查看反馈截止与逾期状态</div>
      </el-card>
    </div>

    <el-row :gutter="16">
      <el-col :span="12">
        <el-card style="--el-card-padding: 0">
          <template #header>
            <div class="flex-between">
              <span>我的待处理</span>
              <el-button link type="primary" @click="router.push('/hr/candidates')">全部候选人</el-button>
            </div>
          </template>
          <div class="p-16">
            <el-empty v-if="!loading && candidateTotal === 0 && jobTotal === 0" description="暂无待办" />
            <div v-else class="todo-list">
              <div class="todo-item">
                <div class="todo-label">我负责的在库候选人</div>
                <div class="todo-value">{{ candidateTotal }}</div>
              </div>
              <div class="todo-item">
                <div class="todo-label">我负责的开放/暂停职位</div>
                <div class="todo-value">{{ jobTotal }}</div>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card style="--el-card-padding: 0">
          <template #header>
            <div class="flex-between">
              <span>我的面试</span>
              <el-button link type="primary" @click="router.push('/hr/my-interviews')">全部面试</el-button>
            </div>
          </template>
          <div class="p-16">
            <el-empty v-if="!loading && interviews.length === 0" description="暂无面试任务" />
            <div v-for="item in interviews.slice(0, 5)" :key="item.interview_id" class="interview-item">
              <div class="flex-between">
                <span class="interview-name">{{ item.candidate_name }} · {{ item.job_name }}</span>
                <el-tag v-if="item.is_overdue" type="danger" size="small">逾期</el-tag>
                <el-tag v-else-if="item.feedback_submitted_at" type="success" size="small">已反馈</el-tag>
                <el-tag v-else type="warning" size="small">待反馈</el-tag>
              </div>
              <div class="color-secondary text-12">
                {{ item.scheduled_at ? new Date(item.scheduled_at).toLocaleString() : '未排期' }}
                <template v-if="item.feedback_deadline"> · 截止 {{ new Date(item.feedback_deadline).toLocaleString() }}</template>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import HrApi from '@/api/hr/recruitment'
import type { MyInterview } from '@/api/type/hr'
import useStore from '@/stores'
import { MsgError } from '@/utils/message'

const router = useRouter()
const { user } = useStore()

const loading = ref(false)
const candidateTotal = ref(0)
const jobTotal = ref(0)
const interviews = ref<MyInterview[]>([])

function loadDashboard() {
  loading.value = true
  const myId = user.userInfo?.id || ''
  Promise.all([
    HrApi.getCandidates({ current_page: 1, page_size: 1 }, { owner_id: myId, status: 'ACTIVE' }),
    HrApi.getJobs({ current_page: 1, page_size: 1 }, { owner_id: myId, status: '' }),
    HrApi.getMyInterviews(),
  ])
    .then(([candidateRes, jobRes, interviewRes]) => {
      candidateTotal.value = candidateRes.data.total || 0
      jobTotal.value = jobRes.data.total || 0
      interviews.value = interviewRes.data || []
    })
    .catch(() => MsgError('工作台数据加载失败'))
    .finally(() => {
      loading.value = false
    })
}

onMounted(loadDashboard)
</script>

<style scoped>
.hr-page { min-width: 0; }
.flex-between { display: flex; justify-content: space-between; align-items: center; }
.mb-16 { margin-bottom: 16px; }
.quick-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
}
.quick-card { cursor: pointer; transition: box-shadow .2s; }
.quick-card:hover { box-shadow: var(--el-box-shadow-light); }
.quick-title { font-weight: 600; margin-bottom: 6px; }
.quick-desc { font-size: 12px; color: var(--el-text-color-secondary); }
.p-16 { padding: 16px; }
.todo-list { display: flex; flex-direction: column; gap: 12px; }
.todo-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}
.todo-label { color: var(--el-text-color-regular); }
.todo-value { font-size: 24px; font-weight: 600; color: var(--el-color-primary); }
.interview-item {
  padding: 10px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.interview-item:last-child { border-bottom: none; }
.interview-name { font-weight: 500; }
.text-12 { font-size: 12px; line-height: 18px; margin-top: 4px; }
</style>
