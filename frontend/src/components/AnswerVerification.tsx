import { SafetyCertificateOutlined } from '@ant-design/icons'
import { Button, Popconfirm, Space, Tag, Typography } from 'antd'
import type { AnswerResponse } from '../api/types'
import { questionsApi } from '../api/questions'

export function AnswerVerification({ answer, canVerify, closed, busy, runAction }: { answer: AnswerResponse; canVerify: boolean; closed: boolean; busy: boolean; runAction: (action: () => Promise<unknown>) => Promise<boolean> }) {
  return <Space direction="vertical" size="small" className="answer-verification">
    {answer.is_teacher_verified ? <Space wrap><Tag color="cyan" icon={<SafetyCertificateOutlined />}>教职认证</Tag><Typography.Text type="secondary">认证人：{answer.verified_by_name ?? '认证人员'}{answer.verified_at ? ` · ${new Date(answer.verified_at).toLocaleString('zh-CN')}` : ''}</Typography.Text></Space> : null}
    {canVerify && !closed ? <Popconfirm title={answer.is_teacher_verified ? '确认取消这个回答的认证？' : '确认认证这个回答？'} okText="确认" cancelText="取消" disabled={busy} onConfirm={() => void runAction(() => answer.is_teacher_verified ? questionsApi.unverifyAnswer(answer.id) : questionsApi.verifyAnswer(answer.id))}>
      <Button size="small" disabled={busy} icon={<SafetyCertificateOutlined />}>{answer.is_teacher_verified ? '取消认证' : '认证回答'}</Button>
    </Popconfirm> : null}
  </Space>
}
