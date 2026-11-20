import { apiRequest } from "./api";
import type { Conversation, ConversationMessage } from "./types";

type MessageResponse = {
  id: string;
  role: ConversationMessage["role"];
  content: string;
  created_at: string;
};

type ConversationResponse = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  messages?: MessageResponse[];
};

function mapMessage(message: MessageResponse): ConversationMessage {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    createdAt: message.created_at,
  };
}

function mapConversation(
  conversation: ConversationResponse,
  messages: ConversationMessage[] = [],
): Conversation {
  return {
    id: conversation.id,
    title: conversation.title,
    createdAt: conversation.created_at,
    updatedAt: conversation.updated_at,
    messageCount: conversation.message_count,
    messages,
  };
}

function identityHeaders(expectedUserId: string): HeadersInit {
  return { "X-Zyrquen-Expected-User-ID": expectedUserId };
}

export async function listConversations(
  expectedUserId: string,
): Promise<Conversation[]> {
  const conversations = await apiRequest<ConversationResponse[]>("conversations", {
    headers: identityHeaders(expectedUserId),
  });
  return conversations.map((item) => mapConversation(item));
}

export async function getConversation(
  id: string,
  expectedUserId: string,
): Promise<Conversation> {
  const conversation = await apiRequest<ConversationResponse>(
    `conversations/${encodeURIComponent(id)}`,
    { headers: identityHeaders(expectedUserId) },
  );
  return mapConversation(
    conversation,
    (conversation.messages ?? []).map(mapMessage),
  );
}

export async function createConversation(
  title: string,
  expectedUserId: string,
): Promise<Conversation> {
  const conversation = await apiRequest<ConversationResponse>("conversations", {
    method: "POST",
    headers: identityHeaders(expectedUserId),
    body: JSON.stringify({ title }),
  });
  return mapConversation(conversation);
}

export async function renameConversation(
  id: string,
  title: string,
  expectedUserId: string,
): Promise<Conversation> {
  const conversation = await apiRequest<ConversationResponse>(
    `conversations/${encodeURIComponent(id)}`,
    {
      method: "PATCH",
      headers: identityHeaders(expectedUserId),
      body: JSON.stringify({ title }),
    },
  );
  return mapConversation(conversation);
}

export async function deleteConversation(
  id: string,
  expectedUserId: string,
): Promise<void> {
  await apiRequest<void>(`conversations/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: identityHeaders(expectedUserId),
  });
}

export async function saveConversationMessage(
  conversationId: string,
  message: ConversationMessage & { role: "user" },
  expectedUserId: string,
): Promise<ConversationMessage> {
  const saved = await apiRequest<MessageResponse>(
    `conversations/${encodeURIComponent(conversationId)}/messages`,
    {
      method: "POST",
      headers: identityHeaders(expectedUserId),
      body: JSON.stringify({
        id: message.id,
        role: "user",
        content: message.content,
      }),
    },
  );
  return mapMessage(saved);
}

export function withConversation(
  conversations: Conversation[],
  conversation: Conversation,
): Conversation[] {
  return [
    conversation,
    ...conversations.filter((item) => item.id !== conversation.id),
  ].sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt));
}

export function updateConversationMessage(
  conversations: Conversation[],
  conversationId: string,
  message: ConversationMessage,
): Conversation[] {
  return conversations
    .map((conversation) => {
      if (conversation.id !== conversationId) return conversation;
      const alreadySaved = conversation.messages.some(
        (existing) => existing.id === message.id,
      );
      return {
        ...conversation,
        updatedAt: message.createdAt,
        messageCount: alreadySaved
          ? conversation.messageCount
          : conversation.messageCount + 1,
        messages: alreadySaved
          ? conversation.messages
          : [...conversation.messages, message],
      };
    })
    .sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt));
}
