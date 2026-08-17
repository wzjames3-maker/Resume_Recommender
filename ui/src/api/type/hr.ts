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

export interface Candidate {
  id: string
  name: string
  email: string | null
  phone: string
  current_city: string
  target_city: string
  highest_degree: string
  years_experience: number | null
  skills: string[]
  source: string
  source_type: ResumeChannel
  source_detail: string
  collected_at: string | null
  consent_status: ConsentStatus
  consent_version: string
  contact_preference: ContactPreference
  note: string
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
  current_city: string
  target_city: string
  years_experience: number | null
  skills: string[]
  match_score: number
  matched_skills: string[]
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

export interface ResumeFile {
  id: string
  file_name: string
  extension: string
  file_size: number
  sha256: string
  source_channel: ResumeChannel
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
}

export type ResumeSearchMode = 'auto' | 'hybrid' | 'dense' | 'phrase' | 'skills'

export interface ResumeSearchCandidate {
  id: string
  name: string
  phone: string
  email: string | null
  highest_degree: string
  years_experience: number | null
  years_unknown?: boolean
  skills: string[]
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
}

export interface DuplicateCheckCandidate {
  id: string
  name: string
  phone: string
  email: string | null
  current_city: string
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
  | 'ACCESS_DENIED'

export type HrAuditObjectType = 'CANDIDATE' | 'JOB' | 'ASSIGNMENT' | 'RESUME' | 'HR_ACCESS' | 'OTHER'
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
