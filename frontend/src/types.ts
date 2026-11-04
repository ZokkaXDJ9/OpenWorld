export type Attribute = {
  name: string
  type: 'text' | 'number' | 'boolean' | 'select' | 'multiselect' | 'date' | 'reference'
  value: string | number | boolean | string[]
  options: string[]
  minimum?: number | null
  maximum?: number | null
}

export type Resource = 'worlds' | 'locations' | 'characters' | 'relationships' | 'knowledge'
export type KnowledgeKind =
  'fact' | 'knowledge' | 'belief' | 'suspicion' | 'rumor' | 'secret' | 'memory' | 'received'
export type Entity = {
  id: string
  world_id?: string
  revision: number
  name?: string
  description?: string
  attributes?: Attribute[]
  state?: Record<string, string | number | boolean | string[]>
  kind?: string
  tags?: string[]
  parent_id?: string | null
  sort_order?: number
  profile?: Record<string, string>
  location_id?: string | null
  destination_id?: string | null
  travel_status?: 'present' | 'traveling' | 'unknown'
  source_id?: string
  target_id?: string
  secret?: boolean
  character_id?: string | null
  content?: string
  source?: string
  confidence?: number
  public?: boolean
  source_message_id?: string | null
  created_at?: string
  status?: string
  origin?: string
  event_id?: string | null
  subject_id?: string | null
  occurred_at?: string | null
  importance?: number
  emotion?: string
}

export type Conversation = {
  id: string
  world_id: string
  character_id: string
  title: string
  created_at: string
}
export type Message = {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
  sequence: number
  revision: number
  speaker_character_id: string | null
}
export type ProviderSettings = {
  base_url: string
  model: string
  context_window: number
  max_output_tokens: number
  temperature: number
  has_api_key: boolean
}

export type EventOperation =
  | { op: 'knowledge'; character_id: string | null; subject_id?: string | null; kind: KnowledgeKind
      content: string; confidence: number; importance?: number; emotion?: string; source?: string
      supersedes?: string[]; contradicts?: string[] }
  | { op: 'state'; entity_type: 'character' | 'world' | 'location'; entity_id: string
      revision: number; values: Record<string, string | number | boolean | string[]> }
  | { op: 'relationship'; entity_id: string; revision: number; attributes: Attribute[] }
  | { op: 'location'; entity_id: string; revision: number; location_id: string | null
      destination_id: string | null; travel_status: 'present' | 'traveling' | 'unknown' }
  | { op: 'archive'; entity_id: string; revision: number }
export type WorldEvent = {
  id: string; world_id: string; event_type: string; description: string
  occurred_at: string; created_at: string; source: string; confidence: number; revision: number
  location_id: string | null; status: string; participants: string[]
  proposal: { operations: EventOperation[]; mode: 'auto' | 'confirm' | 'protected'; reason: string
    preview: { before: Record<string, unknown>; after: Record<string, unknown> }[] }
  sources: { message_id: string | null; quote: string; role: string; conversation_id: string | null
    speaker_character_id: string | null }[]
  targets: { entity_type: string; entity_id: string }[]
  mutations: { id: string; entity_type: string; entity_id: string; before: Record<string, unknown>
    after: Record<string, unknown>; reverted: boolean }[]
  audit: { id: string; action: string; actor: string; created_at: string }[]
}
export type ExtractionJob = {
  id: string; conversation_id: string | null; status: string; error: string; attempts: number
  event_ids: string[]
}
export type EventSettings = { enabled: boolean; revision: number }
export type EventRule = {
  id: string; event_type: string; object_class: string
  mode: 'auto' | 'confirm' | 'protected'; revision: number
}
