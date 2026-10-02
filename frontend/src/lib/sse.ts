/**
 * Minimal Server-Sent Events reader over a fetch() stream.
 *
 * The backend emits `event: <name>\ndata: <json>\n\n` frames; this turns them
 * into `{ event, data }` objects without needing EventSource (which cannot
 * send a POST body).
 */

export interface SseFrame {
  event: string
  data: string
}

function parseBlock(block: string): SseFrame | null {
  let event = 'message'
  const dataLines: string[] = []

  for (const rawLine of block.split(/\r?\n/)) {
    if (!rawLine || rawLine.startsWith(':')) continue
    const colon = rawLine.indexOf(':')
    const field = colon === -1 ? rawLine : rawLine.slice(0, colon)
    let value = colon === -1 ? '' : rawLine.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') event = value
    else if (field === 'data') dataLines.push(value)
  }

  if (dataLines.length === 0) return null
  return { event, data: dataLines.join('\n') }
}

export async function* readSse(response: Response): AsyncGenerator<SseFrame> {
  const body = response.body
  if (!body) throw new Error('streaming response has no body')

  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      let boundary = buffer.indexOf('\n\n')
      while (boundary !== -1) {
        const block = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const frame = parseBlock(block)
        if (frame) yield frame
        boundary = buffer.indexOf('\n\n')
      }
    }
    const frame = parseBlock(buffer)
    if (frame) yield frame
  } finally {
    reader.releaseLock()
  }
}
