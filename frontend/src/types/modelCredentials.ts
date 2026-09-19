/** 后端 `GET/PUT /users/me/model-credentials` 返回的摘要；只有掩码，没有明文。 */
export interface ModelCredentialSummary {
  provider: string
  maskedKey: string
  updatedAt: string
  lastVerifiedAt: string
}

export interface ModelCredentialSaveRequest {
  apiKey: string
}