<template>
  <div class="hr-page p-16-24">
    <div class="flex-between mb-16">
      <div>
        <h2>职位</h2>
        <span class="color-secondary">维护开放职位与候选人筛选进度</span>
      </div>
      <el-button v-if="isHrAdmin" type="primary" @click="openJobDialog()">新建职位</el-button>
      <el-button v-if="isHrAdmin" plain @click="aiSettingVisible = true">AI 设置</el-button>
    </div>

    <el-card style="--el-card-padding: 0" v-loading="loading">
      <div class="p-16 border-b flex gap-12">
        <el-input v-model="filters.name" placeholder="按职位名称搜索" clearable @change="refresh" />
        <el-select v-model="filters.status" placeholder="状态" clearable @change="refresh" style="width: 140px">
          <el-option v-for="(label, value) in jobStatusLabels" :key="value" :label="label" :value="value" />
        </el-select>
        <el-button :type="filters.owner_id ? 'primary' : 'default'" plain @click="toggleMyJobs">待我处理</el-button>
      </div>

      <AppTable :data="jobs" :pagination-config="pagination" @change-page="loadJobs" @size-change="refresh" @expand-change="handleExpand">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="assignment-panel" v-loading="detailLoading === row.id">
              <el-tabs v-model="expandTab[row.id]" @tab-change="(name: string) => handleExpandTab(row, name)">
                <el-tab-pane label="候选人" name="assignments">
                  <el-empty v-if="jobDetails[row.id]?.assignments?.length === 0" description="暂无候选人" />
                  <div v-else-if="boardState[row.id]" class="kanban-board">
                    <div
                      v-for="col in pipelineColumns"
                      :key="col.key"
                      class="kanban-col"
                      :class="['kanban-col--' + col.key, { 'kanban-col--readonly': col.readonly }]"
                    >
                      <div class="kanban-col__header">
                        <span class="kanban-col__title">{{ col.label }}</span>
                        <el-tag size="small" round :type="col.readonly ? 'info' : 'primary'" effect="plain">
                          {{ boardState[row.id][col.key].length }}
                        </el-tag>
                      </div>
                      <VueDraggable
                        v-model="boardState[row.id][col.key]"
                        :group="{ name: 'assignment-board', pull: !col.readonly, put: !col.readonly }"
                        :sort="false"
                        :animation="150"
                        handle=".kanban-card__drag"
                        ghost-class="kanban-card--ghost"
                        class="kanban-col__body"
                        :data-status="col.key"
                        @add="onBoardDrop(row, $event)"
                      >
                        <template v-for="assignment in boardState[row.id][col.key]" :key="assignment.id">
                          <div class="kanban-card" :data-id="assignment.id">
                            <div class="kanban-card__header">
                              <div class="flex align-center">
                                <el-icon v-if="!col.readonly" class="kanban-card__drag"><rank /></el-icon>
                                <span class="kanban-card__name">{{ assignment.candidate_name || '-' }}</span>
                              </div>
                              <el-tag v-if="assignment.is_reapply" size="small" type="warning" effect="plain">重投</el-tag>
                            </div>
                            <div class="kanban-card__meta">
                              <el-tag v-if="assignment.channel" size="small" effect="plain">{{ channelLabels[assignment.channel] || assignment.channel }}</el-tag>
                              <el-tag v-if="assignment.relation_type" size="small" type="info" effect="plain">{{ relationTypeLabels[assignment.relation_type] || assignment.relation_type }}</el-tag>
                            </div>
                            <div class="kanban-card__footer">
                              <span class="color-secondary ellipsis">{{ assignment.owner_id ? memberName(assignment.owner_id) : '未分配' }}</span>
                              <div class="flex align-center">
                                <el-button v-if="isHrOperator" link type="primary" size="small" @click="openInterviewDrawer(row, assignment)">面试</el-button>
                                <el-button v-if="isHrAdmin && assignment.status === 'OFFER'" link type="primary" size="small" @click="openOfferDrawer(row, assignment)">Offer</el-button>
                                <el-dropdown
                                  v-if="isHrOperator"
                                  trigger="click"
                                  size="small"
                                  @click.stop
                                  @command="(cmd: string) => onCardCommand(cmd, row, assignment)"
                                >
                                  <el-button link size="small" @click.stop>更多</el-button>
                                  <template #dropdown>
                                    <el-dropdown-menu>
                                      <el-dropdown-item v-if="isHrAdmin" command="edit">编辑指派</el-dropdown-item>
                                      <el-dropdown-item
                                        v-if="PIPELINE_ORDER.includes(assignment.status as any) && assignment.status !== 'HIRED'"
                                        command="reject"
                                        divided
                                      >淘汰</el-dropdown-item>
                                      <el-dropdown-item
                                        v-if="PIPELINE_ORDER.includes(assignment.status as any) && assignment.status !== 'HIRED'"
                                        command="withdraw"
                                      >候选人退出</el-dropdown-item>
                                      <el-dropdown-item
                                        v-if="PIPELINE_ORDER.includes(assignment.status as any) && assignment.status !== 'HIRED'"
                                        command="close"
                                      >关闭指派</el-dropdown-item>
                                      <el-dropdown-item v-if="isHrAdmin && assignment.status === 'REJECTED'" command="restore" divided>恢复待筛选</el-dropdown-item>
                                    </el-dropdown-menu>
                                  </template>
                                </el-dropdown>
                              </div>
                            </div>
                          </div>
                        </template>
                      </VueDraggable>
                    </div>
                  </div>
                </el-tab-pane>
                <el-tab-pane label="匹配候选人" name="matches">
                  <el-empty v-if="matches[row.id]?.records?.length === 0" description="暂无匹配候选人" />
                  <el-table v-else :data="matches[row.id]?.records || []" size="small">
                    <el-table-column prop="name" label="候选人" min-width="120" />
                    <el-table-column label="匹配分" width="90">
                      <template #default="{ row: match }"><el-tag size="small">{{ match.match_score }}</el-tag></template>
                    </el-table-column>
                    <el-table-column label="命中技能" min-width="160">
                      <template #default="{ row: match }">{{ match.matched_skills.join('、') || '-' }}</template>
                    </el-table-column>
                    <el-table-column prop="current_city" label="现居" width="100"><template #default="{ row: match }">{{ match.current_city || '-' }}</template></el-table-column>
                    <el-table-column label="操作" width="110">
                      <template #default="{ row: match }">
                        <el-button v-if="isHrOperator" link type="primary" size="small" :disabled="row.status === 'CLOSED'" @click="addMatchToJob(row, match)">加入职位</el-button>
                      </template>
                    </el-table-column>
                  </el-table>
                </el-tab-pane>
              </el-tabs>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="职位" min-width="180" />
        <el-table-column prop="department" label="部门" min-width="130"><template #default="{ row }">{{ row.department || '-' }}</template></el-table-column>
        <el-table-column prop="city" label="城市" width="120"><template #default="{ row }">{{ row.city || '-' }}</template></el-table-column>
        <el-table-column label="HC" width="90"><template #default="{ row }">{{ row.active_assignment_count }}/{{ row.headcount }}</template></el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }"><el-tag :type="jobStatusTagType(row.status)">{{ jobStatusLabels[row.status] || row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column label="负责人" width="110">
          <template #default="{ row }">{{ memberName(row.owner_id) || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button v-if="isHrAdmin" link type="primary" @click="openJobDialog(row)">编辑</el-button>
            <el-button v-if="isHrAdmin" link type="warning" :disabled="row.status !== 'ON_HOLD' && row.status !== 'CLOSED'" @click="reopenJob(row)">恢复</el-button>
            <el-button v-if="isHrAdmin" link type="danger" :disabled="row.status === 'CLOSED'" @click="openCloseDialog(row)">关闭</el-button>
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
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="状态">
              <el-select v-model="jobForm.status" style="width: 100%" :disabled="editingJob?.status === 'CLOSED'">
                <el-option v-for="(label, value) in statusOptions" :key="value" :label="label" :value="value" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="负责人">
              <el-select v-model="jobForm.owner_id" clearable filterable placeholder="选择负责人" style="width: 100%">
                <el-option v-for="member in members" :key="member.id" :label="member.nick_name" :value="member.id" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item v-if="jobForm.status === 'CLOSED'" label="关闭原因" required>
          <el-select v-model="jobForm.close_reason" placeholder="选择关闭原因" style="width: 100%">
            <el-option v-for="(label, value) in jobCloseReasonLabels" :key="value" :label="label" :value="value" />
          </el-select>
        </el-form-item>
        <el-form-item label="职位描述"><el-input v-model="jobForm.description" type="textarea" :rows="5" maxlength="4096" show-word-limit /></el-form-item>
        <el-form-item label="技能要求">
          <div class="w-full">
            <el-input v-model="jobSkillsText" placeholder="用逗号分隔，例如 Python, Django" />
            <el-button class="mt-8" size="small" :loading="extractingSkills" :disabled="!jobForm.description.trim()" @click="extractSkillsFromDescription">AI 抽取技能</el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="jobDialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveJob">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="interviewDrawerVisible" title="面试记录" width="640px">
      <div class="flex-between mb-16">
        <span>{{ interviewCandidateName }} · 第 {{ interviewAssignment?.id?.slice(0, 8) }} 指派</span>
        <el-button v-if="isHrOperator" type="primary" size="small" @click="addInterviewFormVisible = true">安排面试</el-button>
      </div>
      <el-form v-if="addInterviewFormVisible" label-width="88px" class="mb-16 p-16 border rounded">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="面试官">
              <el-select v-model="interviewForm.interviewer_user_id" filterable clearable placeholder="选择成员（可留空填临时面试官）" style="width: 100%">
                <el-option v-for="member in members" :key="member.id" :label="member.nick_name" :value="member.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12"><el-form-item label="面试时间"><el-date-picker v-model="interviewForm.scheduled_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" style="width: 100%" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="反馈截止">
              <el-date-picker v-model="interviewForm.feedback_deadline" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" placeholder="可选" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12"><el-form-item label="临时面试官"><el-input v-model="interviewForm.interviewer" placeholder="未选成员时使用" /></el-form-item></el-col>
        </el-row>
        <div class="text-right">
          <el-button size="small" @click="addInterviewFormVisible = false">取消</el-button>
          <el-button size="small" type="primary" @click="createInterviewRecord">保存</el-button>
        </div>
      </el-form>
      <el-table :data="interviewList" size="small">
        <el-table-column prop="round_no" label="轮次" width="60" />
        <el-table-column prop="interviewer" label="面试官" min-width="100" />
        <el-table-column prop="scheduled_at" label="时间" min-width="150">
          <template #default="{ row }">{{ row.scheduled_at ? new Date(row.scheduled_at).toLocaleString() : '-' }}</template>
        </el-table-column>
        <el-table-column label="反馈截止" min-width="170">
          <template #default="{ row }">
            <span v-if="row.feedback_deadline">
              {{ new Date(row.feedback_deadline).toLocaleString() }}
              <el-tag v-if="row.feedback_submitted_at" type="success" size="small">已提交</el-tag>
              <el-tag v-else-if="row.status === 'PENDING' && new Date(row.feedback_deadline) < new Date()" type="danger" size="small">逾期</el-tag>
            </span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="结果" width="130">
          <template #default="{ row }">
            <el-select v-model="row.status" size="small" :disabled="!isHrOperator" @change="updateInterviewRecord(row)">
              <el-option label="待面试" value="PENDING" />
              <el-option label="通过" value="PASSED" />
              <el-option label="未通过" value="FAILED" />
              <el-option label="未到场" value="NO_SHOW" />
              <el-option label="取消" value="CANCELLED" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="反馈" min-width="160">
          <template #default="{ row }">
            <el-input v-model="row.feedback" size="small" :disabled="!isHrOperator" @change="updateInterviewRecord(row)" placeholder="填写反馈" />
          </template>
        </el-table-column>
      </el-table>
      <template #footer><el-button @click="interviewDrawerVisible = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="offerDrawerVisible" title="Offer 管理" width="860px">
      <div class="flex-between mb-16">
        <span>{{ offerCandidateName }} · {{ offerAssignment?.job_name || '' }}</span>
        <el-button v-if="isHrAdmin" type="primary" size="small" @click="addOfferFormVisible = true">新建版本</el-button>
      </div>
      <el-form v-if="addOfferFormVisible" label-width="88px" class="mb-16 p-16 border rounded">
        <el-row :gutter="16">
          <el-col :span="8"><el-form-item label="金额"><el-input-number v-model="offerForm.salary_amount" :min="0" :precision="2" style="width: 100%" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="币种"><el-input v-model="offerForm.currency" maxlength="16" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="备注"><el-input v-model="offerForm.note" /></el-form-item></el-col>
        </el-row>
        <div class="text-right">
          <el-button size="small" @click="addOfferFormVisible = false">取消</el-button>
          <el-button size="small" type="primary" @click="createOfferRecord">保存</el-button>
        </div>
      </el-form>
      <el-table :data="offerList" size="small">
        <el-table-column prop="version" label="版本" width="60" />
        <el-table-column label="金额" width="110">
          <template #default="{ row }">{{ row.salary_amount == null ? '-' : row.salary_amount + ' ' + row.currency }}</template>
        </el-table-column>
        <el-table-column label="审批" width="100">
          <template #default="{ row }">
            <el-tag :type="row.approval_status === 'APPROVED' ? 'success' : row.approval_status === 'REJECTED' ? 'danger' : 'info'" size="small">
              {{ row.approval_status === 'APPROVED' ? '已通过' : row.approval_status === 'REJECTED' ? '已驳回' : '待审批' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }"><el-tag :type="offerStatusTag(row.status)" size="small">{{ offerStatusLabels[row.status] }}</el-tag></template>
        </el-table-column>
        <el-table-column label="时间" min-width="160">
          <template #default="{ row }">{{ offerTimeText(row) }}</template>
        </el-table-column>
        <el-table-column label="附件" min-width="120">
          <template #default="{ row }">
            <template v-if="row.attachment_name">
              <el-button link type="primary" size="small" @click="downloadOfferAttachment(row)">{{ row.attachment_name }}</el-button>
              <el-button v-if="isHrAdmin" link type="danger" size="small" @click="removeOfferAttachment(row)">删除</el-button>
            </template>
            <el-upload v-else-if="isHrAdmin && row.status === 'DRAFT'" :show-file-list="false" :before-upload="(file: File) => uploadOfferAttachment(row, file)">
              <el-button link type="primary" size="small">上传</el-button>
            </el-upload>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <template v-if="isHrAdmin && row.status === 'DRAFT'">
              <el-button link type="primary" size="small" @click="openApproveOfferDialog(row)">审批</el-button>
              <el-button link type="primary" size="small" @click="sendOfferRecord(row)">发送</el-button>
            </template>
            <template v-else-if="isHrAdmin && row.status === 'SENT'">
              <el-button link type="success" size="small" @click="acceptOfferRecord(row)">接受</el-button>
              <el-button link type="danger" size="small" @click="rejectOfferRecord(row)">拒绝</el-button>
              <el-button link type="warning" size="small" @click="withdrawOfferRecord(row)">撤回</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
      <template #footer><el-button @click="offerDrawerVisible = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="approveOfferDialogVisible" title="Offer 审批" width="440px">
      <el-form label-width="88px">
        <el-form-item label="审批结果" required>
          <el-select v-model="approveForm.approval_status" style="width: 100%">
            <el-option label="通过" value="APPROVED" />
            <el-option label="驳回" value="REJECTED" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="approveOfferDialogVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!approveForm.approval_status" @click="approveOfferRecord">提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="closeDialogVisible" title="关闭职位" width="440px">
      <el-form label-width="96px">
        <el-form-item label="职位"><span>{{ closingJob?.name }}</span></el-form-item>
        <el-form-item label="在途关联">
          <el-tag type="warning">{{ closingJob?.active_assignment_count || 0 }}</el-tag>
          <span class="ml-8 color-secondary">将被批量收尾并标记为「职位关闭」</span>
        </el-form-item>
        <el-form-item label="关闭原因" required>
          <el-select v-model="closeReason" placeholder="选择关闭原因" style="width: 100%">
            <el-option v-for="(label, value) in jobCloseReasonLabels" :key="value" :label="label" :value="value" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="closeDialogVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!closeReason" :loading="saving" @click="confirmCloseJob">确认关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="statusDialogVisible" title="状态变更" width="440px">
      <el-form label-width="96px">
        <el-form-item label="候选人"><span>{{ statusDialogAssignment?.candidate_name }}</span></el-form-item>
        <el-form-item label="目标状态"><span>{{ assignmentStatusLabels[statusDialogTarget] || statusDialogTarget }}</span></el-form-item>
        <el-form-item v-if="isRestoreTransition" label="恢复原因" required>
          <el-input v-model="statusDialogNote" placeholder="填写误拒绝恢复原因" />
        </el-form-item>
        <el-form-item v-else label="终止原因" required>
          <el-select v-model="statusDialogReason" placeholder="选择终止原因" style="width: 100%">
            <el-option v-for="(label, value) in terminationReasonLabels" :key="value" :label="label" :value="value" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="statusDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="confirmStatusChange">确认</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="assignmentEditVisible" title="编辑指派" width="480px">
      <el-form label-width="88px">
        <el-form-item label="候选人"><span>{{ assignmentEditForm.candidate_name }}</span></el-form-item>
        <el-form-item label="关系类型">
          <el-select v-model="assignmentEditForm.relation_type" style="width: 100%">
            <el-option v-for="(label, value) in relationTypeLabels" :key="value" :label="label" :value="value" />
          </el-select>
        </el-form-item>
        <el-form-item label="渠道">
          <el-select v-model="assignmentEditForm.channel" style="width: 100%">
            <el-option v-for="(label, value) in channelLabels" :key="value" :label="label" :value="value" />
          </el-select>
        </el-form-item>
        <el-form-item label="负责人">
          <el-select v-model="assignmentEditForm.owner_id" clearable filterable placeholder="选择负责人" style="width: 100%">
            <el-option v-for="member in members" :key="member.id" :label="member.nick_name" :value="member.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="assignmentEditForm.note" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="assignmentEditVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveAssignmentEdit">保存</el-button>
      </template>
    </el-dialog>

    <AiSettingDialog v-model="aiSettingVisible" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { VueDraggable } from 'vue-draggable-plus'
import AppTable from '@/components/app-table/index.vue'
import AiSettingDialog from '@/views/hr/components/AiSettingDialog.vue'
import HrApi from '@/api/hr/recruitment'
import AuthorizationApi from '@/api/system/resource-authorization'
import {
  PIPELINE_ORDER,
  TERMINAL_STATUSES,
  assignmentStatusLabels,
  channelLabels,
  jobCloseReasonLabels,
  jobStatusLabels,
  jobStatusTagType,
  offerStatusLabels,
  offerStatusTag,
  relationTypeLabels,
  terminationReasonLabels,
} from '@/views/hr/constants'
import type {
  Assignment,
  AssignmentStatus,
  Interview,
  Job,
  JobCloseReason,
  JobDetail,
  JobMatchCandidate,
  JobMatchPage,
  JobStatus,
  Offer,
  RelationType,
  ResumeChannel,
  TerminationReason,
} from '@/api/type/hr'
import useStore from '@/stores'
import { MsgConfirm, MsgError, MsgSuccess } from '@/utils/message'

interface WorkspaceMember {
  id: string
  nick_name: string
  roles: string[]
}

const statusOptions = computed(() => {
  if (!editingJob.value) {
    return Object.fromEntries(Object.entries(jobStatusLabels).filter(([value]) => value !== 'CLOSED'))
  }
  if (editingJob.value.status === 'CLOSED') return { CLOSED: jobStatusLabels.CLOSED }
  return jobStatusLabels
})

const loading = ref(false)
const saving = ref(false)
const jobs = ref<Job[]>([])
const members = ref<WorkspaceMember[]>([])
const filters = reactive({ name: '', status: '', owner_id: '' })
const pagination = reactive({ current_page: 1, page_size: 20, total: 0 })
const jobDetails = reactive<Record<string, JobDetail>>({})
const matches = reactive<Record<string, JobMatchPage>>({})
/** 看板列:key 对应后端状态,TERMINAL 收纳全部终态 */
const pipelineColumns = [
  { key: 'PENDING_SCREEN', label: '待筛选', readonly: false },
  { key: 'SCREEN_PASSED', label: '筛选通过', readonly: false },
  { key: 'INTERVIEWING', label: '面试中', readonly: false },
  { key: 'OFFER', label: 'Offer 中', readonly: false },
  { key: 'HIRED', label: '已入职', readonly: true },
  { key: 'TERMINAL', label: '已结束', readonly: true },
] as const

type BoardColumnKey = (typeof pipelineColumns)[number]['key']

const boardState = reactive<Record<string, Record<BoardColumnKey, Assignment[]>>>({})

function syncBoard(jobId: string) {
  const assignments = jobDetails[jobId]?.assignments || []
  const columns: Record<BoardColumnKey, Assignment[]> = {
    PENDING_SCREEN: [], SCREEN_PASSED: [], INTERVIEWING: [], OFFER: [], HIRED: [], TERMINAL: [],
  }
  for (const assignment of assignments) {
    const key = (TERMINAL_STATUSES as readonly string[]).includes(assignment.status) ? 'TERMINAL' : assignment.status
    columns[key as BoardColumnKey].push(assignment)
  }
  boardState[jobId] = columns
}

watch(
  jobDetails,
  () => {
    Object.keys(jobDetails).forEach((jobId) => syncBoard(jobId))
  },
  { deep: true },
)
const detailLoading = ref('')
const jobDialogVisible = ref(false)
const aiSettingVisible = ref(false)
const editingJob = ref<Job | null>(null)
const jobSkillsText = ref('')
const extractingSkills = ref(false)
const expandTab = reactive<Record<string, string>>({})
const jobForm = reactive({
  name: '', department: '', city: '', level: '', headcount: 1, description: '',
  status: 'OPEN' as JobStatus, close_reason: null as JobCloseReason | null, owner_id: null as string | null,
})
const isHrAdmin = computed(() => user.getHrRole() === 'ADMIN')
const isHrOperator = computed(() => user.getHrRole() === 'OPERATOR' || user.getHrRole() === 'ADMIN')
const interviewDrawerVisible = ref(false)
const interviewList = ref<Interview[]>([])
const interviewAssignment = ref<Assignment | null>(null)
const interviewCandidateName = ref('')
const addInterviewFormVisible = ref(false)
const interviewForm = reactive({
  interviewer: '',
  interviewer_user_id: null as string | null,
  feedback_deadline: null as string | null,
  scheduled_at: null as string | null,
})
const closeDialogVisible = ref(false)
const closingJob = ref<Job | null>(null)
const closeReason = ref('')
const statusDialogVisible = ref(false)
const statusDialogAssignment = ref<Assignment | null>(null)
const statusDialogTarget = ref<AssignmentStatus | ''>('')
const statusDialogReason = ref<TerminationReason | ''>('')
const statusDialogNote = ref('')
const assignmentEditVisible = ref(false)
const assignmentEditJob = ref<Job | null>(null)
const boardAssignmentId = ref('')
const assignmentEditForm = reactive({
  candidate_name: '',
  relation_type: 'APPLY' as RelationType,
  channel: 'OTHER' as ResumeChannel,
  owner_id: null as string | null,
  note: '',
})
const { user } = useStore()

const isRestoreTransition = computed(
  () => statusDialogAssignment.value?.status === 'REJECTED' && statusDialogTarget.value === 'PENDING_SCREEN',
)

function memberName(memberId: string | null) {
  if (!memberId) return ''
  return members.value.find((member) => member.id === memberId)?.nick_name || ''
}

function loadMembers() {
  AuthorizationApi.getUserMember(user.getWorkspaceId() || '').then((response) => {
    members.value = response.data || []
  }).catch(() => {})
}

function resetJobForm(job?: Job) {
  jobForm.name = job?.name || ''
  jobForm.department = job?.department || ''
  jobForm.city = job?.city || ''
  jobForm.level = job?.level || ''
  jobForm.headcount = job?.headcount || 1
  jobForm.description = job?.description || ''
  jobForm.status = (job?.status || 'OPEN') as JobStatus
  jobForm.close_reason = job?.close_reason || null
  jobForm.owner_id = job?.owner_id || null
  jobSkillsText.value = job?.skill_requirements?.join(', ') || ''
}

function loadJobs() {
  HrApi.getJobs(pagination, filters).then((response) => {
    jobs.value = response.data.records
    pagination.total = response.data.total
  })
}

function handleExpand(job: Job, expandedRows: Job[]) {
  if (expandedRows.some((row) => row.id === job.id)) {
    if (!expandTab[job.id]) expandTab[job.id] = 'assignments'
    if (!jobDetails[job.id]) {
      loadJobDetail(job)
      loadMatches(job)
    }
  }
}

function handleExpandTab(job: Job, name: string) {
  if (name === 'matches' && !matches[job.id]) loadMatches(job)
}

function loadMatches(job: Job) {
  HrApi.getJobMatches(job.id, { current_page: 1, page_size: 50 }).then((response) => {
    matches[job.id] = response.data
  })
}

function refresh() {
  pagination.current_page = 1
  loadJobs()
}

function loadJobDetail(job: Job) {
  detailLoading.value = job.id
  return HrApi.getJob(job.id).then((response) => {
    jobDetails[job.id] = response.data
    return response.data
  }).finally(() => {
    if (detailLoading.value === job.id) detailLoading.value = ''
  })
}

function openJobDialog(job?: Job) {
  editingJob.value = job || null
  resetJobForm(job)
  jobDialogVisible.value = true
}

function extractSkillsFromDescription() {
  const description = jobForm.description.trim()
  if (!description) return
  extractingSkills.value = true
  HrApi.extractSkills(description)
    .then((response) => {
      jobSkillsText.value = response.data.skills.join(', ')
      MsgSuccess('技能已抽取，可编辑后随职位保存')
    })
    .catch(() => {})
    .finally(() => {
      extractingSkills.value = false
    })
}

function saveJob() {
  if (!jobForm.name.trim()) return
  if (jobForm.status === 'CLOSED' && !jobForm.close_reason) {
    MsgError('关闭职位需要选择关闭原因')
    return
  }
  saving.value = true
  const data = {
    ...jobForm,
    skill_requirements: jobSkillsText.value.split(',').map((skill) => skill.trim()).filter(Boolean),
  }
  if (editingJob.value && jobForm.status === 'CLOSED' && editingJob.value.status !== 'CLOSED') {
    HrApi.closeJob(editingJob.value.id, jobForm.close_reason as JobCloseReason)
      .then((response) => {
        jobDialogVisible.value = false
        const count = response.data.closed_count
        MsgSuccess(count > 0 ? `职位已关闭，收尾 ${count} 个在途关联` : '职位已关闭')
        refresh()
      })
      .catch(() => {})
      .finally(() => { saving.value = false })
    return
  }
  const request = editingJob.value ? HrApi.updateJob(editingJob.value.id, data) : HrApi.createJob(data)
  request.then(() => {
    jobDialogVisible.value = false
    MsgSuccess('职位已保存')
    refresh()
  }).catch(() => {}).finally(() => { saving.value = false })
}

function toggleMyJobs() {
  filters.owner_id = filters.owner_id ? '' : user.userInfo?.id || ''
  refresh()
}

function openCloseDialog(job: Job) {
  closingJob.value = job
  closeReason.value = ''
  closeDialogVisible.value = true
}

function confirmCloseJob() {
  if (!closingJob.value || !closeReason.value) return
  saving.value = true
  HrApi.closeJob(closingJob.value.id, closeReason.value as JobCloseReason)
    .then((response) => {
      closeDialogVisible.value = false
      const count = response.data.closed_count
      MsgSuccess(count > 0 ? `职位已关闭，收尾 ${count} 个在途关联` : '职位已关闭')
      refresh()
    })
    .catch(() => {})
    .finally(() => { saving.value = false })
}

function reopenJob(job: Job) {
  MsgConfirm('恢复招聘', `将把“${job.name}”重新开放，并清空关闭原因。`)
    .then(() => HrApi.reopenJob(job.id))
    .then(() => {
      MsgSuccess('职位已恢复')
      refresh()
    })
    .catch(() => {})
}

/** 看板拖拽落点:仅允许沿管道链向前推进,终态/回退由卡片菜单走状态对话框 */
function onBoardDrop(job: Job, evt: any) {
  const fromStatus: string = evt.from?.dataset?.status || ''
  const toStatus: string = evt.to?.dataset?.status || ''
  const assignmentId: string = evt.item?.dataset?.id || ''
  if (!assignmentId || fromStatus === toStatus || toStatus === 'TERMINAL' || toStatus === 'HIRED') {
    loadJobDetail(job)
    return
  }
  const fromIdx = PIPELINE_ORDER.indexOf(fromStatus as any)
  const toIdx = PIPELINE_ORDER.indexOf(toStatus as any)
  if (fromIdx === -1 || toIdx === -1 || toIdx <= fromIdx) {
    MsgError('只能按 待筛选 → 筛选通过 → 面试中 → Offer 顺序推进')
    loadJobDetail(job)
    return
  }
  HrApi.updateAssignment(assignmentId, { status: toStatus as AssignmentStatus })
    .then(() => {
      MsgSuccess('状态已更新')
      // 仅刷新看板数据,不整体刷新表格,避免展开面板收起
      loadJobDetail(job)
    })
    .catch(() => loadJobDetail(job))
}

/** 卡片菜单命令 */
function onCardCommand(cmd: string, job: Job, assignment: Assignment) {
  if (cmd === 'edit') openAssignmentEditDialog(job, assignment)
  else if (cmd === 'reject') openStatusChangeDialog(assignment, 'REJECTED')
  else if (cmd === 'withdraw') openStatusChangeDialog(assignment, 'WITHDRAWN')
  else if (cmd === 'close') openStatusChangeDialog(assignment, 'CLOSED')
  else if (cmd === 'restore') openStatusChangeDialog(assignment, 'PENDING_SCREEN')
}

function openStatusChangeDialog(assignment: Assignment, target: AssignmentStatus) {
  statusDialogAssignment.value = assignment
  statusDialogTarget.value = target
  statusDialogReason.value = ''
  statusDialogNote.value = ''
  statusDialogVisible.value = true
}

function confirmStatusChange() {
  const assignment = statusDialogAssignment.value
  const target = statusDialogTarget.value
  if (!assignment || !target) return
  if (isRestoreTransition.value) {
    if (!statusDialogNote.value.trim()) {
      MsgError('请填写恢复原因')
      return
    }
    saving.value = true
    HrApi.updateAssignment(assignment.id, { status: target, note: statusDialogNote.value.trim() })
      .then(() => {
        statusDialogVisible.value = false
        MsgSuccess('候选人已恢复待筛选')
        reloadAssignment(assignment)
      })
      .catch(() => {})
      .finally(() => { saving.value = false })
    return
  }
  if (!statusDialogReason.value) {
    MsgError('请选择终止原因')
    return
  }
  saving.value = true
  HrApi.updateAssignment(assignment.id, { status: target, termination_reason: statusDialogReason.value })
    .then(() => {
      statusDialogVisible.value = false
      MsgSuccess('状态已更新')
      reloadAssignment(assignment)
    })
    .catch(() => {})
    .finally(() => { saving.value = false })
}

function reloadAssignment(assignment: Assignment) {
  const job = jobs.value.find((item) => item.id === assignment.job_id)
  if (job) {
    loadJobDetail(job).then((detail) => {
      // 同步表格行的在途数量,避免整体刷新收起展开面板
      if (detail) job.active_assignment_count = detail.active_assignment_count
    })
  }
}

function openAssignmentEditDialog(job: Job, assignment: Assignment) {
  assignmentEditJob.value = job
  boardAssignmentId.value = assignment.id
  assignmentEditForm.candidate_name = assignment.candidate_name || ''
  assignmentEditForm.relation_type = assignment.relation_type || 'APPLY'
  assignmentEditForm.channel = assignment.channel || 'OTHER'
  assignmentEditForm.owner_id = assignment.owner_id || null
  assignmentEditForm.note = assignment.note || ''
  assignmentEditVisible.value = true
}

function saveAssignmentEdit() {
  const assignmentId = boardAssignmentId.value
  if (!assignmentId) return
  saving.value = true
  HrApi.updateAssignment(assignmentId, {
    relation_type: assignmentEditForm.relation_type,
    channel: assignmentEditForm.channel,
    owner_id: assignmentEditForm.owner_id || null,
    note: assignmentEditForm.note,
  })
    .then(() => {
      assignmentEditVisible.value = false
      MsgSuccess('指派已更新')
      if (assignmentEditJob.value) loadJobDetail(assignmentEditJob.value)
      refresh()
    })
    .catch(() => {})
    .finally(() => { saving.value = false })
}

function addMatchToJob(job: Job, match: JobMatchCandidate) {
  HrApi.createAssignment(job.id, match.candidate_id)
    .then(() => {
      MsgSuccess(`已将 ${match.name} 加入职位`)
      loadMatches(job)
      loadJobDetail(job)
      refresh()
    })
    .catch(() => {})
}

function resetInterviewForm() {
  interviewForm.interviewer = ''
  interviewForm.interviewer_user_id = null
  interviewForm.feedback_deadline = null
  interviewForm.scheduled_at = null
}

function openInterviewDrawer(job: Job, assignment: Assignment) {
  interviewAssignment.value = assignment
  interviewCandidateName.value = assignment.candidate_name || ''
  interviewList.value = []
  addInterviewFormVisible.value = false
  resetInterviewForm()
  interviewDrawerVisible.value = true
  HrApi.getInterviews(assignment.id).then((response) => {
    interviewList.value = response.data
  })
}

function createInterviewRecord() {
  if (!interviewAssignment.value) return
  HrApi.createInterview(interviewAssignment.value.id, { ...interviewForm })
    .then(() => {
      MsgSuccess('面试已安排')
      addInterviewFormVisible.value = false
      resetInterviewForm()
      if (interviewAssignment.value) {
        HrApi.getInterviews(interviewAssignment.value.id).then((response) => {
          interviewList.value = response.data
        })
      }
    })
    .catch(() => {})
}

function updateInterviewRecord(interview: Interview) {
  HrApi.updateInterview(interview.id, { status: interview.status, feedback: interview.feedback })
    .then(() => MsgSuccess('面试记录已更新'))
    .catch(() => {})
}

const offerDrawerVisible = ref(false)
const addOfferFormVisible = ref(false)
const approveOfferDialogVisible = ref(false)
const offerAssignment = ref<Assignment | null>(null)
const offerCandidateName = ref('')
const offerList = ref<Offer[]>([])
const offerForm = reactive({ salary_amount: null as number | null, currency: 'CNY', note: '' })
const approveForm = reactive({ approval_status: '' as string })
const approveTarget = ref<Offer | null>(null)

function offerTimeText(offer: Offer) {
  const time = offer.accepted_at || offer.rejected_at || offer.withdrawn_at || offer.sent_at || offer.approved_at
  return time ? new Date(time).toLocaleString() : '-'
}

function resetOfferForm() {
  offerForm.salary_amount = null
  offerForm.currency = 'CNY'
  offerForm.note = ''
}

function openOfferDrawer(job: Job, assignment: Assignment) {
  offerAssignment.value = assignment
  offerCandidateName.value = assignment.candidate_name || ''
  offerList.value = []
  addOfferFormVisible.value = false
  resetOfferForm()
  offerDrawerVisible.value = true
  HrApi.getOffers(assignment.id).then((response) => {
    offerList.value = response.data
  })
}

function createOfferRecord() {
  if (!offerAssignment.value) return
  HrApi.createOffer(offerAssignment.value.id, {
    salary_amount: offerForm.salary_amount == null ? null : String(offerForm.salary_amount),
    currency: offerForm.currency || 'CNY',
    note: offerForm.note,
  })
    .then(() => {
      MsgSuccess('Offer 已创建')
      addOfferFormVisible.value = false
      resetOfferForm()
      reloadOffers()
    })
    .catch(() => {})
}

function reloadOffers() {
  if (offerAssignment.value) {
    HrApi.getOffers(offerAssignment.value.id).then((response) => {
      offerList.value = response.data
    })
  }
}

function openApproveOfferDialog(offer: Offer) {
  approveTarget.value = offer
  approveForm.approval_status = 'APPROVED'
  approveOfferDialogVisible.value = true
}

function approveOfferRecord() {
  if (!approveTarget.value) return
  HrApi.approveOffer(approveTarget.value.id, { approval_status: approveForm.approval_status })
    .then(() => {
      MsgSuccess('审批已提交')
      approveOfferDialogVisible.value = false
      reloadOffers()
    })
    .catch(() => {})
}

function sendOfferRecord(offer: Offer) {
  HrApi.sendOffer(offer.id)
    .then(() => {
      MsgSuccess('Offer 已发送')
      reloadOffers()
    })
    .catch(() => {})
}

function acceptOfferRecord(offer: Offer) {
  MsgConfirm('接受 Offer', '确认接受第 ' + offer.version + ' 版 Offer？指派将自动进入「已入职」，并触发入职交接。', { confirmButtonClass: 'danger' })
    .then(() => HrApi.acceptOffer(offer.id))
    .then(() => {
      MsgSuccess('Offer 已接受，已触发入职交接')
      reloadOffers()
      refresh()
    })
    .catch(() => {})
}

function rejectOfferRecord(offer: Offer) {
  MsgConfirm('拒绝 Offer', '确认拒绝第 ' + offer.version + ' 版 Offer？拒绝原因请直接修改该版本备注。', { confirmButtonClass: 'danger' })
    .then(() => HrApi.rejectOffer(offer.id, { note: offer.note }))
    .then(() => {
      MsgSuccess('Offer 已标记拒绝')
      reloadOffers()
    })
    .catch(() => {})
}

function withdrawOfferRecord(offer: Offer) {
  MsgConfirm('撤回 Offer', '确认撤回第 ' + offer.version + ' 版 Offer？', { confirmButtonClass: 'danger' })
    .then(() => HrApi.withdrawOffer(offer.id))
    .then(() => {
      MsgSuccess('Offer 已撤回')
      reloadOffers()
    })
    .catch(() => {})
}

function uploadOfferAttachment(offer: Offer, file: File) {
  HrApi.uploadOfferAttachment(offer.id, file)
    .then(() => {
      MsgSuccess('附件已上传')
      reloadOffers()
    })
    .catch(() => {})
  return false
}

function removeOfferAttachment(offer: Offer) {
  HrApi.deleteOfferAttachment(offer.id)
    .then(() => {
      MsgSuccess('附件已删除')
      reloadOffers()
    })
    .catch(() => {})
}

function downloadOfferAttachment(offer: Offer) {
  HrApi.downloadOfferAttachment(offer.id, offer.attachment_name || 'offer.pdf')
}

onMounted(() => {
  loadMembers()
  loadJobs()
})
</script>

<style scoped>
.hr-page { min-width: 0; }
.gap-12 { gap: 12px; }
.assignment-panel { padding: 12px 32px; }

.kanban-board {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  overflow-x: auto;
  padding-bottom: 4px;
}

.kanban-col {
  flex: 1 1 0;
  min-width: 190px;
  max-width: 250px;
  background: var(--el-fill-color-light);
  border-radius: 8px;
  padding: 8px;
  display: flex;
  flex-direction: column;
  max-height: 520px;

  &--readonly {
    background: var(--el-fill-color-lighter);
  }
}

.kanban-col__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 2px 6px 10px;
  font-size: 13px;
}

.kanban-col__title {
  font-weight: 600;
}

.kanban-col__body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow-y: auto;
  min-height: 48px;
  flex: 1;
  padding-bottom: 4px;
}

.kanban-card {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 8px 10px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  transition: border-color 0.15s;

  &:hover {
    border-color: var(--el-color-primary-light-5);
  }

  &--ghost {
    opacity: 0.4;
  }
}

.kanban-card__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
  gap: 6px;
}

.kanban-card__name {
  font-weight: 600;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kanban-card__drag {
  cursor: grab;
  color: var(--el-text-color-placeholder);
  margin-right: 6px;
  flex-shrink: 0;
}

.kanban-card__meta {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.kanban-card__footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}
</style>
