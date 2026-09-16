'use client'

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { App, Button, Card, Col, Drawer, Row, Space, Spin, Table, Tag, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import dayjs from 'dayjs'

const BASE = '/api/v1/warehouse'

interface LocationMapItem {
  id: string
  code: string
  name: string
  zone: string
  aisle: string
  location_type: string
  occupied_rows: number
  total_qty: number
}

function occupancyColor(occupied: number): string {
  if (occupied === 0) return '#f5f5f5'
  if (occupied <= 2) return '#d4edda'
  if (occupied <= 5) return '#fff3cd'
  return '#f8d7da'
}

function occupancyLabel(occupied: number): string {
  if (occupied === 0) return '空闲'
  if (occupied <= 2) return '低占用'
  if (occupied <= 5) return '中占用'
  return '高占用'
}

export function LocationMap() {
  const [selectedZone, setSelectedZone] = useState<string | null>(null)
  const [selectedLoc, setSelectedLoc] = useState<LocationMapItem | null>(null)

  const { data: map, isLoading } = useQuery({
    queryKey: ['warehouse', 'locations', 'map'],
    queryFn: async () => {
      const resp = await fetch(`${BASE}/locations/map`)
      const body = await resp.json()
      return body.data as LocationMapItem[]
    },
  })

  if (isLoading || !map) return <Spin />

  const zones = [...new Set(map.map(l => l.zone))].sort()
  const activeZone = selectedZone ?? zones[0] ?? ''
  const zoneItems = map.filter(l => l.zone === activeZone)
  const aisles = [...new Set(zoneItems.map(l => l.aisle))].sort()

  return (
    <div>
      <Space wrap style={{ marginBottom: 12 }}>
        {zones.map(z => (
          <Button
            key={z}
            type={z === activeZone ? 'primary' : 'default'}
            size="small"
            onClick={() => setSelectedZone(z)}
          >
            {z}
          </Button>
        ))}
      </Space>
      <Row gutter={[8, 8]}>
        {aisles.map(aisle => (
          <Col key={aisle} xs={12} md={8} xl={6}>
            <Card size="small" title={aisle}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(64px, 1fr))', gap: 4 }}>
                {zoneItems.filter(l => l.aisle === aisle).map(loc => (
                  <div
                    key={loc.id}
                    onClick={() => setSelectedLoc(loc)}
                    style={{
                      background: occupancyColor(loc.occupied_rows),
                      borderRadius: 4,
                      padding: '4px 2px',
                      textAlign: 'center',
                      cursor: 'pointer',
                      fontSize: 11,
                      border: '1px solid #e5e3de',
                    }}
                  >
                    <div style={{ fontWeight: 600 }}>{loc.code}</div>
                    <div>{loc.total_qty}</div>
                  </div>
                ))}
              </div>
            </Card>
          </Col>
        ))}
      </Row>
      {selectedLoc && (
        <Drawer
          title={`库位 ${selectedLoc.code} ${selectedLoc.name}`}
          open
          width={480}
          onClose={() => setSelectedLoc(null)}
          destroyOnHidden
        >
          <Tag color="blue">{selectedLoc.location_type}</Tag>
          <Tag>{occupancyLabel(selectedLoc.occupied_rows)}</Tag>
          <Typography.Paragraph style={{ marginTop: 8 }}>
            占用行数: {selectedLoc.occupied_rows}，库存数量: {selectedLoc.total_qty}
          </Typography.Paragraph>
          <LocationDetailTable locationId={selectedLoc.id} />
        </Drawer>
      )}
    </div>
  )
}

function LocationDetailTable({ locationId }: { locationId: string }) {
  const { data: res } = useQuery({
    queryKey: ['warehouse', 'stocks', { location: locationId }],
    queryFn: async () => {
      const resp = await fetch(`/api/v1/warehouse/stocks?location_id=${locationId}&page_size=100`)
      const body = await resp.json()
      return body.data as { id: string; material_code: string; material_name: string; batch_no: string; quantity: number; unit: string }[]
    },
  })
  const columns: TableColumnsType<NonNullable<typeof res>[0]> = [
    { title: '物料', dataIndex: 'material_name', ellipsis: true },
    { title: '批次', dataIndex: 'batch_no', width: 80, render: (v: string) => v || '-' },
    { title: '数量', dataIndex: 'quantity', width: 80, align: 'right' },
  ]
  return <Table rowKey="id" size="small" columns={columns} dataSource={res ?? []} pagination={false} />
}
