'use client'

import { useEffect, useRef, useState } from 'react'
import { App, Button, Card, Form, Input, Result, Spin, Typography, Image } from 'antd'
import { CheckCircleOutlined } from '@ant-design/icons'

const { Title, Text } = Typography

interface CertData {
  name: string
  department: string
  position: string
  offboarding_date: string
  sign_status: string
}

export function SignClient({ token }: { token: string }) {
  const { message } = App.useApp()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [signed, setSigned] = useState(false)
  const [data, setData] = useState<CertData | null>(null)
  const [error, setError] = useState('')
  const [drawing, setDrawing] = useState(false)

  useEffect(() => {
    fetch(`/api/v1/public/certificate-sign/${token}`)
      .then(r => r.json())
      .then(d => {
        if (d.code === 200) {
          setData(d.data)
          if (d.data.sign_status === 'signed') setSigned(true)
        } else {
          setError(d.message || '链接无效')
        }
      })
      .catch(() => setError('无法加载签署信息'))
      .finally(() => setLoading(false))
  }, [token])

  // Canvas drawing
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.lineWidth = 2
    ctx.strokeStyle = '#000'
    ctx.lineCap = 'round'

    const getPos = (e: MouseEvent | TouchEvent) => {
      const rect = canvas.getBoundingClientRect()
      if ('touches' in e) {
        return { x: e.touches[0].clientX - rect.left, y: e.touches[0].clientY - rect.top }
      }
      return { x: e.clientX - rect.left, y: e.clientY - rect.top }
    }

    const start = (e: Event) => {
      e.preventDefault()
      setDrawing(true)
      const p = getPos(e as MouseEvent | TouchEvent)
      ctx.beginPath()
      ctx.moveTo(p.x, p.y)
    }
    const move = (e: Event) => {
      e.preventDefault()
      if (!drawing) return
      const p = getPos(e as MouseEvent | TouchEvent)
      ctx.lineTo(p.x, p.y)
      ctx.stroke()
    }
    const end = () => { setDrawing(false); ctx.closePath() }

    canvas.addEventListener('mousedown', start)
    canvas.addEventListener('mousemove', move)
    canvas.addEventListener('mouseup', end)
    canvas.addEventListener('mouseleave', end)
    canvas.addEventListener('touchstart', start)
    canvas.addEventListener('touchmove', move)
    canvas.addEventListener('touchend', end)

    return () => {
      canvas.removeEventListener('mousedown', start)
      canvas.removeEventListener('mousemove', move)
      canvas.removeEventListener('mouseup', end)
      canvas.removeEventListener('mouseleave', end)
      canvas.removeEventListener('touchstart', start)
      canvas.removeEventListener('touchmove', move)
      canvas.removeEventListener('touchend', end)
    }
  }, [drawing])

  const handleClear = () => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height)
  }

  const handleSubmit = async (values: { name: string; idCardLast4: string }) => {
    const canvas = canvasRef.current
    if (!canvas) return message.error('请先签名')
    const signImage = canvas.toDataURL('image/png')
    // Check if signature is empty
    const ctx = canvas.getContext('2d')
    if (ctx) {
      const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)
      const hasSignature = imageData.data.some((v) => v !== 0)
      if (!hasSignature) return message.error('请在签名区手写签名')
    }

    setSubmitting(true)
    try {
      const res = await fetch(`/api/v1/public/certificate-sign/${token}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: values.name,
          id_card_last4: values.idCardLast4,
          sign_image: signImage,
        }),
      })
      const d = await res.json()
      if (res.ok) {
        setSigned(true)
        message.success('签署成功，离职证明已发送至您的邮箱')
      } else {
        message.error(d.message || '签署失败')
      }
    } catch {
      message.error('网络错误')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) return <div style={{ textAlign: 'center', padding: 80 }}><Spin size="large" /></div>
  if (error) return <Result status="error" title="签署链接无效" subTitle={error} />
  if (signed) return <Result status="success" icon={<CheckCircleOutlined />} title="已完成签署" subTitle="离职证明已发送至您的邮箱，请查收。" />

  return (
    <div style={{ maxWidth: 500, margin: '40px auto', padding: '0 20px' }}>
      <Card>
        <Title level={4} style={{ textAlign: 'center' }}>离职证明签署</Title>
        {data && (
          <div style={{ marginBottom: 24, padding: 12, background: '#f5f5f5', borderRadius: 8 }}>
            <Text strong>{data.name}</Text><br />
            <Text type="secondary">{data.department} · {data.position}</Text><br />
            <Text type="secondary">离职日期：{data.offboarding_date}</Text>
          </div>
        )}

        <Form layout="vertical" onFinish={handleSubmit}>
          <Form.Item label="确认姓名" name="name" rules={[{ required: true, message: '请输入姓名' }]}>
            <Input placeholder="请输入您的姓名" />
          </Form.Item>
          <Form.Item label="身份证后四位" name="idCardLast4" rules={[{ required: true, len: 4, message: '请输入身份证后四位' }]}>
            <Input placeholder="身份证后四位" maxLength={4} />
          </Form.Item>
          <Form.Item label="手写签名" required>
            <canvas
              ref={canvasRef}
              width={450}
              height={160}
              style={{ border: '1px solid #d9d9d9', borderRadius: 8, width: '100%', cursor: 'crosshair' }}
            />
            <Button size="small" onClick={handleClear} style={{ marginTop: 4 }}>清除重签</Button>
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={submitting} block size="large">
            确认签署
          </Button>
        </Form>
      </Card>
    </div>
  )
}
