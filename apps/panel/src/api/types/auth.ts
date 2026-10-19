export interface PanelHealth {
  ok: boolean;
  profile: string;
  status: string;
}

export interface PanelSession {
  created_at: string;
  expires_at: string;
  token: string;
}
