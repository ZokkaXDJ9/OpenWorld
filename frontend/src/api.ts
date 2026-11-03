async function httpError(response: Response): Promise<Error> {
  const fallback = response.status >= 500
    ? `Backend oder API-Proxy antwortet mit HTTP ${response.status}. Bitte das Backend in einem zweiten Terminal starten bzw. dessen Protokoll prüfen.`
    : `Backend-Anfrage fehlgeschlagen (HTTP ${response.status}).`
  const body = (await response.text()).trim()
  if (!body) return new Error(fallback)
  if (response.headers.get('content-type')?.includes('json')) {
    let data: unknown
    try {
      data = JSON.parse(body)
    } catch (error) {
      if (!(error instanceof SyntaxError)) throw error
      return new Error(`${fallback} Die Fehlerantwort enthält ungültiges JSON.`, { cause: error })
    }
    if (typeof data === 'object' && data !== null && 'detail' in data && data.detail != null) {
      return new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail))
    }
    return new Error(`${fallback} Die JSON-Fehlerantwort enthält keine Fehlerdetails.`)
  }
  if (response.headers.get('content-type')?.includes('text/plain')) {
    return new Error(`${fallback} ${body.slice(0, 500)}`)
  }
  return new Error(`${fallback} Die Fehlerantwort ist kein JSON.`)
}

export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
  if (!response.ok) throw await httpError(response)
  return response.status === 204 ? undefined as T : response.json() as Promise<T>
}

export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

export async function streamChat(
  path: string, body: unknown, onDelta: (text: string) => void,
  onAccepted?: () => void,
): Promise<void> {
  const response = await fetch(`/api${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) throw await httpError(response)
  if (!response.body) throw new Error('Der Browser unterstützt kein Streaming.')
  onAccepted?.()
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let done = false
  try {
    while (true) {
      const result = await reader.read()
      buffer += decoder.decode(result.value, { stream: !result.done })
      let boundary: number
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        const frame = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const event = frame.split('\n').find(line => line.startsWith('event:'))?.slice(6).trim()
        const payload = frame.split('\n').filter(line => line.startsWith('data:'))
          .map(line => line.slice(5).trim()).join('\n')
        if (!payload) continue
        const data: { text?: string; message?: string } = JSON.parse(payload)
        if (event === 'error') throw new Error(data.message ?? 'KI-Anfrage fehlgeschlagen')
        if (event === 'delta' && typeof data.text === 'string') onDelta(data.text)
        if (event === 'done') done = true
      }
      if (result.done) break
    }
    if (!done) throw new Error('Verbindung unterbrochen. Die Antwort wurde nicht gespeichert.')
  } finally {
    await reader.cancel()
    reader.releaseLock()
  }
}
