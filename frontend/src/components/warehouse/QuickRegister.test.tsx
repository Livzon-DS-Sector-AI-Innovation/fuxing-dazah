import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QuickRegister } from './QuickRegister'

const mocks = vi.hoisted(() => ({
  uploadReceiptImage: vi.fn(),
  webRecognizeReceipt: vi.fn(),
  webUpdateDraftFields: vi.fn(),
  webConfirmDraft: vi.fn(),
}))

vi.mock('@/lib/api/warehouse-quick-register', () => ({
  uploadReceiptImage: mocks.uploadReceiptImage,
}))

vi.mock('@/lib/api/warehouse-quick-register-actions', () => ({
  webRecognizeReceipt: mocks.webRecognizeReceipt,
  webUpdateDraftFields: mocks.webUpdateDraftFields,
  webConfirmDraft: mocks.webConfirmDraft,
}))

const FINISHED_DRAFT = {
  draft_id: 'd1',
  draft_no: 'WR20990101-001',
  status: 'aligned',
  scene: 'finished_receipt',
  recognized: {
    product_name: { value: '达托霉素', confidence: 0.95 },
    product_batch_no: { value: 'DA2609001', confidence: 0.9 },
    quantity: { value: '100', confidence: 0.4 },
    unit: { value: 'kg', confidence: 0.9 },
    rows: [
      {
        product_name: '达托霉素',
        product_batch_no: 'DA2609001',
        quantity: '100',
        unit: 'kg',
      },
    ],
  },
  aligned: { product_name: '达托霉素', match_confidence: 'exact', warnings: {} },
}

async function uploadAndRecognize() {
  mocks.uploadReceiptImage.mockResolvedValue({ upload_id: 'u1' })
  mocks.webRecognizeReceipt.mockResolvedValue(FINISHED_DRAFT)
  const { container } = render(<QuickRegister />)
  const file = new File(['fake'], 'receipt.png', { type: 'image/png' })
  const input = container.querySelector('input[type="file"]') as HTMLInputElement
  fireEvent.change(input, { target: { files: [file] } })
  await screen.findByText(/识别草稿 WR20990101-001/)
}

describe('QuickRegister 表单化修正', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.webConfirmDraft.mockResolvedValue({ ok: true, status: 'ok', draft_status: 'submitted' })
    mocks.webUpdateDraftFields.mockResolvedValue(FINISHED_DRAFT)
  })

  it('低置信度字段标警示且可直接修改', async () => {
    await uploadAndRecognize()
    // quantity 置信度 0.4 → 低置信标签 + 警示输入框（首个=标量字段，其后是明细行）
    expect(screen.getByText(/低置信度 40%/)).toBeInTheDocument()
    const quantityInput = screen.getAllByDisplayValue('100')[0] as HTMLInputElement
    expect(quantityInput.className).toContain('ant-input-status-warning')
  })

  it('修改字段后确认：先 PATCH 差异再确认提交', async () => {
    await uploadAndRecognize()
    const user = userEvent.setup()
    const quantityInput = screen.getAllByDisplayValue('100')[0]
    await user.clear(quantityInput)
    await user.type(quantityInput, '120')

    await user.click(screen.getByRole('button', { name: '确认提交' }))

    await waitFor(() =>
      expect(mocks.webUpdateDraftFields).toHaveBeenCalledWith('d1', {
        fields: { quantity: '120' },
        rows: undefined,
      }),
    )
    await waitFor(() => expect(mocks.webConfirmDraft).toHaveBeenCalledWith('d1', 'confirm'))
    expect(screen.getByText(/已确认提交/)).toBeInTheDocument()
  })

  it('未修改直接确认：不调 PATCH', async () => {
    await uploadAndRecognize()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: '确认提交' }))

    await waitFor(() => expect(mocks.webConfirmDraft).toHaveBeenCalledWith('d1', 'confirm'))
    expect(mocks.webUpdateDraftFields).not.toHaveBeenCalled()
  })

  it('成品明细行可编辑并随确认提交', async () => {
    await uploadAndRecognize()
    const user = userEvent.setup()
    // 明细行表格中的批号输入框（getByDisplayValue 会命中标量+行两处，取表格内的）
    const batchInputs = screen.getAllByDisplayValue('DA2609001')
    expect(batchInputs.length).toBeGreaterThanOrEqual(2)
    const rowBatchInput = batchInputs[batchInputs.length - 1]
    await user.clear(rowBatchInput)
    await user.type(rowBatchInput, 'DA2609002')

    await user.click(screen.getByRole('button', { name: '确认提交' }))

    await waitFor(() => {
      const call = mocks.webUpdateDraftFields.mock.calls[0]
      expect(call?.[0]).toBe('d1')
      expect(call?.[1].rows?.[0].product_batch_no).toBe('DA2609002')
    })
  })
})
