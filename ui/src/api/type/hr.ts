export type CandidateStatus = 'ACTIVE' | 'ARCHIVED' | 'DELETED'
export type ConsentStatus = 'UNKNOWN' | 'NOTIFIED' | 'CONSENTED' | 'NOT_REQUIRED'
export type ContactPreference = 'EMAIL' | 'PHONE' | 'NO_CONTACT' | 'UNSPECIFIED'
export type JobStatus = 'DRAFT' | 'OPEN' | 'ON_HOLD' | 'CLOSED'
export type JobCloseReason = 'FILLED' | 'CANCELLED' | 'DUPLICATE' | 'OTHER'
export type AssignmentStatus =
  | 'PENDING_SCREEN'
  | 'SCREEN_PASSED'
  | 'INTERVIEWING'
  | 'OFFER'
  | 'HIRED'
  | 'REJECTED'
  | 'WITHDRAWN'
  | 'CLOSED'
export type RelationType = 'APPLY' | 'SEEK' | 'REFERRAL' | 'HEADHUNTER'
export type TerminationReason =
  | 'NOT_FIT'
  | 'SALARY'
  | 'UNREACHABLE'
  | 'CANDIDATE_WITHDRAW'
  | 'JOB_CLOSED'
  | 'MERGED'
  | 'OTHER'
export type InterviewStatus = 'PENDING' | 'PASSED' | 'FAILED' | 'NO_SHOW' | 'CANCELLED'
export type ApplicationStatus = 'ACTIVE' | 'HIRED' | 'REJECTED' | 'WITHDRAWN' | 'CLOSED'

export interface Interview {
  id: string
  assignment_id: string | null
  application_id: string | null
  round_no: number
  interviewer: string
  interviewer_user_id: string | null
  feedback_deadline: string | null
  feedback_submitted_at: string | null
  scheduled_at: string | null
  status: InterviewStatus
  feedback: string
  create_time: string
  update_time: string
}

export interface MyInterview {
  interview_id: string
  assignment_id: string
  round_no: number
  scheduled_at: string | null
  status: InterviewStatus
  feedback: string
  feedback_deadline: string | null
  feedback_submitted_at: string | null
  is_overdue: boolean
  candidate_name: string
  job_name: string
}

export interface InterviewAdminRecord {
  interview_id: string
  application_id: string | null
  candidate_id: string | null
  candidate_name: string
  job_id: string | null
  job_name: string
  round_no: number
  interviewer: string
  scheduled_at: string | null
  status: InterviewStatus
  is_overdue: boolean
  feedback_deadline: string | null
  feedback_submitted_at: string | null
  feedback: string
  create_time: string
}

export interface InterviewAdminPage {
  total: number
  records: InterviewAdminRecord[]
  current_page: number
  page_size: number
}

export interface Candidate {
  id: string
  name: string
  email: string | null
  phone: string
  status: CandidateStatus
  create_time: string
  update_time: string
  duplicate_ids?: string[]
}

export interface Assignment {
  id: string
  candidate_id: string
  candidate_name?: string
  job_id: string
  job_name?: string
  status: AssignmentStatus
  relation_type: RelationType
  channel: ResumeChannel
  applied_at: string
  owner_id: string | null
  termination_reason: TerminationReason | null
  is_reapply: boolean
  note: string
  create_time: string
  update_time: string
}

export interface CandidateDetail extends Candidate {
  assignments: Assignment[]
}

export type OfferStatus = 'DRAFT' | 'SENT' | 'ACCEPTED' | 'REJECTED' | 'WITHDRAWN'
export type OfferApprovalStatus = 'PENDING' | 'APPROVED' | 'REJECTED'

export interface Offer {
  id: string
  assignment_id: string | null
  application_id: string | null
  candidate_id: string
  job_id: string
  version: number
  status: OfferStatus
  salary_amount: string | null
  currency: string
  approval_status: OfferApprovalStatus
  approver_id: string | null
  approved_at: string | null
  sent_at: string | null
  accepted_at: string | null
  rejected_at: string | null
  withdrawn_at: string | null
  note: string
  attachment_name: string
  create_time: string
  update_time: string
  candidate_name?: string
  job_name?: string
  assignment_status?: AssignmentStatus
}

export interface ImportRecord {
  row_no: number
  name: string
  status: 'created' | 'duplicate' | 'failed'
  reason?: string
  candidate_id?: string
}

export interface ImportReport {
  total: number
  success: number
  failed: number
  duplicates: number
  records: ImportRecord[]
}

export interface HandoffRecord {
  id: string
  assignment_id: string | null
  application_id: string | null
  candidate_id: string
  job_id: string
  offer_id: string
  status: 'PENDING' | 'SUCCESS' | 'FAILED'
  attempts: number
  last_error: string
  handoff_time: string | null
  candidate_name: string
  job_name: string
  department: string
  phone: string
  email: string
  create_time: string
  update_time: string
}

