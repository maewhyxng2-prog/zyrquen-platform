export type ApiHealth = {
  status: string;
  service?: string;
  native_ai?: NativeHealth;
};

export type NativeHealth = {
  runtime_status: string;
  native_model_loaded: boolean;
  authority: string;
  inference_available: boolean;
};

export type Session = {
  authenticated: boolean;
  email: string | null;
};

export type InferenceResponse = {
  status: string;
  request_id: string;
  provider: string;
  result: string;
};

export type ConversationMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
};

export type Conversation = {
  id: string;
  title: string;
  updatedAt: string;
  messages: ConversationMessage[];
};

export type StatusTone = "good" | "warn" | "bad" | "neutral" | "info";
