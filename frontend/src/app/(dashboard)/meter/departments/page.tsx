import { DepartmentManagement } from '@/components/meter'
import styles from '@/components/meter/MeterModule.module.css'

export default function DepartmentsPage() {
  return <main className={styles.page}><div className={styles.pageNarrow}><DepartmentManagement /></div></main>
}
