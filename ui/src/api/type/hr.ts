export type CandidateStatus = 'ACTIVE' | 'ARCHIVED'
export type JobStatus = 'OPEN' | 'CLOSED'
export type AssignmentStatus = 'PENDING_SCREEN' | 'SCREEN_PASSED' | 'REJECTED' | 'CLOSED'

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
  note: string
  status: CandidateStatus
  create_time: string
  update_time: string
}

export interface Assignment {
  id: string
  candidate_id: string
  candidate_name?: string
  job_id: string
  job_name?: string
  status: AssignmentStatus
  note: string
  create_time: string
  update_time: string
}

export interface CandidateDetail extends Candidate {
  assignments: Assignment[]
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
