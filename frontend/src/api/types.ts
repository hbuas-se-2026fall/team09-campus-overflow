export type UserRole = 'student' | 'teacher'

export type TokenPair = {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

export type RegisterRequest = {
  role: UserRole
  email: string
  password: string
  student_id?: string
  staff_id?: string
}

export type AuthUserResponse = {
  id: string
  role: UserRole
  email: string
  student_id: string | null
  staff_id: string | null
  nickname?: string | null
  college?: string | null
  class_name?: string | null
  email_verified?: boolean
  created_at: string
}

export type LoginRequest = {
  identifier: string
  password: string
}

export type CommentResponse = {
  id: string
  body: string
  author_id: string
  author_name: string
  created_at: string
}

export type AnswerResponse = {
  id: string
  body: string
  author_id: string
  author_name: string
  created_at: string
  votes: number
  is_accepted: boolean
  comments: CommentResponse[]
}

export type ReputationEntryResponse = {
  source: string
  event_id: string
  delta: number
  reason: string
  occurred_at: string
}

export type ReputationResponse = {
  user_id: string
  total: number
  entries: ReputationEntryResponse[]
}

export type PublicUserProfileResponse = {
  user_id: string
  role: UserRole | string
  display_name: string
  nickname: string | null
  college: string | null
  class_name: string | null
}

export type BadgeResponse = {
  code: string
  kind: string
  tier: string
  threshold: number
}

export type UserBadgesResponse = {
  user_id: string
  answer_count: number
  accepted_count: number
  acceptance_rate: number
  longest_streak_days: number
  badges: BadgeResponse[]
}

export type PointEntryResponse = {
  source: string
  event_id: string
  delta: number
  reason: string
  occurred_at: string
}

export type MyPointsResponse = {
  balance: number
  entries: PointEntryResponse[]
}

export type NotificationResponse = {
  id: string
  type: string
  actor_id: string
  actor_name: string
  target_type: string
  target_id: string
  question_id: string | null
  is_read: boolean
  created_at: string
}

export type NotificationListResponse = {
  items: NotificationResponse[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export type LeaderboardPeriod = 'week' | 'month' | 'semester'

export type LeaderboardEntryResponse = {
  user_id: string
  display_name: string
  score: number
  rank: number
}

export type LeaderboardResponse = {
  period: LeaderboardPeriod
  period_start: string
  period_end: string
  entries: LeaderboardEntryResponse[]
}

export type BountyResponse = {
  id: string
  question_id: string
  teacher_id: string
  amount: number
  status: string
  created_at: string
  settled_at: string | null
}

