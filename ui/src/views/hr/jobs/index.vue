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
                      v-for="col in pipelineColumnsFor(row.id)"
                      :key="col.id"
                      class="kanban-col"
                      :class="['kanban-col--' + col.type, { 'kanban-col--readonly': col.readonly }]"
                    >
                      <div class="kanban-col__header">
                        <span class="kanban-col__title">{{ col.label }}</span>
                        <el-tag size="small" round :type="col.readonly ? 'info' : 'primary'" effect="plain">
                          {{ (boardState[row.id][col.id] || []).length }}
                        </el-tag>
                      </div>
                      <VueDraggable
                        v-model="boardState[row.id][col.id]"
                        :group="{ name: 'application-board', pull: !col.readonly, put: !col.readonly }"
                        :sort="false"
                        :animation="150"
                        handle=".kanban-card__drag"
                        ghost-class="kanban-card--ghost"
                        class="kanban-col__body"
                        :data-col-id="col.id"
                        :data-stage-id="col.stageId || ''"
                        :data-order="col.order"
                        @add="onBoardDrop(row, $event)"
                      >
                        <template v-for="application in boardState[row.id][col.id] || []" :key="application.application_id">
                          <div class="kanban-card" :data-id="application.application_id">
                            <div class="kanban-card__header">
                              <div class="flex align-center">
                                <el-icon v-if="!col.readonly" class="kanban-card__drag"><rank /></el-icon>
                                <span class="kanban-card__name">{{ application.candidate_name || '-' }}</span>
                              </div>
                              <div class="flex align-center gap-6">
                                <el-tag v-if="application.reapply_no > 0" size="small" type="warning" effect="plain">重投</el-tag>
                                <el-tag v-if="applicationStatusLabels[application.status] && application.status !== 'ACTIVE'" size="small" :type="applicationStatusTagType(application.status)" effect="plain">
                                  {{ applicationStatusLabels[application.status] }}
                                </el-tag>
                              </div>
                            </div>
                            <div class="kanban-card__meta">
                              <el-tag v-if="application.channel" size="small" effect="plain">{{ channelLabels[application.channel] || application.channel }}</el-tag>
                              <el-tag v-if="application.relation_type" size="small" type="info" effect="plain">{{ relationTypeLabels[application.relation_type] || application.relation_type }}</el-tag>
                            </div>
                            <div class="kanban-card__footer">
                              <span class="color-secondary ellipsis">{{ application.owner_id ? memberName(application.owner_id) : '未分配' }}</span>
                              <div class="flex align-center">
                                <el-button v-if="isHrOperator" link type="primary" size="small" @click="openInterviewDrawer(row, application)">面试</el-button>
                                <el-button v-if="isHrAdmin && isOfferStage(application)" link type="primary" size="small" @click="openOfferDrawer(row, application)">Offer</el-button>
                                <el-dropdown
                                  v-if="isHrOperator"
                                  trigger="click"
                                  size="small"
                                  @click.stop
                                  @command="(cmd: string) => onCardCommand(cmd, row, application)"
                                >
                                  <el-button link size="small" @click.stop>更多</el-button>
                                  <template #dropdown>
                                    <el-dropdown-menu>
                                      <el-dropdown-item v-if="isActiveApplication(application)" command="reject">淘汰</el-dropdown-item>
                                      <el-dropdown-item v-if="isActiveApplication(application)" command="withdraw">候选人退出</el-dropdown-item>
                                      <el-dropdown-item v-if="isActiveApplication(application)" command="close">关闭申请</el-dropdown-item>
                                      <el-dropdown-item v-if="isHrAdmin && application.status === 'REJECTED'" command="restore" divided>恢复申请</el-dropdown-item>
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
        <span>{{ interviewCandidateName }} · 申请 {{ interviewAssignment?.application_id?.slice(0, 8) }}</span>
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
        <span>{{ offerCandidateName }} · {{ offerJobName }}</span>
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

    <el-dialog v-model="closeDialogVisible" title="关闭职位" width="460px">
      <el-form label-width="96px">
        <el-form-item label="职位"><span>{{ closingJob?.name }}</span></el-form-item>
        <el-form-item label="在途申请">
          <el-tag :type="(closePreview?.active_application_count || 0) > 0 ? 'warning' : 'success'">{{ closePreview?.active_application_count || 0 }}</el-tag>
          <span class="ml-8 color-secondary">关闭后逐条写 CLOSED 事件，并自动撤回该申请下 DRAFT/SENT Offer</span>
        </el-form-item>
        <el-form-item v-if="closeMode === 'BULK'" label="批量确认">
          <el-checkbox v-model="bulkConfirmed">确认批量关闭 {{ closePreview?.active_application_count || 0 }} 条在途申请</el-checkbox>
        </el-form-item>
        <el-form-item label="关闭原因" required>
          <el-select v-model="closeReason" placeholder="选择关闭原因" style="width: 100%">
            <el-option v-for="(label, value) in jobCloseReasonLabels" :key="value" :label="label" :value="value" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="closeDialogVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!closeReason || hasActiveApplications && !bulkConfirmed" :loading="saving" @click="confirmCloseJob">确认关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="backwardDialogVisible" title="阶段回退 / 同阶段移动" width="440px">
      <el-form label-width="96px">
        <el-form-item label="候选人"><span>{{ backwardTarget?.candidate_name }}</span></el-form-item>
        <el-form-item label="目标阶段"><span>{{ backwardTarget?.target_stage_name }}</span></el-form-item>
        <el-form-item label="原因" required>
          <el-input v-model="backwardReason" placeholder="回退/同阶段移动必须填写原因（仅负责人或管理员可操作）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="backwardDialogVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!backwardReason.trim()" :loading="saving" @click="confirmBackwardMove">确认</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="statusDialogVisible" :title="isRestoreTransition ? '恢复申请' : '终止申请'" width="440px">
      <el-form label-width="96px">
        <el-form-item label="候选人"><span>{{ statusDialogAssignment?.candidate_name }}</span></el-form-item>
        <el-form-item v-if="!isRestoreTransition" label="操作"><span>{{ applicationActionLabels[statusDialogAction] || statusDialogAction }}</span></el-form-item>
        <el-form-item v-if="isRestoreTransition" label="恢复原因" required>
          <el-input v-model="statusDialogNote" placeholder="填写误淘汰恢复原因" />
        </el-form-item>
        <el-form-item v-else label="终止原因" required>
          <el-select v-model="statusDialogReason" placeholder="选择终止原因" style="width: 100%">
            <el-option v-for="reason in terminalReasonOptionsFor(statusDialogAction)" :key="reason" :label="terminationReasonLabels[reason]" :value="reason" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="statusDialogVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!isRestoreTransition && !statusDialogReason" :loading="saving" @click="confirmStatusChange">确认</el-button>
      </template>
    </el-dialog>

    <AiSettingDialog v-model="aiSettingVisible" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { VueDraggable } from 'vue-draggable-plus'
