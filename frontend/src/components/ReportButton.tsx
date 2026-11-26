import { Alert, Button, Input, Modal, Typography } from 'antd'
import { useState } from 'react'
import { reportsApi } from '../api/reports'
import { getApiErrorMessage } from '../api/errors'
import type { ReportTarget } from '../api/types'

export function ReportButton({ targetType, targetId }: { targetType: ReportTarget; targetId: string }) {
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)
  const [busy, setBusy] = useState(false)
  const submit = async () => {
    if (reason.trim().length < 5) return
    setBusy(true); setError(null)
    try { await reportsApi.create({ target_type: targetType, target_id: targetId, reason: reason.trim() }); setSuccess(true); setOpen(false); setReason('') } catch (cause) { setError(getApiErrorMessage(cause)) } finally { setBusy(false) }
  }
  return <>
    <Button size="small" disabled={success} onClick={() => { setOpen(true); setError(null) }}>{success ? '举报已提交' : `举报${targetType === 'question' ? '问题' : '回答'}`}</Button>
    <Modal title="举报内容" open={open} confirmLoading={busy} onCancel={() => { if (!busy) setOpen(false) }} onOk={() => void submit()} okText="提交举报" okButtonProps={{ disabled: reason.trim().length < 5 }}>
      <Typography.Paragraph>请说明举报原因（5–500 字），管理员将核查并处理。</Typography.Paragraph>
      {error ? <Alert type="error" message={error} showIcon /> : null}
      <Input.TextArea aria-label="举报原因" value={reason} onChange={(event) => setReason(event.target.value)} maxLength={500} showCount autoSize={{ minRows: 4 }} />
    </Modal>
  </>
}
