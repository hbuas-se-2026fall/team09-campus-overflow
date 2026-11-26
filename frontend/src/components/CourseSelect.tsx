import { useInfiniteQuery } from '@tanstack/react-query'
import { Button, Select, Space, Typography } from 'antd'
import { useState } from 'react'
import { coursesApi } from '../api/courses'

export function CourseSelect({ value, onChange, id, label = '关联课程', currentName }: { value?: string | null; onChange?: (value: string | undefined) => void; id?: string; label?: string; currentName?: string | null }) {
  const [opened, setOpened] = useState(false)
  const courses = useInfiniteQuery({
    queryKey: ['courses', 'options'], queryFn: ({ pageParam }) => coursesApi.list({ page: pageParam, page_size: 50 }),
    initialPageParam: 1, getNextPageParam: (last) => last.page < last.total_pages ? last.page + 1 : undefined,
    enabled: opened, staleTime: 60_000,
  })
  const options = courses.data?.pages.flatMap((page) => page.items.map((course) => ({ value: course.id, label: `${course.code} · ${course.name}（${course.semester}）` }))) ?? []
  if (value && !options.some((option) => option.value === value)) options.push({ value, label: currentName ?? value })
  return <Select id={id} aria-label={label} allowClear showSearch optionFilterProp="label" placeholder="不关联课程" value={value ?? undefined} options={options} loading={courses.isFetching} style={{ minWidth: 220, maxWidth: '100%' }} onOpenChange={(open) => { if (open) setOpened(true) }} onChange={onChange} popupRender={(menu) => <>{menu}<Space style={{ padding: 8 }}>{courses.isError ? <><Typography.Text type="danger">课程加载失败</Typography.Text><Button size="small" onClick={() => void courses.refetch()}>重试</Button></> : courses.hasNextPage ? <Button size="small" loading={courses.isFetchingNextPage} onClick={() => void courses.fetchNextPage()}>加载更多课程</Button> : null}</Space></>} />
}
