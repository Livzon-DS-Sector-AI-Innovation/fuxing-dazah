'use client'

import { useEffect, useRef, useCallback, useState } from 'react'
import { usePathname } from 'next/navigation'
import {
  Drawer,
  Input,
  Button,
  Spin,
  Avatar,
  Tag,
  Tooltip,
} from 'antd'
import {
  RobotOutlined,
  SendOutlined,
  ClearOutlined,
  CommentOutlined,
  UserOutlined,
  BulbOutlined,
  AudioOutlined,
  AudioMutedOutlined,
} from '@ant-design/icons'
import { useHrChatStore } from '@/stores/hrChat'

const { TextArea } = Input

function getPageFromPath(path: string): { page: string; name: string } {
  if (path.includes('/hr/profile')) return { page: 'profile', name: '员工档案' }
  if (path.includes('/hr/departments')) return { page: 'departments', name: '部门管理' }
  if (path.includes('/hr/offboarding')) return { page: 'offboarding', name: '离职管理' }
  if (path.includes('/hr/onboarding')) return { page: 'onboarding', name: '入职管理' }
  if (path.includes('/hr/training')) return { page: 'training', name: '培训管理' }
  if (path.includes('/hr/teams')) return { page: 'teams', name: '班组管理' }
  return { page: 'hr', name: '人事管理' }
}

const QUICK_QUESTIONS = [
  '统计各部门人数',
  '分析在职员工学历分布',
  '本月有哪些合同即将到期？',
  '整理一份离职原因汇总',
]


