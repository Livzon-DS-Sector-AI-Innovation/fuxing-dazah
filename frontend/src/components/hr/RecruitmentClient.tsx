'use client'

import { useState, useCallback, useEffect } from 'react'
import { App, Button, Radio, Input, Tabs } from 'antd'
import {
  SearchOutlined,
  AppstoreOutlined,
  UnorderedListOutlined,
  PlusOutlined } from '@ant-design/icons'
import { Candidate } from '@/types/hr'
import { fetchCandidates } from '@/lib/api/hr'
import { deleteCandidateAction } from '@/actions/hr'
import CandidateListView from './CandidateListView'
import CandidateCardView from './CandidateCardView'
import CreateCandidateModal from './CreateCandidateModal'

interface RecruitmentClientProps {
  initialCandidates: Candidate[]
  initialTotal: number
}

export default function RecruitmentClient({
  initialCandidates,
  initialTotal }: RecruitmentClientProps) {
  const { message } = App.useApp()
  const [viewMode, setViewMode] = useState<'list' | 'card'>('list')
  const [candidates, setCandidates] = useState<Candidate[]>(initialCandidates)
  const [total, setTotal] = useState(initialTotal)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [loading, setLoading] = useState(false)
  const [searchKeyword, setSearchKeyword] = useState('')
  const [activeTab, setActiveTab] = useState<'all' | 'recommended'>('all')
  const [modalOpen, setModalOpen] = useState(false)

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchCandidates({
        keyword: searchKeyword || undefined,
        recommendation_level: activeTab === 'recommended' ? '推荐,强烈推荐' : undefined,
        page,
        page_size: pageSize })
      setCandidates(res.data)
      setTotal(res.meta?.total || 0)
    } catch (err: any) {
      message.error(err.message || '加载数据失败')
    } finally {
      setLoading(false)
    }
  }, [searchKeyword, activeTab, page, pageSize])

  const handlePageChange = (newPage: number, newPageSize: number) => {
    setPage(newPage)
    setPageSize(newPageSize)
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteCandidateAction(id)
      message.success('删除成功')
      loadData()
    } catch (err: any) {
      message.error(err.message || '删除失败')
    }
  }

  useEffect(() => {
    loadData()
  }, [searchKeyword, activeTab, page, pageSize])

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-[22px] font-semibold text-[var(--color-charcoal)]">
          候选人筛选
        </h1>
        <div className="flex gap-3">
          <Radio.Group
            value={viewMode}
            onChange={(e) => setViewMode(e.target.value)}
            optionType="button"
            buttonStyle="solid"
          >
            <Radio.Button value="list">
              <UnorderedListOutlined /> 列表
            </Radio.Button>
            <Radio.Button value="card">
              <AppstoreOutlined /> 卡片
            </Radio.Button>
          </Radio.Group>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setModalOpen(true)}
          >
            新建候选人
          </Button>
        </div>
      </div>

      <Tabs
        activeKey={activeTab}
        onChange={(key) => {
          setActiveTab(key as 'all' | 'recommended')
          setPage(1)
        }}
        items={[
          {
            key: 'all',
            label: '全部候选',
            children: null },
          {
            key: 'recommended',
            label: '推荐候选',
            children: null },
        ]}
      />

      <div className="flex flex-wrap gap-3 items-center">
        <Input
          placeholder="搜索姓名或职位"
          value={searchKeyword}
          onChange={(e) => setSearchKeyword(e.target.value)}
          prefix={<SearchOutlined />}
          className="w-64"
          allowClear
        />
      </div>

      {viewMode === 'list' ? (
        <CandidateListView
          candidates={candidates}
          total={total}
          page={page}
          pageSize={pageSize}
          loading={loading}
          onPageChange={handlePageChange}
          onDelete={handleDelete}
        />
      ) : (
        <CandidateCardView
          candidates={candidates}
          total={total}
          page={page}
          pageSize={pageSize}
          loading={loading}
          onPageChange={handlePageChange}
          onDelete={handleDelete}
        />
      )}

      <CreateCandidateModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSuccess={() => {
          setModalOpen(false)
          loadData()
        }}
      />
    </div>
  )
}