export interface Job {
  id: string
  name: string
  department: string
  city: string
  level: string
  headcount: number
  description: string
  skill_requirements: string[]
  status: JobStatus
  close_reason: JobCloseReason | null
  owner_id: string | null
  active_assignment_count: number
  create_time: string
  update_time: string
}

export interface JobMatchCandidate {
  candidate_id: string
  name: string
  match_score: number
  matched_skills: string[]
  create_time?: string
}

export interface JobMatchPage {
  total: number
  records: JobMatchCandidate[]
}

export interface JobStage {
  id: string
  key: string
  name: string
  color: string
  order: number
  is_system: boolean
}

export interface ApplicationStageRef {
  id: string
  key: string
  name: string
  order: number
}

export interface AgentProposalSummary {
  proposal_id: string
  action: 'ADVANCE' | 'DECLINE' | 'HOLD' | 'DRAFT'
  status: 'PENDING' | 'ACCEPTED' | 'DISMISSED' | 'EXPIRED'
  score: number | null
  create_time: string
}

export interface JobApplication {
  application_id: string
  candidate_id: string
  candidate_name: string
  current_stage: ApplicationStageRef | null
  status: ApplicationStatus
  relation_type: RelationType
  channel: ResumeChannel
  owner_id: string | null
  reapply_no: number
  note: string
  applied_at: string
  update_time: string
  agent?: AgentProposalSummary | null
}

export interface AgentProposalPayload {
  stage_key?: string
  hard_conditions: { requirement: string; field: string; met: boolean; detail: string }[]
  dimensions: {
    name: string
    verdict: string
    evidence: { paragraph_id: string | null; excerpt: string; relevance: number }[]
    confidence: number
  }[]
  concerns: string[]
  clarifying_questions: string[]
  decision: {
    score: number | null
    suggested_action: 'ADVANCE' | 'DECLINE' | 'HOLD'
    hard_met: boolean
    evidence_ok: boolean
    required_dims_ok: boolean
    score_version: string
    dimension_details: { name: string; verdict: string; confidence: number; evidence_strength: number; dimension_score: number; evidence_count: number }[]
    warnings: { name?: string; reason: string }[]
  }
}

export interface AgentProposal {
  id: string
  run_id: string | null
  target_type: string
  target_id: string
  action: 'ADVANCE' | 'DECLINE' | 'HOLD' | 'DRAFT'
  status: 'PENDING' | 'ACCEPTED' | 'DISMISSED' | 'EXPIRED'
  payload: AgentProposalPayload
  decided_by: string | null
  decided_at: string | null
  decision_note: string
  create_time: string
  update_time: string
}

export interface AgentWorkbenchEvidence {
  path: string
  paragraph_id: string | null
  excerpt: string
  relevance: number | null
}

export interface AgentWorkbenchEvidenceDetail {
  paragraph_id: string
  document_id: string
  resume_id: string
  candidate_id: string | null
  file_name: string
  title: string
  position: number
  content: string
}

export interface AgentWorkbenchRun {
  id: string
  workspace_id: string
  agent_type: string
  trigger_type: string
  ref_object_type: string
  ref_object_id: string
  status: 'PENDING' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'SKIPPED'
  input_meta: Record<string, unknown>
  error: string
  llm_model: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  prompt_version: string
  duration_ms: number
  proposal_count: number | null
  create_time: string
  update_time: string
  tool_trace?: Record<string, unknown>[]
  output?: unknown
}

export interface AgentWorkbenchProposal extends AgentProposal {
  run_agent_type?: string | null
  summary: string
  evidence_count: number
  evidence: AgentWorkbenchEvidence[]
}

export interface AgentWorkbenchSummary {
  total_runs: number
  status_counts: Record<string, number>
  total_tokens: number
  total_duration_ms: number
}

export interface AgentWorkbenchPage<T> {
  records: T[]
  total: number
  current_page: number
  page_size: number
  summary?: AgentWorkbenchSummary
}

export interface AgentWorkbenchRunDetail {
  run: AgentWorkbenchRun
  proposals: AgentWorkbenchProposal[]
  evidence: AgentWorkbenchEvidence[]
}

export interface Application {
  id: string
  candidate_id: string
  job_id: string
  candidate_name: string
  job_name: string
  current_stage: ApplicationStageRef | null
  status: ApplicationStatus
  relation_type: RelationType
  channel: ResumeChannel
  channel_detail: string
  applied_at: string
  owner_id: string | null
  recruiter_id: string | null
  termination_reason: TerminationReason | null
  terminated_at: string | null
  reapply_no: number
  note: string
  create_time: string
  update_time: string
}

export interface JDDraftSource {
  kind: 'knowledge' | 'similar_job'
  ref: string
  note: string
}