export default function HrChatbot() {
  const pathname = usePathname()
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<any>(null)
  const recognitionRef = useRef<any>(null)
  const buttonRef = useRef<HTMLDivElement>(null)

  const {
    messages,
    isOpen,
    isLoading,
    inputValue,
    toggleOpen,
    setOpen,
    setInputValue,
    setPageContext,
    sendMessage,
    clearMessages,
  } = useHrChatStore()

  const [position, setPosition] = useState({ x: 0, y: 0 })
  const [isDragging, setIsDragging] = useState(false)
  const dragState = useRef({
    isDragging: false,
    hasMoved: false,
    startX: 0,
    startY: 0,
    initialLeft: 0,
    initialTop: 0,
  })

  // Load saved position
  useEffect(() => {
    const saved = localStorage.getItem('hr-chatbot-position')
    if (saved) {
      try {
        const pos = JSON.parse(saved)
        setPosition(pos)
      } catch {
        setPosition({ x: window.innerWidth - 80, y: window.innerHeight - 80 })
      }
    } else {
      setPosition({ x: window.innerWidth - 80, y: window.innerHeight - 80 })
    }
  }, [])

  // Save position
  const savePosition = useCallback((pos: { x: number; y: number }) => {
    localStorage.setItem('hr-chatbot-position', JSON.stringify(pos))
  }, [])

  // Snap to nearest edge
  const snapToEdge = useCallback(
    (x: number, y: number) => {
      const buttonSize = 56
      const margin = 24
      const maxX = window.innerWidth - buttonSize - margin
      const maxY = window.innerHeight - buttonSize - margin

      const clampedX = Math.max(margin, Math.min(x, maxX))
      const clampedY = Math.max(margin, Math.min(y, maxY))

      const centerX = clampedX + buttonSize / 2
      const centerY = clampedY + buttonSize / 2

      const distToLeft = centerX - margin
      const distToRight = window.innerWidth - centerX - margin
      const distToTop = centerY - margin
      const distToBottom = window.innerHeight - centerY - margin

      const minDist = Math.min(distToLeft, distToRight, distToTop, distToBottom)

      let snappedX = clampedX
      let snappedY = clampedY

      if (minDist === distToLeft) {
        snappedX = margin
      } else if (minDist === distToRight) {
        snappedX = window.innerWidth - buttonSize - margin
      } else if (minDist === distToTop) {
        snappedY = margin
      } else if (minDist === distToBottom) {
        snappedY = window.innerHeight - buttonSize - margin
      }

      const newPos = { x: snappedX, y: snappedY }
      setPosition(newPos)
      savePosition(newPos)
    },
    [savePosition]
  )

  const handlePointerDown = useCallback(
    (e: React.PointerEvent) => {
      const state = dragState.current
      state.isDragging = true
      state.hasMoved = false
      state.startX = e.clientX
      state.startY = e.clientY
      state.initialLeft = position.x
      state.initialTop = position.y
      ;(e.target as Element).setPointerCapture(e.pointerId)
      setIsDragging(true)
    },
    [position]
  )

  const handlePointerMove = useCallback(
    (e: React.PointerEvent) => {
      const state = dragState.current
      if (!state.isDragging) return

      const dx = e.clientX - state.startX
      const dy = e.clientY - state.startY

      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
        state.hasMoved = true
      }

      if (state.hasMoved) {
        const buttonSize = 56
        const margin = 24
        const newX = Math.max(
          margin,
          Math.min(state.initialLeft + dx, window.innerWidth - buttonSize - margin)
        )
        const newY = Math.max(
          margin,
          Math.min(state.initialTop + dy, window.innerHeight - buttonSize - margin)
        )
        setPosition({ x: newX, y: newY })
      }
    },
    []
  )

  const handlePointerUp = useCallback(
    (e: React.PointerEvent) => {
      const state = dragState.current
      if (!state.isDragging) return
      state.isDragging = false
      setIsDragging(false)
      ;(e.target as Element).releasePointerCapture(e.pointerId)

      if (state.hasMoved) {
        snapToEdge(position.x, position.y)
      } else {
        // Treat as click
        toggleOpen()
      }
    },
    [position, snapToEdge, toggleOpen]
  )

  // Handle window resize
  useEffect(() => {
    const handleResize = () => {
      const buttonSize = 56
      const margin = 24
      setPosition((prev) => ({
        x: Math.max(margin, Math.min(prev.x, window.innerWidth - buttonSize - margin)),
        y: Math.max(margin, Math.min(prev.y, window.innerHeight - buttonSize - margin)),
      }))
    }
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  const [isRecording, setIsRecording] = useState(false)
  const [speechSupported, setSpeechSupported] = useState(false)

  // Check browser support for SpeechRecognition
  useEffect(() => {
    const SpeechRecognition =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    setSpeechSupported(!!SpeechRecognition)
  }, [])

  // Initialize SpeechRecognition
  useEffect(() => {
    const SpeechRecognition =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SpeechRecognition) return

    const recognition = new SpeechRecognition()
    recognition.lang = 'zh-CN'
    recognition.continuous = false
    recognition.interimResults = false

    recognition.onstart = () => {
      setIsRecording(true)
    }

    recognition.onend = () => {
      setIsRecording(false)
    }

    recognition.onresult = (event: any) => {
      const transcript = event.results[0][0].transcript
      setInputValue((prev: string) => {
        const separator = prev && !prev.endsWith(' ') ? ' ' : ''
        return prev + separator + transcript
      })
      setTimeout(() => inputRef.current?.focus(), 100)
    }

    recognition.onerror = (event: any) => {
      console.error('Speech recognition error:', event.error)
      setIsRecording(false)
    }

    recognitionRef.current = recognition

    return () => {
      recognition.abort()
    }
  }, [setInputValue])

  const toggleRecording = useCallback(() => {
    if (!recognitionRef.current) return
    if (isRecording) {
      recognitionRef.current.stop()
    } else {
      recognitionRef.current.start()
    }
  }, [isRecording])

  // Update page context when pathname changes
  useEffect(() => {
    const { page, name } = getPageFromPath(pathname || '')
    setPageContext({ page: `${page}（${name}）` })
  }, [pathname, setPageContext])

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  // Focus input when drawer opens
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 300)
    }
  }, [isOpen])

  const handleSend = useCallback(async () => {
    if (!inputValue.trim() || isLoading) return
    await sendMessage(inputValue.trim())
  }, [inputValue, isLoading, sendMessage])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <>
      <div
        ref={buttonRef}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        style={{
          position: 'fixed',
          left: position.x,
          top: position.y,
          zIndex: 9999,
          touchAction: 'none',
          userSelect: 'none',
          cursor: isDragging ? 'grabbing' : 'grab',
        }}
        className="transition-shadow"
      >
        <div
          className={`w-10 h-10 rounded-full bg-transparent text-blue-500 flex items-center justify-center text-lg drop-shadow-md hover:text-blue-600 ${isDragging ? 'scale-110' : 'scale-100'} transition-transform`}
          title="HR 智能助手"
        >
          <RobotOutlined />
        </div>
      </div>

      <Drawer
        placement="right"
        size={460}
        open={isOpen}
        onClose={() => setOpen(false)}
        title={
          <div className="flex items-center gap-2">
            <RobotOutlined className="text-blue-500" />
            <span className="font-semibold">HR 智能助手 · 小H</span>
          </div>
        }
        extra={
          <Button
            size="small"
            icon={<ClearOutlined />}
            onClick={clearMessages}
            disabled={isLoading}
          >
            清空
          </Button>
        }
        styles={{ body: { padding: 0, display: 'flex', flexDirection: 'column', height: '100%' } }}
      >
        {/* Messages area */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4 bg-gray-50">
          {messages.map((msg, idx) => {
            const isLastAssistant =
              msg.role === 'assistant' && idx === messages.length - 1
            const isThinking =
              isLastAssistant && isLoading && !!msg.reasoning_content && !msg.content

            return (
              <div
                key={idx}
                className={`flex gap-2 ${msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}
              >
                <Avatar
                  icon={msg.role === 'user' ? <UserOutlined /> : <RobotOutlined />}
                  className={msg.role === 'user' ? 'bg-blue-500' : 'bg-green-500'}
                  size="small"
                />
                <div className="max-w-[85%] space-y-1">
                  {msg.role === 'assistant' && (msg.reasoning_content || isThinking) && (
                    <div className="rounded-md bg-amber-50 border border-amber-100 px-2 py-1.5">
                      <div className="flex items-center gap-1 text-amber-600 text-xs font-medium mb-0.5">
                        <BulbOutlined />
                        {isThinking ? '正在思考...' : '思考过程'}
                      </div>
                      <div className="text-xs text-amber-700 whitespace-pre-wrap leading-relaxed">
                        {msg.reasoning_content}
                      </div>
                    </div>
                  )}

                  <div
                    className={`rounded-lg px-3 py-2 text-sm whitespace-pre-wrap leading-relaxed ${
                      msg.role === 'user'
                        ? 'bg-blue-500 text-white'
                        : 'bg-white text-gray-800 shadow-sm border border-gray-100'
                    }`}
                  >
                    {msg.role === 'assistant' && msg.content ? (
                      <span>{msg.content}</span>
                    ) : msg.role === 'user' ? (
                      <span>{msg.content}</span>
                    ) : isLastAssistant && isLoading && !msg.content ? (
                      <Spin size="small" />
                    ) : null}
                  </div>
                </div>
              </div>
            )
          })}
          <div ref={messagesEndRef} />
        </div>

        {/* Quick questions */}
        {messages.length <= 2 && (
          <div className="px-4 py-2 bg-white border-t border-gray-100">
            <div className="text-xs text-gray-400 mb-2 flex items-center gap-1">
              <CommentOutlined />
              快捷提问
            </div>
            <div className="flex flex-wrap gap-2">
              {QUICK_QUESTIONS.map((q) => (
                <Tag
                  key={q}
                  className="cursor-pointer hover:text-blue-500 hover:border-blue-300 transition-colors"
                  onClick={() => {
                    if (!isLoading) sendMessage(q)
                  }}
                >
                  {q}
                </Tag>
              ))}
            </div>
          </div>
        )}

        {/* Input area */}
        <div className="p-3 bg-white border-t border-gray-200">
          <div className="flex gap-2">
            <TextArea
              ref={inputRef}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="输入问题，按 Enter 发送，Shift+Enter 换行"
              autoSize={{ minRows: 1, maxRows: 4 }}
              disabled={isLoading}
              className="flex-1"
            />
            {speechSupported && (
              <Tooltip title={isRecording ? '点击停止录音' : '点击语音输入'}>
                <Button
                  icon={isRecording ? <AudioMutedOutlined /> : <AudioOutlined />}
                  onClick={toggleRecording}
                  danger={isRecording}
                  className="self-end"
                />
              </Tooltip>
            )}
            <Button
              type="primary"
              icon={<SendOutlined />}
              onClick={handleSend}
              loading={isLoading}
              disabled={!inputValue.trim()}
              className="self-end"
            />
          </div>
          <div className="text-xs text-gray-400 mt-1 text-right">
            由 Moonshot AI 提供支持
            {speechSupported && ' · 支持语音输入'}
          </div>
        </div>
      </Drawer>
    </>
  )
}
