import { PageHeader, QuickRegister } from '@/components/warehouse'

export default function WarehouseQuickRegisterPage() {
  return (
    <div>
      <PageHeader
        title="快速登记"
        description="上传送货单图片，自动识别并确认入库登记"
      />
      <QuickRegister />
    </div>
  )
}
