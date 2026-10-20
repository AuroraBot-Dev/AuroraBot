export type Locale = 'en-US' | 'ja-JP' | 'zh-CN';

export const messages: Record<Locale, Record<string, string>> = {
  'en-US': {
    cancel: 'Cancel',
    collapse: 'Collapse',
    confirm: 'Confirm',
    expand: 'Expand',
    prompt: 'Prompt',
    reset: 'Reset',
    submit: 'Submit',
    confirmTitle: 'Please Confirm',
  },
  'ja-JP': {
    cancel: 'キャンセル',
    collapse: '折りたたむ',
    confirm: '確認',
    expand: '展開',
    prompt: 'プロンプト',
    reset: 'リセット',
    submit: '送信',
    confirmTitle: '確認してください',
  },
  'zh-CN': {
    cancel: '取消',
    collapse: '收起',
    confirm: '确认',
    expand: '展开',
    prompt: '提示',
    reset: '重置',
    submit: '提交',
    confirmTitle: '请确认',
  },
};

export const getMessages = (locale: Locale) => messages[locale];
