import { apiRequest } from "./api";
import type { QuotaSummary, UsageSummary, UserProfile } from "./types";

type ProfileResponse = {
  id: string;
  email: string;
};

function identityHeaders(expectedUserId: string): HeadersInit {
  return { "X-Zyrquen-Expected-User-ID": expectedUserId };
}

export async function getMyProfile(
  expectedUserId: string,
): Promise<UserProfile> {
  const profile = await apiRequest<ProfileResponse>("users/me", {
    headers: identityHeaders(expectedUserId),
  });
  if (profile.id !== expectedUserId) {
    throw new Error("ข้อมูลโปรไฟล์ไม่ตรงกับบัญชีที่เข้าสู่ระบบ");
  }
  return profile;
}

export async function updateMyProfile(
  email: string,
  expectedUserId: string,
): Promise<UserProfile> {
  const profile = await apiRequest<ProfileResponse>("users/me", {
    method: "PATCH",
    headers: identityHeaders(expectedUserId),
    body: JSON.stringify({ email }),
  });
  if (profile.id !== expectedUserId) {
    throw new Error("ข้อมูลโปรไฟล์ไม่ตรงกับบัญชีที่เข้าสู่ระบบ");
  }
  return profile;
}

export async function getMyUsage(
  expectedUserId: string,
): Promise<UsageSummary> {
  const usage = await apiRequest<{
    successful_requests: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    updated_at: string | null;
    records: Array<{
      request_id: string;
      status: string;
      input_tokens: number;
      output_tokens: number;
      total_tokens: number;
      model_version: string | null;
      created_at: string;
      completed_at: string | null;
    }>;
  }>("users/me/usage", { headers: identityHeaders(expectedUserId) });
  return {
    successfulRequests: usage.successful_requests,
    inputTokens: usage.input_tokens,
    outputTokens: usage.output_tokens,
    totalTokens: usage.total_tokens,
    updatedAt: usage.updated_at,
    records: usage.records.map((record) => ({
      requestId: record.request_id,
      status: record.status,
      inputTokens: record.input_tokens,
      outputTokens: record.output_tokens,
      totalTokens: record.total_tokens,
      modelVersion: record.model_version,
      createdAt: record.created_at,
      completedAt: record.completed_at,
    })),
  };
}

export async function getMyQuota(
  expectedUserId: string,
): Promise<QuotaSummary> {
  const quota = await apiRequest<{
    configured: boolean;
    active: boolean;
    max_requests: number | null;
    max_input_tokens: number | null;
    max_output_tokens: number | null;
    max_total_tokens: number | null;
    window_started_at: string | null;
    window_ends_at: string | null;
    successful_requests: number;
    running_requests: number;
    requests_in_use: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
  }>("users/me/quota", { headers: identityHeaders(expectedUserId) });
  return {
    configured: quota.configured,
    active: quota.active,
    maxRequests: quota.max_requests,
    maxInputTokens: quota.max_input_tokens,
    maxOutputTokens: quota.max_output_tokens,
    maxTotalTokens: quota.max_total_tokens,
    windowStartedAt: quota.window_started_at,
    windowEndsAt: quota.window_ends_at,
    successfulRequests: quota.successful_requests,
    runningRequests: quota.running_requests,
    requestsInUse: quota.requests_in_use,
    inputTokens: quota.input_tokens,
    outputTokens: quota.output_tokens,
    totalTokens: quota.total_tokens,
  };
}