export interface JDProposalPayload {
  draft_target: 'JOB'
  fields: { name: string; description: string; skill_requirements: string[] }
  summary: string
  sources: JDDraftSource[]
}

export type JDProposal = AgentProposal & { payload: JDProposalPayload }

export interface CopilotQuestion {
  question: string
  target: string
  difficulty: '基础' | '进阶' | '深挖'
  follow_up: string
}

export interface CopilotWeakSpot {
  name: string
  detail: string
  evidence: { paragraph_id: string | null; excerpt: string; relevance: number }[]
}

export interface CopilotPreparePayload {
  phase: 'prepare'
  weak_spots: CopilotWeakSpot[]
  questions: CopilotQuestion[]
  focus: string[]
}

export interface CopilotFeedbackPayload {
  phase: 'feedback'
  evaluation_draft: string
  recommendation_hint: string
  open_items: string[]
}

export type CopilotPayload = CopilotPreparePayload | CopilotFeedbackPayload

export type CopilotProposal = AgentProposal & { payload: CopilotPayload }

export interface SourcingCandidate {
  candidate_id: string
  name: string
  skills: string[]
  match_reason: string
  risk: string
  evidence: { paragraph_id: string | null; excerpt: string; relevance: number }[]
  document_id: string | null
}

export interface SourcingProposalPayload {
  scope: { job_id: string; job_name: string }
  candidates: SourcingCandidate[]
  summary: string
}

export type SourcingProposal = AgentProposal & { payload: SourcingProposalPayload }

export type CommunicationScenario = 'REJECT' | 'PROGRESS' | 'FAQ' | 'OTHER'

export interface CommunicationDraftPayload {
  scenario: CommunicationScenario
  stage_key?: string
  draft: string
  key_points: string[]
  tone: string
  sources: JDDraftSource[]
}

export type CommunicationDraftProposal = AgentProposal & { payload: CommunicationDraftPayload }

export interface AgentStatsBand {
  count: number
  decided: number
  accept_rate: number | null
}

export interface AgentStatsItem {
  agent_type: string
  runs: number
  succeeded: number
  failed: number
  skipped: number
  proposals: Record<string, Record<string, number>>
  proposal_total: number
  decided: number
  accepted: number
  accept_rate: number | null
  score_bands: Record<string, AgentStatsBand>
}

export interface AgentStats {
  by_agent: AgentStatsItem[]
}

export interface JobCloseApplication {
  application_id: string
  candidate_name: string
  current_stage: string
  owner_id: string | null
}

export interface JobClosePreview {
  job_id: string
  job_status: JobStatus
  active_application_count: number
  applications: JobCloseApplication[]
}

export interface JobCloseResult {
  job_id: string
  closed_count: number
  withdrawn_offer_count: number
  closed_assignment_count: number
}

export interface ApplicationEvent {
  id: string
  application_id: string
  event_type: 'CREATED' | 'IMPORTED' | 'STAGE_MOVED' | 'HIRED' | 'REJECTED' | 'WITHDRAWN' | 'CLOSED' | 'RESTORED'
  from_stage_id: string | null
  to_stage_id: string | null
  from_status: string
  to_status: string
  actor_id: string | null
  reason_code: string
  reason_text: string
  create_time: string
}

export interface JobDetail extends Job {
  assignments: Assignment[]
  applications: JobApplication[]
}

export interface PageResult<T> {
  total: number
  records: T[]
}

export type ResumeStatus = 'PENDING' | 'SUCCESS' | 'FAILED'
export type ResumeChannel = 'REFERRAL' | 'JOB_SITE' | 'HEADHUNTER' | 'CAMPUS' | 'OTHER'
export type ResumeDatabaseStatus = 'ACTIVE' | 'ARCHIVED'

export interface ResumeDatabase {
  id: string
  name: string
  description: string
  status: ResumeDatabaseStatus
  is_default: boolean
  is_system: boolean
  resume_count: number
  candidate_count: number
  pending_count: number
  create_time: string
  update_time: string
}

export interface ResumeFile {
  id: string
  file_name: string
  extension: string
  file_size: number
  sha256: string
  source_channel: ResumeChannel
  resume_database_id: string
  resume_database_name: string
  resume_database_ids?: string[]
  resume_database_names?: string[]
  status: ResumeStatus
  error_message: string
  document_id: string | null
  candidate_id: string | null
  create_time: string
  update_time: string
}

export interface ResumeUploadResult {
  resume_id: string
  file_name: string
  resume_database_id: string
  resume_database_name: string
  resume_database_ids?: string[]
  resume_database_names?: string[]
  status: ResumeStatus
  sha256: string
  duplicate: boolean
  candidate_id: string | null
  document_id: string | null
  error_message: string
}

