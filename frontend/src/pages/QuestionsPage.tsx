import { PlusOutlined, SearchOutlined } from '@ant-design/icons'
import { Button, Card, Empty, Input, List, Pagination, Select, Skeleton, Space, Tag, Typography } from 'antd'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuestions, useTags } from '../hooks/useQuestions'
import type { QuestionSort, QuestionStatus } from '../api/questions'

function dateBoundary(value: string, end = false) {
  if (!value) return undefined
  return `${value}T${end ? '23:59:59.999' : '00:00:00'}+08:00`
}

export function QuestionsPage() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [sort, setSort] = useState<QuestionSort>('latest')
  const [search, setSearch] = useState('')
  const [tags, setTags] = useState<string[]>([])
  const [status, setStatus] = useState<QuestionStatus | undefined>()
  const [createdFrom, setCreatedFrom] = useState('')
  const [createdTo, setCreatedTo] = useState('')
  const { data: tagOptions = [], isLoading: tagsLoading } = useTags()
  const { data, isLoading, isError } = useQuestions({
    page,
    pageSize: 10,
    sort,
    q: search.trim() || undefined,
    tag: tags.length ? tags : undefined,
    status,
    created_from: dateBoundary(createdFrom),
    created_to: dateBoundary(createdTo, true),
  })

  const clearFilters = () => {
    setSearch('')
    setTags([])
    setStatus(undefined)
    setCreatedFrom('')
    setCreatedTo('')
    setPage(1)
  }

  return <div className="page-stack">
    <section className="page-intro">
      <div>
        <Typography.Text className="eyebrow">COMMUNITY QUESTIONS</Typography.Text>
        <Typography.Title level={1}>问题广场</Typography.Title>
        <Typography.Paragraph type="secondary">从同学和老师的经验中找到下一步答案。</Typography.Paragraph>
      </div>
      <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/questions/new')}>发布问题</Button>
    </section>
    <Card size="small" bordered={false}>
      <Space wrap>
        <Input allowClear prefix={<SearchOutlined />} placeholder="搜索标题和正文" aria-label="搜索问题" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1) }} />
        <Select mode="multiple" allowClear maxCount={5} maxTagCount="responsive" loading={tagsLoading} aria-label="按标签筛选" placeholder="按标签筛选" value={tags} options={tagOptions.map((tag) => ({ label: tag, value: tag }))} onChange={(value: string[]) => { setTags(value); setPage(1) }} />
        <Select allowClear aria-label="问题状态" placeholder="全部状态" value={status} options={[{ value: 'open', label: '开放' }, { value: 'closed', label: '已关闭' }]} onChange={(value: QuestionStatus | undefined) => { setStatus(value); setPage(1) }} />
        <Input type="date" aria-label="创建时间起始" value={createdFrom} onChange={(event) => { setCreatedFrom(event.target.value); setPage(1) }} />
        <Input type="date" aria-label="创建时间结束" value={createdTo} onChange={(event) => { setCreatedTo(event.target.value); setPage(1) }} />
        <Select aria-label="问题排序" value={sort} options={[{ value: 'latest', label: '最新发布' }, { value: 'votes', label: '票数优先' }]} onChange={(value: QuestionSort) => { setSort(value); setPage(1) }} />
        <Button onClick={clearFilters}>清除筛选</Button>
      </Space>
    </Card>
    <div className="toolbar-row">
      <Typography.Text type="secondary">共 {data?.total ?? 0} 个问题</Typography.Text>
      {search || tags.length || status || createdFrom || createdTo ? <Typography.Text type="secondary">筛选条件由服务端处理</Typography.Text> : null}
    </div>
    {isError ? <Empty description="暂时无法加载问题，请稍后再试" /> : isLoading ? (
      <List className="question-list" dataSource={[1, 2, 3]} renderItem={() => <List.Item><Skeleton active /></List.Item>} />
    ) : data?.items.length ? (
      <List className="question-list" itemLayout="vertical" dataSource={data.items} renderItem={(question) => (
        <List.Item key={question.id}>
          <List.Item.Meta title={<Link className="question-title" to={`/questions/${question.id}`}>{question.title}</Link>} description={<Space wrap><Typography.Text type="secondary">作者：</Typography.Text><Link to={`/users/${question.author_id}`}>{question.author_name}</Link>{question.status === 'closed' ? <Tag>已关闭</Tag> : <Tag color="green">开放</Tag>}</Space>} />
          {question.tags.length ? <Space wrap className="tag-row">{question.tags.map((tag) => <Tag color="blue" key={tag}>{tag}</Tag>)}</Space> : null}
          <Typography.Text className="question-meta" type="secondary">发布时间：{new Date(question.created_at).toLocaleDateString('zh-CN')}</Typography.Text>
        </List.Item>
      )} />
    ) : (
      <Empty description="没有匹配的问题，请调整筛选条件">
        {!search && !tags.length && !status && !createdFrom && !createdTo ? <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/questions/new')}>发布问题</Button> : null}
      </Empty>
    )}
    {data && data.total_pages > 1 ? <Pagination current={data.page} pageSize={data.page_size} total={data.total} showSizeChanger={false} onChange={(nextPage) => { setPage(nextPage); window.scrollTo({ top: 0, behavior: 'smooth' }) }} /> : null}
  </div>
}
