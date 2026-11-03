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
}
export type ProviderSettings = {
  base_url: string
  model: string
  context_window: number
  max_output_tokens: number
  temperature: number
  has_api_key: boolean
}
