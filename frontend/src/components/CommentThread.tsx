import { useState } from 'react'
import { Button, Input, Space, Typography } from 'antd'
import { Link } from 'react-router-dom'
import type { CommentResponse } from '../api/types'

export function CommentThread({ comments, canReply, busy, onReply }: { comments: CommentResponse[]; canReply: boolean; busy: boolean; onReply: (body: string, parentId: string) => Promise<boolean> }) {
  const [parentId, setParentId] = useState<string | null>(null)
  const [body, setBody] = useState('')
  const roots = comments.filter((comment) => !comment.parent_id)
  return <Space direction="vertical" size="middle" style={{ width: '100%' }}>
    {!comments.length ? <Typography.Text type="secondary">暂无评论</Typography.Text> : null}
    {roots.map((root) => <div key={root.id} className="comment-thread">
      <Typography.Paragraph className="comment-body">{root.body}</Typography.Paragraph>
      <Space wrap><Link to={`/users/${root.author_id}`}>{root.author_name}</Link><Typography.Text type="secondary">{new Date(root.created_at).toLocaleString('zh-CN')}</Typography.Text>{canReply ? <Button type="link" size="small" disabled={busy} onClick={() => { setParentId(root.id); setBody('') }}>回复</Button> : null}</Space>
      {comments.filter((comment) => comment.parent_id === root.id).map((reply) => <div key={reply.id} className="comment-reply"><Typography.Paragraph className="comment-body">{reply.body}</Typography.Paragraph><Space wrap><Link to={`/users/${reply.author_id}`}>{reply.author_name}</Link><Typography.Text type="secondary">{new Date(reply.created_at).toLocaleString('zh-CN')}</Typography.Text></Space></div>)}
      {canReply && parentId === root.id ? <Space.Compact className="comment-form"><Input aria-label="回复内容" maxLength={5000} value={body} placeholder={`回复 ${root.author_name}`} onChange={(event) => setBody(event.target.value)} /><Button disabled={busy || !body.trim()} onClick={async () => { if (await onReply(body.trim(), root.id)) { setBody(''); setParentId(null) } }}>发送回复</Button><Button onClick={() => setParentId(null)}>取消</Button></Space.Compact> : null}
    </div>)}
  </Space>
}
