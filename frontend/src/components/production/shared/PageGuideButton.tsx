'use client'

import { PageGuideButton as BasePageGuideButton } from '@/components/shared/PageGuideButton'
import { PAGE_GUIDES } from './pageGuides'

/** 生产模块的页面使用手册入口，手册正文见 ./pageGuides.ts。 */
export function PageGuideButton() {
  return <BasePageGuideButton guides={PAGE_GUIDES} />
}
