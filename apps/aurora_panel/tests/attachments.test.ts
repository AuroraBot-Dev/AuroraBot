import { describe, expect, it } from 'vitest';

import { attachmentBytes, MAX_FILE_BYTES, readAttachments } from '../src/services/attachments.ts';

describe('附件读取边界', () => {
  it('按文件扩展名生成受支持的附件，保留完整字节', async () => {
    const files = await readAttachments([new File(['hello'], '说明.txt'), new File(['pdf'], 'paper.PDF')], []);
    expect(files[0]).toEqual({ name: '说明.txt', media_type: 'text/plain', data: btoa('hello') });
    expect(files[1]).toEqual({ name: 'paper.PDF', media_type: 'application/pdf', data: btoa('pdf') });
    const first = files[0];
    if (!first) throw new Error('附件缺失');
    expect(attachmentBytes(first)).toBe(5);
  });

  it('拒绝空文件、不支持的类型和超量附件', async () => {
    await expect(readAttachments([new File([], 'empty.pdf')], [])).rejects.toThrow('不能为空');
    await expect(readAttachments([new File(['x'], 'script.exe')], [])).rejects.toThrow('支持');
    await expect(
      readAttachments(
        Array.from({ length: 9 }, () => new File(['x'], 'a.txt')),
        [],
      ),
    ).rejects.toThrow('8');
    const large = new File([new Uint8Array(MAX_FILE_BYTES + 1)], 'large.pdf');
    await expect(readAttachments([large], [])).rejects.toThrow('10 MiB');
  });
});
