import { GasDetectorTable, CalibrationAlertPanel } from '@/components/meter'
import { MeterPageHeader } from '@/components/meter/MeterPageHeader'
import styles from '@/components/meter/MeterModule.module.css'

export default function GasDetectorsPage() {
  return (
    <main className={styles.page}>
      <div className={styles.pageNarrow}>
        <MeterPageHeader title="气体探测器台账" description="集中掌握有毒、有害、可燃气体探测设备的安装位置与检定状态。" eyebrow="DETECTOR LEDGER" />
        <div className={styles.tableFrame}><GasDetectorTable /></div>
        <div className={styles.alertFrame}><CalibrationAlertPanel source="gas_detector" /></div>
      </div>
    </main>
  )
}
