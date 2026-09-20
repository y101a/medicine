import http from './http'

export interface VoiceTranscription {
  text: string
  durationMs: number
}

/**
 * 上传整段录音做转写（阿里云百炼非实时同步接口，由后端代理）。
 *
 * 音频只存在于内存与这一次请求里：后端处理完即弃，不落盘、不写日志。
 * 上传比普通请求慢，因此单独放宽超时，不跟着 `http.ts` 的 15 秒默认值走。
 */
const VOICE_UPLOAD_TIMEOUT_MS = 60_000

export const voiceApi = {
  async transcribe(blob: Blob) {
    const data = new FormData()
    // 不带扩展名：格式由后端按真实内容嗅探，文件名不参与判断。
    data.append('audio', blob, 'voice')
    return (await http.post<VoiceTranscription>('/voice/transcribe', data, {
      timeout: VOICE_UPLOAD_TIMEOUT_MS,
    })).data
  },
}