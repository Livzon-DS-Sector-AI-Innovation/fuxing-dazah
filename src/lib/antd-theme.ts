import type { ThemeConfig } from 'antd'

/**
 * Ant Design 主题配置
 * 基于 DESIGN.md 的 Notion 风格设计系统
 */
export const antdTheme: ThemeConfig = {
  token: {
    // 主色调 - Notion Purple
    colorPrimary: '#5645d4',
    colorPrimaryBg: '#ede9f8',
    colorPrimaryBgHover: '#d6cef3',
    colorPrimaryBorder: '#b8adeb',
    colorPrimaryBorderHover: '#9a8de2',
    colorPrimaryHover: '#6b5ddb',
    colorPrimaryActive: '#4534b3',
    colorPrimaryTextHover: '#6b5ddb',
    colorPrimaryText: '#5645d4',
    colorPrimaryTextActive: '#4534b3',

    // 成功色
    colorSuccess: '#1aae39',
    colorSuccessBg: '#e6f7e6',
    colorSuccessBorder: '#b7eb8f',

    // 警告色
    colorWarning: '#dd5b00',
    colorWarningBg: '#fff7e6',
    colorWarningBorder: '#ffd591',

    // 错误色
    colorError: '#e03131',
    colorErrorBg: '#fff1f0',
    colorErrorBorder: '#ffa8a8',

    // 文本颜色
    colorText: '#1a1a1a',
    colorTextSecondary: '#5d5b54',
    colorTextTertiary: '#787671',
    colorTextQuaternary: '#a4a097',

    // 背景色
    colorBgContainer: '#ffffff',
    colorBgElevated: '#ffffff',
    colorBgLayout: '#f6f5f4',
    colorBgSpotlight: '#f6f5f4',

    // 边框
    colorBorder: '#e5e3df',
    colorBorderSecondary: '#ede9e4',

    // 字体 - Notion Sans (基于 Inter)
    fontFamily: "'Notion Sans', 'Inter', -apple-system, system-ui, 'Segoe UI', Helvetica, sans-serif",

    // 圆角 - 符合 DESIGN.md
    borderRadius: 8,        // rounded.md
    borderRadiusLG: 12,     // rounded.lg
    borderRadiusSM: 6,      // rounded.sm
    borderRadiusXS: 4,      // rounded.xs

    // 控件高度
    controlHeight: 44,      // text-input 高度
    controlHeightLG: 48,
    controlHeightSM: 36,

    // 字体大小
    fontSize: 14,
    fontSizeLG: 16,
    fontSizeSM: 12,
    fontSizeXL: 20,

    // 行高
    lineHeight: 1.5,
    lineHeightLG: 1.5,
    lineHeightSM: 1.4,

    // 间距
    marginXS: 8,
    marginSM: 12,
    marginMD: 16,
    marginLG: 20,
    marginXL: 24,

    paddingXS: 8,
    paddingSM: 12,
    paddingMD: 16,
    paddingLG: 20,
    paddingXL: 24,

    // 阴影
    boxShadow: '0 1px 2px 0 rgba(15, 15, 15, 0.04)',
    boxShadowSecondary: '0 4px 12px 0 rgba(15, 15, 15, 0.08)',

    // 链接色
    colorLink: '#0075de',
    colorLinkHover: '#40a9ff',
  },
  components: {
    // 按钮组件
    Button: {
      borderRadius: 8,
      controlHeight: 44,
      paddingContentHorizontal: 18,
      fontWeight: 500,
    },

    // 输入框组件
    Input: {
      borderRadius: 8,
      controlHeight: 44,
      paddingInline: 12,
    },

    // 选择器组件
    Select: {
      borderRadius: 8,
      controlHeight: 44,
    },

    // 日期选择器
    DatePicker: {
      borderRadius: 8,
      controlHeight: 44,
    },

    // 表格组件
    Table: {
      borderRadius: 8,
      headerBg: '#ffffff',
      headerColor: '#5d5b54',
      headerSortActiveBg: '#f6f5f4',
      rowHoverBg: '#f6f5f4',
      borderColor: '#ede9e4',
      cellPaddingInline: 12,
      cellPaddingBlock: 4,
      headerBorderRadius: 0,
    },

    // 卡片组件
    Card: {
      borderRadiusLG: 12,
      paddingLG: 20,
    },

    // 抽屉组件
    Drawer: {
      borderRadius: 12,
    },

    // 标签页组件
    Tabs: {
      borderRadius: 8,
      itemColor: '#787671',
      itemSelectedColor: '#1a1a1a',
      itemHoverColor: '#1a1a1a',
      inkBarColor: '#1a1a1a',
    },

    // 标签组件
    Tag: {
      borderRadiusSM: 4,
    },

    // 树组件
    Tree: {
      borderRadius: 6,
    },

    // 分页组件
    Pagination: {
      borderRadius: 8,
    },

    // 模态框
    Modal: {
      borderRadiusLG: 12,
    },

    // 消息
    Message: {
      borderRadiusLG: 8,
    },

    // 统计数值
    Statistic: {
      titleFontSize: 14,
      contentFontSize: 28,
    },
  },
}
