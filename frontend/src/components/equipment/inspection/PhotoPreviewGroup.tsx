'use client'

import { Image, Button } from 'antd'
import { DeleteOutlined } from '@ant-design/icons'

interface PhotoPreviewGroupProps {
  photos: File[]
  onRemove?: (index: number) => void
  size?: number
  editable?: boolean
}

export function PhotoPreviewGroup({
  photos,
  onRemove,
  size = 80,
  editable = false,
}: PhotoPreviewGroupProps) {
  if (photos.length === 0) return null

  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
      {photos.map((file, idx) => (
        <div
          key={idx}
          style={{
            position: 'relative',
            width: size,
            height: size,
            borderRadius: 8,
            overflow: 'hidden',
            border: '1px solid #e5e3df',
          }}
        >
          <Image
            src={URL.createObjectURL(file)}
            alt={`照片 ${idx + 1}`}
            width={size}
            height={size}
            style={{ objectFit: 'cover' }}
            preview={{ mask: '查看' }}
          />
          {editable && onRemove && (
            <Button
              size="small"
              danger
              type="text"
              onClick={() => onRemove(idx)}
              style={{
                position: 'absolute',
                top: 0,
                right: 0,
                padding: '2px 4px',
                minWidth: 'auto',
                fontSize: 10,
                background: 'rgba(255,255,255,0.9)',
              }}
            >
              <DeleteOutlined />
            </Button>
          )}
        </div>
      ))}
    </div>
  )
}
