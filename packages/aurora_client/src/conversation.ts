import type {
  ConversationCancelRequest,
  ConversationQueryRequest,
  ConversationSubmitRequest,
} from './generated/ctx-contract.ts';
import type { Transport } from './transport.ts';

/** 直接交流与 ctx 共用连接寿命；请求身份由调用者保留，网络失败不自动重发。 */
export class ConversationClient {
  private readonly transport: Transport;

  constructor(transport: Transport) {
    this.transport = transport;
  }

  /** 明确指定目标 run；关闭客户端或中止 HTTP 等待均不隐式取消运行。 */
  cancel(request: ConversationCancelRequest, signal?: AbortSignal) {
    return this.transport.request('conversationCancel', request, signal);
  }

  info(signal?: AbortSignal) {
    return this.transport.request('conversationInfo', {}, signal);
  }

  query(request: ConversationQueryRequest, signal?: AbortSignal) {
    return this.transport.request('conversationQuery', request, signal);
  }

  /** accepted 只表示引导已接纳；运行结果须通过 query 核对。 */
  submit(request: ConversationSubmitRequest, signal?: AbortSignal) {
    return this.transport.request('conversationSubmit', request, signal);
  }
}