import AppTable from '@/components/app-table/index.vue'
import AiSettingDialog from '@/views/hr/components/AiSettingDialog.vue'
import HrApi from '@/api/hr/recruitment'
import AuthorizationApi from '@/api/system/resource-authorization'
import {
  applicationActionLabels,
  applicationStatusLabels,
  applicationStatusTagType,
  applicationTerminalReasonOptions,
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
  Interview,
  Job,
  JobApplication,
  JobClosePreview,
  JobCloseReason,
  JobDetail,
  JobMatchCandidate,
  JobMatchPage,
  JobStage,
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

interface BoardColumn {
  id: string
  label: string
  readonly: boolean
  stageId: string | null
  order: number
  type: string
}

type ApplicationAction = 'reject' | 'withdraw' | 'close' | 'restore'

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
const detailLoading = ref('')
const expandTab = reactive<Record<string, string>>({})

// ---------- 动态 Pipeline 看板（R4：读取 JobStage，Application 卡片按 current_stage 分列） ----------
const stages = reactive<Record<string, JobStage[]>>({})
const boardColumns = reactive<Record<string, BoardColumn[]>>({})
const boardState = reactive<Record<string, Record<string, JobApplication[]>>>({})

const HIRED_COL = '__hired__'
const TERMINAL_COL = '__terminal__'

function buildColumns(jobId: string) {
  const cols: BoardColumn[] = (stages[jobId] || []).map((stage) => ({
    id: stage.id,
    label: stage.name,
    readonly: false,
    stageId: stage.id,
    order: stage.order,
    type: 'stage',
  }))
  cols.push({ id: HIRED_COL, label: '已入职', readonly: true, stageId: null, order: 999, type: 'terminal' })
  cols.push({ id: TERMINAL_COL, label: '已结束', readonly: true, stageId: null, order: 1000, type: 'terminal' })
  boardColumns[jobId] = cols
}

function pipelineColumnsFor(jobId: string): BoardColumn[] {
  if (!boardColumns[jobId] && stages[jobId]) buildColumns(jobId)
  return boardColumns[jobId] || []
}

function resetBoard(jobId: string) {
  const next: Record<string, JobApplication[]> = {}
  pipelineColumnsFor(jobId).forEach((col) => { next[col.id] = [] })
  boardState[jobId] = next
}

function syncBoard(jobId: string) {
  if (!stages[jobId] || stages[jobId].length === 0 || !boardColumns[jobId]) return
  resetBoard(jobId)
  const applications = jobDetails[jobId]?.applications || []
  const firstStageId = stages[jobId][0].id
  for (const application of applications) {
    if (application.status === 'HIRED') {
      boardState[jobId][HIRED_COL].push(application)
    } else if (application.status !== 'ACTIVE') {
      boardState[jobId][TERMINAL_COL].push(application)
    } else {
      const sid = application.current_stage?.id
      if (sid && boardState[jobId][sid]) boardState[jobId][sid].push(application)
      else boardState[jobId][firstStageId]?.push(application)
    }
  }
}

watch(
  jobDetails,
  () => { Object.keys(jobDetails).forEach((jobId) => syncBoard(jobId)) },
  { deep: true },
)

const jobDialogVisible = ref(false)
const aiSettingVisible = ref(false)
const editingJob = ref<Job | null>(null)
const jobSkillsText = ref('')
const extractingSkills = ref(false)
const jobForm = reactive({
  name: '', department: '', city: '', level: '', headcount: 1, description: '',
  status: 'OPEN' as JobStatus, close_reason: null as JobCloseReason | null, owner_id: null as string | null,
})
const isHrAdmin = computed(() => user.getHrRole() === 'ADMIN')
const isHrOperator = computed(() => user.getHrRole() === 'OPERATOR' || user.getHrRole() === 'ADMIN')
const interviewDrawerVisible = ref(false)
const interviewList = ref<Interview[]>([])
const interviewAssignment = ref<JobApplication | null>(null)
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
const closePreview = ref<JobClosePreview | null>(null)
const closeMode = ref<'STRICT' | 'BULK'>('STRICT')
const bulkConfirmed = ref(false)
const closeReason = ref('')

const hasActiveApplications = computed(() => (closePreview.value?.active_application_count || 0) > 0)

const statusDialogVisible = ref(false)
const statusDialogAssignment = ref<JobApplication | null>(null)
const statusDialogJob = ref<Job | null>(null)
const statusDialogAction = ref<ApplicationAction>('reject')
const statusDialogReason = ref<TerminationReason | ''>('')
const statusDialogNote = ref('')
const backwardDialogVisible = ref(false)
const backwardReason = ref('')
const backwardTarget = ref<{ application_id: string; candidate_name: string; target_stage_id: string; target_stage_name: string } | null>(null)
const backwardJob = ref<Job | null>(null)
const { user } = useStore()
const route = useRoute()

const isRestoreTransition = computed(() => statusDialogAction.value === 'restore')

function terminalReasonOptionsFor(action: ApplicationAction): string[] {
  return applicationTerminalReasonOptions[action] || []
}

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
    if (!stages[job.id]) {
      return HrApi.getJobStages(job.id).then((stageResponse) => {
        stages[job.id] = stageResponse.data
        buildColumns(job.id)
        syncBoard(job.id)
        return response.data
      })
    }
    syncBoard(job.id)
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
  if (editingJob.value && jobForm.status === 'CLOSED' && editingJob.value.status !== 'CLOSED') {
    // R2 两阶段关闭：先预览 STRICT/BULK，由确认窗决定关闭方式
    openCloseDialog(editingJob.value)
    return
  }
  saving.value = true
  const data = {
    ...jobForm,
    skill_requirements: jobSkillsText.value.split(',').map((skill) => skill.trim()).filter(Boolean),
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
  bulkConfirmed.value = false
  closePreview.value = null
  closeDialogVisible.value = true
  HrApi.getJobClosePreview(job.id).then((response) => {
    closePreview.value = response.data
    closeMode.value = response.data.active_application_count > 0 ? 'BULK' : 'STRICT'
  }).catch(() => { closeDialogVisible.value = false })
}

function confirmCloseJob() {
  if (!closingJob.value || !closeReason.value) return
  if (hasActiveApplications.value && !bulkConfirmed.value) {
    MsgError('存在在途申请，请先勾选批量确认')
    return
  }
  saving.value = true
  HrApi.closeJobV2(closingJob.value.id, {
    close_reason: closeReason.value as JobCloseReason,
    mode: closeMode.value,
    bulk_confirmed: bulkConfirmed.value || !hasActiveApplications.value,
  })
    .then((response) => {
      closeDialogVisible.value = false
      MsgSuccess(`职位已关闭，收尾 ${response.data.closed_count} 条在途申请`)
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

/** 看板拖拽落点：调 move-stage 命令；回退/同阶段需 owner/admin + 原因（由弹窗收集） */
function onBoardDrop(job: Job, evt: any) {
  const fromColId: string = evt.from?.dataset?.colId || ''
  const toColId: string = evt.to?.dataset?.colId || ''
  const toStageId: string = evt.to?.dataset?.stageId || ''
  const toOrder = Number(evt.to?.dataset?.order || 0)
  const applicationId: string = evt.item?.dataset?.id || ''
  const application = jobDetails[job.id]?.applications?.find((a) => a.application_id === applicationId)
  if (!applicationId || fromColId === toColId || !toStageId || !application) {
    loadJobDetail(job)
    return
  }
  const fromOrder = application.current_stage?.order ?? 0
  if (fromOrder >= toOrder) {
    const target = (boardColumns[job.id] || []).find((col) => col.id === toColId)
    backwardTarget.value = {
      application_id: applicationId,
      candidate_name: application.candidate_name,
      target_stage_id: toStageId,
      target_stage_name: target?.label || ''
    }
    backwardJob.value = job
    backwardReason.value = ''
    backwardDialogVisible.value = true
    return
  }
  HrApi.moveApplicationStage(applicationId, { to_stage_id: toStageId, reason_text: 'drag' })
    .then(() => { MsgSuccess('阶段已更新'); loadJobDetail(job) })
    .catch(() => loadJobDetail(job))
}

function confirmBackwardMove() {
  const target = backwardTarget.value
  const job = backwardJob.value
  if (!target || !job || !backwardReason.value.trim()) return
  saving.value = true
  HrApi.moveApplicationStage(target.application_id, {
    to_stage_id: target.target_stage_id,
    reason_text: backwardReason.value.trim(),
    idempotency_key: `back-${Date.now()}`
  })
    .then(() => {
      backwardDialogVisible.value = false
      MsgSuccess('阶段已更新')
      loadJobDetail(job)
    })
    .catch(() => {})
    .finally(() => { saving.value = false })
}

function isActiveApplication(application: JobApplication): boolean {
  return application.status === 'ACTIVE'
}

function isOfferStage(application: JobApplication): boolean {
  return application.status === 'ACTIVE' && application.current_stage?.key === 'OFFER'
}

/** 卡片菜单命令：终态走 terminal 命令 API，恢复走 restore 命令 API（不再直接改 status） */
function onCardCommand(cmd: string, job: Job, application: JobApplication) {
  if (cmd === 'reject') openStatusChangeDialog(application, 'reject', job)
  else if (cmd === 'withdraw') openStatusChangeDialog(application, 'withdraw', job)
  else if (cmd === 'close') openStatusChangeDialog(application, 'close', job)
  else if (cmd === 'restore') openStatusChangeDialog(application, 'restore', job)
}

function openStatusChangeDialog(application: JobApplication, action: ApplicationAction, job: Job) {
  statusDialogAssignment.value = application
  statusDialogJob.value = job
  statusDialogAction.value = action
  statusDialogReason.value = ''
  statusDialogNote.value = ''
  statusDialogVisible.value = true
}

function confirmStatusChange() {
  const application = statusDialogAssignment.value
  const job = statusDialogJob.value
  const action = statusDialogAction.value
  if (!application || !job || !action) return
  const applicationId = application.application_id
  if (action === 'restore') {
    if (!statusDialogNote.value.trim()) {
      MsgError('请填写恢复原因')
      return
    }
    saving.value = true
    HrApi.restoreApplication(applicationId, { reason_text: statusDialogNote.value.trim() })
      .then(() => {
        statusDialogVisible.value = false
        MsgSuccess('申请已恢复')
        loadJobDetail(job)
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
  HrApi.terminalApplication(applicationId, { action, termination_reason: statusDialogReason.value })
    .then(() => {
      statusDialogVisible.value = false
      MsgSuccess('操作成功')
      loadJobDetail(job)
    })
    .catch(() => {})
    .finally(() => { saving.value = false })
}

function addMatchToJob(job: Job, match: JobMatchCandidate) {
  HrApi.createApplication(job.id, match.candidate_id)
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

function openInterviewDrawer(job: Job, application: JobApplication) {
  interviewAssignment.value = application
  interviewCandidateName.value = application.candidate_name || ''
  interviewList.value = []
  addInterviewFormVisible.value = false
  resetInterviewForm()
  interviewDrawerVisible.value = true
  HrApi.getInterviewsByApplication(application.application_id).then((response) => {
    interviewList.value = response.data
  })
}

function reloadInterviewsByApplication() {
  const application = interviewAssignment.value
  if (application) {
    HrApi.getInterviewsByApplication(application.application_id).then((response) => {
      interviewList.value = response.data
    })
  }
}

function createInterviewRecord() {
  const application = interviewAssignment.value
  if (!application) return
  HrApi.createInterviewByApplication(application.application_id, { ...interviewForm })
    .then(() => {
      MsgSuccess('面试已安排')
      addInterviewFormVisible.value = false
      resetInterviewForm()
      reloadInterviewsByApplication()
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
const offerAssignment = ref<JobApplication | null>(null)
const offerCandidateName = ref('')
const offerJobName = ref('')
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

function openOfferDrawer(job: Job, application: JobApplication) {
  offerAssignment.value = application
  offerCandidateName.value = application.candidate_name || ''
  offerJobName.value = job.name
  offerList.value = []
  addOfferFormVisible.value = false
  resetOfferForm()
  offerDrawerVisible.value = true
  HrApi.getOffersByApplication(application.application_id).then((response) => {
    offerList.value = response.data
  })
}

function createOfferRecord() {
  const application = offerAssignment.value
  if (!application) return
  HrApi.createOfferByApplication(application.application_id, {
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
  const application = offerAssignment.value
  if (application) {
    HrApi.getOffersByApplication(application.application_id).then((response) => {
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
  MsgConfirm('接受 Offer', '确认接受第 ' + offer.version + ' 版 Offer？申请将自动进入「已入职」，并触发入职交接。', { confirmButtonClass: 'danger' })
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

function openJobFromQuery() {
  if (route.query.new === '1') {
    openJobDialog()
  }
}

onMounted(() => {
  loadMembers()
  loadJobs()
  openJobFromQuery()
})
watch(() => route.query.new, (isNew) => {
  if (isNew === '1') openJobDialog()
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
