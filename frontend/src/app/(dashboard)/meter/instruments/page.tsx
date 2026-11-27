import { InstrumentTable, CalibrationAlertPanel } from '@/components/meter'
import { MeterPageHeader } from '@/components/meter/MeterPageHeader'
import styles from '@/components/meter/MeterModule.module.css'

export default function InstrumentsPage() {
  return (
    <main className={styles.page}>
      <div className={styles.pageNarrow}>
        <MeterPageHeader title="标准计量器具" description="管理压力表、温度计与其他标准计量器具的全生命周期台账。" eyebrow="INSTRUMENT LEDGER" />
        <div className={styles.tableFrame}><InstrumentTable /></div>
        <div className={styles.alertFrame}><CalibrationAlertPanel source="instrument" /></div>
      </div>
    </main>
  )
}
