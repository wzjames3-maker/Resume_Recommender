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

export interface Interview {
  id: string
  assignment_id: string
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
  assignment_id: string
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
  assignment_id: string
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

export interface JobDetail extends Job {
  assignments: Assignment[]
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
  error_message: string
}

export interface HrConfig {
  llm_model_id: string | null
}

export interface ResumeBatchStatus {
  resume_id: string
  file_name: string
  status: 'PENDING' | 'SUCCESS' | 'FAILED'
  candidate_id: string | null
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

export interface HrAuditLogPage extends PageResult<HrAuditLog> {}

export interface HrAccessSetItem {
  user_id: string
  role: HrRole | null
}
