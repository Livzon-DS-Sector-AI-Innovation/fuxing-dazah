'use client'

import { useRef } from 'react'
import { Button } from 'antd'
import { CameraOutlined } from '@ant-design/icons'

interface PhotoUploadButtonProps {
  onFileSelected: (file: File) => void
  disabled?: boolean
  label?: string
}

export function PhotoUploadButton({
  onFileSelected,
  disabled = false,
  label = '拍照上传',
}: PhotoUploadButtonProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  const handleClick = () => {
    inputRef.current?.click()
  }

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      onFileSelected(file)
    }
    // 重置 input，允许重复选择同一文件
    if (inputRef.current) {
      inputRef.current.value = ''
    }
  }

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        capture="environment"
        style={{ display: 'none' }}
        onChange={handleChange}
      />
      <Button
        icon={<CameraOutlined />}
        onClick={handleClick}
        disabled={disabled}
        style={{ borderRadius: 8 }}
      >
        {label}
      </Button>
    </>
  )
}
