'use client'

import { useState } from 'react'
import { App, Modal, Button, Input, Upload, Form, Select } from 'antd'
import { UploadOutlined } from '@ant-design/icons'
import type { UploadFile } from 'antd/es/upload/interface'
import { parseResumePreviewAction, createCandidateAction } from '@/actions/hr'

interface CreateCandidateModalProps {
  open: boolean
  onClose: () => void
  onSuccess: () => void
}

export default function CreateCandidateModal({
  open,
  onClose,
  onSuccess }: CreateCandidateModalProps) {
  const { message } = App.useApp()
  const [form] = Form.useForm()
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [parsing, setParsing] = useState(false)
  const [creating, setCreating] = useState(false)
  const [parsed, setParsed] = useState(false)
  const [previewData, setPreviewData] = useState({
    gender: '',
    school: '',
    education: '',
    major: '',
    recommendation_level: '',
    resume_file_path: '' })

  const handleParse = async () => {
    const values = form.getFieldsValue()
    if (!values.name || !values.position) {
      message.error('请填写姓名和应聘职位')
      return
    }
    if (fileList.length === 0) {
      message.error('请上传简历PDF')
      return
    }

    setParsing(true)
    try {
      const formData = new FormData()
      const file = fileList[0].originFileObj
      if (!file) {
        message.error('文件对象不存在')
        return
      }
      formData.append('resume', file)
      formData.append('position', values.position)
      const res = await parseResumePreviewAction(formData)
      setPreviewData(res.data)
      setParsed(true)
      message.success('简历解析完成，请确认以下信息')
    } catch (err: any) {
      message.error(err.message || '解析失败')
    } finally {
      setParsing(false)
    }
  }

  const handleCreate = async () => {
    const values = form.getFieldsValue()
    if (fileList.length === 0) {
      message.error('请上传简历PDF')
      return
    }

    setCreating(true)
    try {
      const formData = new FormData()
      formData.append('name', values.name)
      formData.append('position', values.position)
      const file = fileList[0].originFileObj
      if (file) {
        formData.append('resume', file)
      }
      formData.append('gender', previewData.gender)
      formData.append('school', previewData.school)
      formData.append('education', previewData.education)
      formData.append('major', previewData.major)
      formData.append('recommendation_level', previewData.recommendation_level)
      if (previewData.resume_file_path) formData.append('resume_file_path', previewData.resume_file_path)

      await createCandidateAction(formData)
      message.success('候选人创建成功')
      onSuccess()
      handleReset()
    } catch (err: any) {
      message.error(err.message || '创建失败')
    } finally {
      setCreating(false)
    }
  }

  const handleReset = () => {
    form.resetFields()
    setFileList([])
    setParsed(false)
    setPreviewData({
      gender: '',
      school: '',
      education: '',
      major: '',
      recommendation_level: '',
    resume_file_path: '' })
  }

  const handleCancel = () => {
    handleReset()
    onClose()
  }

  return (
    <Modal
      title="新建候选人"
      open={open}
      onCancel={handleCancel}
      width={720}
      footer={null}
    >
      <Form form={form} layout="vertical">
        <Form.Item
          name="name"
          label="候选人姓名"
          rules={[{ required: true, message: '请输入姓名' }]}
        >
          <Input placeholder="请输入候选人姓名" />
        </Form.Item>
        <Form.Item
          name="position"
          label="应聘职位"
          rules={[{ required: true, message: '请输入应聘职位' }]}
        >
          <Input placeholder="请输入应聘职位" />
        </Form.Item>
        <Form.Item label="简历PDF" required>
          <Upload
            beforeUpload={() => false}
            fileList={fileList}
            onChange={({ fileList: newFileList }) => setFileList(newFileList)}
            maxCount={1}
            accept=".pdf"
          >
            <Button icon={<UploadOutlined />}>上传简历PDF</Button>
          </Upload>
        </Form.Item>

        {!parsed && (
          <Button
            type="primary"
            onClick={handleParse}
            loading={parsing}
            disabled={fileList.length === 0}
          >
            解析简历
          </Button>
        )}

        {parsed && (
          <>
            <div className="mt-4 mb-2 font-medium">AI 解析结果（可编辑）</div>
            <div className="grid grid-cols-2 gap-3">
              <Form.Item label="性别">
                <Input
                  value={previewData.gender}
                  onChange={(e) =>
                    setPreviewData({ ...previewData, gender: e.target.value })
                  }
                  placeholder="性别"
                />
              </Form.Item>
              <Form.Item label="学校">
                <Input
                  value={previewData.school}
                  onChange={(e) =>
                    setPreviewData({ ...previewData, school: e.target.value })
                  }
                  placeholder="学校"
                />
              </Form.Item>
              <Form.Item label="学历">
                <Input
                  value={previewData.education}
                  onChange={(e) =>
                    setPreviewData({ ...previewData, education: e.target.value })
                  }
                  placeholder="学历"
                />
              </Form.Item>
              <Form.Item label="专业">
                <Input
                  value={previewData.major}
                  onChange={(e) =>
                    setPreviewData({ ...previewData, major: e.target.value })
                  }
                  placeholder="专业"
                />
              </Form.Item>
            </div>
            <Form.Item label="推荐等级">
              <Select
                value={previewData.recommendation_level || undefined}
                onChange={(value) =>
                  setPreviewData({
                    ...previewData,
                    recommendation_level: value })
                }
                placeholder="选择推荐等级"
                options={[
                  { value: '强烈推荐', label: '强烈推荐' },
                  { value: '推荐', label: '推荐' },
                  { value: '待定', label: '待定' },
                  { value: '不推荐', label: '不推荐' },
                ]}
              />
            </Form.Item>
            <div className="flex gap-2 justify-end">
              <Button onClick={handleCancel}>取消</Button>
              <Button onClick={handleReset}>重置</Button>
              <Button
                type="primary"
                onClick={handleCreate}
                loading={creating}
              >
                确认添加
              </Button>
            </div>
          </>
        )}
      </Form>
    </Modal>
  )
}
