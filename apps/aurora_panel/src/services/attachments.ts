import type { ConversationAttachment } from '@aurorabot/client';

export const MAX_FILE_BYTES = 10 * 1024 * 1024;
const types: Record<string, ConversationAttachment['media_type']> = {
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  webp: 'image/webp',
  gif: 'image/gif',
  pdf: 'application/pdf',
  txt: 'text/plain',
  md: 'text/markdown',
  csv: 'text/csv',
  json: 'application/json',
};

export function attachmentBytes(file: ConversationAttachment): number {
  return Math.floor(file.data.length / 4) * 3 - (file.data.match(/=*$/u)?.[0].length ?? 0);
}

export async function readAttachments(
  files: File[],
  existing: ConversationAttachment[],
): Promise<ConversationAttachment[]> {
  if (files.length + existing.length > 8) throw new Error('每条消息最多附加 8 个文件。');
  if (
    files.reduce(
      (size, file) => size + file.size,
      existing.reduce((size, file) => size + attachmentBytes(file), 0),
    ) > MAX_FILE_BYTES
  )
    throw new Error('附件合计不能超过 10 MiB。');
  return Promise.all(
    files.map(async (file) => {
      const extension = file.name.split('.').pop()?.toLowerCase() ?? '';
      const media_type = Object.hasOwn(types, extension) ? types[extension] : undefined;
      if (!media_type) throw new Error('支持 PNG、JPEG、WebP、GIF、PDF，以及 UTF-8 的 TXT、Markdown、CSV、JSON。');
      if (file.size === 0 || [...file.name].length > 256) throw new Error('附件不能为空，文件名不能超过 256 字。');
      const data = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.addEventListener(
          'load',
          () => {
            if (typeof reader.result !== 'string' || !reader.result.includes(',')) reject(new Error('附件读取失败。'));
            else resolve(reader.result.slice(reader.result.indexOf(',') + 1));
          },
          { once: true },
        );
        reader.addEventListener('error', () => reject(new Error('附件读取失败，请重新选择。')), { once: true });
        reader.addEventListener('abort', () => reject(new Error('附件读取已取消。')), { once: true });
        reader.readAsDataURL(file);
      });
      return { name: file.name, media_type, data };
    }),
  );
}