export interface HrConfig {
  llm_model_id: string | null
  rerank_model_id: string | null
  agent_knowledge_bases: string[]
}

export type ResumeSearchMode = 'auto' | 'hybrid' | 'dense' | 'phrase' | 'skills'

export interface ResumeSearchCandidate {
  id: string
  name: string
  phone: string
  email: string | null
  status: string
}

export interface ResumeSearchResume {
  id: string
  file_name: string
  extension: string
}

export interface ResumeSearchParagraph {
  id: string
  title: string
  content: string
  score: number
}

export interface ResumeSearchScore {
  resume?: number
  rerank?: number
  rrf?: number
  dense?: number
  sparse?: number
  hit_vec?: number[]
  hit_count?: number
  name_match?: boolean
  structured?: boolean
}

export interface ResumeSearchItem {
  rank: number
  candidate: ResumeSearchCandidate | null
  resume: ResumeSearchResume | null
  score: ResumeSearchScore
  paragraphs: ResumeSearchParagraph[]
  document_id: string | null
}

export interface ResumeSearchMeta {
  mode: ResumeSearchMode
  search_type: string
  skills?: string[]
  skills_truncated?: boolean
  slots?: Record<string, unknown>
  prefilter?: Record<string, unknown>
  recall?: Record<string, unknown>
  rerank?: Record<string, unknown>
  aggregation?: Record<string, unknown>
  elapsed_ms?: Record<string, number>
  query?: { length: number; truncated: boolean }
  name_matched?: number
  scope?: { applied: boolean; database_count?: number; resume_database_ids?: string[]; document_count?: number; restricted_count?: number }
}

export interface ResumeSearchResponse {
  items: ResumeSearchItem[]
  meta: ResumeSearchMeta
}

export type ResumeFlowLogNode = 'UPLOAD' | 'EXTRACT' | 'SANITIZE' | 'SPLIT' | 'DOCUMENT' | 'LIFECYCLE'

export interface ResumeFlowLog {
  id: string
  node: string
  status: 'SUCCESS' | 'FAILED'
  detail: Record<string, unknown>
  error_message: string
  document_id: string | null
  create_time: string
}

export interface ResumeBatchStatus {
  resume_id: string
  file_name: string
  status: 'PENDING' | 'SUCCESS' | 'FAILED'
  candidate_id: string | null
  document_id: string | null
  error_message: string
}

export interface AiConditions {
  skills: string[]
  city: string | null
  years_min: number | null
  years_max: number | null
  highest_degree: string | null
  status: string | null
  // 0030 后 city/degree/years 仅作 RAG 语义提示，不再作为 Candidate 结构化过滤
}

export interface DuplicateCheckCandidate {
  id: string
  name: string
  phone: string
  email: string | null
}

export type HrRole = 'VIEWER' | 'OPERATOR' | 'ADMIN'

export interface HrAccessMember {
  id: string
  nick_name: string
  roles: string[]
  hr_role: HrRole | null
}

export type HrAuditAction =
  | 'VIEW_DETAIL'
  | 'CREATE'
  | 'UPDATE'
  | 'ARCHIVE'
  | 'RESTORE'
  | 'DELETE'
  | 'JOB_CLOSE'
  | 'JOB_REOPEN'
  | 'ASSIGNMENT_TRANSITION'
  | 'RESUME_UPLOAD'
  | 'RESUME_DOWNLOAD'
  | 'RESUME_DELETE'
  | 'MERGE'
  | 'GRANT_ACCESS'
  | 'REVOKE_ACCESS'
  | 'EXPORT'
  | 'INTERVIEW_FEEDBACK'
  | 'OFFER_SEND'
  | 'OFFER_ACCEPT'
  | 'OFFER_REJECT'
  | 'OFFER_WITHDRAW'
  | 'OFFER_APPROVE'
  | 'HANDOFF'
  | 'IMPORT'
  | 'SEARCH'
  | 'AGENT_RUN'
  | 'AGENT_DECIDE'
  | 'ACCESS_DENIED'

export type HrAuditObjectType =
  | 'CANDIDATE'
  | 'JOB'
  | 'ASSIGNMENT'
  | 'APPLICATION'
  | 'INTERVIEW'
  | 'OFFER'
  | 'ONBOARDING'
  | 'RESUME'
  | 'HR_ACCESS'
  | 'OTHER'
export type HrAuditResult = 'SUCCESS' | 'FAILED' | 'DENIED'

export interface HrAuditLog {
  id: string
  user_id: string
  nick_name: string | null
  action: HrAuditAction
  object_type: HrAuditObjectType
  object_id: string
  result: HrAuditResult
  detail: string
  create_time: string
}

export type HrAuditLogPage = PageResult<HrAuditLog>

export interface HrAccessSetItem {
  user_id: string
  role: HrRole | null
}
