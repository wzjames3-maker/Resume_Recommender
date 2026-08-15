<template>
  <div class="hr-page p-16-24">
    <div class="flex-between mb-16">
      <div>
        <h2>入职交接</h2>
        <span class="color-secondary">Offer 接受后的 HRIS/OA/人工清单交接记录（联系方式已脱敏）</span>
      </div>
      <el-button type="primary" plain :loading="loading" @click="loadHandoffs">刷新</el-button>
      <el-button type="primary" plain @click="openConfig">交接配置</el-button>
    </div>

    <el-card style="--el-card-padding: 0" v-loading="loading">
      <el-table :data="handoffs" empty-text="暂无交接记录">
        <el-table-column prop="candidate_name" label="候选人" min-width="110" />
        <el-table-column prop="job_name" label="职位" min-width="140" />
        <el-table-column prop="department" label="部门" min-width="110" />
        <el-table-column prop="phone" label="手机号" width="120" />
        <el-table-column prop="email" label="邮箱" min-width="150" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'SUCCESS' ? 'success' : row.status === 'FAILED' ? 'danger' : 'info'" size="small">
              {{ row.status === 'SUCCESS' ? '成功' : row.status === 'FAILED' ? '失败' : '待处理' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="attempts" label="尝试" width="70" />
        <el-table-column label="最近投递" min-width="160">
          <template #default="{ row }">{{ row.handoff_time ? new Date(row.handoff_time).toLocaleString() : '-' }}</template>
        </el-table-column>
        <el-table-column label="失败原因" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <el-tooltip v-if="row.last_error" :content="row.last_error" placement="top">
              <el-tag type="danger" size="small">查看</el-tag>
            </el-tooltip>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status === 'FAILED'" link type="danger" @click="retry(row)">重试</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="p-16 flex justify-end">
        <el-pagination
          v-model:current-page="pagination.current_page"
          :page-size="pagination.page_size"
          :total="pagination.total"
          layout="total, prev, pager, next"
          @current-change="loadHandoffs"
        />
      </div>
    </el-card>

    <el-dialog v-model="configVisible" title="交接配置" width="480px">
      <el-form label-width="110px">
        <el-form-item label="交接目标">
          <el-select v-model="configForm.target_type" style="width: 100%">
            <el-option label="人工清单（默认）" value="CHECKLIST" />
            <el-option label="Webhook（HRIS/OA）" value="WEBHOOK" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="configForm.target_type === 'WEBHOOK'" label="Webhook URL">
          <el-input v-model="configForm.webhook_url" placeholder="https://hris.example.com/hires" maxlength="512" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="configVisible = false">取消</el-button>
        <el-button type="primary" @click="saveConfig">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import HrApi from '@/api/hr/recruitment'
import type { HandoffRecord } from '@/api/type/hr'
import { MsgConfirm, MsgSuccess } from '@/utils/message'

const loading = ref(false)
const handoffs = ref<HandoffRecord[]>([])
const pagination = reactive({ current_page: 1, page_size: 20, total: 0 })
const configVisible = ref(false)
const configForm = reactive({ target_type: 'CHECKLIST', webhook_url: '' })

function loadHandoffs() {
  loading.value = true
  HrApi.getHandoffs(pagination)
    .then((response) => {
      handoffs.value = response.data.records
      pagination.total = response.data.total
    })
    .catch(() => {})
    .finally(() => {
      loading.value = false
    })
}

function retry(row: HandoffRecord) {
  MsgConfirm('重试交接', '确认重新投递 ' + row.candidate_name + ' 的入职交接？', { confirmButtonClass: 'danger' })
    .then(() => HrApi.retryHandoff(row.id))
    .then(() => {
      MsgSuccess('已重新投递')
      loadHandoffs()
    })
    .catch(() => {})
}

function openConfig() {
  HrApi.getHandoffConfig().then((response) => {
    configForm.target_type = response.data.target_type
    configForm.webhook_url = response.data.webhook_url
    configVisible.value = true
  })
}

function saveConfig() {
  HrApi.putHandoffConfig({ ...configForm })
    .then(() => {
      MsgSuccess('交接配置已保存')
      configVisible.value = false
    })
    .catch(() => {})
}

onMounted(loadHandoffs)
</script>
