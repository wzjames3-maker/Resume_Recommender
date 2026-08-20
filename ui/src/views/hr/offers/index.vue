<template>
  <div class="hr-page p-16-24">
    <div class="flex-between mb-16">
      <div>
        <div class="eyebrow">OFFER OPERATIONS</div>
        <h2>Offer 管理</h2>
        <span class="color-secondary">统一查看工作区内 Offer 版本、审批与发送状态</span>
      </div>
      <div class="header-actions">
        <el-select v-model="filters.status" placeholder="状态" clearable style="width: 140px" @change="refresh">
          <el-option v-for="(label, value) in offerStatusLabels" :key="value" :label="label" :value="value" />
        </el-select>
        <el-button circle :icon="Refresh" title="刷新 Offer" aria-label="刷新 Offer" :loading="loading" @click="loadOffers" />
      </div>
    </div>

    <el-card style="--el-card-padding: 0" v-loading="loading">
      <el-table :data="offers" empty-text="暂无 Offer">
        <el-table-column label="候选人" min-width="130">
          <template #default="{ row }">
            <el-link v-if="row.candidate_id" type="primary" :underline="false" @click="router.push(`/hr/candidates/${row.candidate_id}`)">
              {{ row.candidate_name || '-' }}
            </el-link>
            <span v-else>{{ row.candidate_name || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="job_name" label="职位" min-width="150" />
        <el-table-column prop="version" label="版本" width="70" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="offerStatusTag(row.status)" size="small">{{ offerStatusLabels[row.status] || row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="审批" width="100">
          <template #default="{ row }">
            <el-tag :type="row.approval_status === 'APPROVED' ? 'success' : row.approval_status === 'REJECTED' ? 'danger' : 'info'" size="small" effect="plain">
              {{ approvalLabels[row.approval_status] || row.approval_status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="薪酬" width="130">
          <template #default="{ row }">{{ row.salary_amount ? `${row.currency} ${row.salary_amount}` : '-' }}</template>
        </el-table-column>
        <el-table-column label="附件" width="90">
          <template #default="{ row }">
            <el-tag v-if="row.attachment_name" size="small" type="success" effect="plain">有附件</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="160">
          <template #default="{ row }">{{ new Date(row.create_time).toLocaleString() }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.attachment_name" link type="primary" @click="downloadAttachment(row)">附件</el-button>
            <el-button v-if="isHrAdmin && row.status === 'DRAFT'" link type="primary" @click="send(row)">发送</el-button>
            <template v-if="isHrAdmin && row.status === 'SENT'">
              <el-button link type="success" @click="accept(row)">接受</el-button>
              <el-button link type="warning" @click="reject(row)">拒绝</el-button>
              <el-button link type="info" @click="withdraw(row)">撤回</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
      <div class="p-16 flex justify-end">
        <el-pagination
          v-model:current-page="pagination.current_page"
          :page-size="pagination.page_size"
          :total="pagination.total"
          layout="total, prev, pager, next"
          @current-change="loadOffers"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import HrApi from '@/api/hr/recruitment'
import type { Offer, OfferStatus } from '@/api/type/hr'
import useStore from '@/stores'
import { MsgConfirm, MsgSuccess } from '@/utils/message'
import { offerStatusLabels, offerStatusTag } from '@/views/hr/constants'

const { user } = useStore()
const router = useRouter()
const isHrAdmin = computed(() => user.getHrRole() === 'ADMIN')

const loading = ref(false)
const offers = ref<Offer[]>([])
const pagination = reactive({ current_page: 1, page_size: 20, total: 0 })
const filters = reactive({ status: '' as OfferStatus | '' })

const approvalLabels: Record<string, string> = {
  PENDING: '待审批',
  APPROVED: '已通过',
  REJECTED: '已驳回',
}

function loadOffers() {
  loading.value = true
  HrApi.getAllOffers(pagination, { status: filters.status || undefined })
    .then((response) => {
      offers.value = response.data.records
      pagination.total = response.data.total
    })
    .catch(() => {})
    .finally(() => {
      loading.value = false
    })
}

function refresh() {
  pagination.current_page = 1
  loadOffers()
}

function downloadAttachment(row: Offer) {
  if (!row.attachment_name) return
  HrApi.downloadOfferAttachment(row.id, row.attachment_name)
}

function send(row: Offer) {
  MsgConfirm('发送 Offer', `确认发送 ${row.candidate_name || ''} 的 Offer v${row.version}？`)
    .then(() => HrApi.sendOffer(row.id))
    .then(() => {
      MsgSuccess('Offer 已发送')
      loadOffers()
    })
    .catch(() => {})
}

function accept(row: Offer) {
  MsgConfirm('接受 Offer', `确认将 ${row.candidate_name || ''} 的 Offer v${row.version} 标记为已接受？关联将自动变为 HIRED。`)
    .then(() => HrApi.acceptOffer(row.id))
    .then(() => {
      MsgSuccess('Offer 已接受，关联已入职')
      loadOffers()
    })
    .catch(() => {})
}

function reject(row: Offer) {
  MsgConfirm('拒绝 Offer', `确认将 ${row.candidate_name || ''} 的 Offer v${row.version} 标记为已拒绝？`)
    .then(() => HrApi.rejectOffer(row.id, { note: 'Offer 被拒绝' }))
    .then(() => {
      MsgSuccess('Offer 已拒绝')
      loadOffers()
    })
    .catch(() => {})
}

function withdraw(row: Offer) {
  MsgConfirm('撤回 Offer', `确认撤回 ${row.candidate_name || ''} 的 Offer v${row.version}？`)
    .then(() => HrApi.withdrawOffer(row.id))
    .then(() => {
      MsgSuccess('Offer 已撤回')
      loadOffers()
    })
    .catch(() => {})
}

onMounted(loadOffers)
</script>

<style scoped>
.hr-page { min-width: 0; }
.flex-between { display: flex; justify-content: space-between; align-items: center; }
.flex { display: flex; }
.gap-12 { gap: 12px; }
.mb-16 { margin-bottom: 16px; }
.p-16 { padding: 16px; }
.justify-end { justify-content: flex-end; }
</style>
