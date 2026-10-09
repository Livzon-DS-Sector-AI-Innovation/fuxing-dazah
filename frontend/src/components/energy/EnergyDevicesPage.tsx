'use client'

import { useEffect, useState } from 'react'
import { Button, Empty, Input, Select } from 'antd'
import { PlusOutlined, ReloadOutlined, SearchOutlined, UndoOutlined } from '@ant-design/icons'
import { getEnabledTypeConfigs, getEnergyDevices } from '@/actions/energy'
import { usePagedList } from '@/lib/energy/usePagedList'
import { useEnergyStore } from '@/stores/energy'
import type { EnergyDeviceConfig, EnergyTypeMeta, PaginatedResponse } from '@/types/energy'
import { PageHeading } from '@/components/shared/PageHeading'
import { DeviceDrawer } from './DeviceDrawer'
import { DeviceTable } from './DeviceTable'
import { EnergyPageFrame } from './EnergyPageFrame'
import styles from './ConfigPages.module.css'

const emptyResponse: PaginatedResponse<EnergyDeviceConfig> = { items: [], total: 0, page: 1, page_size: 10 }

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : '请稍后重试'
}

export function EnergyDevicesPage() {
  const { deviceFilters, setDeviceFilters, resetDeviceFilters, openDeviceDrawer } = useEnergyStore()
  const [typeMetadata, setTypeMetadata] = useState<EnergyTypeMeta[]>([])

  const devicesQuery = usePagedList(['energy', 'devices', deviceFilters], () => getEnergyDevices(deviceFilters), { errorMessage: '获取数据源列表失败' })
  const data = devicesQuery.data ?? emptyResponse
  const loading = devicesQuery.isFetching
  const loadError = devicesQuery.isError ? getErrorMessage(devicesQuery.error) : null
  const fetchData = () => void devicesQuery.refetch()

  useEffect(() => {
    let active = true
    // getEnabledTypeConfigs 已经返回 EnergyTypeMeta[]，无需再逐字段投影一次。
    void getEnabledTypeConfigs().then((configs) => { if (active) setTypeMetadata(configs) }).catch(() => undefined)
    return () => { active = false }
  }, [])

  const hasFilters = Boolean(deviceFilters.keyword || deviceFilters.energy_type || deviceFilters.is_enabled !== undefined)
  const resetFilters = () => resetDeviceFilters()

  return (
    <EnergyPageFrame>
      <PageHeading
        title="数据源配置"
        subtitle="管理能源数据采集来源、平台连接与部门归属。"
        actions={<Button type="primary" icon={<PlusOutlined />} onClick={() => openDeviceDrawer('create')}>新增数据源</Button>}
      />

      <section className={styles.toolbar} aria-label="数据源筛选">
        <Input
          className={styles.filterControl}
          placeholder="搜索数据源名称"
          prefix={<SearchOutlined />}
          value={deviceFilters.keyword}
          allowClear
          onChange={(event) => setDeviceFilters({ keyword: event.target.value || undefined, page: 1 })}
        />
        <Select
          className={styles.filterSelect}
          placeholder="能源类型"
          value={deviceFilters.energy_type}
          allowClear
          onChange={(energy_type) => setDeviceFilters({ energy_type, page: 1 })}
          options={typeMetadata.map((type) => ({ label: type.display_name, value: type.type_code }))}
        />
        <Select
          className={styles.filterSelect}
          placeholder="运行状态"
          value={deviceFilters.is_enabled}
          allowClear
          onChange={(is_enabled) => setDeviceFilters({ is_enabled, page: 1 })}
          options={[{ label: '启用', value: true }, { label: '已停用', value: false }]}
        />
        {hasFilters && <Button className={styles.resetButton} type="text" icon={<UndoOutlined />} onClick={resetFilters}>重置筛选</Button>}
        <span className={styles.toolbarMeta}>{loading ? '正在更新…' : `共 ${data.total} 个数据源`}</span>
        <div className={styles.toolbarActions}>
          <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void fetchData()}>刷新</Button>
        </div>
      </section>

      <section className={styles.tableCard} aria-live="polite">
        {loadError && data.items.length === 0 ? (
          <div className={styles.empty}><Empty description={`加载失败：${loadError}`}><Button onClick={() => void fetchData()}>重新加载</Button></Empty></div>
        ) : !loading && data.items.length === 0 ? (
          <div className={styles.empty}><Empty description={hasFilters ? '没有符合当前筛选条件的数据源' : '暂未配置数据源'}><Button type="primary" icon={<PlusOutlined />} onClick={() => openDeviceDrawer('create')}>新增数据源</Button></Empty></div>
        ) : (
          <DeviceTable data={data.items} loading={loading} total={data.total} onRefresh={fetchData} typeMetadata={typeMetadata} />
        )}
      </section>

      <DeviceDrawer onRefresh={fetchData} />
    </EnergyPageFrame>
  )
}
